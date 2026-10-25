import unittest
from unittest.mock import AsyncMock
import test_onboarding as fixtures
from lumia import onboarding
from lumia.config import validate_config


class DiscordPreferencesTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.PrivateOnboardingTests.setUp
    interaction=fixtures.PrivateOnboardingTests.interaction

    async def test_preferences_work_in_server_with_closed_dms(self):
        self.member.roles=[self.roles[20],self.roles[21]]
        self.member.send=AsyncMock(side_effect=AssertionError('No DM'))
        i=self.interaction(guild_id=123)
        await onboarding.open_preferences(self.bot,i)
        sent=i.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        view=sent['view']
        self.assertTrue(any(o.value=='fivem' and o.default for o in view.select.options))
        self.member.send.assert_not_awaited()

    async def test_preferences_never_grant_member_and_reject_other_guild(self):
        i=self.interaction(guild_id=123)
        await onboarding.open_preferences(self.bot,i)
        self.assertNotIn('view',i.followup.send.call_args.kwargs)
        self.member.add_roles.assert_not_awaited()
        self.guild.fetch_member.reset_mock()
        await onboarding.open_preferences(self.bot,self.interaction(guild_id=999))
        self.guild.fetch_member.assert_not_awaited()

    async def test_web_interest_is_safe_optional_and_preserves_other_roles(self):
        self.roles[25]=fixtures.Role(25)
        self.bot.cfg['roles']['web']=25
        self.member.roles=[self.roles[20],fixtures.Role(98)]
        view=onboarding.RolePanel(self.bot)
        view.select._values=['web']
        await view.select.callback(self.interaction(guild_id=123))
        self.member.add_roles.assert_awaited_once_with(self.roles[25],reason='Preferenze Lumia')
        self.member.remove_roles.assert_not_awaited()
        self.assertEqual(validate_config({'guild_id':123,'roles':{'web':25}})['roles']['web'],25)

    async def test_unconfigured_web_option_reports_setup_before_any_role_change(self):
        self.member.roles=[self.roles[20],self.roles[21]]
        view=onboarding.RolePanel(self.bot);view.select._values=['web']
        await view.select.callback(self.interaction(guild_id=123))
        self.member.add_roles.assert_not_awaited();self.member.remove_roles.assert_not_awaited()
