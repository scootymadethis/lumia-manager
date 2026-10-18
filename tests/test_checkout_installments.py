"""Full Checkout/webhook flows with signed test events and isolated identities."""
import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
import test_web as web_fixtures
from lumia.web import create_app


class CheckoutInstallmentTests(unittest.TestCase):
    setUp=web_fixtures.WebTests.setUp
    tearDown=web_fixtures.WebTests.tearDown
    login=web_fixtures.WebTests.login
    csrf=web_fixtures.WebTests.csrf

    def post(self,path,**values):
        return self.client.post(path,data={'csrf':self.csrf(),**values},headers={'origin':'https://manager.example'})

    def paid(self,event,session,order,part,amount):
        raw=json.dumps({'id':event,'type':'checkout.session.completed','data':{'object':{
            'id':session,'payment_status':'paid','currency':'eur','amount_total':amount,
            'metadata':{'order_id':str(order),'installment_id':str(part)}}}}).encode()
        timestamp=str(int(time.time()))
        signature=hmac.new(b'whsec_test',timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.client.post('/webhooks/stripe',content=raw,headers={'stripe-signature':f't={timestamp},v1={signature}'})

    def create_order_and_plan(self):
        order=self.orders.create(10,'Progetto a tranche',10000)
        self.orders.update(order['id'],'confermato',99)
        self.login()
        response=self.post(f'/orders/{order["id"]}/installments',part_count='2',
            part_0_title='Acconto',part_0_amount='40',part_1_title='Saldo',part_1_amount='60')
        self.assertEqual(response.status_code,303,response.text)
        return order,self.orders.installments(order['id'])

    def test_client_can_pay_two_distinct_installments_and_webhooks_reconcile_automatically(self):
        order,parts=self.create_order_and_plan()
        original=self.transport.handler
        created=[]
        def stripe(request):
            if request.url.host=='api.stripe.com':
                body=parse_qs(request.content.decode())
                created.append(body)
                return httpx.Response(200,json={'id':f'cs_part_{len(created)}',
                    'url':f'https://checkout.stripe.com/c/pay/part_{len(created)}'})
            return original(request)
        self.transport.handler=stripe
        self.login(10)
        result=self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[0]['id']),amount='0.01')
        self.assertEqual(result.status_code,303,result.text)
        self.assertEqual(created[0]['line_items[0][price_data][unit_amount]'],['4000'])
        self.assertEqual(created[0]['metadata[installment_id]'],[str(parts[0]['id'])])
        self.assertEqual(self.paid('evt_part1','cs_part_1',order['id'],parts[0]['id'],4000).status_code,200)
        self.assertEqual(self.paid('evt_part1','cs_part_1',order['id'],parts[0]['id'],4000).status_code,200)
        self.assertIsNone(self.store.get('web_checkout_attempts',order['id']))
        self.assertEqual(self.orders.summary(order)['paid_cents'],4000)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[1]['id'])).status_code,400)
        self.login(99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments/{parts[1]["id"]}/release').status_code,303)
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[1]['id'])).status_code,303)
        self.assertEqual(created[1]['line_items[0][price_data][unit_amount]'],['6000'])
        self.assertEqual(self.paid('evt_part2','cs_part_2',order['id'],parts[1]['id'],6000).status_code,200)
        self.assertEqual(self.orders.summary(order),{'paid_cents':10000,'due_cents':0})
        self.assertEqual(len(self.orders.payments(order['id'])),2)

    def test_client_cannot_change_plan_release_future_payment_or_access_other_order(self):
        order,parts=self.create_order_and_plan()
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments',part_count='1',part_0_title='Fake',part_0_amount='1').status_code,403)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments/{parts[1]["id"]}/release').status_code,403)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[1]['id'])).status_code,409)
        self.login(20)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[0]['id'])).status_code,404)

    def test_invalid_plan_keeps_order_and_money_unchanged(self):
        order=self.orders.create(10,'Piano errato',10000)
        self.login()
        result=self.post(f'/orders/{order["id"]}/installments',part_count='2',part_0_title='A',part_0_amount='40',part_1_title='B',part_1_amount='40')
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.orders.installments(order['id']),[])
        self.assertEqual(self.orders.get(order['id'])['total_cents'],10000)

    def test_small_residual_does_not_create_an_unpayable_stripe_attempt(self):
        order=self.orders.create(10,'Piccolo residuo',100)
        self.orders.update(order['id'],'confermato',99)
        self.orders.record_payment(order['id'],60,'Incasso precedente',99)
        self.login(10)
        result=self.post(f'/orders/{order["id"]}/checkout')
        self.assertEqual(result.status_code,400)
        self.assertIn('0,50',result.text)
        self.assertIsNone(self.sent_checkout)
        self.assertIsNone(self.store.get('web_checkout_attempts',order['id']))
        self.assertEqual(self.orders.summary(order)['due_cents'],40)

    def test_minimum_online_amount_is_accepted_without_rounding(self):
        order=self.orders.create(10,'Importo minimo',50)
        self.orders.update(order['id'],'confermato',99)
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout').status_code,303)
        self.assertEqual(self.sent_checkout['line_items[0][price_data][unit_amount]'],['50'])

    def test_public_landing_host_never_serves_manager_data_or_authentication(self):
        self.orders.create(10,'SEGRETO CLIENTE',10000)
        with patch.dict('os.environ',{'LUMIA_SITE_URL':'https://studio.example'}):
            app=create_app(self.bot,http_transport=self.transport)
            with TestClient(app,base_url='https://studio.example') as public:
                response=public.get('/')
                self.assertEqual(response.status_code,200)
                self.assertIn('Il tuo prossimo server.',response.text)
                self.assertNotIn('SEGRETO CLIENTE',response.text)
                self.assertNotIn('__Host-lumia_session',response.headers.get('set-cookie',''))
                for path in ('/orders','/customers','/auth/discord','/webhooks/stripe'):
                    self.assertEqual(public.get(path).status_code,404,path)
                self.assertEqual(public.get('/',headers={'host':'unknown.example'}).status_code,400)
                self.assertEqual(public.get('/',headers={'host':'manager.example'},follow_redirects=False).status_code,303)
