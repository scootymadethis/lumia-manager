import json
import time
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from .common import embed,is_management,respond,require,safe_role
from .presentation import text_card,with_avatar
from .verification import verification_enabled,VerificationModal


def verify_can_join(store,now=None):
    if store.get('security','raid_until',0) > (time.time() if now is None else now):
        raise ValueError('L’accesso dei nuovi membri è temporaneamente sospeso. Riprova più tardi o contatta lo staff.')


async def reply(i,text,**kwargs):
    return await respond(i,text,ephemeral=i.guild_id is not None,**kwargs)


def assignable(guild,role):
    return bool(safe_role(role) and guild.me and guild.me.guild_permissions.manage_roles
                and role < guild.me.top_role)


async def ensure_pending_role(bot,member):
    """Assign only the gate role; missing setup never grants Member."""
    number=bot.cfg['roles'].get('unverified',0)
    current={role.id for role in member.roles}
    if member.bot or not number or bot.cfg['roles'].get('member',0) in current:
        return False
    role=member.guild.get_role(number)
    if not assignable(member.guild,role):
        raise ValueError('Il ruolo Da verificare non è assegnabile. Controlla /server diagnostica.')
    if number not in current:
        await member.add_roles(role,reason='Lumia: accesso in attesa di verifica')
    return True


async def sync_pending_members(bot,guild):
    """Repair gate roles after downtime without granting Member or sending DMs."""
    if guild.id!=bot.cfg['guild_id']:
        raise ValueError('Server non autorizzato.')
    pending=guild.get_role(bot.cfg['roles'].get('unverified',0))
    if not assignable(guild,pending):
        raise ValueError('Configura Da verificare con /server allestimento e controlla la gerarchia del bot.')
    result={'pending':0,'cleaned':0,'failed':0}
    async for member in guild.fetch_members(limit=None):
        if member.bot:
            continue
        current={role.id for role in member.roles}
        try:
            if bot.cfg['roles']['member'] in current:
                if pending.id in current:
                    await member.remove_roles(pending,reason='Lumia: Member già presente')
                    result['cleaned']+=1
            elif pending.id not in current:
                await ensure_pending_role(bot,member)
                result['pending']+=1
        except discord.HTTPException:
            result['failed']+=1
    return result


def private_text(bot,text):
    aliases={'servizi':'services','portfolio':'portfolio','apri-ticket':'ticket_panel','assistenza':'ticket_panel','verifica':'verification',
             'suggerimenti':'suggestions','ruoli':'role_panel'}
    for alias,key in aliases.items():
        number=bot.cfg.get('channels',{}).get(key,0)
        if number:
            text=text.replace('#'+alias,f'[{alias}](https://discord.com/channels/{bot.cfg["guild_id"]}/{number})')
    return text.replace('#regolamento','il regolamento qui in privato').replace('#benvenuto','questo messaggio')


def private_cards(key,text):
    # Send every part: never silently truncate the rules to the embed limit.
    while text:
        end=len(text) if len(text)<=2800 else text.rfind('\n',0,2800)
        if end<=0:
            end=min(len(text),2800)
        yield text_card(key,text[:end])
        text=text[end:].lstrip('\n')


def bind_private_panel(bot,message,member,kind):
    bot.store.put('onboarding_messages',message.id,
                  {'member':member.id,'guild':bot.cfg['guild_id'],'kind':kind})


async def send_preferences(bot,member):
    selected={key for key in ('fivem','minecraft','web','news','release')
              if bot.cfg['roles'].get(key,0) in {r.id for r in member.roles}}
    message=await member.send(embed=with_avatar(embed('I tuoi interessi',
        'Seleziona FiveM, Minecraft e Discord & Web per i tuoi interessi, Novità e Release per le notifiche. '
        'Puoi scegliere più voci o deselezionarle tutte. Usa /preferenze nel server anche con i DM chiusi.'),member),
        view=RolePanel(bot,selected=selected),allowed_mentions=discord.AllowedMentions.none())
    bind_private_panel(bot,message,member,'roles')


