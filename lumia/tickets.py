"""Private ticket channels, persistent controls, and recoverable local transcripts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from urllib.parse import urlsplit
from collections import defaultdict
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_management, is_support, respond
from .presentation import card,channel_name

log = logging.getLogger(__name__)
PRIVATE_KINDS = frozenset({'partner', 'report'})
KINDS = {
    'fivem': ('FiveM', 'Server, risorse e sviluppo FiveM'),
    'minecraft': ('Minecraft', 'Plugin, configurazioni e server Minecraft'),
    'script': ('Script', 'Script, integrazioni e automazioni'),
    'custom': ('Progetto personalizzato', 'Un progetto su misura per il tuo team'),
    'support': ('Assistenza', 'Aiuto su servizi o lavori esistenti'),
    'partner': ('Partnership', 'Proposte riservate alla Management'),
    'report': ('Segnalazione riservata', 'Solo autore e Management'),
}
FORM_FIELDS = {
    'fivem': ('Server e framework', 'Cosa vuoi realizzare?', 'Budget indicativo', 'Scadenza desiderata', 'Link e riferimenti'),
    'minecraft': ('Versione e piattaforma', 'Cosa vuoi realizzare?', 'Budget indicativo', 'Scadenza desiderata', 'Link e riferimenti'),
    'script': ('Linguaggio e piattaforma', 'Funzioni richieste', 'Budget indicativo', 'Scadenza desiderata', 'Link e riferimenti'),
    'custom': ('Descrivi il progetto', 'Obiettivi e funzionalità', 'Budget indicativo', 'Scadenza desiderata', 'Link e riferimenti'),
    'support': ('Servizio o numero ordine', 'Descrivi il problema', 'Passi e riferimenti utili'),
    'partner': ('Team o organizzazione', 'Proposta di collaborazione', 'Contatto e riferimenti'),
    'report': ('Oggetto della segnalazione', 'Descrivi i fatti', 'Prove e riferimenti'),
}
SUPPORT_KINDS = frozenset({'support', 'partner', 'report'})
STAGES = ('nuovo', 'in_attesa', 'preventivo', 'approvato', 'in_lavorazione', 'revisione', 'consegnato', 'sospeso')
NO_MENTIONS = discord.AllowedMentions.none()


def can_access(member, ticket, cfg, *, staff=False):
    """Private tickets never grant Support or individual developers access."""
    guild = getattr(member, 'guild', None)
    if not guild or guild.id != cfg['guild_id']:
        return False
    if is_management(member, cfg):
        return True
    if ticket['kind'] in PRIVATE_KINDS:
        return not staff and member.id == ticket['owner']
    if is_support(member, cfg):
        return True
    return not staff and (member.id == ticket['owner'] or member.id in ticket.get('extra', []))


def build_overwrites(guild, cfg, ticket, *, closed=False):
    """Build a complete map; never inherit/sync category permissions."""
    def member(number):
        return guild.get_member(number) or discord.Object(id=number, type=discord.Member)

    def participant():
        return discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=not closed,
            attach_files=not closed, embed_links=not closed, add_reactions=not closed,
            create_public_threads=False, create_private_threads=False,
            send_messages_in_threads=False, use_application_commands=True)

    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    management = guild.get_role(cfg['roles'].get('management', 0))
    support = guild.get_role(cfg['roles'].get('support', 0))
    if management:
        overwrites[management] = participant()
    if ticket['kind'] not in PRIVATE_KINDS and support:
        overwrites[support] = participant()
    overwrites[member(ticket['owner'])] = participant()
    for number in {guild.owner_id, *cfg.get('owner_ids', [])}:
        overwrites[member(number)] = participant()
    if ticket['kind'] not in PRIVATE_KINDS:
        for number in ticket.get('extra', []):
            overwrites[member(number)] = participant()
    if guild.me is None:
        raise ValueError('Il bot non è disponibile nel server.')
    overwrites[guild.me] = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True,
        attach_files=True, embed_links=True, manage_channels=True, manage_messages=True,
        create_public_threads=False, create_private_threads=False,
        send_messages_in_threads=False)
    return overwrites


def panel_embed():
    return card('Come possiamo aiutarti?',
        'Discord è dedicato all’assistenza. Richieste, preventivi, ordini e pagamenti PayPal si gestiscono sul sito.',
        section='Lumia / Assistenza',
        fields=[('Hai un ordine?', 'Indica il codice LM del progetto nel ticket: ritrovi dettagli e aggiornamenti nell’area clienti.', False),
                ('Vuoi iniziare un progetto?', 'Usa «Inizia dal sito» per inviare la richiesta guidata.', False)],
        footer='Ticket privati · Massimo 2 attivi · 60 secondi tra le aperture')


class TicketView(discord.ui.View):
    def __init__(self, cog, *, timeout=None):
        super().__init__(timeout=timeout)
        self.cog = cog

    async def interaction_check(self, interaction):
        self.cog.check_guild(interaction)
        return True

    async def on_error(self, interaction, error, item):
        await self.cog.report_error(interaction, error)


class KindSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            custom_id='lumia:tickets:select:v1', placeholder='Scegli il tipo di assistenza…',
            min_values=1, max_values=1, row=0,
            options=[discord.SelectOption(label=label, value=kind, description=description)
                     for kind, (label, description) in KINDS.items() if kind in SUPPORT_KINDS])

    async def callback(self, interaction):
        self.cog.check_guild(interaction)
        self.cog.check_creator(interaction.user)
        if self.values[0] not in SUPPORT_KINDS:
            return await respond(interaction, 'Le nuove richieste si inviano dal sito. Usa /ordina per aprirlo.')
        await interaction.response.send_modal(TicketModal(self.cog, self.values[0], interaction.user.id))


class TicketPanelView(TicketView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(KindSelect(cog))
        origin=os.getenv('LUMIA_PUBLIC_URL','').rstrip('/')
        parsed=urlsplit(origin)
        if parsed.scheme=='https' and parsed.hostname and not (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            self.add_item(discord.ui.Button(label='Inizia dal sito',style=discord.ButtonStyle.link,url=origin+'/start',row=1))

    @discord.ui.button(label='Dati e privacy',style=discord.ButtonStyle.secondary,custom_id='lumia:tickets:privacy:v1',row=1)
    async def privacy(self,i,button):
        await respond(i,None,embed=card('Prima di aprire un ticket',
            'Non inviare password, token o dati di pagamento. I messaggi e i riferimenti agli allegati '
            'vengono archiviati nelle trascrizioni, accessibili alle persone autorizzate al ticket. '
            'Management gestisce manualmente conservazione e cancellazione: non c’è una scadenza automatica. '
            'I canali chiusi restano consultabili per almeno 7 giorni. Gli allegati collegati non vengono copiati in modo permanente.'))


class TicketModal(discord.ui.Modal):
    def __init__(self, cog, kind, owner):
        super().__init__(title=f'Lumia · {KINDS[kind][0]}'[:45],
                         custom_id=f'lumia:ticket:form:{kind}:v1', timeout=600)
        self.cog, self.kind, self.owner = cog, kind, owner
        for index, label in enumerate(FORM_FIELDS[kind]):
            self.add_item(discord.ui.TextInput(
                label=label, custom_id=f'field:{index}',
                style=discord.TextStyle.paragraph, required=index < 2,
                min_length=2 if index < 2 else 0, max_length=2000))

    async def on_submit(self, interaction):
        self.cog.check_guild(interaction)
        if interaction.user.id != self.owner:
            raise app_commands.CheckFailure('Questo modulo appartiene a un altro utente.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        fields = {item.label: str(item.value).strip() for item in self.children if item.value.strip()}
        ticket = await self.cog.create_ticket(interaction.guild, interaction.user, self.kind, fields)
        await respond(interaction, f'Ticket **#{ticket["id"]}** aperto: <#{ticket["channel"]}>.')

    async def on_error(self, interaction, error):
        await self.cog.report_error(interaction, error)


class CloseConfirm(TicketView):
    def __init__(self, cog, number, requester, reason):
        super().__init__(cog, timeout=180)
        self.number, self.requester, self.reason = number, requester, reason

    @discord.ui.button(label='Conferma chiusura', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        self.cog.check_guild(interaction)
        if interaction.user.id != self.requester:
            raise app_commands.CheckFailure('La conferma appartiene a un altro membro dello staff.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.close_ticket(self.number, interaction.user, self.reason)
        self.stop()
        await respond(interaction, f'Ticket **#{self.number}** chiuso. Trascrizione archiviata; il canale resta consultabile.')

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.cog.check_guild(interaction)
        if interaction.user.id != self.requester:
            raise app_commands.CheckFailure('Questa conferma appartiene a un altro utente.')
        self.stop()
        await interaction.response.edit_message(content='Chiusura annullata.', view=None)


class DeleteTicketModal(discord.ui.Modal):
    def __init__(self, cog, number, requester):
        super().__init__(title=f'Elimina canale ticket #{number}'[:45], timeout=180)
        self.cog, self.number, self.requester = cog, number, requester
        self.confirmation = discord.ui.TextInput(
            label=f'Scrivi ELIMINA #{number}'[:45],
            placeholder='Cancella il canale e i messaggi. Archivio conservato.',
            required=True, max_length=50)
        self.add_item(self.confirmation)

    async def on_submit(self, interaction):
        self.cog.check_guild(interaction)
        if interaction.user.id != self.requester:
            raise app_commands.CheckFailure('Questa conferma appartiene a un altro utente.')
        ticket = self.cog.for_interaction(interaction, staff=True)
        if ticket['id'] != self.number:
            raise ValueError('Questa conferma appartiene a un altro ticket.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.delete_closed(self.number, interaction.user, self.confirmation.value)
        await respond(interaction, 'Canale ticket eliminato. La trascrizione verificata è conservata nell’archivio locale.')

    async def on_error(self, interaction, error):
        await self.cog.report_error(interaction, error)


class TicketControls(TicketView):
    @discord.ui.button(label='Prendi in carico', style=discord.ButtonStyle.primary,
                       custom_id='lumia:tickets:claim:v1')
    async def claim(self, interaction, button):
        self.cog.check_guild(interaction)
        ticket = self.cog.for_interaction(interaction, staff=True)
        claimed = await self.cog.claim_ticket(ticket['id'], interaction.user)
        await respond(interaction, 'Ticket preso in carico.' if claimed else 'Ticket già assegnato o non aperto.')

    @discord.ui.button(label='Trascrizione', style=discord.ButtonStyle.secondary,
                       custom_id='lumia:tickets:transcript:v1')
    async def transcript(self, interaction, button):
        self.cog.check_guild(interaction)
        ticket = self.cog.for_interaction(interaction)
        await self.cog.send_transcript(interaction, ticket)

    @discord.ui.button(label='Chiudi / richiedi chiusura', style=discord.ButtonStyle.danger,
                       custom_id='lumia:tickets:close:v1')
    async def close(self, interaction, button):
        self.cog.check_guild(interaction)
        ticket = self.cog.for_interaction(interaction)
        await self.cog.request_close(interaction, ticket, 'Chiusura richiesta dai controlli del ticket')

    @discord.ui.button(label='Elimina ticket', style=discord.ButtonStyle.danger,
                       custom_id='lumia:tickets:delete:v1')
    async def delete(self, interaction, button):
        ticket = self.cog.for_interaction(interaction, staff=True)
        self.cog.deletable_ticket(ticket['id'], interaction.user)
        await interaction.response.send_modal(DeleteTicketModal(self.cog, ticket['id'], interaction.user.id))


class Tickets(commands.Cog):
    ticket = app_commands.Group(name='ticket', description='Assistenza e progetti Lumia', guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.locks = defaultdict(asyncio.Lock)
        self.recovery_lock = asyncio.Lock()
        self.recovered = False
        self.persistent_views = []

    async def cog_load(self):
        self.persistent_views = [TicketPanelView(self), TicketControls(self)]
        for view in self.persistent_views:
            self.bot.add_view(view)

    async def cog_unload(self):
        for view in self.persistent_views:
            view.stop()

    def check_guild(self, interaction):
        if interaction.guild_id != self.bot.cfg['guild_id']:
            raise app_commands.CheckFailure('Questi controlli sono disponibili solo nel server Lumia configurato.')

    def check_creator(self, member):
        role = self.bot.cfg['roles'].get('member', 0)
        if (getattr(member, 'bot', False) or not getattr(member, 'guild', None)
                or member.guild.id != self.bot.cfg['guild_id']
                or not (is_support(member, self.bot.cfg) or (role and role in {r.id for r in member.roles}))):
            raise app_commands.CheckFailure('Completa prima l’accesso al server per ottenere il ruolo Member e aprire un ticket.')

    def checked_ticket(self, number, member, *, staff=False):
        ticket = self.bot.store.ticket(number)
        if ticket is None or not can_access(member, ticket, self.bot.cfg, staff=staff):
            raise app_commands.CheckFailure('Ticket non disponibile o accesso non autorizzato.')
        return ticket

    def ticket_channel(self, ticket):
        guild = self.bot.get_guild(self.bot.cfg['guild_id'])
        channel = guild.get_channel(ticket['channel']) if guild and ticket['channel'] else None
        if (channel is None or channel not in guild.text_channels or channel.guild.id != guild.id
                or channel.topic != f'lumia-ticket:{ticket["id"]}'):
            raise ValueError('Canale ticket non verificato. La Management deve controllare la configurazione.')
        return channel

    def for_interaction(self, interaction, *, staff=False):
        self.check_guild(interaction)
        ticket = next((t for t in self.bot.store.tickets() if t['channel'] == interaction.channel_id), None)
        if ticket is None:
            raise ValueError('Usa questo comando nel canale di un ticket Lumia.')
        ticket = self.checked_ticket(ticket['id'], interaction.user, staff=staff)
        self.ticket_channel(ticket)
        return ticket

    async def report_error(self, interaction, error):
        if isinstance(error, (ValueError, app_commands.CheckFailure)):
            message = str(error)
        else:
            log.error('Ticket operation failed', exc_info=(type(error), error, error.__traceback__))
            message = ('Operazione non completata. Il canale e gli eventuali archivi sono conservati. '
                       'Riprova o contatta la Management.')
        await respond(interaction, message)

    def configured_category(self, guild, kind):
        management = guild.get_role(self.bot.cfg['roles'].get('management', 0))
        support = guild.get_role(self.bot.cfg['roles'].get('support', 0))
        if management is None or management == guild.default_role:
            raise ValueError('Configura prima un ruolo Management valido con /server allestimento.')
        if kind not in PRIVATE_KINDS and (support is None or support == guild.default_role):
            raise ValueError('Configura prima un ruolo Support valido con /server allestimento.')
        key = 'private_tickets' if kind in PRIVATE_KINDS else 'tickets'
        category = guild.get_channel(self.bot.cfg['categories'].get(key, 0))
        if category is None or (isinstance(category, discord.abc.GuildChannel)
                                and not isinstance(category, discord.CategoryChannel)):
            raise ValueError('Configura prima la categoria ticket corretta con /server allestimento.')
        return category

    async def create_ticket(self, guild, author, kind, fields):
        if guild.id != self.bot.cfg['guild_id'] or getattr(author, 'guild', None) != guild:
            raise app_commands.CheckFailure('Server non autorizzato.')
        self.check_creator(author)
        if kind not in SUPPORT_KINDS:
            raise ValueError('Le nuove richieste si inviano dal sito. Su Discord puoi aprire un ticket di assistenza.')
        if kind not in KINDS or not fields or len(fields) > 5:
            raise ValueError('Tipologia o modulo ticket non valido.')
        if any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 100 or len(v) > 2000
               for k, v in fields.items()):
            raise ValueError('Il modulo contiene campi non validi o troppo lunghi.')
        category = self.configured_category(guild, kind)
        ticket = self.bot.store.reserve_ticket(author.id, kind, fields)
        async with self.locks[ticket['id']]:
            try:
                channel = await guild.create_text_channel(
                    channel_name(f'🎫・ticket-{ticket["id"]:04d}-{kind}'), category=category,
                    topic=f'lumia-ticket:{ticket["id"]}',
                    overwrites=build_overwrites(guild, self.bot.cfg, ticket),
                    reason=f'Lumia ticket #{ticket["id"]}')
                self.bot.store.update_ticket(ticket['id'], channel=channel.id)
                await self.send_intro(channel, ticket)
                self.bot.store.update_ticket(ticket['id'], state='open')
            except Exception:
                # A timeout may still create a Discord channel. Recover by unique topic.
                self.bot.store.put('ticket_errors', ticket['id'], {'at': time.time(), 'operation': 'creation'})
                raise
        return self.bot.store.ticket(ticket['id'])

    async def send_intro(self, channel, ticket):
        author=channel.guild.get_member(ticket['owner']) if hasattr(channel.guild,'get_member') else None
        embed = card(title=f'🎫  Ticket #{ticket["id"]:04d} · {KINDS[ticket["kind"]][0]}',
                              text=f'Richiesta di <@{ticket["owner"]}>\n\n'
                              'Il team risponderà qui per l’assistenza. Richieste, preventivi, ordini e pagamenti si gestiscono sul sito.',
                              section='Lumia / Assistenza',subject=author)
        for label, value in ticket['fields'].items():
            summary = value if len(value) <= 950 else value[:850] + '… Testo completo nei messaggi seguenti.'
            embed.add_field(name=label[:100], value=summary or '—', inline=False)
        if ticket['kind'] in PRIVATE_KINDS:
            embed.set_footer(text='Riservato: autore e Management. Gli amministratori Discord possono accedere.')
        else:
            embed.set_footer(text='Autore, Support, Management ed eventuali sviluppatori aggiunti individualmente.')
        message = await channel.send(embed=embed, view=TicketControls(self), allowed_mentions=NO_MENTIONS)
        self.bot.store.put('ticket_controls', ticket['id'], {'message': message.id, 'channel': channel.id})
        for label, value in ticket['fields'].items():
            if len(value) > 950:
                for offset in range(0, len(value), 1800):
                    await channel.send(embed=card(label,value[offset:offset+1800],subject=author),
                                       allowed_mentions=NO_MENTIONS)

    async def claim_ticket(self, number, member):
        async with self.locks[number]:
            ticket = self.checked_ticket(number, member, staff=True)
            self.ticket_channel(ticket)
            return self.bot.store.claim(number, member.id)

    async def change_developer(self, number, actor, developer, *, add):
        async with self.locks[number]:
            ticket = self.checked_ticket(number, actor, staff=True)
            if ticket['state'] != 'open':
                raise ValueError('Il ticket deve essere aperto.')
            if ticket['kind'] in PRIVATE_KINDS:
                raise ValueError('I ticket riservati ammettono solo autore e Management.')
            if getattr(developer, 'guild', None) != getattr(actor, 'guild', None) or developer.bot:
                raise ValueError('Scegli uno sviluppatore di questo server.')
            if add and self.bot.cfg['roles'].get('developer', 0) not in {r.id for r in developer.roles}:
                raise ValueError('Il membro deve avere il ruolo Developer configurato.')
            extra = set(ticket['extra'])
            if add:
                extra.add(developer.id)
            else:
                extra.discard(developer.id)
            changed = dict(ticket, extra=sorted(extra))
            channel = self.ticket_channel(ticket)
            # The durable marker lets recovery reconcile a crash between Discord
            # permissions and the committed list of individual developers.
            self.bot.store.put('ticket_permission_pending', number, {'at': time.time()})
            try:
                await channel.edit(overwrites=build_overwrites(channel.guild, self.bot.cfg, changed),
                                   reason=f'Lumia ticket #{number}: accessi sviluppatore')
                self.bot.store.update_ticket(number, extra=changed['extra'])
            except Exception:
                try:
                    committed = self.bot.store.ticket(number)
                    await channel.edit(overwrites=build_overwrites(channel.guild, self.bot.cfg, committed),
                                       reason=f'Lumia ticket #{number}: ripristino accessi')
                    self.bot.store.delete('ticket_permission_pending', number)
                except Exception:
                    log.exception('Ticket #%s needs permission recovery', number)
                raise
            self.bot.store.delete('ticket_permission_pending', number)

    def archive_path(self, ticket, *, snapshot=False):
        suffix = '-snapshot' if snapshot else ''
        return Path(self.bot.data_dir) / 'transcripts' / f'ticket-{ticket["id"]:06d}{suffix}.txt'

    async def write_transcript(self, ticket, channel, target, *, closure=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                             dir=target.parent, prefix=f'.{target.name}.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(f'Lumia Development — Ticket #{ticket["id"]}\n')
                stream.write(f'Tipo: {ticket["kind"]}\nAutore ID: {ticket["owner"]}\n')
                stream.write(f'Canale ID: {channel.id}\nCreato (Unix UTC): {ticket["created"]}\n')
                stream.write(f'Fase: {ticket["stage"]}\nAssegnato ID: {ticket["staff"]}\n')
                if closure:
                    stream.write('Chiusura: ' + json.dumps(closure, ensure_ascii=False) + '\n')
                stream.write('\nMODULO ORIGINALE\n')
                for label, value in ticket['fields'].items():
                    stream.write(f'\n{label}\n{value}\n')
                stream.write('\nCRONOLOGIA COMPLETA DISPONIBILE SU DISCORD\n')
                async for message in channel.history(limit=None, oldest_first=True):
                    stream.write(f'\n[{message.created_at.isoformat()}] {message.author} '
                                 f'(ID {message.author.id}) — Messaggio {message.id}\n')
                    if message.edited_at:
                        stream.write(f'Modificato: {message.edited_at.isoformat()}\n')
                    stream.write(message.content + '\n')
                    if message.reference:
                        stream.write(f'Risposta al messaggio: {message.reference.message_id}\n')
                    for attachment in message.attachments:
                        stream.write(f'Allegato: {attachment.filename} | {attachment.size} byte | '
                                     f'{attachment.content_type} | {attachment.url}\n')
                    for embed in message.embeds:
                        stream.write('Embed: ' + json.dumps(embed.to_dict(), ensure_ascii=False) + '\n')
                    for sticker in message.stickers:
                        stream.write(f'Sticker: {sticker.name} | {sticker.url}\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def archive_digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def verified_archive(self, ticket):
        path = self.archive_path(ticket)
        metadata = self.bot.store.get('ticket_archives', ticket['id'])
        if (ticket['transcript'] != path.name or not metadata or not path.is_file()
                or path.stat().st_size != metadata['size']
                or self.archive_digest(path) != metadata['sha256']):
            raise ValueError('Archivio finale non verificabile. Il canale deve essere conservato.')
        return path

    async def close_ticket(self, number, actor, reason):
        async with self.locks[number]:
            ticket = self.checked_ticket(number, actor, staff=True)
            if ticket['state'] != 'open':
                raise ValueError('Il ticket non è aperto o è già in chiusura.')
            channel = self.ticket_channel(ticket)
            self.bot.store.update_ticket(number, state='closing')
            closure = {'by': actor.id, 'reason': reason[:1000], 'at': time.time()}
            try:
                # Freeze first so participant messages cannot arrive after the archive.
                await channel.edit(overwrites=build_overwrites(channel.guild, self.bot.cfg, ticket, closed=True),
                                   reason=f'Lumia ticket #{number}: chiusura')
                target = await self.write_transcript(ticket, channel, self.archive_path(ticket), closure=closure)
                metadata = {'sha256': self.archive_digest(target), 'size': target.stat().st_size, 'at': closure['at']}
                self.bot.store.put('ticket_archives', number, metadata)
                self.bot.store.put('ticket_closures', number, closure)
                self.bot.store.update_ticket(number, state='closed', transcript=target.name, closed=closure['at'])
            except Exception:
                try:
                    await channel.edit(overwrites=build_overwrites(channel.guild, self.bot.cfg, ticket),
                                       reason=f'Lumia ticket #{number}: chiusura interrotta')
                    self.bot.store.update_ticket(number, state='open')
                except Exception:
                    # Keep closing if permission rollback fails; startup recovery retries.
                    log.exception('Could not restore interrupted ticket #%s', number)
                raise
            try:
                await channel.send(embed=card('Ticket chiuso','La trascrizione è archiviata. Il canale resta consultabile per almeno 7 giorni.',
                    level='success',subject=actor,fields=[('Richiesta',f'#{number:04d}',True),
                    ('Cliente',f'<@{ticket["owner"]}>',True)]),allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:
                log.warning('Could not post closed confirmation for ticket #%s', number)
            return target

    async def request_close(self, interaction, ticket, reason):
        self.check_guild(interaction)
        current = self.checked_ticket(ticket['id'], interaction.user)
        if current['state'] != 'open':
            raise ValueError('Il ticket non è aperto.')
        if can_access(interaction.user, current, self.bot.cfg, staff=True):
            await respond(interaction, 'Confermi la chiusura? I messaggi verranno bloccati e la '
                          'cronologia archiviata prima di chiudere il ticket.',
                          view=CloseConfirm(self, current['id'], interaction.user.id, reason))
            return
        if interaction.user.id != current['owner']:
            raise app_commands.CheckFailure('Solo autore e staff possono richiedere la chiusura.')
        async with self.locks[current['id']]:
            current = self.checked_ticket(current['id'], interaction.user)
            if current['state'] != 'open':
                raise ValueError('Il ticket non è aperto.')
            if self.bot.store.get('ticket_close_requests', current['id']):
                await respond(interaction, 'La richiesta di chiusura è già in attesa dello staff.')
                return
            channel = self.ticket_channel(current)
            await channel.send(embed=card('Richiesta di chiusura','Lo staff può confermarla con /ticket chiudi.',
                subject=interaction.user,fields=[('Cliente',f'<@{current["owner"]}>',True),
                ('Motivo',reason[:1000] or 'Non specificato',False)]),allowed_mentions=NO_MENTIONS)
            self.bot.store.put('ticket_close_requests', current['id'], {'by': interaction.user.id, 'at': time.time()})
        await respond(interaction, 'Richiesta inviata allo staff. Il ticket rimane aperto fino alla conferma.')

    async def send_transcript(self, interaction, ticket):
        self.check_guild(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.locks[ticket['id']]:
            ticket = self.checked_ticket(ticket['id'], interaction.user)
            if ticket['state'] == 'closed':
                path = self.verified_archive(ticket)
            elif ticket['state'] == 'open':
                channel = self.ticket_channel(ticket)
                path = await self.write_transcript(ticket, channel, self.archive_path(ticket, snapshot=True))
            else:
                raise ValueError('Il ticket è in elaborazione. Riprova tra poco.')
            limit = getattr(interaction.guild, 'filesize_limit', 10 * 1024 * 1024)
            if path.stat().st_size > limit:
                await respond(interaction, 'La trascrizione è archiviata in sicurezza ma supera il limite '
                              'di allegati Discord. Chiedi alla Management una copia tramite un canale riservato.')
            else:
                with discord.File(path, filename=path.name) as attachment:
                    await respond(interaction, f'Trascrizione del ticket **#{ticket["id"]}**.', file=attachment)

    def deletable_ticket(self, number, actor):
        if not is_management(actor, self.bot.cfg):
            raise app_commands.CheckFailure('Solo la Management può eliminare un canale archiviato.')
        ticket = self.checked_ticket(number, actor, staff=True)
        if self.bot.store.get('ticket_deleted_channels', number):
            raise ValueError('Il canale di questo ticket è già stato eliminato.')
        if ticket['state'] != 'closed' or not ticket['closed'] or time.time() - ticket['closed'] < 7 * 86400:
            raise ValueError('Puoi eliminare il canale solo 7 giorni dopo la chiusura confermata. Usa prima Chiudi / richiedi chiusura.')
        self.verified_archive(ticket)
        self.ticket_channel(ticket)
        return ticket

    async def delete_closed(self, number, actor, confirmation):
        async with self.locks[number]:
            ticket = self.deletable_ticket(number, actor)
            if confirmation != f'ELIMINA #{number}':
                raise ValueError(f'Per confermare scrivi esattamente ELIMINA #{number}.')
            channel = self.ticket_channel(ticket)
            await channel.delete(reason=f'Lumia ticket #{number}: archivio finale verificato, conferma Management')
            self.bot.store.put('ticket_deleted_channels', number, {'by': actor.id, 'at': time.time(), 'channel': channel.id})

    async def publish_controls(self, number, actor):
        async with self.locks[number]:
            if not is_management(actor, self.bot.cfg):
                raise app_commands.CheckFailure('Solo la Management può aggiornare i controlli.')
            ticket = self.checked_ticket(number, actor, staff=True)
            if ticket['state'] not in ('open', 'closed'):
                raise ValueError('Il ticket è in elaborazione. Riprova tra poco.')
            channel = self.ticket_channel(ticket)
            saved = self.bot.store.get('ticket_controls', number, {})
            if saved.get('channel') == channel.id and saved.get('message'):
                try:
                    message = await channel.fetch_message(saved['message'])
                    await message.edit(view=TicketControls(self), allowed_mentions=NO_MENTIONS)
                    return
                except discord.NotFound:
                    pass
            # Old installations did not save the intro message ID. Reuse its
            # existing controls instead of creating a second panel.
            bot_user = getattr(self.bot, 'user', None)
            if bot_user:
                expected = {f'lumia:tickets:{action}:v1' for action in ('claim', 'transcript', 'close')}
                async for message in channel.history(limit=None, oldest_first=True):
                    ids = {getattr(item, 'custom_id', None) for row in getattr(message, 'components', [])
                           for item in getattr(row, 'children', [])}
                    if message.author.id == bot_user.id and expected <= ids:
                        await message.edit(view=TicketControls(self), allowed_mentions=NO_MENTIONS)
                        self.bot.store.put('ticket_controls', number, {'message': message.id, 'channel': channel.id})
                        return
            message = await channel.send(embed=card('Controlli del ticket',
                'Assistenza e trascrizione. Eliminazione riservata a Management, con conferma, '
                'archivio verificato e almeno 7 giorni dalla chiusura.'),
                view=TicketControls(self), allowed_mentions=NO_MENTIONS)
            self.bot.store.put('ticket_controls', number, {'message': message.id, 'channel': channel.id})

    @commands.Cog.listener()
    async def on_ready(self):
        async with self.recovery_lock:
            if not self.recovered:
                await self.recover()
                self.recovered = True

    async def recover(self):
        guild = self.bot.get_guild(self.bot.cfg['guild_id'])
        if guild is None:
            return
        for original in self.bot.store.tickets():
            pending_permissions = self.bot.store.get('ticket_permission_pending', original['id'])
            if original['state'] not in ('creating', 'closing') and not pending_permissions:
                continue
            async with self.locks[original['id']]:
                ticket = self.bot.store.ticket(original['id'])
                try:
                    if ticket['state'] == 'creating':
                        matches = [channel for channel in guild.text_channels
                                   if channel.topic == f'lumia-ticket:{ticket["id"]}']
                        if len(matches) > 1:
                            raise ValueError('Più canali con lo stesso identificatore: controllo manuale richiesto.')
                        if not matches:
                            self.bot.store.update_ticket(ticket['id'], state='failed')
                            continue
                        channel = matches[0]
                        self.bot.store.update_ticket(ticket['id'], channel=channel.id)
                        await channel.edit(overwrites=build_overwrites(guild, self.bot.cfg, ticket),
                                           reason=f'Lumia ticket #{ticket["id"]}: ripristino')
                        await self.send_intro(channel, ticket)
                        self.bot.store.update_ticket(ticket['id'], state='open')
                    elif ticket['state'] == 'closing':
                        channel = self.ticket_channel(ticket)
                        await channel.edit(overwrites=build_overwrites(guild, self.bot.cfg, ticket),
                                           reason=f'Lumia ticket #{ticket["id"]}: ripresa sicura della chiusura')
                        self.bot.store.update_ticket(ticket['id'], state='open')
                        await channel.send(embed=card('Ticket riaperto','La chiusura precedente è stata interrotta. '
                            'Lo staff può ripetere /ticket chiudi per creare una nuova trascrizione completa.',level='warning'),
                            allowed_mentions=NO_MENTIONS)
                    elif pending_permissions and ticket['state'] in ('open', 'closed'):
                        channel = self.ticket_channel(ticket)
                        await channel.edit(overwrites=build_overwrites(guild, self.bot.cfg, ticket,
                                                                       closed=ticket['state'] == 'closed'),
                                           reason=f'Lumia ticket #{ticket["id"]}: ripristino accessi')
                    self.bot.store.delete('ticket_permission_pending', ticket['id'])
                except Exception:
                    log.exception('Manual recovery needed for ticket #%s', ticket['id'])

    @ticket.command(name='pannello', description='Pubblica il pannello di apertura ticket')
    async def panel(self, interaction: discord.Interaction, canale: discord.TextChannel | None = None):
        self.check_guild(interaction)
        if not is_management(interaction.user, self.bot.cfg):
            raise app_commands.CheckFailure('Solo la Management può pubblicare il pannello.')
        channel = canale or interaction.guild.get_channel(self.bot.cfg['channels'].get('ticket_panel', 0))
        if channel is None or channel.guild.id != self.bot.cfg['guild_id']:
            raise ValueError('Configura il canale ticket oppure seleziona un canale del server.')
        await interaction.response.defer(ephemeral=True)
        await channel.send(embed=panel_embed(), view=TicketPanelView(self), allowed_mentions=NO_MENTIONS)
        await respond(interaction, 'Pannello ticket pubblicato.')

    @ticket.command(name='prendi', description='Prendi in carico questo ticket')
    async def claim_command(self, interaction: discord.Interaction):
        ticket = self.for_interaction(interaction, staff=True)
        claimed = await self.claim_ticket(ticket['id'], interaction.user)
        await respond(interaction, 'Ticket preso in carico.' if claimed else 'Il ticket è già assegnato o non aperto.')

    @ticket.command(name='assegna', description='Assegna questo ticket a un membro dello staff')
    async def assign(self, interaction: discord.Interaction, staff: discord.Member):
        ticket = self.for_interaction(interaction, staff=True)
        if not is_management(interaction.user, self.bot.cfg):
            raise app_commands.CheckFailure('Solo la Management può assegnare i ticket.')
        async with self.locks[ticket['id']]:
            ticket = self.checked_ticket(ticket['id'], interaction.user, staff=True)
            if ticket['state'] != 'open' or staff.bot or not can_access(staff, ticket, self.bot.cfg, staff=True):
                raise ValueError('Scegli uno staff autorizzato per un ticket aperto.')
            self.bot.store.update_ticket(ticket['id'], staff=staff.id)
        await respond(interaction, f'Ticket assegnato a {staff.display_name}.')

    @ticket.command(name='stato', description='Aggiorna la fase del lavoro nel ticket')
    @app_commands.choices(fase=[app_commands.Choice(name=stage.replace('_', ' ').capitalize(), value=stage) for stage in STAGES])
    async def status(self, interaction: discord.Interaction, fase: app_commands.Choice[str]):
        ticket = self.for_interaction(interaction, staff=True)
        async with self.locks[ticket['id']]:
            ticket = self.checked_ticket(ticket['id'], interaction.user, staff=True)
            if ticket['state'] != 'open' or fase.value not in STAGES:
                raise ValueError('Puoi aggiornare la fase solo per un ticket aperto.')
            self.bot.store.update_ticket(ticket['id'], stage=fase.value)
            history = self.bot.store.get('ticket_stage_history', ticket['id'], [])
            history.append({'actor': interaction.user.id, 'at': time.time(),
                            'current': ticket['stage'], 'new': fase.value})
            self.bot.store.put('ticket_stage_history', ticket['id'], history)
        await respond(interaction, f'Fase aggiornata: **{fase.name}**.')

    @ticket.command(name='aggiungi-sviluppatore', description='Concedi accesso a uno sviluppatore specifico')
    async def add_developer(self, interaction: discord.Interaction, sviluppatore: discord.Member):
        ticket = self.for_interaction(interaction, staff=True)
        await interaction.response.defer(ephemeral=True)
        await self.change_developer(ticket['id'], interaction.user, sviluppatore, add=True)
        await respond(interaction, 'Sviluppatore aggiunto individualmente al ticket.')

    @ticket.command(name='rimuovi-sviluppatore', description='Revoca l’accesso individuale di uno sviluppatore')
    async def remove_developer(self, interaction: discord.Interaction, sviluppatore: discord.Member):
        ticket = self.for_interaction(interaction, staff=True)
        await interaction.response.defer(ephemeral=True)
        await self.change_developer(ticket['id'], interaction.user, sviluppatore, add=False)
        await respond(interaction, 'Accesso individuale revocato. Gli eventuali ruoli Support o Management conservano il proprio accesso.')

    @ticket.command(name='trascrizione', description='Scarica privatamente la cronologia del ticket')
    async def transcript_command(self, interaction: discord.Interaction):
        ticket = self.for_interaction(interaction)
        await self.send_transcript(interaction, ticket)

    @ticket.command(name='chiudi', description='Conferma o richiedi la chiusura del ticket')
    async def close_command(self, interaction: discord.Interaction, motivo: app_commands.Range[str, 2, 1000] = 'Lavoro completato'):
        ticket = self.for_interaction(interaction)
        await self.request_close(interaction, ticket, motivo)

    @ticket.command(name='elimina-canale', description='Management: elimina un ticket chiuso da almeno 7 giorni')
    async def delete_command(self, interaction: discord.Interaction, conferma: str):
        ticket = self.for_interaction(interaction, staff=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.delete_closed(ticket['id'], interaction.user, conferma)
        await respond(interaction, 'Canale eliminato dopo verifica dell’archivio finale. La trascrizione locale è conservata.')

    @ticket.command(name='controlli', description='Management: aggiorna i pulsanti anche nei ticket già esistenti')
    async def controls_command(self, interaction: discord.Interaction):
        ticket = self.for_interaction(interaction, staff=True)
        if not is_management(interaction.user, self.bot.cfg):
            raise app_commands.CheckFailure('Solo la Management può aggiornare i controlli.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.publish_controls(ticket['id'], interaction.user)
        await respond(interaction, 'Controlli aggiornati, incluso il pulsante Elimina ticket.')

    @ticket.command(name='recupera', description='Management: riprova le creazioni e chiusure interrotte')
    async def recover_command(self, interaction: discord.Interaction):
        self.check_guild(interaction)
        if not is_management(interaction.user, self.bot.cfg):
            raise app_commands.CheckFailure('Solo la Management può ripristinare i ticket.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.recovery_lock:
            await self.recover()
        await respond(interaction, 'Ripristino eseguito. I ticket ancora in elaborazione richiedono '
                      'un controllo della Management nei log locali.')


async def setup(bot):
    await bot.add_cog(Tickets(bot))
