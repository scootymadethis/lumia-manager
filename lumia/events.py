"""Restart-safe event panels and opt-in reminders for studio demos and meetings."""
import asyncio
import time
import uuid
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from .presentation import card
from discord import app_commands
from discord.ext import commands, tasks

from .common import is_management, require, respond
from .core import next_occurrence, parse_when


class EventService:
    def __init__(self, store):
        self.store = store

    def get(self, event_id):
        event = self.store.get('events', event_id)
        if not event:
            raise ValueError('Evento non trovato.')
        return event

    def events(self):
        return sorted(self.store.records('events').values(), key=lambda e: e['starts'])

    def create(self, *, title, description, starts, timezone, repeat, capacity, creator, channel, now=None):
        now = time.time() if now is None else now
        if not title.strip() or len(title) > 100 or len(description) > 1500:
            raise ValueError('Titolo richiesto (massimo 100 caratteri); descrizione massimo 1500.')
        if starts <= now or repeat not in ('none', 'daily', 'weekly') or not 0 <= capacity <= 500:
            raise ValueError('Controlla data futura, ricorrenza e capienza (0–500).')
        ZoneInfo(timezone)
        event = dict(id=uuid.uuid4().hex[:12], title=title.strip(), description=description.strip(),
                     starts=starts, timezone=timezone, repeat=repeat, capacity=capacity,
                     creator=creator, channel=channel, message=None, status='active',
                     rsvp={'yes': [], 'maybe': [], 'no': []}, reminded=False, started=False)
        self.store.put('events', event['id'], event)
        return event

    def rsvp(self, event_id, member_id, choice, now=None):
        now = time.time() if now is None else now
        if choice not in ('yes', 'maybe', 'no'):
            raise ValueError('Risposta non valida.')
        # Capacity check and membership transition share the store's transaction lock.
        with self.store.lock:
            event = self.get(event_id)
            if event['status'] != 'active' or event['starts'] <= now:
                raise ValueError('Le iscrizioni a questa data sono chiuse.')
            yes = event['rsvp']['yes']
            if choice == 'yes' and member_id not in yes and event['capacity'] and len(yes) >= event['capacity']:
                raise ValueError('Posti esauriti. Puoi scegliere «Forse».')
            for participants in event['rsvp'].values():
                if member_id in participants:
                    participants.remove(member_id)
            event['rsvp'][choice].append(member_id)
            self.store.put('events', event_id, event)
            return event

    def cancel(self, event_id):
        with self.store.lock:
            event = self.get(event_id)
            event['status'] = 'cancelled'
            self.store.put('events', event_id, event)
            return event

    def mark_sent(self, event_id, kind, starts):
        with self.store.lock:
            event = self.get(event_id)
            if event['starts'] == starts:
                event['reminded' if kind == 'reminder' else 'started'] = True
                self.store.put('events', event_id, event)

    def due(self, now=None):
        now = time.time() if now is None else now
        actions = []
        with self.store.lock:
            for event in self.events():
                if event['status'] != 'active':
                    continue
                if now >= event['starts'] + 900:
                    old_start = event['starts']
                    self.store.put('event_history', f"{event['id']}:{old_start}", event)
                    if event['repeat'] == 'none':
                        event['status'] = 'completed'
                    else:
                        while event['starts'] <= now:
                            event['starts'] = next_occurrence(event['starts'], event['repeat'], event['timezone'])
                        event.update(rsvp={'yes': [], 'maybe': [], 'no': []}, reminded=False, started=False)
                    self.store.put('events', event['id'], event)
                    actions.append({'kind': 'refresh', 'event': event})
                    continue
                if event['starts'] <= now and not event.get('started'):
                    actions.append({'kind': 'start', 'event': event})
                elif event['starts'] - 1800 <= now < event['starts'] and not event.get('reminded'):
                    actions.append({'kind': 'reminder', 'event': event})
        return actions


def event_embed(event,subject=None):
    labels = {'active': 'Iscrizioni aperte', 'cancelled': 'Annullato', 'completed': 'Concluso'}
    capacity = str(event['capacity']) if event['capacity'] else 'senza limite'
    fields=[('Quando',f'<t:{int(event["starts"])}:F>\n<t:{int(event["starts"])}:R>',False),
            ('Partecipanti',f'{len(event["rsvp"]["yes"])} / {capacity}',True),
            ('Stato',labels[event['status']],True),('Organizzatore',f'<@{event["creator"]}>',True)]
    if event['repeat']!='none':
        fields.append(('Ricorrenza',{'daily':'Giornaliera','weekly':'Settimanale'}[event['repeat']],True))
    embed = card(event['title'],event['description'],section='Lumia / Eventi',subject=subject,fields=fields,
                 level={'cancelled':'danger','completed':'neutral'}.get(event['status'],'info'))
    embed.set_footer(text=f'Evento {event["id"]} · Promemoria solo per Sì/Forse · Le risposte si azzerano a ogni ricorrenza')
    return embed


