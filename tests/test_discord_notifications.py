import asyncio
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from lumia.core import Store
from lumia.orders import Orders
from lumia import notifications


class NotificationQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.orders=Orders(self.store)
        self.order=self.orders.create(10,'Test',10000)
        self.member=NS(id=10,send=AsyncMock())
        self.guild=NS(fetch_member=AsyncMock(return_value=self.member))
        self.bot=NS(cfg={'guild_id':1},store=self.store,orders=self.orders,
                    get_guild=lambda n:self.guild,log=AsyncMock())

    async def test_transient_failure_survives_queue_restart_and_retries(self):
        self.member.send.side_effect=discord.HTTPException(NS(status=503,reason='Unavailable'),'later')
        self.assertFalse(await notifications.notify_order(self.bot,self.order,'Aggiornamento'))
        saved=list(self.store.records('discord_outbox').values())[0]
        self.assertEqual(saved['status'],'pending')
        self.member.send.side_effect=None
        restarted=notifications.NotificationQueue(self.bot)
        await restarted.drain(now=saved['next_attempt']+1)
        self.assertEqual(self.store.get('discord_outbox',saved['id'])['status'],'sent')
        self.assertEqual(self.member.send.await_count,2)

    async def test_closed_dms_stop_retries_and_log_only_once(self):
        self.member.send.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'DM closed')
        await notifications.notify_order(self.bot,self.order,'Aggiornamento')
        await notifications.notify_order(self.bot,self.order,'Aggiornamento')
        await notifications.NotificationQueue(self.bot).drain(now=time.time()+86400)
        self.assertEqual(self.member.send.await_count,1)
        self.bot.log.assert_awaited_once()
        self.assertEqual(len(self.store.records('discord_outbox')),1)

    async def test_concurrent_same_event_is_sent_once_in_process(self):
        queue=notifications.NotificationQueue(self.bot)
        item=queue.enqueue(self.order,'Test')
        await asyncio.gather(queue.deliver(item['id']),queue.deliver(item['id']))
        self.member.send.assert_awaited_once()

    async def test_changed_customer_or_missing_order_is_never_notified(self):
        queue=notifications.NotificationQueue(self.bot)
        item=queue.enqueue(self.order,'Test')
        self.orders.get=lambda n:{**self.order,'customer':20}
        self.assertFalse(await queue.deliver(item['id']))
        self.member.send.assert_not_awaited()
        self.assertEqual(self.store.get('discord_outbox',item['id'])['status'],'failed')

    async def test_old_notifications_expire_without_contacting_discord(self):
        queue=notifications.NotificationQueue(self.bot)
        item=queue.enqueue(self.order,'Test',now=1)
        await queue.deliver(item['id'],now=8*86400)
        self.member.send.assert_not_awaited()
        self.assertEqual(self.store.get('discord_outbox',item['id'])['status'],'expired')

    async def test_successful_delivery_is_durable_and_drain_does_not_resend(self):
        self.assertTrue(await notifications.notify_order(self.bot,self.order,'Consegna pronta'))
        await notifications.NotificationQueue(self.bot).drain(now=9999999999)
        self.member.send.assert_awaited_once()

    async def test_pending_duplicates_reuse_event_and_are_not_retried_early(self):
        self.member.send.side_effect=OSError('network')
        await notifications.notify_order(self.bot,self.order,'Test')
        await notifications.notify_order(self.bot,self.order,'Test')
        self.assertEqual(len(self.store.records('discord_outbox')),1)
        self.member.send.assert_awaited_once()

    async def test_retry_limit_prevents_infinite_network_attempts(self):
        queue=notifications.NotificationQueue(self.bot)
        item=queue.enqueue(self.order,'Test')
        self.member.send.side_effect=OSError('network')
        for _ in range(10):
            current=self.store.get('discord_outbox',item['id'])
            await queue.deliver(item['id'],now=current['next_attempt']+1)
        self.assertEqual(self.member.send.await_count,6)
        self.assertEqual(self.store.get('discord_outbox',item['id'])['status'],'failed')

    async def test_unsupported_delivery_is_recorded_without_breaking_caller(self):
        self.guild.fetch_member.return_value=NS(id=10)
        self.assertFalse(await notifications.notify_order(self.bot,self.order,'Test'))
        self.assertEqual(list(self.store.records('discord_outbox').values())[0]['reason'],'delivery_unavailable')
