"""PayPal routes exercised against a simulated provider; no real payments."""
import copy
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import httpx
import test_web as fixtures
from lumia.web import create_app


class CheckoutInstallmentTests(unittest.TestCase):
    setUp=fixtures.WebTests.setUp
    tearDown=fixtures.WebTests.tearDown
    login=fixtures.WebTests.login
    csrf=fixtures.WebTests.csrf

    def post(self,path,**values):
        return self.client.post(path,data={'csrf':self.csrf(),**values},headers={'origin':'https://manager.example'})

    def order(self,amount=10000):
        order=self.orders.create(10,'Progetto PayPal',amount)
        self.orders.update(order['id'],'confermato',99)
        self.login(10)
        return order

    def begin(self,order,part=None):
        result=self.post(f'/orders/{order["id"]}/checkout',**({'installment_id':str(part)} if part else {}))
        self.assertEqual(result.status_code,303,result.text)
        return self.orders.recent_checkout(order['id'])['session_id']

    def complete(self,token):
        result=self.paypal_orders[token]
        unit=result['purchase_units'][0]
        result['status']='COMPLETED'
        unit['payments']={'captures':[{'id':'CAP'+token,'status':'COMPLETED','amount':unit['amount'].copy()}]}
        return result

    def webhook(self,event,signed=True):
        headers={key:'test' for key in ('paypal-auth-algo','paypal-cert-url','paypal-transmission-id','paypal-transmission-sig','paypal-transmission-time')}
        return self.client.post('/webhooks/paypal',json=event,headers=headers if signed else {})

    def paid_event(self,token,id='WH-PAID'):
        return {'id':id,'event_type':'PAYMENT.CAPTURE.COMPLETED','resource':{'id':'CAP'+token,'supplementary_data':{'related_ids':{'order_id':token}}}}

    def test_two_installments_capture_webhook_duplicates_and_future_release(self):
        order=self.order()
        parts=self.orders.create_installments(order['id'],[{'title':'Acconto','amount_cents':4000},{'title':'Saldo','amount_cents':6000}],99)
        token=self.begin(order,parts[0]['id'])
        self.assertEqual(self.sent_checkout['purchase_units'][0]['amount']['value'],'40.00')
        self.complete(token)
        path=f'/orders/{order["id"]}/paypal/capture'
        self.assertEqual(self.post(path,token=token).status_code,303)
        self.assertEqual(self.post(path,token=token).status_code,303)
        self.assertEqual(self.webhook(self.paid_event(token)).status_code,200)
        self.assertEqual(self.webhook(self.paid_event(token,'WH-SECOND')).status_code,200)
        self.assertEqual(self.orders.summary(order)['paid_cents'],4000)
        self.assertIsNone(self.store.get('web_checkout_attempts',order['id']))
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[1]['id'])).status_code,409)
        self.login(99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments/{parts[1]["id"]}/release').status_code,303)
        self.login(10);token=self.begin(order,parts[1]['id']);self.complete(token)
        self.assertEqual(self.webhook(self.paid_event(token,'WH-SALDO')).status_code,200)
        self.assertEqual(self.orders.summary(order),{'paid_cents':10000,'due_cents':0})
        self.assertEqual(len(self.orders.payments(order['id'])),2)
        self.assertTrue(all(p['provider']=='paypal' for p in self.orders.payments(order['id'])))

    def test_capture_posts_only_after_provider_approval(self):
        order=self.order();token=self.begin(order);self.paypal_orders[token]['status']='APPROVED'
        original=self.transport.handler;keys=[]
        def provider(request):
            if request.url.path.endswith('/capture'):
                keys.append(request.headers['paypal-request-id'])
                return httpx.Response(201,json=self.complete(token))
            return original(request)
        self.transport.handler=provider
        self.assertEqual(self.post(f'/orders/{order["id"]}/paypal/capture',token=token).status_code,303)
        self.assertEqual(len(keys),1)
        self.assertEqual(self.orders.summary(order)['paid_cents'],10000)

    def test_signed_approval_completes_when_buyer_closes_browser(self):
        order=self.order();token=self.begin(order);self.paypal_orders[token]['status']='APPROVED'
        original=self.transport.handler
        def provider(request):
            if request.url.path.endswith('/capture'):
                return httpx.Response(201,json=self.complete(token))
            return original(request)
        self.transport.handler=provider
        self.assertEqual(self.webhook({'id':'WH-APPROVAL','event_type':'CHECKOUT.ORDER.APPROVED','resource':{'id':token}}).status_code,200)
        self.assertEqual(self.orders.summary(order)['paid_cents'],10000)

    def test_capture_timeout_can_be_retried_without_changing_idempotency_key(self):
        order=self.order();token=self.begin(order);self.paypal_orders[token]['status']='APPROVED'
        original=self.transport.handler;keys=[]
        def provider(request):
            if request.url.path.endswith('/capture'):
                keys.append(request.headers['paypal-request-id'])
                if len(keys)==1:
                    raise httpx.ReadTimeout('response lost',request=request)
                return httpx.Response(201,json=self.complete(token))
            return original(request)
        self.transport.handler=provider
        path=f'/orders/{order["id"]}/paypal/capture'
        self.assertEqual(self.post(path,token=token).status_code,502)
        self.assertEqual(self.orders.summary(order)['paid_cents'],0)
        self.assertEqual(self.post(path,token=token).status_code,303)
        self.assertEqual(keys[0],keys[1])
        self.assertEqual(len(self.orders.payments(order['id'])),1)

    def test_checkout_rejects_provider_redirect_to_an_unexpected_host(self):
        order=self.order();original=self.transport.handler
        def provider(request):
            if request.url.path=='/v2/checkout/orders':
                return httpx.Response(201,json={'id':'PPBAD','links':[{'rel':'payer-action','href':'https://paypal.com.attacker.example/pay'}]})
            return original(request)
        self.transport.handler=provider
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout').status_code,409)
        self.assertIsNone(self.orders.recent_checkout(order['id']))

    def test_return_and_success_queries_never_credit_unverified_money(self):
        order=self.order();token=self.begin(order)
        self.assertEqual(self.client.get(f'/orders/{order["id"]}/paypal/return?token={token}').status_code,200)
        self.assertEqual(self.client.get(f'/orders/{order["id"]}?checkout=success').status_code,200)
        self.post(f'/orders/{order["id"]}/paypal/capture',token=token)
        self.assertEqual(self.orders.summary(order)['paid_cents'],0)

    def test_wrong_order_foreign_customer_csrf_and_origin_are_rejected(self):
        order=self.order();token=self.begin(order);path=f'/orders/{order["id"]}/paypal/capture'
        self.assertEqual(self.client.post(path,data={'token':token},headers={'origin':'https://manager.example'}).status_code,403)
        self.assertEqual(self.client.post(path,data={'csrf':self.csrf(),'token':token},headers={'origin':'https://evil.example'}).status_code,403)
        second=self.order()
        self.assertEqual(self.post(f'/orders/{second["id"]}/paypal/capture',token=token).status_code,404)
        self.login(20)
        self.assertEqual(self.post(path,token=token).status_code,404)
        self.assertEqual(self.client.get(f'/orders/{order["id"]}/paypal/return?token={token}').status_code,404)

    def test_bad_amount_currency_custom_id_or_pending_capture_never_credit(self):
        order=self.order();token=self.begin(order);original=copy.deepcopy(self.complete(token));variants=[]
        for value,currency in [('99.00','EUR'),('100.00','USD'),('NaN','EUR'),('100.001','EUR')]:
            result=copy.deepcopy(original)
            result['purchase_units'][0]['payments']['captures'][0]['amount']={'value':value,'currency_code':currency}
            variants.append(result)
        result=copy.deepcopy(original);result['purchase_units'][0]['custom_id']='lumia:999:0';variants.append(result)
        result=copy.deepcopy(original);result['purchase_units'][0]['payments']['captures'][0]['status']='PENDING';variants.append(result)
        for index,result in enumerate(variants):
            with self.subTest(index=index):
                self.paypal_orders[token]=result
                self.webhook(self.paid_event(token,'WH-BAD-'+str(index)))
                self.assertEqual(self.orders.summary(order)['paid_cents'],0)
        self.login(99)
        self.assertIn('Riconciliazione richiesta',self.client.get('/').text)

    def test_unsigned_failed_signature_and_outage_reject_event(self):
        order=self.order();token=self.begin(order);self.complete(token)
        self.assertEqual(self.webhook(self.paid_event(token),signed=False).status_code,400)
        original=self.transport.handler
        def invalid(request):
            if request.url.path.endswith('/verify-webhook-signature'):
                return httpx.Response(200,json={'verification_status':'FAILURE'})
            return original(request)
        self.transport.handler=invalid
        self.assertEqual(self.webhook(self.paid_event(token)).status_code,400)
        def unavailable(request):
            raise httpx.ConnectError('offline',request=request)
        self.transport.handler=unavailable
        self.assertEqual(self.webhook(self.paid_event(token)).status_code,503)
        self.assertEqual(self.orders.summary(order)['paid_cents'],0)

    def test_refunds_flag_reconciliation_and_preserve_ledger(self):
        order=self.order();token=self.begin(order);self.complete(token);self.webhook(self.paid_event(token))
        self.assertEqual(self.webhook({'id':'WH-REFUND','event_type':'PAYMENT.CAPTURE.REFUNDED','resource':{'id':'REFUND1'}}).status_code,200)
        self.assertEqual(self.orders.summary(order)['paid_cents'],10000)
        self.login(99);page=self.client.get('/payments').text
        self.assertIn('da riconciliare',page);self.assertIn('WH-REFUND',page)

    def test_small_residual_is_exact_and_customer_amount_is_ignored(self):
        order=self.order(100);self.orders.record_payment(order['id'],60,'storico',99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',amount='999.99').status_code,303)
        self.assertEqual(self.sent_checkout['purchase_units'][0]['amount']['value'],'0.40')

    def test_legacy_checkout_and_changed_balance_block_another_payment(self):
        order=self.order();self.orders.save_checkout(order['id'],'cs_old',10000,'https://checkout.stripe.com/old')
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout').status_code,409)
        self.orders.expire_checkout('cs_old');self.begin(order)
        self.orders.record_payment(order['id'],1000,'new-payment',99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout').status_code,409)
        self.assertEqual(len(self.paypal_orders),1)

    def test_customer_cannot_change_plan_or_release_future_payment(self):
        order=self.order();parts=self.orders.create_installments(order['id'],[{'title':'A','amount_cents':4000},{'title':'B','amount_cents':6000}],99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments',part_count='1').status_code,403)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments/{parts[1]["id"]}/release').status_code,403)
        self.assertEqual(self.post(f'/orders/{order["id"]}/checkout',installment_id=str(parts[1]['id'])).status_code,409)

    def test_invalid_plan_keeps_money_unchanged(self):
        order=self.order();self.login(99)
        self.assertEqual(self.post(f'/orders/{order["id"]}/installments',part_count='2',part_0_title='A',part_0_amount='40',part_1_title='B',part_1_amount='40').status_code,400)
        self.assertEqual(self.orders.installments(order['id']),[])

    def test_public_landing_never_serves_manager_data_or_authentication(self):
        self.orders.create(10,'SEGRETO CLIENTE',10000)
        with patch.dict('os.environ',{'LUMIA_SITE_URL':'https://studio.example'}):
            with TestClient(create_app(self.bot,http_transport=self.transport),base_url='https://studio.example') as public:
                response=public.get('/');self.assertEqual(response.status_code,200)
                self.assertIn('Il tuo prossimo server.',response.text);self.assertIn('PayPal',response.text)
                self.assertNotIn('SEGRETO CLIENTE',response.text)
                for path in ('/orders','/customers','/auth/discord','/webhooks/paypal','/workspace/version'):
                    self.assertEqual(public.get(path).status_code,404,path)

    def test_version_is_authenticated_and_scoped_to_customer(self):
        self.assertEqual(self.client.get('/workspace/version').status_code,303)
        order=self.order();first=self.client.get('/workspace/version').json()['version']
        self.orders.create(20,'Ordine privato',100)
        self.assertEqual(self.client.get('/workspace/version').json()['version'],first)
        self.orders.update(order['id'],'in_corso',99)
        self.assertNotEqual(self.client.get('/workspace/version').json()['version'],first)

    def test_queues_and_unconfigured_paypal_state(self):
        order=self.order();other=self.orders.create(10,'Richiesta da definire',0)
        page=self.client.get('/orders?focus=payments').text
        self.assertIn(f'data-project-id="{order["id"]}"',page);self.assertNotIn(f'data-project-id="{other["id"]}"',page)
        with patch.dict('os.environ',{'PAYPAL_CLIENT_SECRET':''}):
            with TestClient(create_app(self.bot,http_transport=self.transport),base_url='https://manager.example',follow_redirects=False) as client:
                client.cookies.update(self.client.cookies)
                self.assertEqual(client.post(f'/orders/{order["id"]}/checkout',data={'csrf':self.csrf()},headers={'origin':'https://manager.example'}).status_code,503)
                self.assertNotIn('Paga con PayPal',client.get(f'/orders/{order["id"]}').text)

    def test_staff_can_recover_a_completed_payment_without_charging_again(self):
        order=self.order();token=self.begin(order);self.complete(token)
        path=f'/payments/paypal/{token}/verify'
        self.assertEqual(self.post(path).status_code,403)
        self.login(99)
        self.assertIn(token,self.client.get('/payments').text)
        self.assertEqual(self.post(path).status_code,303)
        self.assertEqual(self.orders.summary(order)['paid_cents'],10000)
        self.assertEqual(len(self.orders.payments(order['id'])),1)

    def test_staff_closes_only_provider_voided_attempts(self):
        order=self.order();token=self.begin(order);self.login(99)
        path=f'/payments/paypal/{token}/verify'
        self.assertEqual(self.post(path).status_code,303)
        self.assertIsNotNone(self.orders.recent_checkout(order['id']))
        self.paypal_orders[token]['status']='VOIDED'
        self.assertEqual(self.post(path).status_code,303)
        self.assertIsNone(self.orders.recent_checkout(order['id']))
        self.assertIsNone(self.store.get('web_checkout_attempts',order['id']))
        self.assertEqual(self.orders.summary(order)['paid_cents'],0)
