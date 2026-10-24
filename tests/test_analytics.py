import json
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from lumia.analytics import Analytics, page_key
from lumia.core import Store
from lumia.web import create_app
from tests import test_web

BROWSER = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1'


def batch(*events):
    return json.dumps({'events': list(events)})


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.analytics = Analytics(self.store)
        self.now = time.time()

    def test_visitor_is_a_daily_hash_and_no_address_is_stored(self):
        self.analytics.record('landing', '203.0.113.9', BROWSER, [{'kind': 'view', 'path': '/', 'view': 'abcdef12'}], now=self.now)
        dump = '\n'.join(self.store.db.iterdump())
        self.assertNotIn('203.0.113.9', dump)
        first = self.analytics.visitor('203.0.113.9', BROWSER, self.now)
        self.assertEqual(first, self.analytics.visitor('203.0.113.9', BROWSER, self.now))
        self.assertNotEqual(first, self.analytics.visitor('203.0.113.9', BROWSER, self.now + 86400))

    def test_sessions_split_after_thirty_minutes_and_bots_are_ignored(self):
        view = {'kind': 'view', 'path': '/', 'view': 'abcdef12'}
        self.analytics.record('landing', '1.1.1.1', BROWSER, [view], now=self.now)
        self.analytics.record('landing', '1.1.1.1', BROWSER, [view], now=self.now + 600)
        self.analytics.record('landing', '1.1.1.1', BROWSER, [view], now=self.now + 600 + 1801)
        self.assertEqual(self.analytics.record('landing', '1.1.1.1', 'Googlebot/2.1', [view], now=self.now), 0)
        sessions = [row[0] for row in self.store.db.execute('SELECT DISTINCT session FROM analytics_events')]
        self.assertEqual(len(sessions), 2)

    def test_invalid_items_are_dropped_and_text_is_bounded(self):
        stored = self.analytics.record('landing', '1.1.1.1', BROWSER, [
            {'kind': 'view', 'path': 'https://evil.example/', 'view': 'abcdef12'},
            {'kind': 'eval', 'path': '/', 'view': 'abcdef12'},
            {'kind': 'click', 'path': '/', 'view': 'abc'},
            {'kind': 'click', 'path': '/', 'view': 'abcdef12', 'label': 'x' * 500, 'x': 7, 'y': -1}], now=self.now)
        self.assertEqual(stored, 1)
        row = self.store.db.execute('SELECT label, x, y FROM analytics_events').fetchone()
        self.assertEqual((len(row['label']), row['x'], row['y']), (120, 1, 0))

    def test_funnel_follows_a_person_from_landing_to_payment(self):
        events = [{'kind': 'view', 'path': '/', 'view': 'landing1', 'ref': 'https://www.google.com/search'},
                  {'kind': 'leave', 'path': '/', 'view': 'landing1', 'value': 30, 'y': .5,
                   'sections': [{'id': 'hero', 'label': 'Hero', 'seen': True}, {'id': 'faq', 'label': 'FAQ', 'seen': False}]}]
        self.analytics.record('landing', '1.1.1.1', BROWSER, events, now=self.now - 300)
        self.analytics.record('manager', '1.1.1.1', BROWSER, [{'kind': 'view', 'path': '/start', 'view': 'start123'},
                              {'kind': 'step', 'path': '/start', 'view': 'start123', 'label': 'Riepilogo', 'value': 5}], now=self.now - 200)
        self.analytics.goal('1.1.1.1', BROWSER, 'request', 10, 4, now=self.now - 100)
        self.analytics.goal(None, '', 'paid', 10, 4, now=self.now - 50)  # webhook, no browser
        self.analytics.record('landing', '9.9.9.9', BROWSER, [{'kind': 'view', 'path': '/', 'view': 'other123'}], now=self.now - 30)
        report = self.analytics.report('today', names=lambda user: 'Giulia', now=self.now)
        funnel = {step['key']: step['count'] for step in report['funnel']}
        self.assertEqual((funnel['visit'], funnel['start'], funnel['summary'], funnel['request'], funnel['paid']), (2, 1, 1, 1, 1))
        self.assertEqual(report['kpis']['requests'], 1)
        self.assertEqual(report['reach'][0]['sections'], [{'label': 'Hero', 'share': 100.0}, {'label': 'FAQ', 'share': 0.0}])
        self.assertIn('Google', [row['label'] for row in report['sources']])
        visit = next(v for v in report['recent'] if v['known'] and 'Landing' in v['trail'])
        self.assertEqual((visit['person'], visit['order'], visit['trail']), ('Giulia', 4, ['Landing', 'Inizia un progetto']))
        webhook = next(v for v in report['recent'] if v['known'] and v is not visit)
        self.assertEqual(webhook['trail'], ['Pagamento completato'])
        journey = self.analytics.session(visit['id'])
        self.assertEqual([e['kind'] for e in journey['timeline']], ['view', 'leave', 'view', 'step', 'goal'])

    def test_team_visits_are_excluded_unless_requested(self):
        self.analytics.mark_staff(99)
        self.analytics.record('manager', '1.1.1.1', BROWSER, [{'kind': 'view', 'path': '/', 'view': 'staff123'}], 99, now=self.now)
        self.analytics.record('landing', '1.1.1.1', BROWSER, [{'kind': 'view', 'path': '/', 'view': 'staff456'}], now=self.now + 10)
        self.assertTrue(self.analytics.report('today', now=self.now + 20)['empty'])
        self.assertEqual(self.analytics.report('today', include_staff=True, now=self.now + 20)['kpis']['sessions'], 1)

    def test_page_keys_group_order_numbers(self):
        self.assertEqual(page_key('manager', '/orders/12/paypal/return?token=x'), 'manager:/orders/:id/paypal/return')
        self.assertEqual(page_key('landing', '/'), 'landing:/')


class AnalyticsWebTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    tearDown = test_web.WebTests.tearDown
    login = test_web.WebTests.login

    def beacon(self, client, body, origin='https://manager.example'):
        return client.post('/_t', content=body, headers={'origin': origin, 'content-type': 'text/plain', 'user-agent': BROWSER,
                                                         'cf-connecting-ip': '198.51.100.7'})

    def test_beacon_requires_same_origin_and_links_signed_in_people(self):
        view = {'kind': 'view', 'path': '/', 'view': 'abcdef12'}
        self.assertEqual(self.beacon(self.client, batch(view), origin='https://evil.example').status_code, 403)
        self.assertEqual(self.beacon(self.client, batch(view)).status_code, 204)
        self.assertEqual(self.beacon(self.client, 'not json').status_code, 204)
        self.login(10)
        self.beacon(self.client, batch(view))
        users = [row[0] for row in self.store.db.execute('SELECT user_id FROM analytics_events ORDER BY id')]
        self.assertEqual(users[0], None)
        self.assertEqual(users[-1], 10)
        goals = [row[0] for row in self.store.db.execute("SELECT target FROM analytics_events WHERE kind='goal'")]
        self.assertEqual(goals, ['login'])

    def test_only_management_opens_the_analysis(self):
        self.assertEqual(self.client.get('/analytics').status_code, 303)
        self.login(10)
        self.assertEqual(self.client.get('/analytics').status_code, 403)
        self.login(99)
        page = self.client.get('/analytics?range=30d&team=1')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Dal sito all’ordine', page.text)
        session = self.store.db.execute('SELECT session FROM analytics_events LIMIT 1').fetchone()[0]
        self.assertEqual(self.client.get(f'/analytics/sessions/{session}').status_code, 200)
        self.assertEqual(self.client.get('/analytics/sessions/nope').status_code, 404)

    def test_landing_host_records_its_own_beacons(self):
        with patch.dict(os.environ, {'LUMIA_SITE_URL': 'https://studio.example'}):
            app = create_app(self.bot, http_transport=self.transport)
        with TestClient(app, base_url='https://studio.example') as site:
            body = batch({'kind': 'view', 'path': '/', 'view': 'abcdef12'})
            self.assertEqual(self.beacon(site, body, origin='https://evil.example').status_code, 204)
            self.assertEqual(self.beacon(site, body, origin='https://studio.example').status_code, 204)
        rows = list(self.store.db.execute('SELECT site FROM analytics_events'))
        self.assertEqual([row[0] for row in rows], ['landing'])
        with open('lumia/templates/landing.html', encoding='utf-8') as landing:
            self.assertIn('/static/track.js', landing.read())


if __name__ == '__main__':
    unittest.main()
