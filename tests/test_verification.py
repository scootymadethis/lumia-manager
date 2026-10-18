"""Verification must never grant roles on failed/foreign/expired membership checks."""
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from discord import app_commands
import test_onboarding as onboarding_fixtures
from lumia.onboarding import RulesPanel,complete_acceptance
from lumia.verification import Verification,VerificationModal,verification_enabled,duration_seconds


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    setUp=onboarding_fixtures.PrivateOnboardingTests.setUp
    interaction=onboarding_fixtures.PrivateOnboardingTests.interaction

    async def test_verification_is_enabled_by_default_and_timed_pause_expires(self):
        self.store.delete('verification','policy')
        self.assertTrue(verification_enabled(self.store))
        self.store.put('verification','policy',{'enabled':False,'until':1000})
        self.assertFalse(verification_enabled(self.store,now=999))
        self.assertTrue(verification_enabled(self.store,now=1000))
        self.store.put('verification','policy',{'enabled':False,'until':None})
        self.assertFalse(verification_enabled(self.store,now=9999999999))

    async def test_acceptance_opens_challenge_before_granting_member(self):
        self.store.delete('verification','policy')
        i=self.interaction()
        i.response.send_modal=AsyncMock()
        await RulesPanel(self.bot).accept.callback(i)
        i.response.send_modal.assert_awaited_once()
        self.member.add_roles.assert_not_awaited()
        self.assertIsNone(self.store.get('rules',10))

    async def test_correct_answer_grants_only_own_member_and_records_verification(self):
        self.store.delete('verification','policy')
        modal=VerificationModal(self.bot,10,complete_acceptance)
        modal.value._value=modal.answer
        await modal.on_submit(self.interaction())
        self.member.add_roles.assert_awaited_once()
        self.assertTrue(self.store.get('rules',10)['verified'])

    async def test_wrong_answers_lock_out_repeated_attempts_without_roles(self):
        self.store.delete('verification','policy')
        for _ in range(5):
            modal=VerificationModal(self.bot,10,complete_acceptance)
            modal.value._value='999'
            await modal.on_submit(self.interaction())
        modal=VerificationModal(self.bot,10,complete_acceptance)
        modal.value._value=modal.answer
        await modal.on_submit(self.interaction())
        self.member.add_roles.assert_not_awaited()
        self.assertGreater(self.store.get('verification_attempts',10)['blocked_until'],time.time())

    async def test_another_user_cannot_submit_a_challenge(self):
        modal=VerificationModal(self.bot,10,complete_acceptance)
        modal.value._value=modal.answer
        await modal.on_submit(self.interaction(user=11))
        self.member.add_roles.assert_not_awaited()

    async def test_management_can_pause_indefinitely_and_resume(self):
        self.member.guild=self.guild
        self.guild.owner_id=10
        i=self.interaction(guild_id=123)
        i.guild=self.guild
        i.user=self.member
        cog=Verification(self.bot)
        await Verification.disable.callback(cog,i)
        self.assertFalse(verification_enabled(self.store))
        self.assertIsNone(self.store.get('verification','policy')['until'])
        await Verification.enable.callback(cog,i)
        self.assertTrue(verification_enabled(self.store))

    async def test_customer_cannot_disable_verification(self):
        self.guild.owner_id=999
        i=self.interaction(guild_id=123)
        i.guild=self.guild
        i.user=self.member
        with self.assertRaises(app_commands.CheckFailure):
            await Verification.disable.callback(Verification(self.bot),i,'30m')

    async def test_duration_parser_accepts_minutes_hours_days_and_rejects_bad_values(self):
        for value,expected in [('30m',1800),('2h',7200),('1g',86400),('15',900)]:
            self.assertEqual(duration_seconds(value),expected)
        for value in ('0m','-2h','due ore','999999d','1.5h'):
            with self.assertRaises(ValueError): duration_seconds(value)
