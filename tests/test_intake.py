import asyncio
import json
import os
import re
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse
import httpx
import test_web as fixtures
from lumia.briefing import Briefing
from lumia.intake import Intake,validate_brief


def brief(**changes):
    return {'platform':'fivem','service':'custom','name':'Il mio progetto',
        'goal':'Un server roleplay con un ingresso guidato per tutti i giocatori.',
        'features':'Inventario, lavori e un tutorial iniziale.','technical':'ESX, versione da verificare',
        'texts':'Testi di benvenuto da definire','style':'Scuro e minimale','budget':'500-1500',
        'timeline':'flexible','deadline':'','acknowledged':True,'answers':[],**changes}


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.WebTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.client=self.fixture.client;self.app=self.fixture.app
        self.intake=self.app.state.intake
        self.origin={'origin':'https://manager.example'}

    def web_login(self,actor=77):
        self.fixture.actor=actor
        response=self.client.get('/auth/discord?customer=1&return=start')
        query=parse_qs(urlparse(response.headers['location']).query)
        self.assertEqual(query['scope'],['identify'])
        response=self.client.get('/auth/callback',params={'state':query['state'][0],'code':'code'})
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'/start?connected=1')

    def csrf(self):
        return re.search(r'data-csrf="([^"]+)"',self.client.get('/start').text)[1]

    def submit(self,key='request-key-123456789012345',raw=None,csrf=None):
        return self.client.post('/requests',data={'csrf':csrf or self.csrf(),'submission':key,'brief':json.dumps(raw or brief())},headers=self.origin)

    def test_anonymous_can_prepare_but_cannot_submit_or_call_ai(self):
        page=self.client.get('/start')
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.headers['cache-control'],'no-store')
        self.assertIn('Non devi entrare nel server.',page.text)
        self.assertEqual(self.client.post('/requests',data={},headers=self.origin).status_code,303)
        self.assertEqual(self.client.post('/requests/questions',data={},headers=self.origin).status_code,303)

    def test_nonmember_customer_can_order_and_remains_nonstaff(self):
        self.web_login()
        response=self.submit()
        self.assertEqual(response.status_code,201,response.text)
        number=response.json()['id']
        project=self.client.get(response.json()['url'])
        self.assertEqual(project.status_code,200)
        self.assertIn('Richiesta ricevuta',project.text)
        self.assertIn('da definire',project.text)
        self.assertNotIn('Tutto saldato.',project.text)
        self.assertIn('Testi di benvenuto da definire',project.text)
        self.assertEqual(self.client.get('/customers').status_code,403)
        self.assertEqual(self.client.get('/settings').status_code,403)
        order=self.fixture.orders.get(number)
        self.assertEqual(order['customer'],77);self.assertEqual(order['total_cents'],0)
        self.assertEqual(self.client.post(f'/orders/{number}/checkout',data={'csrf':self.csrf()},headers=self.origin).status_code,400)

    def test_web_customer_staff_is_always_fresh_and_downgrades_when_removed(self):
        self.fixture.guild.members[90]=[500]
        self.web_login(90)
        self.assertEqual(self.client.get('/customers').status_code,200)
        self.fixture.guild.members[90]=[600]
        self.assertEqual(self.client.get('/customers').status_code,403)
        del self.fixture.guild.members[90]
        self.assertEqual(self.client.get('/customers').status_code,403)
        self.assertEqual(self.client.get('/orders').status_code,200)

    def test_website_sessions_work_when_bot_is_offline_without_staff_permissions(self):
        self.web_login()
        self.fixture.bot.get_guild=lambda _:None
        self.assertEqual(self.client.get('/orders').status_code,200)
        self.assertEqual(self.client.get('/settings').status_code,403)

    def test_submission_is_idempotent_and_changed_retry_never_creates_twin(self):
        self.web_login()
        first=self.submit();second=self.submit()
        self.assertEqual(first.status_code,201);self.assertEqual(second.status_code,200)
        self.assertEqual(first.json(),second.json())
        self.assertEqual(self.submit(raw=brief(name='Modificato dopo invio')).status_code,400)
        self.assertEqual(len(self.fixture.orders.list_for(77)),1)

    def test_validation_acknowledgment_body_and_csrf_origin(self):
        self.web_login()
        self.assertEqual(self.submit(csrf='wrong').status_code,403)
        self.assertEqual(self.client.post('/requests',data={},headers={'origin':'https://evil.example'}).status_code,403)
        for changes in ({'acknowledged':False},{'platform':'unknown'},{'goal':123},{'features':['invalid']},{'style':'a'*1001},{'other_budget':'a'*301}):
            self.assertEqual(self.submit(raw=brief(**changes)).status_code,400,changes)
        self.assertEqual(self.client.post('/requests',data={'csrf':self.csrf(),'brief':'[]'},headers=self.origin).status_code,400)
        self.assertEqual(self.client.post('/requests',content='a'*132000,headers={**self.origin,'content-type':'application/x-www-form-urlencoded'}).status_code,413)
        self.assertEqual(len(self.fixture.orders.list_for(77)),0)

    def test_all_questions_can_be_skipped_and_order_gets_a_neutral_title(self):
        self.web_login()
        response=self.submit(raw={'acknowledged':True})
        self.assertEqual(response.status_code,201,response.text)
        number=response.json()['id']
        order=self.fixture.orders.get(number)
        self.assertEqual(order['title'],'Nuovo progetto')
        self.assertEqual(order['total_cents'],0)
        saved=self.intake.get(number)['brief']
        self.assertEqual(saved['platform'],'discuss')
        self.assertEqual(saved['service'],'help')
        self.assertEqual(saved['budget'],'discuss')
        self.assertEqual(saved['timeline'],'flexible')
        self.assertEqual(saved['goal'],'')
        page=self.client.get(response.json()['url'])
        self.assertEqual(page.status_code,200)
        self.assertIn('Dettagli da definire insieme.',page.text)

    def test_short_answers_and_unspecified_date_are_accepted(self):
        self.web_login()
        response=self.submit(raw=brief(name='A',goal='Un bot',features='',timeline='date',deadline=''))
        self.assertEqual(response.status_code,201,response.text)
        saved=self.intake.get(response.json()['id'])['brief']
        self.assertEqual(saved['goal'],'Un bot')
        self.assertEqual(saved['deadline'],'')

    def test_other_is_supported_for_every_choice_with_optional_details(self):
        self.web_login()
        raw=brief(platform='other',service='other',budget='other',timeline='other',
                  other_platform='Un’app',other_service='Un’idea diversa',other_budget='Ne parliamo insieme',other_timeline='Dopo le vacanze')
        response=self.submit(raw=raw)
        self.assertEqual(response.status_code,201,response.text)
        saved=self.intake.get(response.json()['id'])['brief']
        self.assertEqual(saved['other_platform'],'Un’app')
        page=self.client.get(response.json()['url']).text
        self.assertIn('Ne parliamo insieme',page)
        self.assertIn('Dopo le vacanze',page)
        response=self.submit(key='other-empty-details-123456',raw=brief(platform='other',service='other',budget='other',timeline='other',name='',goal='',features=''))
        self.assertEqual(response.status_code,201,response.text)

    def test_retry_of_an_old_brief_keeps_same_order_after_new_optional_fields(self):
        import hashlib
        raw=brief()
        order,_=self.intake.submit(77,'legacy-brief-retry-123456789',raw)
        encoded=json.dumps(raw,ensure_ascii=False,sort_keys=True)
        with self.fixture.store.db:
            self.fixture.store.db.execute('UPDATE web_requests SET brief=?,fingerprint=? WHERE order_id=?',
                (encoded,hashlib.sha256(encoded.encode()).hexdigest(),order['id']))
        repeated,created=self.intake.submit(77,'legacy-brief-retry-123456789',raw)
        self.assertFalse(created)
        self.assertEqual(repeated['id'],order['id'])

    def test_maximum_unicode_brief_is_accepted_and_preserved(self):
        self.web_login()
        raw=brief(name='è'*120,goal='è'*2000,features='è'*2400,technical='è'*1200,texts='è'*2000,style='è'*1000,deadline='è'*200,
                  answers=[{'question':'è'*240,'answer':'è'*1000} for _ in range(3)])
        response=self.submit(raw=raw)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.intake.get(response.json()['id'])['brief']['texts'],'è'*2000)

    def test_customer_isolation_and_submission_key_ownership(self):
        self.web_login(77);created=self.submit().json()
        self.web_login(88)
        self.assertEqual(self.client.get(created['url']).status_code,404)
        self.assertNotIn('Il mio progetto',self.client.get('/orders').text)
        self.assertEqual(self.submit().status_code,400)
        number=created['id']
        self.assertEqual(self.client.post(f'/orders/{number}/quote',data={'csrf':self.csrf(),'total':'100','scope':'a'*30},headers=self.origin).status_code,403)

    def test_quote_acceptance_and_milestone_checkout_use_existing_finance(self):
        self.web_login();number=self.submit().json()['id']
        with self.assertRaises(ValueError):self.fixture.orders.update(number,'confermato',99)
        self.fixture.login(99)
        csrf=self.fixture.csrf()
        self.assertEqual(self.client.post(f'/orders/{number}/stage',data={'csrf':csrf,'stage':'preventivo'},headers=self.origin).status_code,400)
        response=self.client.post(f'/orders/{number}/quote',data={'csrf':csrf,'total':'750,00','scope':'Inventario e lavori ESX. Consegna e due revisioni secondo le date concordate.'},headers=self.origin)
        self.assertEqual(response.status_code,303,response.text)
        order=self.fixture.orders.get(number);self.assertEqual(order['stage'],'preventivo');self.assertEqual(order['total_cents'],75000)
        self.fixture.orders.create_installments(number,[{'title':'Acconto','amount_cents':25000},{'title':'Consegna','amount_cents':50000,'due':'2099-12-31'}],99)
        self.web_login()
        response=self.client.post(f'/orders/{number}/accept',data={'csrf':self.csrf()},headers=self.origin)
        self.assertEqual(response.status_code,303)
        response=self.client.post(f'/orders/{number}/checkout',data={'csrf':self.csrf(),'installment_id':str(self.fixture.orders.installments(number)[0]['id'])},headers=self.origin)
        self.assertEqual(response.status_code,303,response.text)
        self.assertEqual(self.fixture.sent_checkout['purchase_units'][0]['amount']['value'],'250.00')
        self.assertEqual(self.fixture.orders.summary(self.fixture.orders.get(number))['paid_cents'],0)
        with self.assertRaises(ValueError):self.fixture.orders.update(number,'bozza',99)

    def test_quote_price_cannot_change_after_sending(self):
        order,_=self.intake.submit(77,'submission-abcdefghijklmnop',brief())
        with self.assertRaises(ValueError):self.intake.quote(order['id'],0,'Work scope that is long enough',99)
        self.intake.quote(order['id'],10000,'Work scope that is long enough',99)
        with self.assertRaises(ValueError):self.intake.quote(order['id'],20000,'Another scope that is long enough',99)
        self.assertEqual(self.fixture.orders.get(order['id'])['total_cents'],10000)

    def test_transaction_rolls_back_if_request_insert_fails(self):
        with patch.object(self.fixture.orders,'_audit',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):self.intake.submit(77,'submission-rollback-123456',brief())
        self.assertEqual(len(self.fixture.orders.list_for(77)),0)
        self.assertEqual(self.fixture.store.db.execute('SELECT COUNT(*) FROM web_requests').fetchone()[0],0)

    def test_daily_limit_is_persistent_and_retries_still_work(self):
        for i in range(10):self.intake.submit(77,f'submission-1234567890-{i}',brief())
        self.intake.submit(77,'submission-1234567890-0',brief())
        with self.assertRaises(ValueError):self.intake.submit(77,'submission-1234567890-10',brief())

    def test_html_in_brief_is_escaped_in_manager(self):
        self.web_login()
        response=self.submit(raw=brief(texts='<img src=x onerror=alert(1)>'))
        page=self.client.get(response.json()['url'])
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',page.text)
        self.assertNotIn('<img src=x',page.text)

    def test_question_endpoint_requires_csrf_and_has_guided_fallback(self):
        self.web_login()
        self.assertEqual(self.client.post('/requests/questions',data={'csrf':'wrong'},headers=self.origin).status_code,403)
        payload={'csrf':self.csrf(),'brief':json.dumps(brief())}
        response=self.client.post('/requests/questions',data=payload,headers=self.origin)
        self.assertEqual(response.json()['source'],'guided')
        self.assertEqual(len(response.json()['questions']),2)
        for _ in range(5):self.client.post('/requests/questions',data=payload,headers=self.origin)
        self.assertEqual(self.client.post('/requests/questions',data=payload,headers=self.origin).status_code,429)

    def test_board_and_list_do_not_describe_unquoted_requests_as_paid(self):
        self.web_login();self.submit()
        response=self.client.get('/orders')
        self.assertIn('Preventivo da definire',response.text)
        self.assertIn('In valutazione',response.text)
        self.assertNotIn('>Saldato<',response.text)

    def test_landing_order_redirect_is_fixed_and_platform_is_allowlisted(self):
        from lumia.site import create_site_app
        from fastapi.testclient import TestClient
        with TestClient(create_site_app('https://site.example','https://manager.example'),base_url='https://site.example',follow_redirects=False) as client:
            self.assertEqual(client.get('/ordina?platform=fivem').headers['location'],'https://manager.example/start?platform=fivem')
            self.assertEqual(client.get('/ordina?platform=https://evil.example').headers['location'],'https://manager.example/start')
            page=client.get('/')
            self.assertIn('href="/ordina">Inizia il tuo progetto',page.text)
            self.assertEqual(client.get('/orders').status_code,404)


