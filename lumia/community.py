"""Welcomes, conservative invite accounting, maintenance and suggestions."""
import asyncio
import time
import uuid

import discord
from .presentation import card,member_label
from discord import app_commands
from discord.ext import commands, tasks

from .common import is_management, require, respond
from .core import attribute_invite
from .moderation import RaidGuard
from .onboarding import send_onboarding


class InviteTracker:
    def __init__(self, store):
        self.store = store
        # A fresh Discord baseline is essential after downtime; old counts are unsafe.
        self.snapshot = None

    def seed(self, snapshot):
        self.snapshot = snapshot

    def join(self, member_id, snapshot, *, bot=False, now=None):
        now = time.time() if now is None else now
        code = None
        if self.snapshot is not None and snapshot is not None and not bot and set(self.snapshot) == set(snapshot):
            code = attribute_invite({k: v['uses'] for k, v in self.snapshot.items()},
                                    {k: v['uses'] for k, v in snapshot.items()})
        inviter = snapshot[code].get('inviter') if code and snapshot is not None else None
        self.snapshot = snapshot
        with self.store.lock:
            old = self.store.get('community_members', member_id)
            if old and old.get('active'):
                previous = self.store.get('invite_joins', old['join'])
                if previous:
                    previous.update(active=False, left=now)
                    self.store.put('invite_joins', old['join'], previous)
            joined = {'id': uuid.uuid4().hex, 'member': member_id, 'inviter': inviter,
                      'code': code, 'at': now, 'active': True, 'left': None, 'bot': bot}
            self.store.put('invite_joins', joined['id'], joined)
            self.store.put('community_members', member_id, {'join': joined['id'], 'active': True})
        return joined

    def leave(self, member_id, now=None):
        now = time.time() if now is None else now
        with self.store.lock:
            member = self.store.get('community_members', member_id)
            if member and member.get('active'):
                joined = self.store.get('invite_joins', member['join'])
                if joined:
                    joined.update(active=False, left=now)
                    self.store.put('invite_joins', member['join'], joined)
                member['active'] = False
                self.store.put('community_members', member_id, member)

    def totals(self, inviter):
        joins = [j for j in self.store.records('invite_joins').values() if j['inviter'] == inviter and not j.get('bot')]
        active = sum(j['active'] for j in joins)
        return {'total': len(joins), 'active': active, 'left': len(joins) - active}

    def reconcile(self, present_ids, now=None):
        # This is called only with a complete Discord member cache. It can repair
        # known departures during downtime, never reconstruct missed invite credits.
        for key, member in self.store.records('community_members').items():
            if member.get('active') and int(key) not in present_ids:
                self.leave(int(key), now=now)



