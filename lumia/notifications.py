"""Durable Discord delivery. Orders and payments remain authoritative in the website."""
import asyncio
import logging
import time
import uuid
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands, tasks
from .common import is_management, require, respond
from .orders import STAGES, _eur
from .presentation import card, member_label, dashboard_view

log = logging.getLogger(__name__)
MAX_AGE = 7 * 86400
MAX_ATTEMPTS = 6


class NotificationQueue:
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    def enqueue(self, order, message, now=None):
        now = time.time() if now is None else now
        message = str(message)[:1800]
        with self.bot.store.lock:
            for item in self.bot.store.records('discord_outbox').values():
                if (item['order'] == order['id'] and item['customer'] == order['customer']
                        and item['message'] == message and item['status'] in ('pending', 'blocked')):
                    return item
            item = {'id': uuid.uuid4().hex, 'order': order['id'], 'customer': order['customer'],
                    'message': message[:1800], 'status': 'pending', 'created': now,
                    'next_attempt': now, 'attempts': 0}
            self.save(item)
            return item

    def save(self, item):
        self.bot.store.put('discord_outbox', item['id'], item)

    async def alert(self, item):
        if not hasattr(self.bot, 'log'):
            return
        try:
            await self.bot.log('staff_orders',
                'Notifica Discord non consegnata. Il progetto resta consultabile nel sito. '
                'Usa /notifiche stato per il riepilogo e /notifiche ritenta solo dopo aver risolto il problema.',
                title='Notifica cliente', fields=[('Cliente', member_label(item['customer']), True),
                ('Ordine', f'LM-{item["order"]:04d}', True), ('ID notifica', item['id'], False)],
                order_id=item['order'])
        except Exception:
            log.exception('Could not report failed notification %s', item['id'])

    async def deliver(self, ident, now=None):
        now = time.time() if now is None else now
        async with self.lock:
            item = self.bot.store.get('discord_outbox', ident)
            if not item or item['status'] != 'pending':
                return bool(item and item['status'] == 'sent')
            if now - item['created'] > MAX_AGE:
                item.update(status='expired', finished=now)
                self.save(item)
                return False
            if item['next_attempt'] > now:
                return False
            order = self.bot.orders.get(item['order'])
            if not order or order['customer'] != item['customer']:
                item.update(status='failed', reason='order_changed', finished=now)
                self.save(item)
                return False
            item['attempts'] += 1
            # Checkpoint before network IO. After an ambiguous timeout a retry can
            # repeat a DM; never imply exactly-once delivery across Discord crashes.
            item['next_attempt'] = now + min(3600, 60 * 2 ** (item['attempts'] - 1))
            self.save(item)
            try:
                guild = self.bot.get_guild(self.bot.cfg['guild_id'])
                if guild is None:
                    raise OSError('guild_unavailable')
                member = await guild.fetch_member(item['customer'])
                if not callable(getattr(member, 'send', None)):
                    item.update(status='blocked', reason='delivery_unavailable', finished=now)
                    self.save(item)
                    return False
                balance = self.bot.orders.summary(order)
                payable = self.bot.orders.payable(order['id'])
                fields = [('Progetto', f'LM-{order["id"]:04d} · {order["title"]}', False),
                    ('Cliente', member_label(order['customer']), True), ('Stato', STAGES[order['stage']], True),
                    ('Ricevuto', _eur(balance['paid_cents']), True), ('Residuo', _eur(balance['due_cents']), True)]
                if payable['installment_id'] and payable['amount_cents']:
                    fields.append(('Prossima tranche', f'{payable["title"]} · {_eur(payable["amount_cents"])}', False))
                await member.send(embed=card('Il tuo progetto', item['message'], section='Lumia / Area clienti',
                    fields=fields, subject=member, timestamp=True), view=dashboard_view(order['id']),
                    allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, OSError, asyncio.TimeoutError) as error:
                permanent = isinstance(error, (discord.Forbidden, discord.NotFound))
                item.update(status='blocked' if permanent else ('failed' if item['attempts'] >= MAX_ATTEMPTS else 'pending'),
                            reason=type(error).__name__)
                if item['status'] != 'pending':
                    item['finished'] = now
                self.save(item)
                if permanent or item['attempts'] in (1, MAX_ATTEMPTS):
                    await self.alert(item)
                return False
            item.update(status='sent', finished=now)
            self.save(item)
            if (payable['installment_id'] and payable['amount_cents']
                    and order['stage'] in ('confermato', 'in_corso', 'in_revisione', 'completato')):
                key = f'{order["id"]}:{payable["installment_id"]}:{payable["amount_cents"]}'
                self.bot.store.put('payment_reminders', key, {'sent': True, 'at': now})
            return True

    async def drain(self, now=None):
        now = time.time() if now is None else now
        items = sorted(self.bot.store.records('discord_outbox').values(), key=lambda item: item['created'])
        pending = [item for item in items if item['status'] == 'pending' and item['next_attempt'] <= now]
        for item in pending[:10]:
            try:
                await self.deliver(item['id'], now)
            except Exception:
                # One damaged record must not stop all notifications or kill the loop.
                log.exception('Notification delivery failed: %s', item['id'])
        for item in items:
            if item['status'] != 'pending' and now - item.get('finished', item['created']) > 30 * 86400:
                self.bot.store.delete('discord_outbox', item['id'])


