"""Read-only operational checks for the configured Discord guild."""
import discord
from .common import safe_role

PUBLIC_ROLES = ('member','unverified','customer','fivem','minecraft','web','news','release')


async def inspect_discord(bot, guild):
    issues = []
    cfg = bot.cfg
    if not bot.is_ready():
        issues.append('Gateway Discord non pronto: il bot non è ancora operativo.')
    if guild.me is None:
        return issues + ['Il membro bot non è disponibile nel server.']
    for key, number in cfg['roles'].items():
        role = guild.get_role(number) if number else None
        if role is None:
            issues.append('Ruolo mancante: ' + key)
            continue
        if not role < guild.me.top_role:
            issues.append('Gerarchia ruolo: ' + key)
        if key in PUBLIC_ROLES and not safe_role(role):
            issues.append('Ruolo pubblico non sicuro: ' + key)
    for key, number in cfg['channels'].items():
        if key == 'member_counter':
            continue
        channel = guild.get_channel(number) if number else None
        if channel is None:
            issues.append('Canale mancante: ' + key)
            continue
        if not isinstance(channel, discord.TextChannel):
            issues.append('Canale testuale atteso: ' + key)
            continue
        effective = channel.permissions_for(guild.me)
        for permission in ('view_channel','send_messages','read_message_history','embed_links','attach_files'):
            if not getattr(effective, permission):
                issues.append(f'{key}: manca {permission} effettivo')
        if key in ('transcripts','mod_log','server_log','staff_orders'):
            if channel.permissions_for(guild.default_role).view_channel:
                issues.append(f'{key}: registro accessibile pubblicamente a @everyone')
            for rolekey in PUBLIC_ROLES:
                role = guild.get_role(cfg['roles'].get(rolekey, 0))
                if role and channel.permissions_for(role).view_channel:
                    issues.append(f'{key}: registro accessibile al ruolo {rolekey}')
    for permission in ('manage_channels','manage_roles','view_audit_log'):
        if not getattr(guild.me.guild_permissions, permission):
            issues.append('Permesso generale mancante: ' + permission)
    for key in ('verification','rules','role_panel'):
        channel = guild.get_channel(cfg['channels'].get(key, 0))
        number = bot.store.get('panels', key)
        if not number:
            issues.append('Pannello ' + key + ' non registrato: usa /pannelli')
        elif isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(number)
                if not message.components:
                    issues.append('Pannello ' + key + ' senza pulsanti: usa /pannelli')
            except discord.NotFound:
                issues.append('Pannello ' + key + ' eliminato: usa /pannelli')
            except discord.HTTPException:
                issues.append('Pannello ' + key + ' non leggibile')
    for cogname, loopname in (('Notifications','worker'),('Events','scheduler'),
                              ('OrderCommands','payment_reminders'),('Community','maintenance')):
        cog = bot.get_cog(cogname)
        task = getattr(cog, loopname, None) if cog else None
        if task is None or not task.is_running() or task.failed():
            issues.append('Processo periodico non attivo: ' + cogname)
    if bot.store.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        issues.append('Database: controllo integrità fallito; verifica i backup.')
    return issues