class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invites = InviteTracker(bot.store)
        self.join_lock = asyncio.Lock()

    async def cog_load(self):
        self.maintenance.start()

    def cog_unload(self):
        self.maintenance.cancel()

    async def snapshot(self, guild):
        try:
            invites = await guild.invites()
            result = {i.code: {'uses': i.uses or 0, 'inviter': i.inviter.id if i.inviter else None} for i in invites}
            if guild.vanity_url_code:
                vanity = await guild.vanity_invite()
                if vanity is None or vanity.uses is None:
                    return None
                result['vanity:' + vanity.code] = {'uses': vanity.uses, 'inviter': None}
            return result
        except discord.HTTPException:
            return None

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(self.bot.cfg.get('guild_id', 0))
        if guild:
            async with self.join_lock:
                # Reconnects may hide joins: reset the baseline instead of inventing credits.
                self.invites.seed(await self.snapshot(guild))
                if guild.chunked:
                    self.invites.reconcile({m.id for m in guild.members})

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != self.bot.cfg.get('guild_id'):
            return
        cfg = self.bot.cfg.get('security', {})
        young = (discord.utils.utcnow() - member.created_at).total_seconds() < max(1, cfg.get('young_days', 7)) * 86400
        raid = RaidGuard(self.bot.store, cfg).join(member.id, young=young)
        # Serializing the snapshot diff avoids attributing a batch to one arbitrary member.
        async with self.join_lock:
            joined = self.invites.join(member.id, await self.snapshot(member.guild), bot=member.bot)
        if raid['triggered']:
            await self.bot.log('mod_log','La verifica Member è temporaneamente in pausa. Nessun ban automatico.',
                title='Protezione anti-raid attiva',level='danger',fields=[
                    ('Ingressi recenti',str(raid['count']),True),('Verifica sospesa fino a',f"<t:{int(raid['until'])}:T>",True),
                    ('Rilevamento','Almeno il 60% degli account nella finestra di controllo è recente.',False)])
        await self.bot.log('server_log','Un nuovo membro è entrato nella community.',title='Nuovo ingresso',level='success',fields=[
            ('Membro',member_label(member.id),True),('Account creato',f'<t:{int(member.created_at.timestamp())}:R>',True),
            ('Invito',member_label(joined['inviter']) if joined['inviter'] else 'Non determinabile',True),
            ('Controlli',f"Account recente: {'sì' if young else 'no'} · Accesso Member: {'in pausa' if raid['active'] else 'disponibile'}",False)])
        await send_onboarding(self.bot,member)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id != self.bot.cfg.get('guild_id'):
            return
        self.invites.leave(member.id)
        await self.bot.log('server_log','Un membro ha lasciato la community.',title='Uscita dal server',level='neutral',fields=[
            ('Membro',member_label(member.id),True),('Account',discord.utils.escape_markdown(str(member)),True)])
        if self.bot.cfg.get('community', {}).get('leave_messages', True):
            channel = member.guild.get_channel(self.bot.cfg.get('channels', {}).get('welcome', 0))
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=card('Un saluto dalla community',f'<@{member.id}> ha lasciato Lumia Development.',level='neutral',subject=member), allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

    @tasks.loop(minutes=10)
    async def maintenance(self):
        # This task does not read or rename any Discord statistics channel.
        # Bound audit deduplication metadata without removing incident history.
        cutoff = time.time() - 86400
        for key, entry in self.bot.store.records('security_seen').items():
            if entry.get('at', 0) < cutoff:
                self.bot.store.delete('security_seen', key)

    @maintenance.before_loop
    async def before_maintenance(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='inviti', description='Mostra gli inviti attribuiti con certezza da quando il bot è attivo.')
    async def invite_stats(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        member = membro or interaction.user
        totals = self.invites.totals(member.id)
        await respond(interaction, f"**Inviti di {discord.utils.escape_markdown(member.display_name)}**\nIngressi confermati: {totals['total']}\nAncora presenti: {totals['active']} · Uscite: {totals['left']}\nSono inclusi solo ingressi tracciati da Lumia Manager. Inviti eliminati, vanity, batch e dati non disponibili restano sconosciuti.")

    @app_commands.command(name='suggerisci', description='Proponi un miglioramento per Lumia Development.')
    async def suggest(self, interaction: discord.Interaction, proposta: str):
        proposal = proposta.strip()
        if not 10 <= len(proposal) <= 1200:
            return await respond(interaction, 'Scrivi una proposta da 10 a 1200 caratteri.')
        channel = interaction.guild.get_channel(self.bot.cfg.get('channels', {}).get('suggestions', 0))
        if not isinstance(channel, discord.TextChannel):
            return await respond(interaction, 'Il canale suggerimenti non è configurato.')
        now = time.time()
        last = self.bot.store.get('suggestion_cooldown', interaction.user.id, 0)
        if now - last < 600:
            return await respond(interaction, 'Puoi inviare una proposta ogni 10 minuti.')
        # Reserve before the first network await so concurrent interactions cannot bypass the cooldown.
        self.bot.store.put('suggestion_cooldown', interaction.user.id, now)
        await interaction.response.defer(ephemeral=True)
        number = uuid.uuid4().hex[:10]
        embed = card('Una nuova idea',proposal,section='Lumia / Suggerimenti',subject=interaction.user,
            fields=[('Autore',member_label(interaction.user.id),True),('Stato','In valutazione',True)])
        embed.set_footer(text=f'Proposta {number}')
        try:
            message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            self.bot.store.put('suggestion_cooldown', interaction.user.id, last)
            return await respond(interaction, 'Pubblicazione non riuscita. Riprova dopo aver controllato i permessi.')
        self.bot.store.put('suggestions', number, {'id': number, 'author': interaction.user.id, 'text': proposal,
                                                'channel': channel.id, 'message': message.id, 'status': 'In valutazione', 'at': now})
        try:
            await message.add_reaction('👍')
            await message.add_reaction('👎')
        except discord.HTTPException:
            pass
        await respond(interaction, f'Proposta pubblicata: {message.jump_url}')

    @app_commands.command(name='suggerimento_stato', description='Aggiorna pubblicamente la decisione su una proposta.')
    @app_commands.choices(stato=[app_commands.Choice(name=s, value=s) for s in ('In valutazione', 'Pianificato', 'Accolto', 'Non previsto')])
    async def suggestion_status(self, interaction: discord.Interaction, proposta: str, stato: str, motivazione: str):
        require(interaction, lambda m: is_management(m, self.bot.cfg))
        suggestion = self.bot.store.get('suggestions', proposta)
        if not suggestion:
            return await respond(interaction, 'Proposta non trovata.')
        if not 3 <= len(motivazione.strip()) <= 500:
            return await respond(interaction, 'Inserisci una motivazione da 3 a 500 caratteri.')
        channel = interaction.guild.get_channel(suggestion['channel'])
        if not isinstance(channel, discord.TextChannel):
            return await respond(interaction, 'Il canale della proposta non è disponibile.')
        await interaction.response.defer(ephemeral=True)
        embed = card(f'Proposta · {stato}',suggestion['text'],section='Lumia / Suggerimenti',
                     level={'Accolto':'success','Non previsto':'neutral','Pianificato':'success'}.get(stato,'info'),
                     subject=interaction.guild.get_member(suggestion['author']),
                     fields=[('Autore',member_label(suggestion['author']),True),('Stato',stato,True)])
        embed.add_field(name='Decisione dello staff', value=motivazione.strip(), inline=False)
        embed.set_footer(text=f'Proposta {proposta}')
        await channel.get_partial_message(suggestion['message']).edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        suggestion.update(status=stato, decision=motivazione.strip(), staff=interaction.user.id)
        self.bot.store.put('suggestions', proposta, suggestion)
        await respond(interaction, 'Decisione pubblicata.')


async def setup(bot):
    await bot.add_cog(Community(bot))