async def send_onboarding(bot,member):
    if member.bot or member.guild.id!=bot.cfg['guild_id']:
        return 'ignored'
    try:
        await ensure_pending_role(bot,member)
    except (ValueError,discord.HTTPException):
        await bot.log('server_log',f'Ruolo Da verificare non assegnato a <@{member.id}>. Controlla gerarchia e /server diagnostica.')
    previous=bot.store.get('onboarding_delivery',member.id,{})
    if time.time()-previous.get('sent',0)<60:
        return 'recent'
    try:
        texts=json.loads((Path(__file__).parent.parent/'server_texts.json').read_text(encoding='utf-8'))
        for card in private_cards('welcome',private_text(bot,texts['welcome'])):
            await member.send(embed=with_avatar(card,member),allowed_mentions=discord.AllowedMentions.none())
        rules=list(private_cards('rules',private_text(bot,texts['rules'])))
        if not rules:
            raise ValueError('Il testo del regolamento è vuoto.')
        for index,card in enumerate(rules):
            view=RulesPanel(bot) if index==len(rules)-1 else None
            message=await member.send(embed=with_avatar(card,member),view=view,allowed_mentions=discord.AllowedMentions.none())
            if view:
                bind_private_panel(bot,message,member,'rules')
        if bot.cfg['roles'].get('member',0) in {r.id for r in member.roles}:
            await send_preferences(bot,member)
    except discord.HTTPException:
        verification=bot.cfg['channels'].get('verification',0)
        fallback=f' Può completare la verifica in <#{verification}> anche con i DM chiusi.' if verification else ''
        await bot.log('server_log',f'Onboarding privato non consegnato a <@{member.id}>. '
                      'Può abilitare i messaggi privati dal server e usare /inizia.'+fallback)
        return 'blocked'
    except (OSError,ValueError,KeyError):
        await bot.log('server_log','Onboarding privato non inviato: verifica welcome e rules in server_texts.json.')
        return 'invalid'
    bot.store.put('onboarding_delivery',member.id,{'sent':time.time()})
    return 'sent'


class LocalView(discord.ui.View):
    dm_kind=None
    def __init__(self,bot):
        super().__init__(timeout=None)
        self.bot=bot

    async def interaction_check(self,i):
        if i.guild_id is not None:
            if i.guild_id==self.bot.cfg['guild_id']:
                return True
            await reply(i,'Questo pannello appartiene a un altro server.')
            return False
        message=getattr(i,'message',None)
        entry=self.bot.store.get('onboarding_messages',message.id) if message else None
        if (self.dm_kind and entry and entry.get('member')==i.user.id
                and entry.get('guild')==self.bot.cfg['guild_id'] and entry.get('kind')==self.dm_kind):
            return True
        await reply(i,'Questo pannello non è disponibile per il tuo account. Usa /inizia nel server Lumia.')
        return False

    async def member(self,i):
        guild=self.bot.get_guild(self.bot.cfg['guild_id'])
        if guild is None:
            await reply(i,'Il server non è disponibile. Riprova tra poco.')
            return None
        try:
            # DM interactions contain a User, not a guild Member. Fetch fresh
            # membership and roles before every assignment, also after restarts.
            return await guild.fetch_member(i.user.id)
        except discord.NotFound:
            await reply(i,'Non risulti più membro del server Lumia. Rientra nel server prima di continuare.')
        except discord.HTTPException:
            await reply(i,'Non riesco a verificare la tua presenza nel server. Riprova tra poco.')
        return None

    async def on_error(self,i,error,item):
        await reply(i,'Operazione non riuscita. Lo staff può verificare i permessi del bot.')
        await self.bot.log('server_log',f'Errore pannello: {type(error).__name__}')


class RulesPanel(LocalView):
    dm_kind='rules'
    @discord.ui.button(label='Accetto le regole',style=discord.ButtonStyle.success,custom_id='lumia:rules:accept')
    async def accept(self,i,button):
        try:
            verify_can_join(self.bot.store)
        except ValueError as exc:
            return await reply(i,str(exc))
        if verification_enabled(self.bot.store):
            return await i.response.send_modal(VerificationModal(self.bot,i.user.id,complete_acceptance))
        await i.response.defer(ephemeral=i.guild_id is not None,thinking=True)
        await complete_acceptance(self.bot,i)