def notification_queue(bot):
    queue = getattr(bot, '_lumia_notification_queue', None)
    if queue is None:
        queue = NotificationQueue(bot)
        bot._lumia_notification_queue = queue
    return queue


async def notify_order(bot, order, message):
    if not order or not hasattr(bot, 'get_guild'):
        return False
    queue = notification_queue(bot)
    item = queue.enqueue(order, message)
    return await queue.deliver(item['id'])


class Notifications(commands.Cog):
    notifiche = app_commands.Group(name='notifiche', description='Management: stato delle notifiche Discord')

    def __init__(self, bot):
        self.bot = bot
        self.queue = notification_queue(bot)

    async def cog_load(self):
        self.worker.start()

    def cog_unload(self):
        self.worker.cancel()

    @tasks.loop(seconds=60)
    async def worker(self):
        await self.queue.drain()

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    def check(self, interaction):
        require(interaction, lambda member: is_management(member, self.bot.cfg))
        if interaction.guild_id != self.bot.cfg['guild_id']:
            raise app_commands.CheckFailure('Server non autorizzato.')

    @notifiche.command(name='stato', description='Mostra le notifiche in attesa e non consegnate')
    async def status(self, interaction: discord.Interaction):
        self.check(interaction)
        items = list(self.bot.store.records('discord_outbox').values())
        counts = Counter(item['status'] for item in items)
        lines = [f'{key}: {counts[key]}' for key in ('pending', 'sent', 'blocked', 'failed', 'expired')]
        problems = sorted((item for item in items if item['status'] in ('pending', 'blocked', 'failed')),
                          key=lambda item: item['created'], reverse=True)[:8]
        lines += [f'`{item["id"]}` · LM-{item["order"]:04d} · {item["status"]} · tentativi {item["attempts"]}' for item in problems]
        await respond(interaction, None, embed=card('Notifiche Discord', '\n'.join(lines)))

    @notifiche.command(name='ritenta', description='Riprova esplicitamente una notifica dopo aver risolto il problema')
    async def retry(self, interaction: discord.Interaction, identificativo: str):
        self.check(interaction)
        async with self.queue.lock:
            item = self.bot.store.get('discord_outbox', identificativo)
            if not item or item['status'] not in ('blocked', 'failed'):
                raise ValueError('Scegli una notifica blocked o failed da /notifiche stato.')
            if time.time() - item['created'] > MAX_AGE:
                raise ValueError('Notifica troppo vecchia: consulta e comunica lo stato attuale del progetto.')
            item.update(status='pending', attempts=0, next_attempt=time.time(), retried_by=interaction.user.id)
            self.queue.save(item)
        await interaction.response.defer(ephemeral=True, thinking=True)
        sent = await self.queue.deliver(identificativo)
        await respond(interaction, 'Notifica consegnata.' if sent else 'Non consegnata. Controlla /notifiche stato; nessun ordine o pagamento è stato modificato.')


async def setup(bot):
    await bot.add_cog(Notifications(bot))
