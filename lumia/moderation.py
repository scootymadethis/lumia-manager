"""Moderation, conservative audit attribution, and a persistent join-rate gate."""
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import discord
from .presentation import member_label
from discord import app_commands
from discord.ext import commands

from .common import is_management, is_moderator, require, respond
from .core import Window


DANGEROUS = ('administrator', 'manage_guild', 'manage_roles', 'manage_channels',
             'ban_members', 'kick_members', 'manage_webhooks', 'moderate_members', 'manage_messages')
AUDIT_ACTIONS = {'channel_create', 'channel_delete', 'role_create', 'role_delete', 'ban',
                 'kick', 'bot_add', 'webhook_create', 'webhook_delete', 'role_update', 'member_role_update'}


def audit_change_is_risky(action, before=None, after=None):
    if action == 'role_update':
        old = getattr(before, 'permissions', None)
        new = getattr(after, 'permissions', None)
        return old is not None and new is not None and any(
            getattr(new, p, False) and not getattr(old, p, False) for p in DANGEROUS)
    if action == 'member_role_update':
        # Discord's audit diff exposes only removed and added roles. Unknown role
        # permissions are deliberately ignored, rather than treating a name as proof.
        return any(any(getattr(getattr(role, 'permissions', None), p, False) for p in DANGEROUS)
                   for role in getattr(after, 'roles', []))
    return action in AUDIT_ACTIONS


def has_permission(member, permission):
    perms = member.guild_permissions
    return bool(getattr(perms, 'administrator', False) or getattr(perms, permission, False))


def moderation_error(actor, target, bot_member, guild_owner, permission):
    if target.id in (actor.id, bot_member.id, guild_owner):
        return 'Non puoi intervenire su te stesso, sul bot o sul proprietario del server.'
    if not has_permission(actor, permission):
        return f'Ti manca il permesso Discord richiesto: {permission}.'
    if actor.id != guild_owner and actor.top_role <= target.top_role:
        return 'Il membro ha un ruolo uguale o superiore al tuo.'
    if not has_permission(bot_member, permission) or bot_member.top_role <= target.top_role:
        return 'Il bot non ha il permesso o un ruolo abbastanza alto per questo membro.'
    if permission == 'moderate_members' and getattr(target.guild_permissions, 'administrator', False):
        return 'Discord non consente il timeout dei membri con Amministratore.'
    return None


def blocked_domain(content, domains):
    hosts = re.findall(r'(?i)(?:https?://|www\.)?([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,})(?=[/:?#\s)>\],!]|$)', content)
    for raw in domains:
        blocked = (urlsplit(raw if '://' in raw else 'https://' + raw).hostname or '').lower().strip('.')
        if blocked.startswith('www.'):
            blocked = blocked[4:]
        if blocked and any(host.lower() == blocked or host.lower().endswith('.' + blocked) for host in hosts):
            return blocked
    return None


class RaidGuard:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg

    def active(self, now=None):
        return self.store.get('security', 'raid_until', 0) > (time.time() if now is None else now)

    def join(self, member_id, *, young=False, now=None):
        now = time.time() if now is None else now
        window = max(1, int(self.cfg.get('join_window', 30)))
        limit = max(2, int(self.cfg.get('join_limit', 8)))
        with self.store.lock:
            joins = [x for x in self.store.get('security', 'joins', []) if x['at'] > now - window]
            joins.append({'member': member_id, 'at': now, 'young': bool(young)})
            self.store.put('security', 'joins', joins[-2000:])
            old_until = self.store.get('security', 'raid_until', 0)
            young_ratio = sum(bool(j.get('young')) for j in joins) / len(joins)
            triggered = len(joins) >= limit and young_ratio >= 0.6
            if triggered:
                until = max(old_until, now + max(60, int(self.cfg.get('raid_seconds', 300))))
                self.store.put('security', 'raid_until', until)
                if old_until <= now:
                    self.store.put('security_incidents', uuid.uuid4().hex, {'kind': 'join_rate', 'at': now, 'count': len(joins), 'young_ratio': young_ratio, 'until': until})
            else:
                until = old_until
        return {'active': until > now, 'triggered': triggered and old_until <= now, 'count': len(joins), 'until': until}