class VerificationPanel(LocalView):
    @discord.ui.button(label='Inizia la verifica',style=discord.ButtonStyle.success,custom_id='lumia:verification:start:v1')
    async def verify(self,i,button):
        if i.guild_id!=self.bot.cfg['guild_id']:
            return await reply(i,'Apri la verifica nel server Lumia.')
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            verify_can_join(self.bot.store)
            member=await self.member(i)
            if member is None:
                return
            await ensure_pending_role(self.bot,member)
            texts=json.loads((Path(__file__).parent.parent/'server_texts.json').read_text(encoding='utf-8'))
            rules=list(private_cards('rules',texts['rules']))
            if not rules:
                raise ValueError('Il regolamento non è disponibile. Avvisa lo staff.')
        except (ValueError,OSError,KeyError) as error:
            return await reply(i,str(error))
        for index,part in enumerate(rules):
            await reply(i,None,embed=with_avatar(part,member),view=RulesPanel(self.bot) if index==len(rules)-1 else None)


async def publish_verification_panel(bot,guild):
    channel=guild.get_channel(bot.cfg['channels'].get('verification',0))
    if not isinstance(channel,discord.TextChannel):
        raise ValueError('Configura il canale verifica con /server allestimento.')
    panel=embed('🔓  Benvenuto: verifica il tuo accesso',
        'Hai il ruolo **Da verificare**. Premi «Inizia la verifica», leggi e accetta le regole '
        'e rispondi al semplice controllo. Riceverai **Member** e il ruolo Da verificare verrà rimosso.\n\n'
        'Le risposte sono private. Puoi completare tutto qui anche con i DM chiusi. '
        'Ordini e pagamenti si gestiscono nel sito; Discord è dedicato all’assistenza.')
    options={'embed':panel,'view':VerificationPanel(bot),'allowed_mentions':discord.AllowedMentions.none()}
    number=bot.store.get('panels','verification')
    if number:
        try:
            message=await channel.fetch_message(number)
            await message.edit(content=None,**options)
            return message
        except discord.NotFound:
            pass
    message=await channel.send(**options)
    bot.store.put('panels','verification',message.id)
    return message


async def complete_acceptance(bot,i,verified=False):
    member=await RulesPanel(bot).member(i)
    if member is None:
        return
    try:
        verify_can_join(bot.store)
    except ValueError as exc:
        return await reply(i,str(exc))
    role=member.guild.get_role(bot.cfg['roles']['member'])
    if not assignable(member.guild,role):
        return await reply(i,'Il ruolo Member non è configurato correttamente. Avvisa lo staff.')
    pending_id=bot.cfg['roles'].get('unverified',0)
    pending=member.guild.get_role(pending_id) if pending_id else None
    if pending_id and not assignable(member.guild,pending):
        return await reply(i,'Il ruolo Da verificare non è configurato correttamente. Avvisa lo staff.')
    if role.id not in {r.id for r in member.roles}:
        await member.add_roles(role,reason='Accettazione regolamento Lumia')
    if pending and pending.id in {r.id for r in member.roles}:
        await member.remove_roles(pending,reason='Lumia: verifica completata')
    bot.store.put('rules',i.user.id,{'accepted':time.time(),'verified':time.time() if verified else None})
    await reply(i,'Accesso completato. Il ruolo Member è attivo.')
    try:
        await send_preferences(bot,member)
    except discord.HTTPException:
        await reply(i,'Il ruolo Member è attivo. Usa /preferenze nel server per scegliere gli interessi anche con i DM chiusi.')
        await bot.log('server_log',f'Menu ruoli privato non consegnato a <@{member.id}>.')


