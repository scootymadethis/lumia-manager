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


def private_text(bot,text):
    aliases={'servizi':'services','portfolio':'portfolio','apri-ticket':'ticket_panel',
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
    selected={key for key in ('fivem','minecraft','news','release')
              if bot.cfg['roles'].get(key,0) in {r.id for r in member.roles}}
    message=await member.send(embed=with_avatar(embed('I tuoi interessi',
        'Seleziona FiveM e Minecraft per i tuoi interessi, Novità e Release per le notifiche. '
        'Puoi scegliere più voci o deselezionarle tutte. Per riaprire questo menu usa /inizia nel server.'),member),
        view=RolePanel(bot,selected=selected),allowed_mentions=discord.AllowedMentions.none())
    bind_private_panel(bot,message,member,'roles')


async def send_onboarding(bot,member):
    if member.bot or member.guild.id!=bot.cfg['guild_id']:
        return 'ignored'
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
        await bot.log('server_log',f'Onboarding privato non consegnato a <@{member.id}>. '
                      'Può abilitare i messaggi privati dal server e usare /inizia. Nessun benvenuto pubblico inviato.')
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
    if role.id not in {r.id for r in member.roles}:
        await member.add_roles(role,reason='Accettazione regolamento Lumia')
    bot.store.put('rules',i.user.id,{'accepted':time.time(),'verified':time.time() if verified else None})
    await reply(i,'Accesso completato. Il ruolo Member è attivo.')
    try:
        await send_preferences(bot,member)
    except discord.HTTPException:
        await reply(i,'Il ruolo Member è attivo. Per ricevere il menu interessi abilita i DM dal server e usa /inizia.')
        await bot.log('server_log',f'Menu ruoli privato non consegnato a <@{member.id}>.')


class RolePanel(LocalView):
    dm_kind='roles'

    def __init__(self,bot,selected=()):
        super().__init__(bot)
        for option in self.select.options:
            option.default=option.value in selected

    @discord.ui.select(placeholder='Scegli interessi e notifiche',min_values=0,max_values=4,custom_id='lumia:roles:select',options=[
        discord.SelectOption(label='FiveM',value='fivem'),discord.SelectOption(label='Minecraft',value='minecraft'),
        discord.SelectOption(label='Novità',value='news'),discord.SelectOption(label='Release',value='release')])
    async def select(self,i,select):
        await i.response.defer(ephemeral=i.guild_id is not None,thinking=True)
        member=await self.member(i)
        if member is None:
            return
        if self.bot.cfg['roles']['member'] not in {r.id for r in member.roles}:
            return await reply(i,'Accetta prima il regolamento.')
        keys=('fivem','minecraft','news','release')
        selected=set(select.values)
        if not selected.issubset(keys):
            return await reply(i,'Preferenze non valide. Riapri il menu con /inizia.')
        roles={key:member.guild.get_role(self.bot.cfg['roles'].get(key,0)) for key in keys}
        if any(not assignable(member.guild,r) for r in roles.values()):
            return await reply(i,'Uno dei ruoli selezionabili non è configurato correttamente.')
        current={r.id for r in member.roles}
        add=[r for k,r in roles.items() if k in selected and r.id not in current]
        remove=[r for k,r in roles.items() if k not in selected and r.id in current]
        if remove:
            await member.remove_roles(*remove,reason='Preferenze Lumia')
        if add:
            await member.add_roles(*add,reason='Preferenze Lumia')
        await reply(i,'Preferenze aggiornate. Puoi modificarle quando vuoi con questo menu o /inizia nel server.')


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
        'blocked':'Non riesco a scriverti in privato. Abilita i messaggi diretti dai membri di questo server nelle impostazioni privacy, poi usa /inizia.',
        'invalid':'I testi di benvenuto non sono disponibili. Avvisa lo staff.',
        'ignored':'Questo percorso è disponibile per gli utenti del server Lumia.'}
    await reply(i,messages[status])


class Onboarding(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        bot.add_view(RulesPanel(bot))
        bot.add_view(RolePanel(bot))
        bot.add_view(PrivateStartPanel(bot))

    @app_commands.command(name='inizia',description='Ricevi in privato benvenuto, regolamento e menu dei ruoli')
    @app_commands.guild_only()
    async def start(self,i:discord.Interaction):
        await open_private_onboarding(self.bot,i)

    @app_commands.command(name='pannelli',description='Pubblica i pulsanti per ricevere l’accesso e i ruoli in privato')
    async def panels(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        await i.response.defer(ephemeral=True)
        for key,view,title,text in (
            ('rules',PrivateStartPanel(self.bot),'🔓  Il tuo accesso a Lumia','Benvenuto e regolamento arrivano in privato. Premi qui sotto o usa /inizia, poi accetta le regole nei DM per ricevere il ruolo Member.\n\nSe non ricevi il messaggio, abilita i messaggi diretti dal server e riprova.'),
            ('role_panel',PrivateStartPanel(self.bot),'🔔  Il tuo spazio, le tue preferenze','Interessi e notifiche si scelgono in privato. Premi qui sotto o usa /inizia per ricevere il menu FiveM, Minecraft, Novità e Release.')):
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
            '**Vuoi un preventivo?**\nApri un ticket con piattaforma, versione o framework, funzioni richieste, budget e scadenza desiderata.\n\n'
            '**Hai bisogno di assistenza?**\nIndica l’ordine e descrivi il problema, allegando gli errori utili senza credenziali.\n\n'
            '**Prima di partire**\nPrezzo, tempi, sorgenti e licenza vengono concordati nel preventivo.'))


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
