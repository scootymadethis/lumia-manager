"""The customer tutorial remains readable, isolated and safe to explore."""
import re
import unittest

from fastapi.testclient import TestClient
import test_web as fixtures
from lumia.site import create_site_app
from lumia.web import create_demo_app


class CustomerTutorialTests(unittest.TestCase):
    setUp = fixtures.WebTests.setUp
    tearDown = fixtures.WebTests.tearDown
    login = fixtures.WebTests.login
    csrf = fixtures.WebTests.csrf

    def tutorial(self):
        with TestClient(self.app, base_url='https://manager.example', raise_server_exceptions=False) as client:
            client.cookies.update(self.client.cookies)
            return client.get('/tutorial')

    def test_client_can_read_all_eight_chapters_without_changing_a_project(self):
        order = self.orders.create(10, 'Il mio progetto', 10000)
        before = self.orders.get(order['id'])
        self.login(10)
        response = self.tutorial()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(re.findall(r'data-tutorial-chapter="[0-7]"', response.text)), 8)
        for text in ('Account Discord', 'Nuova richiesta', 'preventivo', 'PayPal', 'tranche', 'Milestone', 'Conversazione', 'Attività', 'consegna', 'Supporto Discord', 'Esci dall’account'):
            self.assertIn(text, response.text)
        self.assertIn('data-tutorial-next', response.text)
        self.assertIn('data-tutorial-back', response.text)
        self.assertIn('/static/customer-tutorial.js', response.text)
        self.assertEqual(self.orders.get(order['id']), before)
        self.assertEqual(self.orders.payments(order['id']), [])

    def test_tutorial_uses_only_own_project_for_context_links(self):
        own = self.orders.create(10, 'PROGETTO MIO', 10000)
        other = self.orders.create(20, 'PROGETTO SEGRETO', 20000)
        self.login(10)
        response = self.tutorial()
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'href="/orders/{own["id"]}#conversation"', response.text)
        self.assertNotIn(f'href="/orders/{other["id"]}', response.text)
        self.assertNotIn('PROGETTO SEGRETO', response.text)

    def test_no_project_has_readable_fallback_and_persistent_entry_points(self):
        self.login(10)
        response = self.tutorial()
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/orders"', response.text)
        for path in ('/', '/orders', '/payments'):
            page = self.client.get(path)
            self.assertGreaterEqual(page.text.count('href="/tutorial"'), 2, path)

    def test_anonymous_tutorial_requires_login(self):
        response = self.client.get('/tutorial')
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login')

    def test_demo_tutorial_links_keep_client_view(self):
        with TestClient(create_demo_app(), base_url='http://127.0.0.1:8765', raise_server_exceptions=False) as client:
            response = client.get('/tutorial?view=client')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('href="/tutorial?view=client"', response.text)
            self.assertIn('href="/orders?view=client"', response.text)
            self.assertRegex(response.text, r'href="/orders/\d+\?view=client#conversation"')

    def test_client_guide_progress_uses_new_version_and_admin_keeps_version_two(self):
        for actor, version in ((10, 3), (99, 2)):
            self.login(actor)
            response = self.client.post('/preferences/tour', data={'csrf': self.csrf(), 'status': 'started', 'page': 'tutorial', 'step': '2'}, headers={'origin': 'https://manager.example'})
            self.assertEqual(response.status_code, 200)
            role = 'admin' if actor == 99 else 'client'
            self.assertEqual(self.store.get('workspace_tour', f'{actor}:{role}')['version'], version)

    def test_landing_highlights_existing_order_access(self):
        with TestClient(create_site_app('https://site.example', 'https://manager.example'), base_url='https://site.example') as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertRegex(response.text, r'class="returning-client"[^>]*href="https://manager.example/login"')
            self.assertIn('Hai già un ordine in corso?', response.text)
            self.assertIn('Vai all’area clienti', response.text)