class RolePanel(LocalView):
    dm_kind='roles'

    def __init__(self,bot,selected=()):
        super().__init__(bot)
        for option in self.select.options:
            option.default=option.value in selected

    @discord.ui.select(placeholder='Scegli interessi e notifiche',min_values=0,max_values=5,custom_id='lumia:roles:select',options=[
        discord.SelectOption(label='FiveM',value='fivem'),discord.SelectOption(label='Minecraft',value='minecraft'),
        discord.SelectOption(label='Discord & Web',value='web'),
        discord.SelectOption(label='Novità',value='news'),discord.SelectOption(label='Release',value='release')])
    async def select(self,i,select):
        await i.response.defer(ephemeral=i.guild_id is not None,thinking=True)
        member=await self.member(i)
        if member is None:
            return
        if self.bot.cfg['roles']['member'] not in {r.id for r in member.roles}:
            return await reply(i,'Accetta prima il regolamento.')
        keys=('fivem','minecraft','web','news','release')
        selected=set(select.values)
        if not selected.issubset(keys):
            return await reply(i,'Preferenze non valide. Riapri il menu con /inizia.')
        if any(not self.bot.cfg['roles'].get(key,0) for key in selected):
            return await reply(i,'Un interesse non è ancora configurato. Lo staff deve aggiornare /server allestimento.')
        roles={key:member.guild.get_role(self.bot.cfg['roles'].get(key,0)) for key in keys
               if self.bot.cfg['roles'].get(key,0)}
        if any(not assignable(member.guild,r) for r in roles.values()):
            return await reply(i,'Uno dei ruoli selezionabili non è configurato correttamente.')
        current={r.id for r in member.roles}
        add=[r for k,r in roles.items() if k in selected and r.id not in current]
        remove=[r for k,r in roles.items() if k not in selected and r.id in current]
        if remove:
            await member.remove_roles(*remove,reason='Preferenze Lumia')
        if add:
            await member.add_roles(*add,reason='Preferenze Lumia')
        await reply(i,'Preferenze aggiornate. Puoi modificarle con questo menu o /preferenze nel server.')


async def open_preferences(bot,i):
    if i.guild_id!=bot.cfg['guild_id']:
        return await reply(i,'Usa /preferenze nel server Lumia.')
    await i.response.defer(ephemeral=True,thinking=True)
    member=await RolePanel(bot).member(i)
    if member is None:
        return
    if bot.cfg['roles']['member'] not in {r.id for r in member.roles}:
        return await reply(i,'Completa prima la verifica per ricevere Member.')
    selected={key for key in ('fivem','minecraft','web','news','release')
              if bot.cfg['roles'].get(key,0) in {r.id for r in member.roles}}
    await reply(i,None,embed=embed('I tuoi interessi e le notifiche',
        'Scegli solo ciò che ti interessa. Puoi deselezionare tutte le voci. Le risposte sono private e non richiedono DM.'),
        view=RolePanel(bot,selected=selected))


class PreferencesPanel(LocalView):
    @discord.ui.button(label='Scegli interessi e notifiche',style=discord.ButtonStyle.primary,
                       custom_id='lumia:preferences:open:v1')
    async def preferences(self,i,button):
        await open_preferences(self.bot,i)


class PrivateStartPanel(LocalView):
    @discord.ui.button(label='Ricevi benvenuto e regole in privato',style=discord.ButtonStyle.primary,
                       custom_id='lumia:onboarding:open')
    async def start(self,i,button):
        await open_private_onboarding(self.bot,i)


