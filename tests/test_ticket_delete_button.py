"""Ticket deletion is immediate after closure, with confirmation and verified archive."""
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import discord
from discord import app_commands
import test_tickets as fixtures


class TicketDeleteButtonTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.TicketTests.asyncSetUp
    ticket = fixtures.TicketTests.ticket

    def interaction(self, actor=None, channel=700, guild=77):
        return NS(guild_id=guild, guild=self.guild, channel_id=channel,
                  user=actor or self.manager,
                  response=NS(send_modal=AsyncMock(), defer=AsyncMock(), is_done=lambda:True),
                  followup=NS(send=AsyncMock()))

    async def archived(self):
        ticket,channel=self.ticket()
        await self.cog.close_ticket(ticket['id'],self.manager,'finito')
        return self.store.ticket(ticket['id']),channel

    async def modal(self):
        i=self.interaction()
        await self.module.TicketControls(self.cog).delete.callback(i)
        return i.response.send_modal.call_args.args[0]

    async def test_persistent_delete_button_opens_confirmation_without_deleting(self):
        ticket,channel=await self.archived()
        view=self.module.TicketControls(self.cog)
        self.assertTrue(view.is_persistent())
        self.assertEqual(view.delete.custom_id,'lumia:tickets:delete:v1')
        modal=await self.modal()
        self.assertIn(f'#{ticket["id"]}',modal.title)
        self.assertTrue(modal.children[0].required)
        self.assertFalse(channel.deleted)

    async def test_customer_support_and_foreign_server_cannot_open_confirmation(self):
        await self.archived()
        for i in (self.interaction(self.author),self.interaction(self.support),self.interaction(guild=88)):
            with self.assertRaises(app_commands.CheckFailure):
                await self.module.TicketControls(self.cog).delete.callback(i)
            i.response.send_modal.assert_not_awaited()

    async def test_open_or_corrupt_archive_cannot_open_confirmation(self):
        ticket,channel=self.ticket()
        for stage in ('open','corrupt'):
            if stage=='corrupt':
                await self.cog.close_ticket(ticket['id'],self.manager,'finito')
                self.cog.archive_path(ticket).write_text('corrupt',encoding='utf-8')
            i=self.interaction()
            with self.assertRaises(ValueError):
                await self.module.TicketControls(self.cog).delete.callback(i)
            i.response.send_modal.assert_not_awaited()
        self.assertFalse(channel.deleted)

    async def test_confirmation_deletes_only_the_channel_and_keeps_verified_archive(self):
        ticket,channel=await self.archived()
        modal=await self.modal()
        modal.children[0]._value=f'ELIMINA #{ticket["id"]}'
        await modal.on_submit(self.interaction())
        self.assertTrue(channel.deleted)
        self.assertTrue(self.cog.verified_archive(self.store.ticket(ticket['id'])).is_file())
        self.assertEqual(self.store.get('ticket_deleted_channels',ticket['id'])['by'],self.manager.id)

    async def test_incorrect_confirmation_does_not_delete(self):
        _,channel=await self.archived()
        modal=await self.modal();modal.children[0]._value='ELIMINA #999'
        with self.assertRaises(ValueError):await modal.on_submit(self.interaction())
        self.assertFalse(channel.deleted)

    async def test_confirmation_rechecks_actor_permission_channel_and_closed_state(self):
        ticket,channel=await self.archived()
        modal=await self.modal();modal.children[0]._value=f'ELIMINA #{ticket["id"]}'
        other_manager=self.guild.member(206,(101,))
        for i in (self.interaction(other_manager),self.interaction(channel=999),self.interaction(guild=88)):
            with self.assertRaises((app_commands.CheckFailure,ValueError)):
                await modal.on_submit(i)
        self.manager.roles=[]
        with self.assertRaises(app_commands.CheckFailure):await modal.on_submit(self.interaction())
        self.manager.roles=[self.guild.roles[101]]
        self.store.update_ticket(ticket['id'],state='open')
        with self.assertRaises(ValueError):await modal.on_submit(self.interaction())
        self.assertFalse(channel.deleted)

    async def test_slash_command_deletes_immediately_after_closure(self):
        ticket,channel=await self.archived()
        self.assertLess(time.time()-ticket['closed'],60)
        await self.cog.delete_command.callback(self.cog,self.interaction(),f'ELIMINA #{ticket["id"]}')
        self.assertTrue(channel.deleted)
        self.assertTrue(self.cog.verified_archive(self.store.ticket(ticket['id'])).is_file())

    async def test_repeat_confirmation_never_deletes_a_channel_twice(self):
        ticket,channel=await self.archived()
        channel.delete=AsyncMock()
        first,second=await self.modal(),await self.modal()
        for modal in (first,second):modal.children[0]._value=f'ELIMINA #{ticket["id"]}'
        await first.on_submit(self.interaction())
        with self.assertRaises(ValueError):await second.on_submit(self.interaction())
        channel.delete.assert_awaited_once()

    async def test_existing_ticket_controls_command_reuses_message_and_rejects_customer(self):
        ticket,channel=self.ticket()
        message=NS(id=800,edit=AsyncMock())
        channel.fetch_message=AsyncMock(return_value=message)
        i=self.interaction()
        await self.cog.controls_command.callback(self.cog,i)
        self.assertEqual(self.store.get('ticket_controls',ticket['id'])['message'],800)
        self.assertEqual(channel.sent[-1][1]['view'].delete.custom_id,'lumia:tickets:delete:v1')
        count=len(channel.sent)
        await self.cog.controls_command.callback(self.cog,self.interaction())
        self.assertEqual(len(channel.sent),count)
        message.edit.assert_awaited_once()
        with self.assertRaises(app_commands.CheckFailure):
            await self.cog.controls_command.callback(self.cog,self.interaction(self.author))

    async def test_new_ticket_remembers_its_controls_for_later_updates(self):
        ticket=await self.cog.create_ticket(self.guild,self.author,'support',{'Problema':'test'})
        controls=self.store.get('ticket_controls',ticket['id'])
        self.assertEqual(controls['channel'],ticket['channel'])
        self.assertEqual(controls['message'],800)

    async def test_discord_delete_failure_keeps_archive_and_does_not_record_success(self):
        ticket,channel=await self.archived()
        channel.delete=AsyncMock(side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'No permission'))
        modal=await self.modal();modal.children[0]._value=f'ELIMINA #{ticket["id"]}'
        with self.assertRaises(discord.Forbidden):await modal.on_submit(self.interaction())
        self.assertIsNone(self.store.get('ticket_deleted_channels',ticket['id']))
        self.assertTrue(self.cog.verified_archive(self.store.ticket(ticket['id'])).is_file())

    async def test_removed_controls_are_replaced_but_permission_errors_create_no_duplicates(self):
        ticket,channel=self.ticket()
        self.store.put('ticket_controls',ticket['id'],{'message':799,'channel':channel.id})
        channel.fetch_message=AsyncMock(side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'No permission'))
        with self.assertRaises(discord.Forbidden):await self.cog.publish_controls(ticket['id'],self.manager)
        self.assertEqual(channel.sent,[])
        channel.fetch_message.side_effect=discord.NotFound(NS(status=404,reason='Not Found'),'Deleted')
        await self.cog.publish_controls(ticket['id'],self.manager)
        self.assertEqual(len(channel.sent),1)
        self.assertEqual(self.store.get('ticket_controls',ticket['id'])['message'],800)

    async def test_legacy_intro_controls_are_updated_in_place_without_a_second_panel(self):
        ticket,channel=self.ticket()
        self.bot.user=NS(id=999)
        components=[NS(children=[NS(custom_id=f'lumia:tickets:{action}:v1') for action in ('claim','transcript','close')])]
        foreign=NS(id=790,author=NS(id=123),components=components,edit=AsyncMock())
        original=NS(id=791,author=self.bot.user,components=components,edit=AsyncMock())
        channel.messages=[foreign,original]
        await self.cog.publish_controls(ticket['id'],self.manager)
        original.edit.assert_awaited_once()
        foreign.edit.assert_not_awaited()
        self.assertEqual(channel.sent,[])
        self.assertEqual(self.store.get('ticket_controls',ticket['id'])['message'],791)

    async def test_existing_controls_panel_text_is_updated_without_replacing_ticket_intro(self):
        ticket,channel=self.ticket()
        self.store.put('ticket_controls',ticket['id'],{'message':800,'channel':channel.id})
        message=NS(id=800,embeds=[discord.Embed(title='Controlli del ticket',description='Attendi almeno 7 giorni dalla chiusura.')],edit=AsyncMock())
        channel.fetch_message=AsyncMock(return_value=message)
        await self.cog.publish_controls(ticket['id'],self.manager)
        updated=message.edit.call_args.kwargs.get('embed')
        self.assertIsNotNone(updated)
        self.assertNotIn('7 giorni',updated.description)
        self.assertIn('Nessuna attesa',updated.description)
        message.embeds=[discord.Embed(title='Ticket #0001 · Assistenza',description='Dettagli originali del cliente')]
        message.edit.reset_mock()
        await self.cog.publish_controls(ticket['id'],self.manager)
        self.assertNotIn('embed',message.edit.call_args.kwargs)
        self.assertEqual(channel.sent,[])
