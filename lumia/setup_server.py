"""Setup confirmed by the guild owner or explicitly configured owner IDs."""
import json
import re
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from .common import respond,require,is_management,embed
from .presentation import card,channel_name,small_caps,text_card,log_card,COLORS,with_avatar,message_subject,dashboard_view

ROLE_DEFS=(
 ('member','Member',0xCBD5E1),('fivem','FiveM',0x64748B),('minecraft','Minecraft',0x64748B),
 ('news','News Ping',0x64748B),('release','Release Ping',0x64748B),('customer','Customer',0xA78BFA),
 ('developer','Developer',0x93C5FD),('support','Support',0x34D399),('moderator','Moderator',0xF59E0B),('management','Management',0x38BDF8))
ROLE_DEFS=tuple((key,label+' ®',color) for key,label,color in ROLE_DEFS)
CAT_NAMES={'start':'INIZIA DA QUI','info':'LUMIA DEVELOPMENT','community':'COMMUNITY','tickets':'TICKET APERTI','private_tickets':'TICKET RISERVATI','staff':'STAFF E GESTIONE'}
CHANNEL_DEFS=(
 ('welcome','👋・benvenuto','start'),('rules','📜・regolamento','start'),
 ('announcements','📢・annunci','info'),('services','🛠・servizi','info'),('portfolio','🎨・portfolio','info'),
 ('faq','❓・faq','info'),('role_panel','🔔・ruoli','info'),('ticket_panel','🎫・apri-ticket','info'),('events','📅・eventi','info'),
 ('suggestions','💡・suggerimenti','community'),('general','💬・generale','community'),
 ('transcripts','📁・trascrizioni','staff'),('mod_log','🛡・mod-log','staff'),('server_log','📡・server-log','staff'),('staff_orders','📋・commissioni','staff'))
CHANNEL_DEFS=tuple((key,channel_name(label),category) for key,label,category in CHANNEL_DEFS)
CAT_NAMES={key:small_caps(label) for key,label in CAT_NAMES.items()}
CHANNEL_TOPICS={
 'welcome':'Benvenuto in Lumia Development. Il tuo prossimo progetto inizia qui.',
 'rules':'Regole della community e accesso ai canali.',
 'announcements':'Novità ufficiali, aggiornamenti e comunicazioni del team.',
 'services':'FiveM, Minecraft, script, gamemode e sviluppo su misura.',
 'portfolio':'Lavori, demo e anteprime condivisi dal team Lumia.',
 'faq':'Preventivi, tempi, consegne e assistenza: le domande frequenti.',
 'role_panel':'Personalizza i tuoi interessi e le notifiche che ricevi.',
 'ticket_panel':'Un canale dedicato per il tuo progetto o per ricevere assistenza.',
 'events':'Appuntamenti, demo e sessioni della community.',
 'suggestions':'Proponi un miglioramento e confrontati con la community.',
 'general':'Parliamo di sviluppo, server e nuove idee. Benvenuto nella community.',
 'transcripts':'Archivio riservato delle trascrizioni dei ticket.',
 'mod_log':'Registro riservato: moderazione, automod e sicurezza.',
 'server_log':'Registro riservato: ingressi, uscite e stato dei servizi.',
 'staff_orders':'Area riservata: commissioni, aggiornamenti e movimenti amministrativi.',
}


def style_targets(cfg,registry):
    """Resolve existing Lumia destinations by ID, preferring current configuration."""
    targets=[]
    for key,label in CAT_NAMES.items():
        number=cfg['categories'].get(key,0) or registry.get('cat:'+key,0)
        if number:
            targets.append((number,label,None))
    for key,label,_ in CHANNEL_DEFS:
        number=cfg['channels'].get(key,0) or registry.get('channel:'+key,0)
        if number:
            targets.append((number,label,CHANNEL_TOPICS.get(key)))
    if registry.get('lounge'):
        targets.append((registry['lounge'],channel_name('🔊・lounge'),None))
    return targets


def category_policy(kind):
    return {'tickets':('management','support'),'private_tickets':('management',),'staff':('management',)}.get(kind,('member','management','support','moderator','developer'))