async def open_private_onboarding(bot,i):
    if i.guild_id!=bot.cfg['guild_id']:
        return await reply(i,'Usa /inizia nel server Lumia.')
    await i.response.defer(ephemeral=True,thinking=True)
    guild=bot.get_guild(bot.cfg['guild_id'])
    if guild is None:
        return await reply(i,'Il server non è disponibile. Riprova tra poco.')
    try:
        member=await guild.fetch_member(i.user.id)
    except discord.HTTPException:
        return await reply(i,'Non riesco a verificare la tua presenza nel server. Riprova tra poco.')
    status=await send_onboarding(bot,member)
    messages={
        'sent':'Ti ho inviato benvenuto e regolamento in privato. Accetta le regole lì per ricevere Member e scegliere i tuoi interessi.',
        'recent':'Ti ho già inviato i messaggi privati. Controlla i DM; puoi richiederli di nuovo dopo un minuto.',
        'blocked':'Non riesco a scriverti in privato. Puoi usare il pulsante nel canale di verifica anche con i DM chiusi, oppure abilita i messaggi diretti e usa /inizia.',
        'invalid':'I testi di benvenuto non sono disponibili. Avvisa lo staff.',
        'ignored':'Questo percorso è disponibile per gli utenti del server Lumia.'}
    await reply(i,messages[status])


class Onboarding(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        bot.add_view(RulesPanel(bot))
        bot.add_view(RolePanel(bot))
        bot.add_view(PrivateStartPanel(bot))
        bot.add_view(VerificationPanel(bot))
        bot.add_view(PreferencesPanel(bot))

    @app_commands.command(name='preferenze',description='Scegli interessi e notifiche, anche con i DM chiusi')
    @app_commands.guild_only()
    async def preferences(self,i:discord.Interaction):
        await open_preferences(self.bot,i)

    @app_commands.command(name='inizia',description='Ricevi in privato benvenuto, regolamento e menu dei ruoli')
    @app_commands.guild_only()
    async def start(self,i:discord.Interaction):
        await open_private_onboarding(self.bot,i)

    @app_commands.command(name='pannelli',description='Pubblica i pulsanti per ricevere l’accesso e i ruoli in privato')
    async def panels(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await i.response.defer(ephemeral=True)
        for key,view,title,text in (
            ('verification',VerificationPanel(self.bot),'🔓  Verifica il tuo accesso','Appena entri ricevi Da verificare. Premi «Inizia la verifica», leggi e accetta le regole e rispondi al breve controllo. Il bot assegna Member e rimuove Da verificare.\n\nLa verifica è privata e funziona anche con i DM chiusi. Non servono password o pagamenti.'),
            ('rules',VerificationPanel(self.bot),'📜  Regole e accesso','Leggi e accetta il regolamento dal pulsante qui sotto. Dopo la verifica ricevi Member. Le risposte sono visibili soltanto a te. Puoi anche usare i pulsanti ricevuti in privato.'),
            ('role_panel',PreferencesPanel(self.bot),'🔔  Il tuo spazio, le tue preferenze','Premi qui sotto o usa /preferenze: scegli FiveM, Minecraft, Discord & Web, Novità e Release. La risposta è privata e funziona anche con i DM chiusi.')):
            channel=i.guild.get_channel(self.bot.cfg['channels'][key])
            if not isinstance(channel,discord.TextChannel):
                return await respond(i,f'Configura prima il canale {key} con /server allestimento.')
            old=self.bot.store.get('panels',key)
            if old:
                try:
                    message=await channel.fetch_message(old)
                    await message.edit(embed=embed(title,text),view=view)
                    continue
                except discord.NotFound:
                    pass
            message=await channel.send(embed=embed(title,text),view=view)
            self.bot.store.put('panels',key,message.id)
        await respond(i,'Pannelli pubblicati o aggiornati.')

    @app_commands.command(name='faq',description='Informazioni su preventivi e assistenza Lumia')
    async def faq(self,i:discord.Interaction):
        await respond(i,None,embed=embed('💬  Da un’idea a un progetto',
            '**Cosa realizziamo**\nServer FiveM e Minecraft, script, plugin, gamemode e integrazioni.\n\n'
            '**Vuoi un preventivo?**\nUsa /ordina: il sito raccoglie piattaforma, requisiti, budget e scadenza. Preventivo, ordine e pagamenti PayPal restano nell’area clienti.\n\n'
            '**Hai bisogno di assistenza?**\nIndica l’ordine e descrivi il problema, allegando gli errori utili senza credenziali.\n\n'
            '**Prima di partire**\nPrezzo, tempi, sorgenti e licenza vengono concordati nel preventivo.'))


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