class BriefingTests(unittest.IsolatedAsyncioTestCase):
    def make(self,handler):
        with patch.dict(os.environ,{'LUMIA_AI_ENABLED':'true','LUMIA_OLLAMA_URL':'http://ollama:11434','LUMIA_AI_MODEL':'qwen3:4b'}):
            return Briefing(transport=httpx.MockTransport(handler))

    async def test_ai_schema_and_data_minimization(self):
        def handler(request):
            raw=json.loads(request.content)
            self.assertEqual(str(request.url),'http://ollama:11434/api/chat')
            self.assertFalse(raw['stream']);self.assertFalse(raw['think']);self.assertEqual(raw['format']['required'],['questions'])
            self.assertNotIn('PRIVATE CONTENT',json.dumps(raw));self.assertNotIn('PRIVATE NAME',json.dumps(raw))
            return httpx.Response(200,json={'message':{'content':json.dumps({'questions':['Quali lavori devono essere disponibili ai giocatori?']})}})
        result=await self.make(handler).questions(brief(texts='PRIVATE CONTENT',name='PRIVATE NAME'),True)
        self.assertEqual(result['source'],'local-ai')

    async def test_failures_invalid_or_oversized_output_fall_back(self):
        responses=[httpx.Response(503),httpx.Response(200,json={'message':{'content':'not json'}}),httpx.Response(200,json={'message':{'content':json.dumps({'questions':['x']})}}),httpx.Response(200,content='x'*40000)]
        for response in responses:
            result=await self.make(lambda _:response).questions(brief(),True)
            self.assertEqual(result['source'],'guided');self.assertTrue(result['unavailable'])
        def timeout(_):raise httpx.ReadTimeout('model slow')
        self.assertEqual((await self.make(timeout).questions(brief(),True))['source'],'guided')

    async def test_busy_ai_does_not_queue_users(self):
        ai=self.make(lambda _:None)
        async with ai.lock:
            self.assertTrue((await ai.questions(brief(),True))['unavailable'])

    async def test_disabled_ai_never_makes_network_calls(self):
        with patch.dict(os.environ,{'LUMIA_AI_ENABLED':'false'}):ai=Briefing(transport=httpx.MockTransport(lambda _:self.fail('network')))
        self.assertEqual((await ai.questions(brief(),True))['source'],'guided')

    async def test_remote_ai_url_is_rejected(self):
        for url in ('https://cloud.example','http://evil.example','http://ollama:11434/path','http://user:secret@localhost:11434'):
            with patch.dict(os.environ,{'LUMIA_AI_ENABLED':'true','LUMIA_OLLAMA_URL':url}),self.assertRaises(RuntimeError):Briefing()