class RSVPView(discord.ui.View):
    def __init__(self, cog, event):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event['id']
        closed = event['status'] != 'active' or event['starts'] <= time.time()
        for choice, label, style in (('yes', 'Partecipo', discord.ButtonStyle.success),
                                     ('maybe', 'Forse', discord.ButtonStyle.secondary),
                                     ('no', 'Non partecipo', discord.ButtonStyle.danger)):
            button = discord.ui.Button(label=label, style=style, custom_id=f"lumia:event:{event['id']}:{choice}", disabled=closed)
            async def clicked(interaction, selected=choice):
                if (interaction.guild_id != self.cog.bot.cfg.get('guild_id')
                        or not isinstance(interaction.user, discord.Member)):
                    return await respond(interaction, 'Questo pannello è disponibile solo ai membri del server Lumia.')
                await interaction.response.defer(ephemeral=True)
                try:
                    changed = self.cog.service.rsvp(self.event_id, interaction.user.id, selected)
                except ValueError as exc:
                    return await respond(interaction, str(exc))
                await self.cog.refresh(changed)
                await respond(interaction, "Risposta salvata. Puoi cambiarla fino all'inizio dell'evento.")
            button.callback = clicked
            self.add_item(button)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = EventService(bot.store)
        self.panel_locks = defaultdict(asyncio.Lock)

    async def cog_load(self):
        for event in self.service.events():
            if event['status'] == 'active' and event.get('message'):
                self.bot.add_view(RSVPView(self, event), message_id=event['message'])
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()

    async def refresh(self, event):
        async with self.panel_locks[event['id']]:
            await self._refresh(self.service.get(event['id']))

    async def _refresh(self, event):
        guild = self.bot.get_guild(self.bot.cfg.get('guild_id', 0))
        channel = guild.get_channel(event['channel']) if guild else None
        if channel and event.get('message'):
            try:
                await channel.get_partial_message(event['message']).edit(embed=event_embed(event,guild.get_member(event['creator'])), view=RSVPView(self, event))
            except discord.NotFound:
                # Persist the missing panel; event reminders can still use its channel.
                latest = self.service.get(event['id'])
                if latest.get('message') == event['message']:
                    latest['message'] = None
                    self.bot.store.put('events', event['id'], latest)
                await self.bot.log('server_log', f"Pannello evento {event['id']} eliminato; ricrealo con /evento_ripubblica.")
            except discord.HTTPException:
                await self.bot.log('server_log', f"Impossibile aggiornare il pannello evento {event['id']}. Controlla i permessi.")

    @tasks.loop(seconds=30)
    async def scheduler(self):
        for action in self.service.due():
            event = action['event']
            if action['kind'] == 'refresh':
                await self.refresh(event)
                continue
            guild = self.bot.get_guild(self.bot.cfg.get('guild_id', 0))
            channel = guild.get_channel(event['channel']) if guild else None
            if not channel:
                continue
            participants = list(dict.fromkeys(event['rsvp']['yes'] + event['rsvp']['maybe']))
            # Do not ping people who have since left the server.
            participants = [uid for uid in participants if guild.get_member(uid)]
            delivered = self.bot.store.get('event_deliveries', f"{event['id']}:{event['starts']}:{action['kind']}", [])
            pending = [uid for uid in participants if uid not in delivered]
            prefix = 'Inizia tra meno di 30 minuti' if action['kind'] == 'reminder' else 'È il momento di'
            try:
                for offset in range(0, len(pending), 80):
                    batch = pending[offset:offset + 80]
                    await channel.send(' '.join(f'<@{uid}>' for uid in batch),
                                       embed=card(event['title'],prefix,section='Lumia / Eventi',
                                            fields=[('Quando',f'<t:{int(event["starts"])}:F>',False)],
                                            subject=guild.get_member(event['creator'])),
                                       allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[discord.Object(uid) for uid in batch], replied_user=False))
                    delivered.extend(batch)
                    self.bot.store.put('event_deliveries', f"{event['id']}:{event['starts']}:{action['kind']}", delivered)
                self.service.mark_sent(event['id'], action['kind'], event['starts'])
                if action['kind'] == 'start':
                    await self.refresh(self.service.get(event['id']))
            except discord.HTTPException:
                await self.bot.log('server_log', f"Promemoria evento {event['id']} non consegnato: riprovo al prossimo controllo.")

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='evento_crea', description='Crea una demo, riunione o appuntamento con iscrizioni.')
    @app_commands.describe(quando='Data e ora: AAAA-MM-GG HH:MM, nel fuso del server', capienza='0 per nessun limite, massimo 500')
    @app_commands.choices(ricorrenza=[app_commands.Choice(name='Singolo', value='none'), app_commands.Choice(name='Ogni giorno', value='daily'), app_commands.Choice(name='Ogni settimana', value='weekly')])
    async def create_event(self, interaction: discord.Interaction, titolo: str, quando: str, descrizione: str = '', capienza: app_commands.Range[int, 0, 500] = 30, ricorrenza: str = 'none'):
        require(interaction, lambda m: is_management(m, self.bot.cfg))
        channel = interaction.guild.get_channel(self.bot.cfg.get('channels', {}).get('events', 0))
        if not isinstance(channel, discord.TextChannel):
            return await respond(interaction, 'Configura prima il canale eventi con /server allestimento.')
        try:
            timezone = self.bot.cfg.get('timezone', 'Europe/Rome')
            starts = parse_when(quando, timezone)
            event = self.service.create(title=titolo, description=descrizione, starts=starts, timezone=timezone,
                                        repeat=ricorrenza, capacity=capienza, creator=interaction.user.id, channel=channel.id)
        except (ValueError, KeyError) as exc:
            return await respond(interaction, str(exc))
        await interaction.response.defer(ephemeral=True)
        try:
            message = await channel.send(embed=event_embed(event,interaction.user), view=RSVPView(self, event), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            self.service.cancel(event['id'])
            return await respond(interaction, 'Pubblicazione non riuscita. Controlla i permessi del canale eventi; nessun evento è rimasto attivo.')
        event['message'] = message.id
        self.bot.store.put('events', event['id'], event)
        await respond(interaction, f"Evento {event['id']} pubblicato: {message.jump_url}")

    @app_commands.command(name='evento_annulla', description='Annulla un evento e tutti i suoi promemoria.')
    async def cancel_event(self, interaction: discord.Interaction, evento: str):
        require(interaction, lambda m: is_management(m, self.bot.cfg))
        try:
            event = self.service.cancel(evento)
        except ValueError as exc:
            return await respond(interaction, str(exc))
        await interaction.response.defer(ephemeral=True)
        await self.refresh(event)
        await respond(interaction, 'Evento annullato.')

    @app_commands.command(name='evento_ripubblica', description='Ripristina un pannello evento eliminato.')
    async def republish_event(self, interaction: discord.Interaction, evento: str):
        require(interaction, lambda m: is_management(m, self.bot.cfg))
        try:
            event = self.service.get(evento)
        except ValueError as exc:
            return await respond(interaction, str(exc))
        channel = interaction.guild.get_channel(event['channel'])
        if not isinstance(channel, discord.TextChannel) or event['status'] != 'active':
            return await respond(interaction, 'Serve un evento attivo con un canale eventi disponibile.')
        await interaction.response.defer(ephemeral=True)
        # Keep one active panel per event. Update an existing message when possible.
        if event.get('message'):
            try:
                await channel.fetch_message(event['message'])
                await self.refresh(event)
                return await respond(interaction, 'Il pannello esistente è stato aggiornato.')
            except discord.NotFound:
                pass
        message = await channel.send(embed=event_embed(event,interaction.guild.get_member(event['creator'])), view=RSVPView(self, event), allowed_mentions=discord.AllowedMentions.none())
        event['message'] = message.id
        self.bot.store.put('events', event['id'], event)
        await respond(interaction, f'Pannello ripristinato: {message.jump_url}')

    @app_commands.command(name='eventi', description='Mostra i prossimi eventi, demo e riunioni.')
    async def list_events(self, interaction: discord.Interaction):
        events = [e for e in self.service.events() if e['status'] == 'active'][:15]
        lines = [f"**{discord.utils.escape_markdown(e['title'])}** · <t:{int(e['starts'])}:F> · ID `{e['id']}`" for e in events]
        await respond(interaction, '\n'.join(lines) or 'Non ci sono eventi in programma.')


async def setup(bot):
    await bot.add_cog(Events(bot))