class AuditGuard:
    def __init__(self, store, cfg, owner):
        self.store, self.cfg, self.owner = store, cfg, owner

    def observe(self, entry, now=None):
        now = time.time() if now is None else now
        if entry.get('id') is None or entry.get('action') not in AUDIT_ACTIONS:
            return None
        if entry['action'] in ('role_update', 'member_role_update') and not entry.get('dangerous_grant'):
            return None
        with self.store.lock:
            if self.store.get('security_seen', entry['id']) is not None:
                return None
            observed = {k: entry.get(k) for k in ('id', 'actor', 'action', 'target', 'detail')}
            observed['at'] = now
            self.store.put('security_seen', entry['id'], observed)
            actor = entry.get('actor')
            if actor is None or actor == self.owner or actor in self.cfg.get('whitelist_users', []):
                return None
            window = max(1, int(self.cfg.get('audit_window', 60)))
            previous = [e for e in self.store.get('security_audit', actor, []) if e['at'] > now - window]
            previous.append(observed)
            self.store.put('security_audit', actor, previous[-200:])
            limit = max(2, int(self.cfg.get('audit_limit', 5)))
            if len(previous) < limit:
                return None
            # One incident per actor/window avoids repeatedly stripping roles or flooding logs.
            last = self.store.get('security_alerted', actor, 0)
            if last and now - last < window:
                return None
            incident = {'kind': 'audit_threshold', 'actor': actor, 'at': now, 'entries': previous,
                        'mode': self.cfg.get('mode', 'observe'), 'response': 'observed'}
            self.store.put('security_incidents', entry['id'], incident)
            self.store.put('security_alerted', actor, now)
            return incident


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.spam = Window()
        self.audit = None

    def check(self, interaction, member, permission):
        require(interaction, lambda m: is_moderator(m, self.bot.cfg))
        if not interaction.guild.me:
            raise app_commands.CheckFailure('Il membro bot non è disponibile.')
        error = moderation_error(interaction.user, member, interaction.guild.me, interaction.guild.owner_id, permission)
        if error:
            raise app_commands.CheckFailure(error)

    def reason(self, interaction, text):
        text = text.strip()
        if not 3 <= len(text) <= 400:
            raise app_commands.CheckFailure('Inserisci un motivo da 3 a 400 caratteri.')
        return f'{text} | Staff {interaction.user} ({interaction.user.id})'

    async def record(self, interaction, member, action, reason, **extra):
        case = {'id': uuid.uuid4().hex[:12], 'at': time.time(), 'actor': interaction.user.id,
                'member': member.id, 'action': action, 'reason': reason, **extra}
        self.bot.store.put('moderation_cases', case['id'], case)
        await self.bot.log('mod_log','Intervento registrato nello storico di moderazione.',
            title=action.replace('_',' ').capitalize(),level='danger' if action in ('ban','kick','bando','espulsione') else 'warning',fields=[
                ('Membro',member_label(member.id),True),('Operatore',member_label(interaction.user.id),True),
                ('Motivazione',reason,False),('Caso',f"`{case['id']}`",True)])
        return case

    @app_commands.command(name='avvisa', description='Registra un avvertimento motivato nello storico del membro.')
    async def warn(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        self.check(interaction, membro, 'moderate_members')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        case = await self.record(interaction, membro, 'avvertimento', reason)
        await respond(interaction, f"Avvertimento registrato: caso {case['id']}. Nessun messaggio privato inviato.")

    @app_commands.command(name='storico', description='Mostra gli ultimi interventi di moderazione su un membro.')
    async def history(self, interaction: discord.Interaction, membro: discord.Member):
        require(interaction, lambda m: is_moderator(m, self.bot.cfg))
        if not has_permission(interaction.user, 'moderate_members'):
            raise app_commands.CheckFailure('Serve il permesso Discord Modera membri.')
        cases = sorted((c for c in self.bot.store.records('moderation_cases').values() if c['member'] == membro.id), key=lambda c: c['at'], reverse=True)
        lines = [f"`{c['id']}` · {c['action']} · <t:{int(c['at'])}:d>\n{discord.utils.escape_markdown(c['reason'])[:160]}" for c in cases[:8]]
        await respond(interaction, '\n\n'.join(lines) or 'Nessun intervento registrato da Lumia Manager per questo membro.')

    @app_commands.command(name='timeout', description='Imposta un timeout motivato, fino a 28 giorni.')
    async def timeout(self, interaction: discord.Interaction, membro: discord.Member, minuti: app_commands.Range[int, 1, 40320], motivo: str):
        self.check(interaction, membro, 'moderate_members')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        await membro.timeout(timedelta(minutes=minuti), reason=reason)
        await self.record(interaction, membro, 'timeout', reason, minutes=minuti)
        await respond(interaction, f'Timeout applicato per {minuti} minuti.')

    @app_commands.command(name='rimuovi_timeout', description='Rimuove il timeout di un membro con motivazione.')
    async def untimeout(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        self.check(interaction, membro, 'moderate_members')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        await membro.timeout(None, reason=reason)
        await self.record(interaction, membro, 'rimozione timeout', reason)
        await respond(interaction, 'Timeout rimosso.')

    @app_commands.command(name='espelli', description='Espelle un membro, rispettando permessi e gerarchie.')
    async def kick(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        self.check(interaction, membro, 'kick_members')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        await membro.kick(reason=reason)
        await self.record(interaction, membro, 'espulsione', reason)
        await respond(interaction, 'Membro espulso.')

    @app_commands.command(name='banna', description='Banna un membro con motivazione, senza cancellarne la cronologia.')
    async def ban(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        self.check(interaction, membro, 'ban_members')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        await membro.ban(reason=reason, delete_message_seconds=0)
        await self.record(interaction, membro, 'ban', reason)
        await respond(interaction, 'Membro bannato.')

    @app_commands.command(name='pulisci', description='Elimina fino a 100 messaggi dal canale corrente.')
    async def purge(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, 100], motivo: str):
        require(interaction, lambda m: is_moderator(m, self.bot.cfg))
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise app_commands.CheckFailure('Usa un canale testuale del server.')
        if not channel.permissions_for(interaction.user).manage_messages or not channel.permissions_for(interaction.guild.me).manage_messages:
            raise app_commands.CheckFailure('Tu e il bot dovete avere Gestisci messaggi in questo canale.')
        reason = self.reason(interaction, motivo)
        await interaction.response.defer(ephemeral=True)
        deleted = await channel.purge(limit=numero, reason=reason)
        await self.record(interaction, interaction.user, 'pulizia messaggi', reason, channel=channel.id, count=len(deleted))
        await respond(interaction, f'Eliminati {len(deleted)} messaggi.')

    @app_commands.command(name='sicurezza', description='Mostra la modalità di sicurezza e il blocco temporaneo ingressi.')
    @app_commands.choices(modalita=[app_commands.Choice(name='Solo osservazione audit', value='observe'), app_commands.Choice(name='Rimuovi ruoli pericolosi alla soglia', value='enforce')])
    async def security_status(self, interaction: discord.Interaction, modalita: str | None = None):
        require(interaction, lambda m: is_management(m, self.bot.cfg))
        cfg = self.bot.cfg.setdefault('security', {})
        if modalita is not None:
            if not has_permission(interaction.user, 'manage_guild'):
                raise app_commands.CheckFailure('Serve anche il permesso Discord Gestisci server per cambiare modalità.')
            # Persist independently of the external configuration file, so restarts retain the choice.
            self.bot.store.put('security', 'mode', modalita)
            cfg['mode'] = modalita
            await self.bot.log('mod_log','La configurazione della protezione audit è stata aggiornata.',title='Impostazioni sicurezza',fields=[
                ('Modalità','Osservazione' if modalita=='observe' else 'Intervento sui ruoli pericolosi',True),
                ('Operatore',member_label(interaction.user.id),True)])
        mode = self.bot.store.get('security', 'mode', cfg.get('mode', 'observe'))
        until = self.bot.store.get('security', 'raid_until', 0)
        mode_text = 'osservazione: registra e segnala gli audit' if mode == 'observe' else 'intervento: tenta di rimuovere i ruoli pericolosi modificabili alla soglia'
        gate = f'attivo fino a <t:{int(until)}:T>' if until > time.time() else 'non attivo'
        await respond(interaction, f"Sicurezza audit: **{mode_text}**.\nSoglia: {cfg.get('audit_limit', 5)} azioni in {cfg.get('audit_window', 60)} secondi.\nPausa verifica Member anti-raid: **{gate}**.\nIl blocco temporaneo Member funziona anche in osservazione. Nessun CAPTCHA o ripristino integrale del server è incluso.")

    @commands.Cog.listener()
    async def on_message(self, message):
        cfg = self.bot.cfg.get('automod', {})
        if not cfg.get('enabled') or not message.guild or message.guild.id != self.bot.cfg.get('guild_id') or message.author.bot or message.webhook_id:
            return
        member = message.author
        if not isinstance(member, discord.Member) or is_moderator(member, self.bot.cfg):
            return
        ignored = set(cfg.get('ignore_channels', []))
        if message.channel.id in ignored or getattr(message.channel, 'parent_id', None) in ignored:
            return
        if set(cfg.get('ignore_roles', [])) & {r.id for r in member.roles}:
            return
        count = self.spam.hit((message.guild.id, member.id), max(1, cfg.get('spam_seconds', 8)))
        violation = None
        if count >= max(3, cfg.get('spam_count', 6)):
            violation = 'invio troppo rapido di messaggi'
        elif message.mention_everyone or len({u.id for u in message.mentions}) + len(message.role_mentions) >= max(3, cfg.get('mention_limit', 8)):
            violation = 'menzioni di massa'
        else:
            domain = blocked_domain(message.content, cfg.get('blocked_domains', []))
            if domain:
                violation = f'dominio bloccato: {domain}'
        if not violation:
            return
        me = message.guild.me
        if not me or me.top_role <= member.top_role or member.id == message.guild.owner_id:
            return
        deleted = False
        try:
            if message.channel.permissions_for(me).manage_messages:
                await message.delete()
                deleted = True
            minutes = min(40320, max(0, int(cfg.get('timeout_minutes', 0))))
            if minutes and moderation_error(me, member, me, message.guild.owner_id, 'moderate_members') is None:
                await member.timeout(timedelta(minutes=minutes), reason=f'Lumia automod: {violation}')
        except discord.HTTPException:
            pass
        case = {'id': uuid.uuid4().hex[:12], 'at': time.time(), 'actor': self.bot.user.id, 'member': member.id,
                'action': 'automod', 'reason': violation, 'channel': message.channel.id, 'deleted': deleted}
        self.bot.store.put('moderation_cases', case['id'], case)
        await self.bot.log('mod_log','Il controllo automatico ha rilevato una violazione.',title='Intervento automod',level='warning',fields=[
            ('Membro',member_label(member.id),True),('Canale',f'<#{message.channel.id}>',True),
            ('Rilevamento',violation,False),('Messaggio eliminato','Sì' if deleted else 'No',True),('Caso',f"`{case['id']}`",True)])

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        if entry.guild.id != self.bot.cfg.get('guild_id') or entry.action.name not in AUDIT_ACTIONS:
            return
        if not audit_change_is_risky(entry.action.name, entry.before, entry.after):
            return
        # This event supplies the exact Discord entry. Never infer an actor from the latest audit item.
        actor_id = entry.user.id if entry.user else None
        if actor_id == getattr(self.bot.user, 'id', None):
            return
        cfg = dict(self.bot.cfg.get('security', {}))
        cfg['mode'] = self.bot.store.get('security', 'mode', cfg.get('mode', 'observe'))
        guard = AuditGuard(self.bot.store, cfg, entry.guild.owner_id)
        incident = guard.observe({'id': entry.id, 'actor': actor_id, 'action': entry.action.name,
                                  'target': getattr(entry.target, 'id', None),
                                  'dangerous_grant': entry.action.name in ('role_update', 'member_role_update'),
                                  'detail': {'granted_roles': [r.id for r in getattr(entry.after, 'roles', [])]}})
        if incident is None:
            return
        response = 'Solo segnalazione: nessun ruolo rimosso.'
        if cfg['mode'] == 'enforce':
            actor = entry.guild.get_member(actor_id)
            me = entry.guild.me
            if actor and me and actor.id != entry.guild.owner_id and actor.top_role < me.top_role and me.guild_permissions.manage_roles:
                roles = [r for r in actor.roles if not r.managed and not r.is_default() and r < me.top_role
                         and any(getattr(r.permissions, p, False) for p in DANGEROUS)]
                if roles:
                    incident['role_candidates'] = [r.id for r in roles]
                    try:
                        await actor.remove_roles(*roles, reason=f'Lumia: soglia audit, evento {entry.id}', atomic=True)
                        response = 'Ruoli pericolosi rimossi: ' + ', '.join(str(r.id) for r in roles)
                    except discord.HTTPException:
                        response = 'Rimozione ruoli fallita: controllare subito permessi e gerarchia.'
                else:
                    response = 'Nessun ruolo pericoloso modificabile.'
            else:
                response = 'Attore assente o protetto dalla gerarchia; intervento manuale richiesto.'
        incident['response'] = response
        self.bot.store.put('security_incidents', entry.id, incident)
        details = ', '.join(f"{e['action']}→{e['target']} (audit {e['id']})" for e in incident['entries'][-8:])
        await self.bot.log('mod_log','Raggiunta la soglia di azioni sensibili nel registro audit.',title='Allerta sicurezza',level='danger',fields=[
            ('Attore confermato',member_label(actor_id),True),('Modalità',cfg['mode'],True),
            ('Azioni rilevate',details,False),('Esito',response,False)])


async def setup(bot):
    await bot.add_cog(Moderation(bot))