def role_permissions(key):
    if key in ('management','moderator'):
        return discord.Permissions(moderate_members=True,manage_messages=True,kick_members=True,ban_members=True,view_audit_log=True,manage_guild=key=='management')
    return discord.Permissions.none()


def role_position_map(roles):
    ordered=[roles[key] for key,_,_ in ROLE_DEFS if key in roles]
    return {role:index+1 for index,role in enumerate(ordered)}


def can_setup(interaction,cfg):
    guild=interaction.guild
    return bool(guild and guild.id==cfg['guild_id'] and interaction.guild_id==guild.id
                and (interaction.user.id==guild.owner_id or interaction.user.id in cfg.get('owner_ids',[])))


class SetupConfirm(discord.ui.View):
    def __init__(self,cog,owner):
        super().__init__(timeout=180)
        self.cog,self.owner=cog,owner
        self.applied=False

    @discord.ui.button(label='Crea la struttura Lumia',style=discord.ButtonStyle.success)
    async def apply(self,i,button):
        if i.user.id != self.owner or not can_setup(i,self.cog.bot.cfg):
            return await respond(i,'Può confermare solo chi ha richiesto l’allestimento ed è proprietario del server o autorizzato in owner_ids.')
        await i.response.defer(ephemeral=True)
        async with self.cog.lock:
            if not can_setup(i,self.cog.bot.cfg):
                return await respond(i,'La tua autorizzazione all’allestimento è stata rimossa.')
            if self.applied:
                return await respond(i,'Questa conferma è già stata utilizzata. Per un nuovo allestimento ripeti /server allestimento.')
            self.applied=True
            self.stop()
            button.disabled=True
            try:
                await self.cog.build(i.guild)
            except discord.HTTPException:
                await respond(i,'Allestimento interrotto. Le risorse già create sono registrate: controlla i permessi e ripeti il comando. Nessun canale precedente è stato eliminato.')
                raise
        await respond(i,'Struttura creata. Assegna manualmente i ruoli al team, poi usa /server testi, /pannelli e /ticket pannello. Il nome e l’icona si cambiano dalle impostazioni del server.')


