"""Support workflows use real local archives and isolated Discord fakes."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from discord import app_commands
import test_tickets as fixtures


class SupportToolsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.TicketTests.asyncSetUp
    ticket=fixtures.TicketTests.ticket

    def interaction(self,actor=None):
        return NS(user=actor or self.manager,guild=self.guild,guild_id=77,channel_id=700,
                  response=NS(is_done=lambda:True,defer=AsyncMock(),edit_message=AsyncMock()),
                  followup=NS(send=AsyncMock()))

    async def test_queue_filters_private_tickets_before_pagination(self):
        ordinary,_=self.ticket('support')
        private=self.store.reserve_ticket(250,'report',{'Secret':'reserved'})
        self.store.update_ticket(private['id'],state='open',channel=777)
        rows=self.cog.queue_rows(self.support)
        self.assertEqual([row['id'] for row in rows],[ordinary['id']])
        self.assertEqual(len(self.cog.queue_rows(self.manager)),2)
        with self.assertRaises(app_commands.CheckFailure):self.cog.queue_rows(self.author)

    async def test_customer_and_staff_replies_track_waiting_side_and_first_response(self):
        ticket,channel=self.ticket('support')
        def message(number,author):
            return NS(id=number,author=author,guild=self.guild,channel=channel,
                      webhook_id=None,created_at=discord.utils.utcnow())
        await self.cog.on_message(message(10,self.author))
        current=self.store.get('ticket_queue',ticket['id'])
        self.assertEqual(current['waiting'],'staff')
        since=current['waiting_since']
        await self.cog.on_message(message(11,self.author))
        self.assertEqual(self.store.get('ticket_queue',ticket['id'])['waiting_since'],since)
        await self.cog.on_message(message(12,self.support))
        current=self.store.get('ticket_queue',ticket['id'])
        self.assertEqual(current['waiting'],'client')
        self.assertGreater(current['first_response'],0)
        await self.cog.on_message(message(9,self.author))
        self.assertEqual(self.store.get('ticket_queue',ticket['id'])['waiting'],'client')
        outsider=self.guild.member(909)
        await self.cog.on_message(message(13,outsider))
        self.assertEqual(self.store.get('ticket_queue',ticket['id'])['last_message'],12)

    async def test_queue_command_is_private_and_paginates_without_losing_tickets(self):
        for number in range(23):
            ticket=self.store.reserve_ticket(1000+number,'support',{'Request':'x'})
            self.store.update_ticket(ticket['id'],state='open',channel=700+number)
        i=self.interaction()
        await self.cog.queue_command.callback(self.cog,i)
        sent=i.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertLessEqual(len(sent['embed']),6000)
        view=sent['view']
        await view.next.callback(i)
        self.assertIn('2 / 3',i.response.edit_message.call_args.kwargs['embed'].footer.text)
        other=self.interaction(self.support)
        with self.assertRaises(app_commands.CheckFailure):await view.next.callback(other)
        self.manager.roles=[]
        with self.assertRaises(app_commands.CheckFailure):await view.refresh.callback(i)

    async def test_ticket_owner_with_staff_role_still_waits_for_staff_reply(self):
        ticket,channel=self.ticket('support')
        self.author.roles.append(self.guild.roles[102])
        message=NS(id=10,author=self.author,guild=self.guild,channel=channel,
                   webhook_id=None,created_at=discord.utils.utcnow())
        await self.cog.on_message(message)
        current=self.store.get('ticket_queue',ticket['id'])
        self.assertEqual(current['waiting'],'staff')
        self.assertNotIn('first_response',current)

    async def test_archive_download_after_channel_deletion_checks_permission_and_integrity(self):
        ticket,channel=self.ticket()
        await self.cog.close_ticket(ticket['id'],self.manager,'finito')
        await self.cog.delete_closed(ticket['id'],self.manager,f'ELIMINA #{ticket["id"]}')
        self.guild.text_channels=[]
        i=self.interaction()
        await self.cog.archive_command.callback(self.cog,i,ticket['id'])
        self.assertIn('file',i.followup.send.call_args.kwargs)
        self.assertEqual(len(self.store.records('ticket_archive_access')),1)
        with self.assertRaises(app_commands.CheckFailure):
            await self.cog.archive_command.callback(self.cog,self.interaction(self.support),ticket['id'])
        self.cog.archive_path(ticket).write_text('corrupted',encoding='utf-8')
        with self.assertRaises(ValueError):await self.cog.archive_command.callback(self.cog,i,ticket['id'])

    async def test_staff_can_set_waiting_and_priority_but_not_on_private_or_closed_ticket(self):
        ticket,_=self.ticket()
        await self.cog.waiting_command.callback(self.cog,self.interaction(self.support),'client')
        await self.cog.priority_command.callback(self.cog,self.interaction(self.support),'alta')
        self.assertEqual(self.cog.queue_rows(self.support)[0]['priority'],'alta')
        self.assertEqual(self.cog.queue_rows(self.support)[0]['waiting'],'client')
        self.store.update_ticket(ticket['id'],state='closed')
        with self.assertRaises(ValueError):await self.cog.priority_command.callback(self.cog,self.interaction(),'urgente')

    async def test_partnership_workflow_is_management_only_and_keeps_history(self):
        ticket,_=self.ticket('partner')
        with self.assertRaises(app_commands.CheckFailure):
            await self.cog.partnership_command.callback(self.cog,self.interaction(self.support),'attiva','Prova')
        await self.cog.partnership_command.callback(self.cog,self.interaction(),'attiva','Accordo approvato')
        entry=self.store.get('ticket_partnerships',ticket['id'])
        self.assertEqual(entry['status'],'attiva')
        self.assertEqual(entry['history'][0]['actor'],self.manager.id)
        self.assertEqual(self.cog.queue_rows(self.manager)[0]['partnership'],'attiva')

    async def test_general_ticket_panel_updates_in_place_and_replaces_only_missing_message(self):
        _,channel=self.ticket()
        self.bot.cfg['channels']['ticket_panel']=700
        message=NS(id=800,edit=AsyncMock())
        channel.fetch_message=AsyncMock(return_value=message)
        await self.cog.panel.callback(self.cog,self.interaction())
        await self.cog.panel.callback(self.cog,self.interaction())
        self.assertEqual(len(channel.sent),1)
        message.edit.assert_awaited_once()
        channel.fetch_message.side_effect=discord.NotFound(NS(status=404,reason='Not Found'),'Deleted')
        await self.cog.panel.callback(self.cog,self.interaction())
        self.assertEqual(len(channel.sent),2)

    async def test_legacy_general_panel_is_reused_on_first_upgrade(self):
        _,channel=self.ticket()
        self.bot.cfg['channels']['ticket_panel']=700
        self.bot.user=NS(id=999)
        original=NS(id=799,author=self.bot.user,edit=AsyncMock(),
                    components=[NS(children=[NS(custom_id='lumia:tickets:select:v1')])])
        channel.messages=[original]
        await self.cog.panel.callback(self.cog,self.interaction())
        self.assertEqual(channel.sent,[])
        original.edit.assert_awaited_once()
        self.assertEqual(self.store.get('ticket_panels',700)['message'],799)

    async def test_queue_never_mutates_waiting_side_from_bot_webhook_or_closed_ticket(self):
        ticket,channel=self.ticket()
        bot=self.guild.member(999);bot.bot=True
        message=NS(id=10,guild=self.guild,channel=channel,author=bot,webhook_id=None,created_at=discord.utils.utcnow())
        await self.cog.on_message(message)
        message.author=self.author;message.webhook_id=111
        await self.cog.on_message(message)
        message.webhook_id=None;self.store.update_ticket(ticket['id'],state='closed')
        await self.cog.on_message(message)
        self.assertIsNone(self.store.get('ticket_queue',ticket['id']))
