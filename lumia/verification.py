"""Small private challenge with a persistent, staff-controlled pause."""
import re
import secrets
import time
import discord
from discord import app_commands
from discord.ext import commands
from .common import require,is_management,respond
from .presentation import card,member_label


def verification_enabled(store,now=None):
    now=time.time() if now is None else now
    policy=store.get('verification','policy',{'enabled':True})
    return bool(policy.get('enabled',True) or (policy.get('until') is not None and now>=policy['until']))


def duration_seconds(value):
    if value is None:
        return None
    match=re.fullmatch(r'\s*([1-9]\d{0,5})\s*([mhgd]?)\s*',value.lower())
    if not match:
        raise ValueError('Usa ad esempio 30m, 2h o 1g. Senza durata la pausa resta attiva fino a /verifica attiva.')
    seconds=int(match[1])*{'':60,'m':60,'h':3600,'g':86400,'d':86400}[match[2]]
    if seconds>365*86400:
        raise ValueError('La durata massima è un anno. Per una pausa senza scadenza ometti la durata.')
    return seconds


class VerificationModal(discord.ui.Modal,title='Verifica account'):
    def __init__(self,bot,author,finish):
        super().__init__(timeout=300)
        self.bot,self.author,self.finish=bot,author,finish
        first,second=secrets.randbelow(8)+2,secrets.randbelow(8)+2
        self.answer=str(first+second)
        self.value=discord.ui.TextInput(label=f'Quanto fa {first} + {second}?',
                                       placeholder='Scrivi il risultato',min_length=1,max_length=3)
        self.add_item(self.value)

    async def on_submit(self,i):
        private=i.guild_id is not None
        if i.user.id!=self.author or i.guild_id not in (None,self.bot.cfg['guild_id']):
            return await respond(i,'Questa verifica appartiene a un altro account.',ephemeral=private)
        await i.response.defer(ephemeral=private,thinking=True)
        current=time.time()
        failures=self.bot.store.get('verification_attempts',self.author,{})
        if failures.get('blocked_until',0)>current:
            return await respond(i,'Troppi tentativi. Riprova tra dieci minuti.',ephemeral=private)
        enabled=verification_enabled(self.bot.store)
        if enabled and self.value.value.strip()!=self.answer:
            count=failures.get('count',0)+1 if failures.get('at',0)>current-600 else 1
            self.bot.store.put('verification_attempts',self.author,
                {'count':count,'at':current,'blocked_until':current+600 if count>=5 else 0})
            return await respond(i,'Il risultato non è corretto. Premi di nuovo «Accetto le regole» per riprovare.',ephemeral=private)
        self.bot.store.delete('verification_attempts',self.author)
        await self.finish(self.bot,i,verified=enabled)

    async def on_error(self,i,error):
        await respond(i,'Verifica non completata. Riprova dal pulsante nei DM o usa /inizia nel server.',
                      ephemeral=i.guild_id is not None)
        await self.bot.log('server_log',f'Verifica non completata per {member_label(i.user.id)}: {type(error).__name__}.')


class Verification(commands.Cog):
    verifica=app_commands.Group(name='verifica',description='Gestisci la verifica di accesso al server')

    def __init__(self,bot):
        self.bot=bot

    @verifica.command(name='stato',description='Mostra se la verifica è attiva')
    async def status(self,i:discord.Interaction):
        enabled=verification_enabled(self.bot.store)
        policy=self.bot.store.get('verification','policy',{})
        until=policy.get('until')
        detail='Il controllo viene richiesto dopo l’accettazione delle regole.' if enabled else (
            f'Riattivazione automatica <t:{int(until)}:R>.' if until else 'In pausa fino a /verifica attiva.')
        await respond(i,None,embed=card('Verifica attiva' if enabled else 'Verifica in pausa',detail,
                                       level='success' if enabled else 'warning'))

    @verifica.command(name='disattiva',description='Sospendi la verifica; senza durata la pausa è senza scadenza')
    @app_commands.describe(durata='Esempi: 30m, 2h, 1g. Ometti per sospendere fino alla riattivazione manuale.')
    async def disable(self,i:discord.Interaction,durata:str|None=None):
        require(i,lambda m:is_management(m,self.bot.cfg))
        seconds=duration_seconds(durata)
        until=time.time()+seconds if seconds is not None else None
        self.bot.store.put('verification','policy',{'enabled':False,'until':until,'actor':i.user.id})
        detail=f'Riprende automaticamente <t:{int(until)}:F>.' if until else 'Riprende quando usi /verifica attiva.'
        await respond(i,None,embed=card('Verifica sospesa',detail+'\nL’accettazione delle regole resta richiesta.',level='warning'))
        await self.bot.log('server_log',detail,title='Verifica sospesa',level='warning',
                           fields=[('Operatore',member_label(i.user.id),True)])

    @verifica.command(name='attiva',description='Riattiva immediatamente la verifica')
    async def enable(self,i:discord.Interaction):
        require(i,lambda m:is_management(m,self.bot.cfg))
        self.bot.store.put('verification','policy',{'enabled':True,'until':None,'actor':i.user.id})
        await respond(i,None,embed=card('Verifica attiva','Il controllo è nuovamente richiesto ai nuovi accessi.',level='success'))
        await self.bot.log('server_log','La verifica di accesso è stata riattivata.',title='Verifica attiva',
                           fields=[('Operatore',member_label(i.user.id),True)])


async def setup(bot):
    await bot.add_cog(Verification(bot))
