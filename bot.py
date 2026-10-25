"""Lumia Manager entry point. Tokens are never embedded in source."""
import argparse
import asyncio
import logging
import os
import re
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from lumia.config import load_config,save_config
from lumia.core import Store
from lumia.orders import Orders
from lumia.presentation import log_card,with_avatar,message_subject,dashboard_view

LOG=logging.getLogger('lumia')


def load_env(path):
    file=Path(path)
    if file.exists():
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            key,sep,value=line.strip().partition('=')
            if sep and re.fullmatch('[A-Z][A-Z0-9_]*',key):
                value=value.strip()
                if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
                    value=value[1:-1]
                os.environ.setdefault(key,value)


class LocalTree(app_commands.CommandTree):
    async def interaction_check(self,i):
        if i.guild_id != self.client.cfg['guild_id']:
            await i.response.send_message('Comando disponibile solo nel server Lumia configurato.',ephemeral=True)
            return False
        return True

    async def on_error(self,i,error):
        original=getattr(error,'original',error)
        if isinstance(original,(app_commands.CheckFailure,ValueError)):
            message=str(original)
        elif isinstance(original,discord.Forbidden):
            message='Al bot manca un permesso. Chiedi al Management di verificare /server diagnostica.'
        else:
            message='Operazione non riuscita. Lo staff può consultare i log del servizio.'
            LOG.error('Errore comando %s',getattr(i.command,'qualified_name','?'),exc_info=(type(original),original,original.__traceback__))
        from lumia.common import respond
        await respond(i,message[:1800])


class LumiaBot(commands.Bot):
    def __init__(self,cfg,config_path='config.json',data_dir='data'):
        self.cfg=cfg
        self.config_path=Path(config_path)
        self.data_dir=Path(data_dir)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.data_dir/'lumia.sqlite')
        self.orders=Orders(self.store)
        intents=discord.Intents.default()
        intents.members=True
        intents.message_content=True
        intents.moderation=True
        intents.voice_states=True
        super().__init__(command_prefix=commands.when_mentioned,intents=intents,tree_cls=LocalTree,allowed_mentions=discord.AllowedMentions.none(),help_command=None)

    def save_config(self):
        save_config(self.config_path,self.cfg)

    async def log(self,key,text,*,title=None,fields=(),level='info',subject=None,order_id=None):
        channel=self.get_channel(self.cfg['channels'].get(key,0))
        if not isinstance(channel,discord.TextChannel):
            LOG.warning('Canale log %s non configurato',key)
            return False
        try:
            fields=list(fields)
            if order_id is None:
                for name,value,_ in fields:
                    if name.lower()=='ordine':
                        match=re.search(r'(?:#|LM-)(\d+)',str(value))
                        if match and self.orders.get(int(match[1])):
                            order_id=int(match[1])
                            break
            order=self.orders.get(order_id) if order_id is not None else None
            if order and not any(name.lower()=='cliente' for name,_,_ in fields):
                fields.append(('Cliente',f'<@{order["customer"]}>',True))
            result=with_avatar(log_card(key,text,title=title,fields=fields,level=level),subject or message_subject(self,text,fields))
            await channel.send(embed=result,view=dashboard_view(order_id) if order_id is not None else None,
                               allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            LOG.exception('Invio log non riuscito: %s',key)
            return False

    async def setup_hook(self):
        for ext in ('setup_server','onboarding','verification','tickets','notifications','order_commands','moderation','community','events'):
            await self.load_extension('lumia.'+ext)
        guild=discord.Object(id=self.cfg['guild_id'])
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        LOG.info('Lumia Manager connesso. Server autorizzato: %s',self.cfg['guild_id'])
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name='Lumia Development • /faq'))


async def run(args):
    cfg=load_config(args.config)
    if args.check:
        print('Configurazione valida. Nessuna connessione Discord effettuata.')
        return
    token=os.getenv('DISCORD_TOKEN','')
    if not token:
        raise ValueError('Configura DISCORD_TOKEN nel file .env locale.')
    bot=LumiaBot(cfg,args.config,os.getenv('LUMIA_DATA_DIR','data'))
    try:
        async with bot:
            web_server=None
            if os.getenv('WEB_ENABLED','false').lower()=='true':
                import uvicorn
                from lumia.web import create_app
                web_server=uvicorn.Server(uvicorn.Config(create_app(bot),host=os.getenv('WEB_HOST','127.0.0.1'),port=int(os.getenv('WEB_PORT','8080')),log_level='info',access_log=False,proxy_headers=False))
            jobs=[asyncio.create_task(bot.start(token))]
            if web_server:
                jobs.append(asyncio.create_task(web_server.serve()))
            try:
                done,pending=await asyncio.wait(jobs,return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in jobs:
                    task.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
    finally:
        bot.store.close()


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    parser=argparse.ArgumentParser(description='Lumia Manager: bot e dashboard')
    parser.add_argument('--config',default='config.json')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--preview',action='store_true',help='Dashboard dimostrativa locale, dati fittizi e sola lettura')
    args=parser.parse_args()
    load_env('.env')
    try:
        if args.preview:
            import uvicorn
            from lumia.web import create_demo_app
            os.environ['LUMIA_DEMO_URL']='http://127.0.0.1:8080'
            uvicorn.run(create_demo_app(),host='127.0.0.1',port=8080,access_log=False)
        else:
            asyncio.run(run(args))
    except (ValueError,RuntimeError,FileNotFoundError) as exc:
        parser.exit(2,str(exc)+'\n')
