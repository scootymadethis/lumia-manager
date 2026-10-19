"""PayPal Orders v2: server-side amounts, durable retries and verified captures."""
import os
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx


class PayPal:
    def __init__(self, orders, public, transport=None):
        self.orders, self.store = orders, orders.store
        self.public, self.transport = public, transport
        self.client_id = os.getenv('PAYPAL_CLIENT_ID', '').strip()
        self.secret = os.getenv('PAYPAL_CLIENT_SECRET', '').strip()
        self.webhook_id = os.getenv('PAYPAL_WEBHOOK_ID', '').strip()
        self.environment = os.getenv('PAYPAL_ENVIRONMENT', 'sandbox').strip()
        if self.environment not in ('sandbox', 'live'):
            raise RuntimeError('PAYPAL_ENVIRONMENT deve essere sandbox oppure live.')
        self.base = 'https://api-m.paypal.com' if self.environment == 'live' else 'https://api-m.sandbox.paypal.com'
        self.host = 'www.paypal.com' if self.environment == 'live' else 'www.sandbox.paypal.com'
        with self.store.lock, self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS paypal_events (
                id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL)''')

    @property
    def ready(self):
        return bool(self.client_id and self.secret and self.webhook_id)

    async def api(self, method, path, *, data=None, key=None):
        async with httpx.AsyncClient(transport=self.transport, timeout=20) as http:
            token = await http.post(self.base + '/v1/oauth2/token',
                                    auth=(self.client_id, self.secret), data={'grant_type': 'client_credentials'})
            token.raise_for_status()
            headers = {'Authorization': 'Bearer ' + token.json()['access_token'], 'Prefer': 'return=representation'}
            if key:
                headers['PayPal-Request-Id'] = key
            response = await http.request(method, self.base + path, headers=headers, json=data)
            response.raise_for_status()
            return response.json()

    def checkout(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Z0-9]{1,36}', token):
            raise ValueError('Riferimento PayPal non valido.')
        with self.store.lock:
            row = self.store.db.execute("SELECT * FROM order_checkouts WHERE session_id=? AND provider='paypal'", (token,)).fetchone()
            if not row:
                raise ValueError('Pagamento PayPal non riconosciuto.')
            return dict(row)

    async def create(self, number, requested_installment):
        order = self.orders.get(number)
        if not order or order['stage'] not in ('confermato', 'in_corso', 'in_revisione', 'completato'):
            raise ValueError('Conferma il preventivo prima del pagamento.')
        payable = self.orders.payable(number)
        amount, part = payable['amount_cents'], payable['installment_id']
        if part is not None and requested_installment != str(part):
            raise ValueError('Il piano è stato aggiornato. Ricarica e scegli la tranche disponibile.')
        if amount <= 0:
            raise ValueError('Non ci sono pagamenti disponibili per questo ordine.')
        recent = self.orders.recent_checkout(number)
        if recent:
            if (recent['provider'] == 'paypal' and recent['amount_cents'] == amount
                    and recent['installment_id'] == part):
                # Never return a historical Stripe URL, or one from another environment.
                if urlsplit(recent['url']).hostname != self.host:
                    raise ValueError('Esiste un pagamento in un altro ambiente PayPal. Verificalo prima di continuare.')
                result = await self.api('GET', '/v2/checkout/orders/' + recent['session_id'])
                if result.get('status') == 'COMPLETED':
                    self.apply(result, 'resume:' + recent['session_id'])
                    return f'{self.public}/orders/{number}?checkout=success'
                if result.get('status') == 'APPROVED':
                    return f'{self.public}/orders/{number}/paypal/return?token={recent["session_id"]}'
                return recent['url']
            raise ValueError('Un pagamento precedente è ancora aperto. Chiedi una verifica al team.')
        attempt = self.store.get('web_checkout_attempts', number)
        if attempt:
            # Do not rotate a key after an ambiguous network failure. Reconciliation is
            # required beyond PayPal's guaranteed idempotency retention window.
            if (attempt.get('provider') != 'paypal' or attempt['amount_cents'] != amount
                    or attempt.get('installment_id') != part or attempt['expires_at'] <= time.time()):
                raise ValueError('Un pagamento precedente è in verifica. Contatta il team prima di riprovare.')
        else:
            key = secrets.token_hex(16)
            attempt = {'key': key, 'provider': 'paypal', 'amount_cents': amount,
                       'installment_id': part, 'expires_at': time.time() + 5 * 3600}
            attempt['data'] = {
                'intent': 'CAPTURE',
                'purchase_units': [{'reference_id': str(number), 'custom_id': f'lumia:{number}:{part or 0}',
                    'description': f'Lumia · {order["title"]} · {payable["title"]}'[:127],
                    'amount': {'currency_code': 'EUR', 'value': f'{amount // 100}.{amount % 100:02d}'}}],
                'payment_source': {'paypal': {'experience_context': {
                    'brand_name': 'Lumia Development', 'locale': 'it-IT', 'shipping_preference': 'NO_SHIPPING',
                    'user_action': 'PAY_NOW', 'return_url': f'{self.public}/orders/{number}/paypal/return',
                    'cancel_url': f'{self.public}/orders/{number}?checkout=cancelled'}}}}
            self.store.put('web_checkout_attempts', number, attempt)
        result = await self.api('POST', '/v2/checkout/orders', data=attempt['data'], key=attempt['key'])
        token = result['id']
        if not re.fullmatch(r'[A-Z0-9]{1,36}', token):
            raise ValueError('Risposta PayPal non valida.')
        url = next((link['href'] for link in result['links'] if link['rel'] in ('approve', 'payer-action')), '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != self.host or parsed.username or parsed.password:
            raise ValueError('Indirizzo PayPal non valido.')
        self.orders.save_checkout(number, token, amount, url, part, attempt['expires_at'], attempt['key'], provider='paypal')
        return url

    def event(self, event_id, status, detail):
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT OR IGNORE INTO paypal_events VALUES(?,?,?,?)',
                                 (event_id, status, str(detail)[:1000], time.time()))

    def pending(self):
        with self.store.lock:
            return [dict(row) for row in self.store.db.execute('''SELECT c.*,o.title FROM order_checkouts c
                JOIN orders o ON o.id=c.order_id WHERE c.provider='paypal' AND c.status='open' ORDER BY c.created DESC''')]

    def apply(self, result, event_id):
        """Only call with a response obtained from the authenticated PayPal API."""
        checkout = self.checkout(result.get('id'))
        units = result.get('purchase_units', [])
        if result.get('status') != 'COMPLETED':
            return False
        if len(units) != 1 or units[0].get('custom_id') != f'lumia:{checkout["order_id"]}:{checkout["installment_id"] or 0}':
            raise ValueError('Ordine e tranche PayPal non corrispondono.')
        captures = units[0].get('payments', {}).get('captures', [])
        if len(captures) != 1 or captures[0].get('status') != 'COMPLETED':
            return False
        capture = captures[0]
        money = capture.get('amount', {})
        try:
            amount = Decimal(money['value']) * 100
            if not amount.is_finite() or amount != amount.to_integral_value():
                raise ValueError('Importo PayPal non valido.')
        except (KeyError, InvalidOperation, TypeError):
            raise ValueError('Importo PayPal non valido.') from None
        if money.get('currency_code') != 'EUR' or amount != checkout['amount_cents']:
            raise ValueError('Valuta o importo PayPal non corrispondono.')
        if not re.fullmatch(r'[A-Z0-9]{1,36}', capture.get('id', '')):
            raise ValueError('Identificativo incasso PayPal non valido.')
        with self.store.lock, self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            applied = self.orders._record_payment(checkout['order_id'], int(amount), capture['id'], 0,
                                                  'paypal', 'paypal:capture:' + capture['id'], checkout['installment_id'])
            self.store.db.execute("UPDATE order_checkouts SET status='paid' WHERE session_id=?", (result['id'],))
            self.orders._clear_checkout_attempt(checkout)
            self.store.db.execute('INSERT OR IGNORE INTO paypal_events VALUES(?,?,?,?)',
                                 (event_id, 'registrato', capture['id'], time.time()))
            return applied

    async def capture(self, token):
        checkout = self.checkout(token)
        # GET recovers a completed capture even when the original POST timed out.
        result = await self.api('GET', '/v2/checkout/orders/' + token)
        if result.get('status') == 'APPROVED':
            if self.orders.get(checkout['order_id'])['stage'] == 'annullato':
                raise ValueError('Ordine annullato: contatta il team per verificare il pagamento.')
            result = await self.api('POST', f'/v2/checkout/orders/{token}/capture', data={}, key='c-' + checkout['attempt_key'])
        return self.apply(result, 'return:' + token)

    async def verify(self, event, headers):
        fields = {'auth_algo': 'paypal-auth-algo', 'cert_url': 'paypal-cert-url',
                  'transmission_id': 'paypal-transmission-id', 'transmission_sig': 'paypal-transmission-sig',
                  'transmission_time': 'paypal-transmission-time'}
        if not all(headers.get(header) for header in fields.values()):
            return False
        data = {key: headers[header] for key, header in fields.items()}
        data.update(webhook_id=self.webhook_id, webhook_event=event)
        result = await self.api('POST', '/v1/notifications/verify-webhook-signature', data=data)
        return result.get('verification_status') == 'SUCCESS'
