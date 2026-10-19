import discord
import time
import os
from urllib.parse import urlsplit
from discord import app_commands
from discord.ext import commands,tasks
from .common import require,is_management,respond
from .orders import STAGES,to_cents
from .presentation import card,member_label,dashboard_view,with_avatar
from .notifications import notify_order


def describe_order(orders,order):
    balance=orders.summary(order)
    euros=lambda v:f'{v/100:.2f} EUR'
    return (f"**Ordine #{order['id']} • {order['title']}**\nStato: {STAGES[order['stage']]}\n"
            f"Totale: {euros(order['total_cents'])} • Registrato: {euros(balance['paid_cents'])} • Residuo: {euros(balance['due_cents'])}")


def order_card(orders,order):
    balance=orders.summary(order)
    euros=lambda value:f'{value/100:,.2f} €'.replace(',','_').replace('.',',').replace('_','.')
    return card(f'📋  Ordine #{order["id"]} · {order["title"]}',
        'Il riepilogo del tuo progetto. Dettagli e aggiornamenti sono disponibili nella dashboard.',
        section='LUMIA / Progetti',level={'completato':'success','annullato':'neutral'}.get(order['stage'],'info'),fields=[
            ('Cliente',member_label(order['customer']),True),('Stato',STAGES[order['stage']],True),
            ('Totale concordato',euros(order['total_cents']),True),
            ('Pagamenti registrati',euros(balance['paid_cents']),True),('Residuo',euros(balance['due_cents']),True)],
        footer='Lumia Development • Riepilogo amministrativo, non costituisce fattura')


class OrderCommands(commands.Cog):
    ordine=app_commands.Group(name='ordine',description='Preventivi, ordini e registro pagamenti Lumia')

    def __init__(self,bot):
        self.bot=bot

    async def cog_load(self):
        self.payment_reminders.start()

    def cog_unload(self):
        self.payment_reminders.cancel()

    @tasks.loop(minutes=30)
    async def payment_reminders(self):
        for order in self.bot.orders.list_for(0,staff=True):
            if order['stage'] not in ('confermato','in_corso','in_revisione','completato'):
                continue
            payable=self.bot.orders.payable(order['id'])
            if not payable['installment_id'] or not payable['amount_cents']:
                continue
            key=f'{order["id"]}:{payable["installment_id"]}:{payable["amount_cents"]}'
            previous=self.bot.store.get('payment_reminders',key,{})
            if previous.get('sent') or previous.get('retry',0)>time.time():
                continue
            sent=await notify_order(self.bot,order,f'La tranche «{payable["title"]}» è disponibile per il pagamento.')
            self.bot.store.put('payment_reminders',key,{'sent':sent,'retry':time.time()+21600})

    @payment_reminders.before_loop
    async def before_payment_reminders(self):
        await self.bot.wait_until_ready()

    def staff(self,i):
        require(i,lambda m:is_management(m,self.bot.cfg))

    @app_commands.command(name='ordina',description='Inizia una richiesta guidata sul sito Lumia')
    async def website_order(self,i:discord.Interaction):
        origin=os.getenv('LUMIA_PUBLIC_URL','https://manager.lumiadevelopment.it').rstrip('/')
        parsed=urlsplit(origin)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return await respond(i,'Il collegamento al sito non è ancora configurato. Contatta il team.')
        view=discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='Inizia il tuo progetto',style=discord.ButtonStyle.link,url=origin+'/start'))
        await respond(i,None,embed=with_avatar(card('La tua idea parte da qui.',
            'Il sito ti guida nei dettagli del progetto. Ritroverai preventivo, messaggi, consegne e pagamenti nella tua area clienti. '
            'Discord rimane disponibile per l’assistenza sui tuoi progetti.',section='Lumia / Nuovo progetto',
            fields=[('Un passo alla volta','Scegli la piattaforma e raccontaci cosa vuoi creare.',False),
                    ('Nessun addebito adesso','Il team prepara il preventivo prima di iniziare.',False)]),i.user),view=view)

    @ordine.command(name='crea',description='Crea un preventivo o una commissione per un cliente')
    async def create(self,i:discord.Interaction,cliente:discord.Member,titolo:str,totale_euro:str,dettagli:str='',ticket:int|None=None):
        self.staff(i)
        return await respond(i, 'Gestisci ordini, milestone e pagamenti dal sito.', view=dashboard_view())

    @ordine.command(name='vedi',description='Consulta un tuo ordine o, per Management, una commissione')
    async def view(self,i:discord.Interaction,numero:int):
        order=self.bot.orders.get(numero)
        if not order or not (order['customer']==i.user.id or is_management(i.user,self.bot.cfg)):
            return await respond(i,'Ordine non trovato o non accessibile.')
        member=i.guild.get_member(order['customer'])
        await respond(i,None,embed=with_avatar(order_card(self.bot.orders,order),member),view=dashboard_view(numero))

    @ordine.command(name='lista',description='Mostra i tuoi ordini o il riepilogo Management')
    async def listing(self,i:discord.Interaction):
        items=self.bot.orders.list_for(i.user.id,staff=is_management(i.user,self.bot.cfg))
        lines=[f"#{r['id']} • {r['title'][:70]} • {STAGES[r['stage']]}" for r in items[:15]]
        await respond(i,None,embed=card('I progetti Lumia','\n'.join(lines) if lines else 'Nessun ordine presente.'),view=dashboard_view())

    @ordine.command(name='stato',description='Aggiorna lo stato di una commissione')
    @app_commands.choices(stato=[app_commands.Choice(name=v,value=k) for k,v in STAGES.items()])
    async def state(self,i:discord.Interaction,numero:int,stato:app_commands.Choice[str]):
        self.staff(i)
        return await respond(i, 'Gestisci ordini, milestone e pagamenti dal sito.', view=dashboard_view())

    @ordine.command(name='pagamento',description='Registra un pagamento già ricevuto: non effettua un addebito')
    async def payment(self,i:discord.Interaction,numero:int,importo_euro:str,riferimento:str):
        self.staff(i)
        return await respond(i, 'Gestisci ordini, milestone e pagamenti dal sito.', view=dashboard_view())

    @ordine.command(name='scadenza',description='Aggiunge una consegna o una scadenza a un ordine')
    async def milestone(self,i:discord.Interaction,numero:int,titolo:str,data:str):
        self.staff(i)
        return await respond(i, 'Gestisci ordini, milestone e pagamenti dal sito.', view=dashboard_view())

    @ordine.command(name='movimenti',description='Consulta i movimenti amministrativi di un ordine')
    async def movements(self,i:discord.Interaction,numero:int):
        order=self.bot.orders.get(numero)
        if not order or not (order['customer']==i.user.id or is_management(i.user,self.bot.cfg)):
            return await respond(i,'Ordine non trovato o non accessibile.')
        lines=[f"ID {p['id']} • {p['amount_cents']/100:.2f} EUR • {p['provider']}"+(' • STORNATO' if p.get('reversed_at') else '') for p in self.bot.orders.payments(numero)[:15]]
        await respond(i,'**Movimenti amministrativi**\n'+ ('\n'.join(lines) if lines else 'Nessun pagamento registrato.'))

    @ordine.command(name='storna',description='Corregge una registrazione manuale errata senza movimentare denaro')
    async def reverse(self,i:discord.Interaction,movimento:int,motivo:app_commands.Range[str,3,500]):
        self.staff(i)
        return await respond(i, 'Gestisci ordini, milestone e pagamenti dal sito.', view=dashboard_view())


async def setup(bot):
    await bot.add_cog(OrderCommands(bot))
