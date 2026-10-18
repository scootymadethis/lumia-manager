"""Best-effort Discord notifications; the database remains authoritative."""
import discord
import time
from .orders import STAGES, _eur
from .presentation import card, member_label, dashboard_view


async def notify_order(bot,order,message):
    if not order or not hasattr(bot,'get_guild'):
        return False
    guild=bot.get_guild(bot.cfg['guild_id'])
    if guild is None:
        return False
    try:
        member=await guild.fetch_member(order['customer'])
        if not hasattr(member,'send'):
            return False
        balance=bot.orders.summary(order)
        payable=bot.orders.payable(order['id'])
        fields=[('Progetto',f'LM-{order["id"]:04d} · {order["title"]}',False),
                ('Cliente',member_label(order['customer']),True),('Stato',STAGES[order['stage']],True),
                ('Ricevuto',_eur(balance['paid_cents']),True),('Residuo',_eur(balance['due_cents']),True)]
        if payable['installment_id'] and payable['amount_cents']:
            fields.append(('Prossima tranche',f'{payable["title"]} · {_eur(payable["amount_cents"])}',False))
        await member.send(embed=card('Il tuo progetto',message,section='Lumia / Area clienti',
            fields=fields,subject=member,timestamp=True),view=dashboard_view(order['id']),
            allowed_mentions=discord.AllowedMentions.none())
        if payable['installment_id'] and payable['amount_cents'] and order['stage'] in ('confermato','in_corso','in_revisione','completato'):
            key=f'{order["id"]}:{payable["installment_id"]}:{payable["amount_cents"]}'
            bot.store.put('payment_reminders',key,{'sent':True,'at':time.time()})
        return True
    except discord.HTTPException:
        if hasattr(bot,'log'):
            await bot.log('staff_orders','Aggiornamento disponibile nella dashboard. Il DM al cliente non è stato consegnato.',
                          title='Notifica cliente',fields=[('Cliente',member_label(order['customer']),True),
                          ('Ordine',f'LM-{order["id"]:04d}',True)],order_id=order['id'])
        return False
