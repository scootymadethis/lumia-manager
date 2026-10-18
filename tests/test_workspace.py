"""Project collaboration must preserve customer isolation and the money ledger."""
import csv
import io
import unittest
import test_web as web_fixtures


class WorkspaceTests(unittest.TestCase):
    setUp=web_fixtures.WebTests.setUp
    tearDown=web_fixtures.WebTests.tearDown
    login=web_fixtures.WebTests.login
    csrf=web_fixtures.WebTests.csrf

    def post(self,path,**values):
        return self.client.post(path,data={'csrf':self.csrf(),**values},headers={'origin':'https://manager.example'})

    def project(self,customer=10,title='Progetto riservato'):
        order=self.orders.create(customer,title,10000)
        self.orders.update(order['id'],'in_corso',99)
        return order

    def delivery(self,order):
        self.login()
        response=self.post(f'/orders/{order["id"]}/deliveries',title='Versione uno',url='https://example.com/release',description='Istruzioni per la prova')
        self.assertEqual(response.status_code,303)
        return self.app.state.workspace.deliveries(order['id'])[0]

    def test_messages_and_internal_notes_are_isolated_in_pages_and_activity(self):
        order=self.project()
        self.login()
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='NOTA INTERNA SEGRETA',internal='1').status_code,303)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='AGGIORNAMENTO PUBBLICO').status_code,303)
        self.assertIn('NOTA INTERNA SEGRETA',self.client.get('/activity').text)
        self.login(10)
        for path in ('/','/activity',f'/orders/{order["id"]}'):
            text=self.client.get(path).text
            self.assertNotIn('NOTA INTERNA SEGRETA',text,path)
        self.assertIn('AGGIORNAMENTO PUBBLICO',self.client.get('/activity').text)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='TENTATIVO',internal='1').status_code,403)
        self.assertEqual(len(self.app.state.workspace.messages(order['id'],staff=True)),2)
        self.login(20)
        self.assertNotIn('AGGIORNAMENTO PUBBLICO',self.client.get('/activity').text)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='Fuori progetto').status_code,404)
        self.assertEqual(self.client.get(f'/orders/{order["id"]}').status_code,404)

    def test_message_content_is_escaped_and_does_not_become_script_or_markup(self):
        order=self.project()
        self.login(10)
        body='<img src=x onerror=alert(1)><script>alert(2)</script>'
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body=body).status_code,303)
        for path in ('/activity',f'/orders/{order["id"]}'):
            text=self.client.get(path).text
            self.assertNotIn(body,text)
            self.assertIn('&lt;script&gt;',text)

    def test_message_size_and_rate_limits_do_not_commit_invalid_content(self):
        order=self.project()
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='').status_code,400)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='x'*4001).status_code,400)
        for _ in range(6):self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='Messaggio valido').status_code,303)
        self.assertEqual(self.post(f'/orders/{order["id"]}/messages',body='Troppi messaggi').status_code,429)
        self.assertEqual(len(self.app.state.workspace.messages(order['id'])),6)

    def test_client_delivery_approval_preserves_stage_balance_and_ledger(self):
        order=self.project()
        delivery=self.delivery(order)
        before=self.orders.summary(order)
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/deliveries/{delivery["id"]}/review',state='approved').status_code,303)
        self.assertEqual(self.app.state.workspace.deliveries(order['id'])[0]['state'],'approved')
        self.assertEqual(self.orders.summary(order),before)
        self.assertEqual(self.orders.payments(order['id']),[])
        self.assertEqual(self.orders.get(order['id'])['stage'],'in_corso')
        self.assertEqual(self.post(f'/orders/{order["id"]}/deliveries/{delivery["id"]}/review',state='changes',feedback='Cambio idea').status_code,400)

    def test_changes_need_feedback_and_staff_cannot_review_on_behalf_of_client(self):
        order=self.project()
        delivery=self.delivery(order)
        path=f'/orders/{order["id"]}/deliveries/{delivery["id"]}/review'
        self.assertEqual(self.post(path,state='approved').status_code,403)
        self.login(20)
        self.assertEqual(self.post(path,state='approved').status_code,404)
        self.login(10)
        self.assertEqual(self.post(path,state='changes',feedback='').status_code,400)
        self.assertEqual(self.post(path,state='changes',feedback='Sistema il menu iniziale').status_code,303)
        self.assertEqual(self.app.state.workspace.deliveries(order['id'])[0]['feedback'],'Sistema il menu iniziale')

    def test_delivery_belongs_to_the_order_in_the_url(self):
        first=self.project()
        second=self.project()
        delivery=self.delivery(first)
        self.login(10)
        self.assertEqual(self.post(f'/orders/{second["id"]}/deliveries/{delivery["id"]}/review',state='approved').status_code,400)
        self.assertEqual(self.app.state.workspace.deliveries(first['id'])[0]['state'],'pending')

    def test_only_staff_can_publish_and_delivery_links_require_https(self):
        order=self.project()
        self.login(10)
        self.assertEqual(self.post(f'/orders/{order["id"]}/deliveries',title='No',url='https://example.com').status_code,403)
        self.login()
        for url in ('javascript:alert(1)','http://example.com','https://user:secret@example.com','https://exam ple.com','https://'):
            self.assertEqual(self.post(f'/orders/{order["id"]}/deliveries',title='No',url=url).status_code,400,url)
        self.assertEqual(self.app.state.workspace.deliveries(order['id']),[])

    def test_csv_exports_own_projects_only_and_neutralizes_spreadsheet_formulas(self):
        first=self.project(title='=HYPERLINK("https://example.com")')
        self.project(customer=20,title='SEGRETO ALTRO CLIENTE')
        self.orders.record_payment(first['id'],3000,'incasso',99)
        self.login(10)
        response=self.client.get('/exports/projects.csv')
        self.assertEqual(response.status_code,200)
        rows=list(csv.reader(io.StringIO(response.text.lstrip('\ufeff')),delimiter=';'))
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertNotIn('SEGRETO ALTRO CLIENTE',response.text)
        payments=self.client.get('/exports/payments.csv')
        self.assertNotIn('SEGRETO ALTRO CLIENTE',payments.text)
        self.assertIn('attachment',payments.headers['content-disposition'])
        self.assertEqual(self.client.get('/exports/internal.csv').status_code,404)
        self.login()
        self.assertIn('SEGRETO ALTRO CLIENTE',self.client.get('/exports/projects.csv').text)

    def test_tour_progress_is_role_scoped_and_requires_csrf(self):
        self.login(10)
        self.assertEqual(self.post('/preferences/tour',status='started',step='3',page='overview').status_code,200)
        self.assertEqual(self.store.get('workspace_tour','10:client')['step'],3)
        self.assertIsNone(self.store.get('workspace_tour','10:admin'))
        self.assertIn('data-tour-status="started"',self.client.get('/').text)
        self.assertEqual(self.client.post('/preferences/tour',data={'status':'completed'},headers={'origin':'https://manager.example'}).status_code,403)
        self.assertEqual(self.post('/preferences/tour',status='completed',step='999',page='overview').status_code,400)
        self.assertEqual(self.post('/preferences/tour',status='completed',step='1',page='https://evil.example').status_code,400)
        self.guild.members[10]=[500]
        response=self.client.get('/')
        self.assertIn('data-role="admin"',response.text)
        self.assertIn('data-tour-status=""',response.text)

    def test_reading_activity_and_agenda_does_not_expose_other_customers(self):
        first=self.project()
        other=self.project(customer=20,title='Progetto altrui')
        self.orders.add_milestone(first['id'],'MIA DATA','2099-01-01',99)
        self.orders.add_milestone(other['id'],'DATA SEGRETA','2099-02-02',99)
        self.app.state.workspace.message(first['id'],99,'Management','Da leggere',staff=True)
        self.login(10)
        self.assertIn('MIA DATA',self.client.get('/agenda').text)
        self.assertNotIn('DATA SEGRETA',self.client.get('/agenda').text)
        self.assertIn('activity-item unread',self.client.get('/activity').text)
        self.assertEqual(self.post('/activity/read').status_code,303)
        self.assertNotIn('activity-item unread',self.client.get('/activity').text)

    def test_new_mutations_reject_foreign_origins(self):
        order=self.project()
        self.login(10)
        response=self.client.post(f'/orders/{order["id"]}/messages',data={'csrf':self.csrf(),'body':'No'},headers={'origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.app.state.workspace.messages(order['id']),[])

    def test_manual_customer_fallback_is_supported_and_ambiguous_selection_is_rejected(self):
        self.login()
        self.assertEqual(self.post('/orders',customer='',customer_id='10',title='Cliente manuale',total='100').status_code,303)
        self.assertEqual(self.orders.list_for(10)[0]['title'],'Cliente manuale')
        self.assertEqual(self.post('/orders',customer='10',customer_id='20',title='Cliente ambiguo',total='100').status_code,400)
        self.assertEqual(self.orders.list_for(20),[])
