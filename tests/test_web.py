import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from lumia.core import Store
from lumia.orders import Orders
from lumia.web import create_app, create_demo_app, verify_stripe_signature


class Guild:
    def __init__(self):
        self.owner_id = 1000
        self.members = {99: [500], 10: [600], 20: [600]}

    async def fetch_member(self, user_id):
        if user_id not in self.members:
            raise LookupError('not a guild member')
        return SimpleNamespace(id=user_id, guild=self, roles=[SimpleNamespace(id=i) for i in self.members[user_id]])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        self.addCleanup(self.store.close)
        self.orders = Orders(self.store)
        self.guild = Guild()
        self.bot = SimpleNamespace(cfg={'guild_id': 1, 'owner_ids': [99], 'roles': {'management': 500}},
                                   store=self.store, orders=self.orders, get_guild=lambda _: self.guild)
        self.actor = 99
        self.sent_checkout = None
        self.paypal_orders = {}
        def discord(request):
            if request.url.host == 'api-m.sandbox.paypal.com':
                if request.url.path.endswith('/v1/oauth2/token'):
                    return httpx.Response(200,json={'access_token':'paypal-test-token'})
                if request.url.path.endswith('/verify-webhook-signature'):
                    return httpx.Response(200,json={'verification_status':'SUCCESS'})
                if request.url.path == '/v2/checkout/orders':
                    self.sent_checkout = json.loads(request.content)
                    token = f'PP{len(self.paypal_orders)+1}'
                    self.paypal_orders[token] = {'id':token,'status':'CREATED',**self.sent_checkout}
                    return httpx.Response(201,json={'id':token,'links':[{'rel':'payer-action','href':f'https://www.sandbox.paypal.com/checkoutnow?token={token}'}]})
                token = request.url.path.split('/')[4]
                return httpx.Response(200,json=self.paypal_orders[token])
            if request.url.host == 'api.stripe.com':
                self.sent_checkout = parse_qs(request.content.decode())
                return httpx.Response(200, json={'id': 'cs_created', 'url': 'https://checkout.stripe.com/c/pay/cs_created'})
            if request.url.path.endswith('/oauth2/token'):
                return httpx.Response(200, json={'access_token': 'external-test-token', 'token_type': 'Bearer', 'expires_in': 600})
            if request.url.path.endswith('/users/@me'):
                return httpx.Response(200, json={'id': str(self.actor), 'username': f'utente{self.actor}', 'global_name': f'Cliente {self.actor}'})
            if request.url.path.endswith('/member'):
                return httpx.Response(200, json={'roles': [str(r) for r in self.guild.members[self.actor]], 'user': {'id': str(self.actor)}})
            return httpx.Response(404)
        self.transport = httpx.MockTransport(discord)
        self.env = patch.dict(os.environ, {'DISCORD_CLIENT_ID': '123', 'DISCORD_CLIENT_SECRET': 'test-secret',
                                          'LUMIA_PUBLIC_URL': 'https://manager.example',
                                          'STRIPE_WEBHOOK_SECRET': 'whsec_test', 'STRIPE_SECRET_KEY': 'sk_test',
                                          'PAYPAL_CLIENT_ID':'test-id','PAYPAL_CLIENT_SECRET':'test-secret','PAYPAL_WEBHOOK_ID':'hook-test'}, clear=True)
        self.env.start()
        self.app = create_app(self.bot, http_transport=self.transport)
        self.client = TestClient(self.app, base_url='https://manager.example', follow_redirects=False)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def login(self, actor=99):
        self.actor = actor
        begin = self.client.get('/auth/discord')
        state = parse_qs(urlparse(begin.headers['location']).query)['state'][0]
        finish = self.client.get('/auth/callback', params={'state': state, 'code': 'test-code'})
        self.assertEqual(finish.status_code, 303)
        return state

    def csrf(self):
        response = self.client.get('/')
        return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)

    def test_production_requires_https_configuration_and_anonymous_cannot_read(self):
        self.assertEqual(self.client.get('/orders').status_code, 303)
        self.assertEqual(self.client.get('/orders', headers={'host': 'attacker.example'}).status_code, 400)
        with patch.dict(os.environ, {'LUMIA_PUBLIC_URL': 'http://manager.example'}), self.assertRaises(RuntimeError):
            create_app(self.bot)
        with patch.dict(os.environ, {'DISCORD_CLIENT_SECRET': ''}), self.assertRaises(RuntimeError):
            create_app(self.bot)

    def test_oauth_state_is_single_use_and_cookie_is_hardened(self):
        begin = self.client.get('/auth/discord')
        self.assertIn('Secure', begin.headers['set-cookie'])
        self.assertIn('HttpOnly', begin.headers['set-cookie'])
        self.assertIn('SameSite=lax', begin.headers['set-cookie'])
        self.assertEqual(self.client.get('/auth/callback?code=x&state=forged').status_code, 400)
        state = parse_qs(urlparse(begin.headers['location']).query)['state'][0]
        good = self.client.get('/auth/callback', params={'state': state, 'code': 'test-code'})
        self.assertEqual(good.status_code, 303)
        self.assertEqual(self.client.get('/auth/callback', params={'state': state, 'code': 'test-code'}).status_code, 400)

    def test_non_ascii_oauth_state_is_rejected_without_server_error(self):
        self.client.get('/auth/discord')
        self.assertEqual(self.client.get('/auth/callback', params={'state': 'stato-non-valido-è', 'code': 'test-code'}).status_code, 400)

    def test_non_ascii_csrf_is_rejected_without_server_error(self):
        self.login()
        response = self.client.post('/orders', data={'csrf': 'token-è'}, headers={'origin': 'https://manager.example'})
        self.assertEqual(response.status_code, 403)

    def test_staff_mutations_require_csrf_and_origin(self):
        self.login()
        payload = {'customer': '10', 'title': 'Progetto sicuro', 'total': '100,00', 'details': 'Dettaglio'}
        self.assertEqual(self.client.post('/orders', data=payload, headers={'origin': 'https://manager.example'}).status_code, 403)
        payload['csrf'] = self.csrf()
        self.assertEqual(self.client.post('/orders', data=payload, headers={'origin': 'https://evil.example'}).status_code, 403)
        good = self.client.post('/orders', data=payload, headers={'origin': 'https://manager.example'})
        self.assertEqual(good.status_code, 303)
        self.assertEqual(self.orders.list_for(10)[0]['total_cents'], 10000)

    def test_customer_isolation_finance_permissions_and_membership_revocation(self):
        mine = self.orders.create(10, 'ORDINE-MIO', 10000)
        other = self.orders.create(20, 'SEGRETO-ALTRO-CLIENTE', 10000)
        self.login(10)
        listing = self.client.get('/orders')
        self.assertIn('ORDINE-MIO', listing.text)
        self.assertNotIn('SEGRETO-ALTRO-CLIENTE', listing.text)
        self.assertEqual(self.client.get(f'/orders/{other["id"]}').status_code, 404)
        self.assertEqual(self.client.get('/customers').status_code, 403)
        response = self.client.post(f'/orders/{mine["id"]}/payments', data={'csrf': self.csrf(), 'amount': '100', 'reference': 'fake'}, headers={'origin': 'https://manager.example'})
        self.assertEqual(response.status_code, 403)
        del self.guild.members[10]
        self.assertEqual(self.client.get('/orders').status_code, 403)

    def test_success_url_never_credits_and_signed_webhook_is_idempotent(self):
        order = self.orders.create(10, 'Progetto', 10000)
        self.orders.save_checkout(order['id'], 'cs_paid', 10000, 'https://checkout.stripe.com/pay/test')
        event = {'id': 'evt_paid', 'type': 'checkout.session.completed', 'data': {'object': {'id': 'cs_paid', 'payment_status': 'paid', 'currency': 'eur', 'amount_total': 10000, 'metadata': {'order_id': str(order['id'])}}}}
        raw = json.dumps(event, separators=(',', ':')).encode()
        stamp = int(time.time())
        sig = hmac.new(b'whsec_test', str(stamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
        self.assertEqual(self.client.post('/webhooks/stripe', content=raw, headers={'stripe-signature': 't=1,v1=bad'}).status_code, 400)
        self.login(10)
        self.client.get(f'/orders/{order["id"]}?checkout=success')
        self.assertEqual(self.orders.summary(order)['paid_cents'], 0)
        headers = {'stripe-signature': f't={stamp},v1={sig}'}
        self.assertEqual(self.client.post('/webhooks/stripe', content=raw, headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/webhooks/stripe', content=raw, headers=headers).status_code, 200)
        self.assertEqual(self.orders.summary(order)['paid_cents'], 10000)
        self.assertEqual(len(self.orders.payments(order['id'])), 1)

    def test_demo_is_explicit_read_only_and_has_no_real_orders(self):
        self.orders.create(10, 'DATI-REALI-PRIVATI', 10000)
        with TestClient(create_demo_app(), base_url='http://127.0.0.1:8765') as demo:
            response = demo.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('DEMO', response.text)
            self.assertNotIn('DATI-REALI-PRIVATI', response.text)
            self.assertEqual(demo.post('/orders', data={}).status_code, 403)

    def test_checkout_uses_server_balance_and_existing_session(self):
        order = self.orders.create(10, 'Saldo da server', 10000)
        self.orders.update(order['id'], 'confermato', 99)
        self.orders.record_payment(order['id'], 3000, 'acconto', 99)
        self.login(10)
        response = self.client.post(f'/orders/{order["id"]}/checkout', data={'csrf': self.csrf(), 'amount': '0.01'}, headers={'origin': 'https://manager.example'})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.sent_checkout['purchase_units'][0]['amount']['value'], '70.00')
        self.assertEqual(self.sent_checkout['purchase_units'][0]['custom_id'], f'lumia:{order["id"]}:0')
        self.assertEqual(self.orders.recent_checkout(order['id'])['amount_cents'], 7000)
        self.assertEqual(self.orders.summary(order)['paid_cents'], 3000)
        self.sent_checkout = None
        second = self.client.post(f'/orders/{order["id"]}/checkout', data={'csrf': self.csrf()}, headers={'origin': 'https://manager.example'})
        self.assertEqual(second.headers['location'], response.headers['location'])
        self.assertIsNone(self.sent_checkout)

    def test_templates_escape_content_and_render_every_management_page(self):
        order = self.orders.create(10, '<script>alert(1)</script>', 10000, details='<img src=x onerror=alert(1)>')
        self.login()
        for path in ('/', '/orders', '/orders/new', '/customers', '/payments', '/settings', f'/orders/{order["id"]}'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('<script>alert(1)</script>', response.text)
        detail = self.client.get(f'/orders/{order["id"]}').text
        self.assertIn('&lt;script&gt;', detail)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', detail)

    def test_refund_is_flagged_for_reconciliation_and_expired_signatures_fail(self):
        event = {'id': 'evt_refund', 'type': 'charge.refunded', 'data': {'object': {'id': 'ch_refund'}}}
        raw = json.dumps(event).encode()
        stamp = int(time.time())
        sig = hmac.new(b'whsec_test', str(stamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
        self.assertFalse(verify_stripe_signature(raw, f't={stamp},v1={sig}', 'whsec_test', now=stamp + 301))
        self.assertEqual(self.client.post('/webhooks/stripe', content=raw, headers={'stripe-signature': f't={stamp},v1={sig}'}).status_code, 200)
        self.assertEqual(self.orders.events()[0]['status'], 'da_riconciliare')
        self.login()
        self.assertIn('Riconciliazione richiesta', self.client.get('/').text)

    def test_order_rejects_link_to_another_customers_ticket(self):
        ticket = self.store.reserve_ticket(20, 'support', {})
        self.login()
        response = self.client.post('/orders', data={'csrf': self.csrf(), 'customer': '10', 'title': 'Collegamento non valido', 'total': '100', 'ticket_id': str(ticket['id'])}, headers={'origin': 'https://manager.example'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.orders.list_for(10), [])

    def test_only_management_can_reverse_manual_payment_with_csrf(self):
        order = self.orders.create(10, 'Storno protetto', 10000)
        self.orders.record_payment(order['id'], 9000, 'errore', 99)
        payment = self.orders.payments(order['id'])[0]
        path = f'/orders/{order["id"]}/payments/{payment["id"]}/reverse'
        self.login(10)
        self.assertEqual(self.client.post(path, data={'csrf': self.csrf(), 'reason': 'Test'}, headers={'origin': 'https://manager.example'}).status_code, 403)
        self.login(99)
        self.assertEqual(self.client.post(path, data={'reason': 'Test'}, headers={'origin': 'https://manager.example'}).status_code, 403)
        response = self.client.post(path, data={'csrf': self.csrf(), 'reason': 'Errore di digitazione'}, headers={'origin': 'https://manager.example'})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.orders.summary(order)['due_cents'], 10000)
        self.assertIn('Errore di digitazione', self.client.get(f'/orders/{order["id"]}').text)

    def test_checkout_retry_after_timeout_uses_persisted_identical_attempt(self):
        order = self.orders.create(10, 'Riprova pagamento', 10000)
        self.orders.update(order['id'], 'confermato', 99)
        self.login(10)
        sent = []
        def timeout_once(request):
            if request.url.path.endswith('/oauth2/token'):
                return httpx.Response(200,json={'access_token':'test'})
            sent.append((request.headers['paypal-request-id'], request.content))
            if len(sent) == 1:
                raise httpx.ReadTimeout('response lost', request=request)
            return httpx.Response(200, json={'id': 'PPRETRY', 'links':[{'rel':'payer-action','href':'https://www.sandbox.paypal.com/checkoutnow?token=PPRETRY'}]})
        self.app = create_app(self.bot, http_transport=httpx.MockTransport(timeout_once))
        self.client.close()
        # Preserve the authenticated browser session while restarting the app object.
        cookies = self.client.cookies
        self.client = TestClient(self.app, base_url='https://manager.example', follow_redirects=False)
        self.client.cookies.update(cookies)
        payload = {'csrf': self.csrf()}
        first = self.client.post(f'/orders/{order["id"]}/checkout', data=payload, headers={'origin': 'https://manager.example'})
        self.assertEqual(first.status_code, 502)
        self.assertEqual(self.orders.summary(order)['paid_cents'], 0)
        # Recreate app to prove retry identity survives process/application state.
        cookies = self.client.cookies
        self.client.close()
        self.app = create_app(self.bot, http_transport=httpx.MockTransport(timeout_once))
        self.client = TestClient(self.app, base_url='https://manager.example', follow_redirects=False)
        self.client.cookies.update(cookies)
        second = self.client.post(f'/orders/{order["id"]}/checkout', data=payload, headers={'origin': 'https://manager.example'})
        self.assertEqual(second.status_code, 303)
        self.assertEqual(sent[0], sent[1])


if __name__ == '__main__':
    unittest.main()
