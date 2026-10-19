"""Ticket privacy and lifecycle tests. Discord network calls use local fakes."""
import asyncio
import importlib
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import discord
from discord import app_commands
from lumia.core import Store


class Entity:
    def __init__(self, number, roles=(), guild=None):
        self.id = number
        self.roles = list(roles)
        self.guild = guild
        self.bot = False
        self.display_name = f'user-{number}'
        self.guild_permissions = SimpleNamespace(administrator=False)

    def __hash__(self):
        return self.id

    def __eq__(self, other):
        return isinstance(other, Entity) and self.id == other.id

    def __str__(self):
        return self.display_name


class Guild:
    id = 77
    owner_id = 901
    filesize_limit = 1024 * 1024

    def __init__(self):
        self.default_role = Entity(1)
        self.roles = {n: Entity(n) for n in (101, 102, 103, 104, 105)}
        self.members = {}
        self.text_channels = []
        self.me = self.member(999)
        self.owner = self.member(901)
        self.category = SimpleNamespace(id=600)
        self.created_kwargs = None

    def member(self, number, roles=()):
        item = Entity(number, [self.roles[r] for r in roles], self)
        self.members[number] = item
        return item

    def get_member(self, number):
        return self.members.get(number)

    async def fetch_member(self, number):
        if number not in self.members:
            raise RuntimeError('missing member')
        return self.members[number]

    def get_role(self, number):
        return self.roles.get(number)

    def get_channel(self, number):
        if number == 600:
            return self.category
        return next((c for c in self.text_channels if c.id == number), None)

    async def create_text_channel(self, name, **kwargs):
        self.created_kwargs = kwargs
        channel = Channel(self, 700 + len(self.text_channels), kwargs['topic'])
        channel.overwrites = kwargs['overwrites']
        self.text_channels.append(channel)
        return channel


class Channel:
    def __init__(self, guild, number=700, topic='lumia-ticket:1'):
        self.guild, self.id, self.topic = guild, number, topic
        self.mention = f'<#{number}>'
        self.overwrites = {}
        self.sent = []
        self.messages = []
        self.history_failure = False
        self.deleted = False
        self.history_args = None

    async def edit(self, **kwargs):
        self.overwrites = kwargs.get('overwrites', self.overwrites)
        return self

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return SimpleNamespace(id=800)

    def history(self, **kwargs):
        self.history_args = kwargs
        async def stream():
            if self.history_failure:
                raise OSError('history unavailable')
            for message in self.messages:
                yield message
        return stream()

    async def delete(self, **kwargs):
        self.deleted = True


class Bot:
    def __init__(self, store, directory, guild):
        self.store, self.data_dir, self.guild = store, Path(directory), guild
        self.cfg = {'guild_id': 77, 'owner_ids': [902], 'roles': {
            'management': 101, 'support': 102, 'developer': 103,
            'member': 104, 'customer': 105}, 'categories': {
            'tickets': 600, 'private_tickets': 600}, 'channels': {}, 'retention_days': 90}
        self.views = []
        self.logs = []

    def get_guild(self, number):
        return self.guild if number == 77 else None

    def add_view(self, view):
        self.views.append(view)

    async def log(self, key, text):
        self.logs.append((key, text))
        return True


class TicketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.module = importlib.import_module('lumia.tickets')
        except ModuleNotFoundError:
            self.fail('The ticket engine must exist before its privacy contract can pass')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state.db')
        self.addCleanup(self.store.close)
        self.guild = Guild()
        self.author = self.guild.member(201, (104, 105))
        self.support = self.guild.member(202, (102,))
        self.manager = self.guild.member(203, (101,))
        self.developer = self.guild.member(204, (103,))
        self.guild.member(902)
        self.bot = Bot(self.store, self.temp.name, self.guild)
        self.cog = self.module.Tickets(self.bot)

    def ticket(self, kind='custom', state='open'):
        ticket = self.store.reserve_ticket(201, kind, {'Richiesta': 'progetto riservato'})
        channel = Channel(self.guild, 700, f'lumia-ticket:{ticket["id"]}')
        self.guild.text_channels.append(channel)
        self.store.update_ticket(ticket['id'], state=state, channel=700)
        return self.store.ticket(ticket['id']), channel

    async def test_ordinary_overwrites_exclude_generic_and_developer_roles(self):
        ticket, _ = self.ticket()
        overwrites = self.module.build_overwrites(self.guild, self.bot.cfg, ticket)
        self.assertFalse(overwrites[self.guild.default_role].view_channel)
        self.assertTrue(overwrites[self.author].read_message_history)
        self.assertTrue(overwrites[self.author].send_messages)
        self.assertTrue(overwrites[self.author].attach_files)
        self.assertTrue(overwrites[self.author].embed_links)
        self.assertTrue(overwrites[self.guild.roles[102]].view_channel)
        for role in (103, 104, 105):
            self.assertNotIn(self.guild.roles[role], overwrites)

    async def test_private_ticket_support_cannot_access_or_receive_overwrite(self):
        ticket, _ = self.ticket('report')
        overwrites = self.module.build_overwrites(self.guild, self.bot.cfg, ticket)
        self.assertNotIn(self.guild.roles[102], overwrites)
        self.assertFalse(self.module.can_access(self.support, ticket, self.bot.cfg))
        self.assertFalse(self.module.can_access(self.support, ticket, self.bot.cfg, staff=True))
        self.assertTrue(self.module.can_access(self.author, ticket, self.bot.cfg))
        self.assertTrue(self.module.can_access(self.manager, ticket, self.bot.cfg, staff=True))
        self.assertIn(self.guild.get_member(902), overwrites)

    async def test_persistent_views_have_stable_dispatch_identifiers(self):
        await self.cog.cog_load()
        self.assertEqual(len(self.bot.views), 2)
        self.assertTrue(all(view.is_persistent() for view in self.bot.views))
        ids = [item.custom_id for view in self.bot.views for item in view.children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('lumia:tickets:select:v1', ids)

    async def test_startup_with_public_url_keeps_select_separate_from_buttons(self):
        with patch.dict(os.environ,{'LUMIA_PUBLIC_URL':'https://manager.lumiadevelopment.it'}):
            await self.cog.cog_load()
        panel=self.bot.views[0]
        self.assertTrue(panel.is_persistent())
        rows=panel.to_components()
        self.assertEqual(len(rows),2)
        self.assertEqual([item['type'] for item in rows[0]['components']],[3])
        self.assertEqual([item['type'] for item in rows[1]['components']],[2,2])
        buttons=rows[1]['components']
        self.assertEqual(buttons[0]['custom_id'],'lumia:tickets:privacy:v1')
        self.assertEqual(buttons[1]['url'],'https://manager.lumiadevelopment.it/start')
        self.assertEqual(len(self.bot.views),2)
        await self.cog.cog_unload()

    async def test_panel_without_public_url_still_has_valid_persistent_layout(self):
        with patch.dict(os.environ,{'LUMIA_PUBLIC_URL':''}):
            panel=self.module.TicketPanelView(self.cog)
        self.assertTrue(panel.is_persistent())
        rows=panel.to_components()
        self.assertEqual([item['type'] for item in rows[0]['components']],[3])
        self.assertEqual([item['type'] for item in rows[1]['components']],[2])
        panel.stop()

    async def test_components_reject_other_guild_before_action(self):
        interaction = SimpleNamespace(guild_id=88, user=self.manager)
        with self.assertRaises(app_commands.CheckFailure):
            self.cog.check_guild(interaction)

    async def test_creation_requires_management_role_without_consuming_quota(self):
        self.bot.cfg['roles']['management'] = 0
        with self.assertRaises(ValueError):
            await self.cog.create_ticket(self.guild, self.author, 'support', {'Richiesta': 'x'})
        self.assertEqual(self.store.tickets(), [])

    async def test_new_project_tickets_are_redirected_to_the_site_without_using_quota(self):
        for kind in ('fivem','minecraft','script','custom'):
            with self.assertRaises(ValueError):
                await self.cog.create_ticket(self.guild,self.author,kind,{'Richiesta':'Progetto'})
        self.assertEqual(self.store.tickets(),[])

    async def test_creation_uses_explicit_overwrites_and_persistent_controls(self):
        ticket = await self.cog.create_ticket(self.guild, self.author, 'support', {'Richiesta': 'x'})
        self.assertEqual(ticket['state'], 'open')
        self.assertIn(self.author, self.guild.created_kwargs['overwrites'])
        channel = self.guild.get_channel(ticket['channel'])
        self.assertTrue(any(kwargs.get('view') and kwargs['view'].is_persistent() for _, kwargs in channel.sent))
        self.assertEqual(channel.topic, f'lumia-ticket:{ticket["id"]}')

    async def test_close_history_failure_keeps_ticket_open_and_never_deletes(self):
        ticket, channel = self.ticket()
        channel.history_failure = True
        with self.assertRaises(OSError):
            await self.cog.close_ticket(ticket['id'], self.support, 'finito')
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertFalse(channel.deleted)
        self.assertTrue(channel.overwrites[self.author].send_messages)
        self.assertEqual(list((Path(self.temp.name) / 'transcripts').glob('*.txt')), [])

    async def test_private_close_rejects_support_before_mutating(self):
        ticket, channel = self.ticket('partner')
        with self.assertRaises(app_commands.CheckFailure):
            await self.cog.close_ticket(ticket['id'], self.support, 'finito')
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertEqual(channel.overwrites, {})

    async def test_successful_close_archives_full_utf8_history_and_denies_sending(self):
        ticket, channel = self.ticket()
        channel.messages = [SimpleNamespace(
            id=n, author=self.author, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            edited_at=None, content='à' * 3000 + f' messaggio {n}',
            attachments=[SimpleNamespace(filename='disegno.png', url='https://cdn.example/file', size=12, content_type='image/png')],
            embeds=[], stickers=[], reference=None) for n in range(125)]
        await self.cog.close_ticket(ticket['id'], self.support, 'consegnato')
        saved = self.store.ticket(ticket['id'])
        self.assertEqual(saved['state'], 'closed')
        data = (Path(self.temp.name) / 'transcripts' / saved['transcript']).read_text('utf-8')
        self.assertIn('messaggio 124', data)
        self.assertIn('à' * 3000, data)
        self.assertIn('https://cdn.example/file', data)
        self.assertIn('2026-01-01', data)
        self.assertIsNone(channel.history_args['limit'])
        self.assertTrue(channel.history_args['oldest_first'])
        self.assertFalse(channel.overwrites[self.author].send_messages)
        self.assertFalse(channel.overwrites[self.guild.roles[102]].send_messages)
        self.assertFalse(channel.deleted)

    async def test_replace_failure_does_not_publish_partial_transcript(self):
        ticket, channel = self.ticket()
        with patch.object(self.module.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                await self.cog.close_ticket(ticket['id'], self.support, 'finito')
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertEqual(list((Path(self.temp.name) / 'transcripts').iterdir()), [])

    async def test_concurrent_claim_has_one_winner(self):
        ticket, _ = self.ticket()
        results = await asyncio.gather(*(self.cog.claim_ticket(ticket['id'], self.support) for _ in range(8)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.store.ticket(ticket['id'])['staff'], self.support.id)

    async def test_private_ticket_cannot_gain_individual_developer(self):
        ticket, channel = self.ticket('report')
        with self.assertRaises(ValueError):
            await self.cog.change_developer(ticket['id'], self.manager, self.developer, add=True)
        self.assertEqual(self.store.ticket(ticket['id'])['extra'], [])
        self.assertEqual(channel.overwrites, {})

    async def test_remove_developer_revokes_explicit_visibility(self):
        ticket, channel = self.ticket()
        await self.cog.change_developer(ticket['id'], self.manager, self.developer, add=True)
        self.assertTrue(channel.overwrites[self.developer].view_channel)
        await self.cog.change_developer(ticket['id'], self.manager, self.developer, add=False)
        self.assertNotIn(self.developer, channel.overwrites)
        self.assertEqual(self.store.ticket(ticket['id'])['extra'], [])

    async def test_recovery_links_creating_ticket_from_topic(self):
        ticket, channel = self.ticket(state='creating')
        self.store.update_ticket(ticket['id'], channel=None)
        await self.cog.recover()
        self.assertEqual(self.store.ticket(ticket['id'])['channel'], channel.id)
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertTrue(channel.sent)

    async def test_recovery_reopens_interrupted_close(self):
        ticket, channel = self.ticket(state='closing')
        await self.cog.recover()
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertTrue(channel.overwrites[self.author].send_messages)

    async def test_channel_topic_mismatch_blocks_ticket_operations(self):
        ticket, channel = self.ticket()
        channel.topic = 'not a ticket'
        with self.assertRaises(ValueError):
            await self.cog.close_ticket(ticket['id'], self.support, 'finito')
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'open')
        self.assertFalse(channel.deleted)

    async def test_delete_requires_seven_days_and_intact_archive(self):
        ticket, channel = self.ticket()
        await self.cog.close_ticket(ticket['id'], self.manager, 'finito')
        with self.assertRaises(ValueError):
            await self.cog.delete_closed(ticket['id'], self.manager, f'ELIMINA #{ticket["id"]}')
        self.store.update_ticket(ticket['id'], closed=time.time() - 8 * 86400)
        saved = self.store.ticket(ticket['id'])
        archive = Path(self.temp.name) / 'transcripts' / saved['transcript']
        archive.write_text('corrupted', encoding='utf-8')
        with self.assertRaises(ValueError):
            await self.cog.delete_closed(ticket['id'], self.manager, f'ELIMINA #{ticket["id"]}')
        self.assertFalse(channel.deleted)

    async def test_long_form_is_visible_in_full_inside_private_ticket_channel(self):
        text = 'requisito à ' * 150
        ticket = await self.cog.create_ticket(self.guild, self.author, 'support', {'Richiesta': text})
        channel = self.guild.get_channel(ticket['channel'])
        posted = '\n'.join(content or (kwargs['embed'].description or '') if 'embed' in kwargs else content or ''
                           for content,kwargs in channel.sent)
        self.assertIn(text, posted)

    async def test_concurrent_close_cannot_archive_and_close_twice(self):
        ticket, channel = self.ticket()
        results = await asyncio.gather(
            self.cog.close_ticket(ticket['id'], self.manager, 'finito'),
            self.cog.close_ticket(ticket['id'], self.manager, 'finito'),
            return_exceptions=True)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'closed')
        self.assertFalse(channel.deleted)

    async def test_verified_closed_channel_can_be_deleted_after_seven_days(self):
        ticket, channel = self.ticket()
        await self.cog.close_ticket(ticket['id'], self.manager, 'finito')
        self.store.update_ticket(ticket['id'], closed=time.time() - 8 * 86400)
        await self.cog.delete_closed(ticket['id'], self.manager, f'ELIMINA #{ticket["id"]}')
        self.assertTrue(channel.deleted)
        self.assertTrue(self.cog.verified_archive(self.store.ticket(ticket['id'])).is_file())

    async def test_failed_developer_state_commit_rolls_back_discord_visibility(self):
        ticket, channel = self.ticket()
        with patch.object(self.store, 'update_ticket', side_effect=OSError('database unavailable')):
            with self.assertRaises(OSError):
                await self.cog.change_developer(ticket['id'], self.manager, self.developer, add=True)
        self.assertNotIn(self.developer, channel.overwrites)
        self.assertEqual(self.store.ticket(ticket['id'])['extra'], [])

    async def test_recovery_without_channel_releases_quota_without_deleting_any_channel(self):
        ticket = self.store.reserve_ticket(self.author.id, 'custom', {'Richiesta': 'x'})
        unrelated = Channel(self.guild, 987, 'Ordinary channel')
        self.guild.text_channels.append(unrelated)
        await self.cog.recover()
        self.assertEqual(self.store.ticket(ticket['id'])['state'], 'failed')
        self.assertFalse(unrelated.deleted)

    async def test_unverified_user_cannot_create_ticket_or_consume_quota(self):
        newcomer = self.guild.member(205)
        with self.assertRaises(app_commands.CheckFailure):
            await self.cog.create_ticket(self.guild, newcomer, 'custom', {'Richiesta': 'x'})
        self.assertEqual(self.store.tickets(), [])

    async def test_status_change_keeps_actor_timestamp_and_previous_stage(self):
        ticket, _ = self.ticket()
        class Response:
            def is_done(self):
                return False
            async def send_message(self, text, **kwargs):
                pass
        interaction = SimpleNamespace(guild_id=77, guild=self.guild, channel_id=700,
                                      user=self.support, response=Response())
        await self.cog.status.callback(self.cog, interaction,
                                      app_commands.Choice(name='Revisione', value='revisione'))
        self.assertEqual(self.store.ticket(ticket['id'])['stage'], 'revisione')
        history = self.store.get('ticket_stage_history', ticket['id'], [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['actor'], self.support.id)
        self.assertGreater(history[0]['at'], 0)
        self.assertEqual(history[0]['current'], 'nuovo')
        self.assertEqual(history[0]['new'], 'revisione')