class ServerSetup(commands.Cog):
    server=app_commands.Group(name='server',description='Allestimento e diagnostica Lumia')

    def __init__(self,bot):
        import asyncio
        self.bot=bot
        self.lock=asyncio.Lock()

    def member_role(self,guild):
        number=self.bot.cfg['roles'].get('member',0)
        role=guild.get_role(number) if number else None
        if role is None:
            raise ValueError(f'Il ruolo membro configurato ({number}) non esiste. Inserisci in roles.member l’ID del ruolo già presente: non verrà creato un sostituto.')
        if role.is_default() or role.managed:
            raise ValueError('Il ruolo membro deve essere un ruolo assegnabile: non @everyone o un ruolo gestito da un’app.')
        return role

    async def apply_role_style(self,guild):
        member=self.member_role(guild)
        registry=self.bot.store.get('setup','resources',{})
        updated=0
        for key,label,_ in ROLE_DEFS:
            role=member if key=='member' else guild.get_role(self.bot.cfg['roles'].get(key,0) or registry.get('role:'+key,0))
            if role is not None and not role.managed and not role.is_default() and role.name!=label:
                await role.edit(name=label,reason='Lumia: aggiornamento nomi ruoli')
                updated+=1
        return updated

    async def migrate_member_access(self,guild,registry):
        """Move only the old Lumia member overwrite on bot-owned public resources."""
        member=self.member_role(guild)
        previous=registry.get('member_access_role',registry.get('role:member',0))
        if not previous:
            registry['member_access_role']=member.id
            self.bot.store.put('setup','resources',registry)
            return
        if previous==member.id:
            return
        public={key for key in CAT_NAMES if 'member' in category_policy(key)}
        numbers={registry.get('cat:'+key) for key in public
                 if self.bot.cfg['categories'].get(key,registry.get('cat:'+key))==registry.get('cat:'+key)}
        numbers.update(registry.get('channel:'+key) for key,_,cat in CHANNEL_DEFS if cat in public
                       and self.bot.cfg['channels'].get(key,registry.get('channel:'+key))==registry.get('channel:'+key))
        for number in numbers-{None,0}:
            channel=guild.get_channel(number)
            if not isinstance(channel,(discord.TextChannel,discord.CategoryChannel)):
                continue
            overwrites=dict(channel.overwrites)
            old=next((target for target in overwrites if target.id==previous),None)
            if old is None:
                continue
            access=overwrites.pop(old)
            # Preserve any deliberate permissions already set on the selected role.
            if member not in overwrites:
                overwrites[member]=access
            await channel.edit(overwrites=overwrites,reason='Lumia: riutilizzo del ruolo membro esistente')
        registry['member_access_role']=member.id
        self.bot.store.put('setup','resources',registry)

    @server.command(name='allestimento',description='Mostra e conferma la creazione di ruoli e canali Lumia')
    async def prepare(self,i:discord.Interaction):
        if not can_setup(i,self.bot.cfg):
            raise app_commands.CheckFailure('Allestimento riservato al proprietario del server e agli account autorizzati in owner_ids, nel server configurato.')
        self.member_role(i.guild)
        permissions=i.guild.me.guild_permissions
        if not permissions.manage_channels or not permissions.manage_roles:
            return await respond(i,'Servono Gestisci canali e Gestisci ruoli. Posiziona il ruolo del bot sopra i ruoli che dovrà gestire.')
        await respond(i,None,embed=card('✦  Il nuovo spazio Lumia',
            'Una struttura dedicata ai progetti e alla community, con nomi come **🎫・ᴀᴘʀɪ-ᴛɪᴄᴋᴇᴛ**.\n\n'
            'Le risorse Lumia già create vengono riutilizzate e aggiornate nello stile. Conferma per procedere.',
            fields=[('Struttura',f'{len(ROLE_DEFS)} ruoli (membro esistente incluso) · {len(CAT_NAMES)} categorie · {len(CHANNEL_DEFS)} canali di testo',False),
                    ('Spazi dedicati','Community, Lounge, ticket privati e area staff. Statistiche gestite da ServerStats.',False)]),view=SetupConfirm(self,i.user.id))

    async def build(self,guild):
        cfg=self.bot.cfg
        member=self.member_role(guild)
        registry=self.bot.store.get('setup','resources',{})

        def checkpoint():
            self.bot.store.put('setup','resources',registry)
            self.bot.save_config()

        resolved_roles={}
        for key,label,color in ROLE_DEFS:
            role=member if key=='member' else guild.get_role(cfg['roles'].get(key,0) or registry.get('role:'+key,0))
            if role is None:
                role=await guild.create_role(name=label,color=discord.Color(color),permissions=role_permissions(key),hoist=key in ('management','developer','support','customer'),reason='Allestimento Lumia confermato da un responsabile autorizzato')
                cfg['roles'][key]=role.id
                registry['role:'+key]=role.id
                checkpoint()
            elif cfg['roles'].get(key)!=role.id:
                cfg['roles'][key]=role.id
                checkpoint()
            resolved_roles[key]=role
        await self.apply_role_style(guild)
        owned_roles={key:role for key,role in resolved_roles.items() if key!='member' and registry.get('role:'+key)==role.id}
        if owned_roles:
            await guild.edit_role_positions(positions=role_position_map(owned_roles),reason='Gerarchia dei ruoli Lumia creati dal bot')
        categories={}
        for key,label in CAT_NAMES.items():
            channel=guild.get_channel(cfg['categories'].get(key,0) or registry.get('cat:'+key,0))
            if channel is None:
                everyone=discord.PermissionOverwrite(view_channel=(key=='start'),send_messages=False,create_public_threads=False,create_private_threads=False)
                overwrites={guild.default_role:everyone,guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)}
                for rolekey in category_policy(key):
                    role=resolved_roles[rolekey]
                    overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=(key in ('community','staff','tickets','private_tickets')),read_message_history=True)
                channel=await guild.create_category(label,overwrites=overwrites,reason='Allestimento Lumia')
                registry['cat:'+key]=channel.id
                if key in cfg['categories']:
                    cfg['categories'][key]=channel.id
                checkpoint()
            if not isinstance(channel,discord.CategoryChannel):
                raise ValueError('Una categoria registrata non è più valida.')
            categories[key]=channel
        for key,label,cat in CHANNEL_DEFS:
            current=guild.get_channel(cfg['channels'].get(key,0) or registry.get('channel:'+key,0))
            if current is None:
                current=await guild.create_text_channel(label,category=categories[cat],topic=CHANNEL_TOPICS.get(key),slowmode_delay=5 if key=='general' else 0,reason='Allestimento Lumia')
                if key in cfg['channels']:
                    cfg['channels'][key]=current.id
                registry['channel:'+key]=current.id
                checkpoint()
        if not guild.get_channel(registry.get('lounge',0)):
            lounge=await guild.create_voice_channel(channel_name('🔊・lounge'),category=categories['community'],reason='Allestimento Lumia')
            registry['lounge']=lounge.id
            checkpoint()
        await self.migrate_member_access(guild,registry)
        await self.apply_style(guild)

    async def apply_style(self,guild,*,topics=True):
        updated=0
        targets=style_targets(self.bot.cfg,self.bot.store.get('setup','resources',{}))
        for ticket in self.bot.store.tickets() if hasattr(self.bot.store,'tickets') else []:
            number=ticket.get('channel')
            channel=guild.get_channel(number) if number else None
            if isinstance(channel,discord.TextChannel):
                targets.append((number,channel_name(channel.name),None))
        counter=self.bot.cfg['channels'].get('member_counter',0)
        retired=self.bot.store.get('community_features','retired_counter',{})
        excluded={counter,retired.get('channel',0)}
        seen=set()
        for number,name,topic in targets:
            if number in seen or number in excluded:
                continue
            seen.add(number)
            channel=guild.get_channel(number)
            if not isinstance(channel,(discord.TextChannel,discord.CategoryChannel,discord.VoiceChannel)):
                continue
            changes={}
            # Discord may lowercase an ASCII Q in a text-channel name.
            if channel.name!=name and channel.name!=name.replace('Q','q'):
                changes['name']=name
            if topics and topic is not None and isinstance(channel,discord.TextChannel) and channel.topic!=topic:
                changes['topic']=topic
            if changes:
                await channel.edit(**changes,reason='Lumia: aggiornamento stile canali')
                updated+=1
        return updated

    async def retire_counter(self,guild):
        """Detach statistics; delete only an empty voice channel proven Lumia-owned."""
        store=self.bot.store
        registry=store.get('setup','resources',{})
        previous=store.get('community_features','retired_counter',{})
        if not self.bot.cfg['channels'].get('member_counter',0) and previous.get('removed'):
            return {'removed':False,'review':0}
        number=self.bot.cfg['channels'].get('member_counter',0) or previous.get('channel',0)
        if not number:
            return {'removed':False,'review':0}
        channel=guild.get_channel(number)
        prefix=channel_name('👥・membri-')
        label=channel_name(channel.name) if channel else ''
        legacy_name=label.startswith(prefix) and label[len(prefix):].isdigit()
        owned=registry.get('channel:member_counter')==number or registry.get('member_counter')==number
        me=guild.me
        if legacy_name and isinstance(channel,discord.VoiceChannel) and not channel.members and not owned and me and me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(limit=200,action=discord.AuditLogAction.channel_create):
                    if getattr(entry.target,'id',None)==number:
                        owned=bool(entry.user and entry.user.id==me.id)
                        break
            except discord.HTTPException:
                pass
        removed=False
        if owned and legacy_name and isinstance(channel,discord.VoiceChannel) and not channel.members:
            try:
                await channel.delete(reason='Lumia: contatore dismesso, statistiche gestite da ServerStats')
                removed=True
            except discord.HTTPException:
                pass
        if self.bot.cfg['channels'].get('member_counter',0):
            self.bot.cfg['channels']['member_counter']=0
            self.bot.save_config()
        registry.pop('channel:member_counter',None)
        registry.pop('member_counter',None)
        store.put('setup','resources',registry)
        store.put('community_features','retired_counter',{'channel':number,'removed':removed or not channel})
        return {'removed':removed,'review':number if channel and not removed else 0}

    @server.command(name='canali',description='Rinomina i canali Lumia esistenti e disattiva il vecchio contatore')
    async def channels(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        if not i.guild or i.guild.id!=self.bot.cfg['guild_id']:
            raise app_commands.CheckFailure('Comando disponibile solo nel server Lumia configurato.')
        await i.response.defer(ephemeral=True)
        async with self.lock:
            updated=await self.apply_style(i.guild,topics=False)
            retired=await self.retire_counter(i.guild)
        fields=[('Canali e categorie aggiornati',str(updated),True),
                ('Commissioni',channel_name('📋・commissioni'),True),
                ('Statistiche','Gestite da ServerStats. Contatore e comando statistiche Lumia disattivati.',False)]
        if retired['removed']:
            fields.append(('Vecchio contatore Lumia','Eliminato: canale vocale vuoto creato da Lumia.',False))
        elif retired['review']:
            fields.append(('Contatore precedente',f'<#{retired["review"]}> non è più gestito da Lumia. Controllalo prima di eliminarlo: la proprietà o l’assenza di utenti non è verificata.',False))
        await respond(i,None,embed=card('Canali aggiornati',
            'Nomi aggiornati sugli stessi canali. ID, messaggi, permessi e collegamenti rimangono invariati.',
            level='success',fields=fields))

    @server.command(name='stile',description='Aggiorna i nomi dei ruoli Lumia e lo stile dei canali')
    async def style(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await i.response.defer(ephemeral=True)
        async with self.lock:
            roles_updated=await self.apply_role_style(i.guild)
            updated=await self.apply_style(i.guild)
            await self.retire_counter(i.guild)
        await respond(i,None,embed=card('✦  Lo stile Lumia è pronto',
            f'**{roles_updated}** ruoli e **{updated}** canali o categorie aggiornati.\n\n'
            'Per aggiornare anche i messaggi già pubblicati:\n'
            '**1.** `/server testi` — presentazione, servizi e regolamento\n'
            '**2.** `/pannelli` — accesso e interessi\n'
            '**3.** `/ticket pannello` — apertura richieste\n\n'
            'I nuovi log useranno automaticamente le schede aggiornate.',level='success'))

    @server.command(name='anteprima',description='Mostra un esempio del nuovo stile dei log senza pubblicarlo')
    async def preview(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await respond(i,None,embed=log_card('mod_log','Esempio dimostrativo: nessuna azione è stata eseguita.',
            title='Avvertimento registrato',level='warning',fields=[
                ('Membro','Mario · @mario\n`123456789`',True),('Operatore','Team Lumia',True),
                ('Motivazione','Messaggi ripetuti nel canale generale.',False),('Caso','`ESEMPIO-001`',True)]))

    @server.command(name='testi',description='Pubblica i testi ufficiali nei canali Lumia configurati')
    async def texts(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await i.response.defer(ephemeral=True)
        texts=json.loads((Path(__file__).parent.parent/'server_texts.json').read_text(encoding='utf-8'))
        published=0
        for key,content in texts.items():
            if key in ('welcome','rules'):
                content=('**Benvenuto in Lumia Development**\n\n' if key=='welcome' else '**Regolamento e accesso**\n\n')+(
                    'Benvenuto e regolamento vengono inviati in privato all’ingresso. '
                    'Usa /inizia per riceverli di nuovo. Dopo aver accettato le regole nei DM, '
                    'il bot assegna Member e invia il menu interessi e notifiche.\n\n'
                    'Se i DM non arrivano, abilita i messaggi diretti dal server e riprova.')
            for alias,channelkey in {'benvenuto':'welcome','regolamento':'rules','servizi':'services','portfolio':'portfolio','apri-ticket':'ticket_panel','suggerimenti':'suggestions'}.items():
                number=self.bot.cfg['channels'].get(channelkey,0)
                if number:
                    content=content.replace('#'+alias,f'<#{number}>')
            channel=i.guild.get_channel(self.bot.cfg['channels'].get(key,0))
            if not isinstance(channel,discord.TextChannel):
                continue
            old=self.bot.store.get('texts',key)
            if old:
                try:
                    msg=await channel.fetch_message(old)
                    await msg.edit(content=None,embed=text_card(key,content),allowed_mentions=discord.AllowedMentions.none())
                    published+=1
                    continue
                except discord.NotFound:
                    pass
            msg=await channel.send(embed=text_card(key,content),allowed_mentions=discord.AllowedMentions.none())
            self.bot.store.put('texts',key,msg.id)
            published+=1
        await respond(i,f'Testi pubblicati o aggiornati in {published} canali.')

    @server.command(name='embed',description='Aggiorna lo stile degli ultimi 20 messaggi del bot per canale configurato')
    async def refresh_embeds(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await i.response.defer(ephemeral=True,thinking=True)
        numbers={n for n in self.bot.cfg['channels'].values() if n}
        numbers.update(t['channel'] for t in self.bot.store.tickets() if t.get('channel'))
        old_colors={0x93C5FD:COLORS['info'],0x6EE7B7:COLORS['success'],0xFBBF24:COLORS['warning'],
                    0xFB7185:COLORS['danger'],0xCBD5E1:COLORS['neutral']}
        updated=failed=0
        for number in numbers:
            channel=i.guild.get_channel(number)
            if not isinstance(channel,discord.TextChannel):
                continue
            try:
                async for message in channel.history(limit=20):
                    if message.author.id!=self.bot.user.id or not message.embeds:
                        continue
                    results=[]
                    order_id=None
                    changed=False
                    for original in message.embeds:
                        item=original.copy()
                        if item.type=='rich':
                            if item.colour and item.colour.value in old_colors:
                                item.colour=old_colors[item.colour.value]
                            for index,field in enumerate(item.fields):
                                value=re.sub(r'(<@!?(\d+)>)\s*\n`\2`',r'\1',field.value)
                                item.set_field_at(index,name=field.name,value=value,inline=field.inline)
                                if field.name.lower()=='ordine':
                                    match=re.search(r'#(\d+)',value)
                                    if match and self.bot.orders.get(int(match[1])):
                                        order_id=int(match[1])
                            subject=message_subject(self.bot,item.description or '',[(f.name,f.value,f.inline) for f in item.fields])
                            with_avatar(item,subject)
                        changed=changed or item.to_dict()!=original.to_dict()
                        results.append(item)
                    view=dashboard_view(order_id) if order_id and not message.components else None
                    if changed or view:
                        kwargs={'embeds':results,'allowed_mentions':discord.AllowedMentions.none()}
                        if view:
                            kwargs['view']=view
                        await message.edit(**kwargs)
                        updated+=1
            except discord.HTTPException:
                failed+=1
        await respond(i,None,embed=card('Stile aggiornato',fields=[('Messaggi',str(updated),True),
            ('Canali non accessibili',str(failed),True)],footer='Solo messaggi del bot · Nessuna modifica agli incassi'))

    @server.command(name='diagnostica',description='Controlla configurazione, ruoli e servizi')
    async def diagnostics(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        missing=[]
        for key,number in self.bot.cfg['channels'].items():
            if key=='member_counter':
                continue  # Legacy key retained only to migrate old installations.
            if not i.guild.get_channel(number):
                missing.append('Canale '+key)
        for key,number in self.bot.cfg['roles'].items():
            role=i.guild.get_role(number)
            if not role:
                missing.append('Ruolo '+key)
            elif role>=i.guild.me.top_role:
                missing.append('Gerarchia ruolo '+key)
        perms=i.guild.me.guild_permissions
        for name in ('manage_channels','manage_roles','view_channel','send_messages','read_message_history','attach_files','embed_links'):
            if not getattr(perms,name):
                missing.append('Permesso '+name)
        await respond(i,'**Diagnostica Lumia**\n'+('\n'.join(missing)[:1700] if missing else 'Configurazione principale presente. Verifica anche i permessi specifici dei canali e prova un ticket con due utenti.'))


async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
