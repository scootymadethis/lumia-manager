"""Money conservation, legacy migrations and installment boundaries."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from lumia.core import Store
from lumia.orders import Orders


class InstallmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'test.sqlite')
        self.addCleanup(self.store.close)
        self.orders=Orders(self.store)
        self.order=self.orders.create(10,'Progetto',10000)
        self.orders.update(self.order['id'],'confermato',99)

    def plan(self):
        return self.orders.create_installments(self.order['id'],[
            {'title':'Acconto','amount_cents':4000}, {'title':'Saldo','amount_cents':6000}],99)

    def session(self,session_id,part,amount):
        return {'id':session_id,'currency':'eur','payment_status':'paid','amount_total':amount,
                'metadata':{'order_id':str(self.order['id']),'installment_id':str(part)}}

    def test_total_must_match_and_no_partial_plan_is_created(self):
        with self.assertRaises(ValueError):
            self.orders.create_installments(self.order['id'],[{'title':'Acconto','amount_cents':9000}],99)
        self.assertEqual(self.orders.installments(self.order['id']),[])

    def test_two_payments_credit_only_their_installments_without_duplicate_income(self):
        first,second=self.plan()
        self.orders.save_checkout(self.order['id'],'cs_1',4000,'https://checkout.stripe.com/1',first['id'])
        self.assertTrue(self.orders.apply_checkout('evt_1',self.session('cs_1',first['id'],4000)))
        self.assertFalse(self.orders.apply_checkout('evt_1',self.session('cs_1',first['id'],4000)))
        self.assertIsNone(self.orders.recent_checkout(self.order['id']))
        self.assertEqual(self.orders.payable(self.order['id'])['amount_cents'],0)
        self.orders.release_installment(self.order['id'],second['id'],99)
        self.assertEqual(self.orders.payable(self.order['id'])['amount_cents'],6000)
        self.orders.save_checkout(self.order['id'],'cs_2',6000,'https://checkout.stripe.com/2',second['id'])
        self.orders.apply_checkout('evt_2',self.session('cs_2',second['id'],6000))
        self.assertEqual(self.orders.summary(self.order),{'paid_cents':10000,'due_cents':0})
        self.assertEqual([p['remaining_cents'] for p in self.orders.installments(self.order['id'])],[0,0])

    def test_forged_installment_metadata_cannot_credit_another_tranche(self):
        first,second=self.plan()
        self.orders.save_checkout(self.order['id'],'cs_1',4000,'https://checkout.stripe.com/1',first['id'])
        with self.assertRaises(ValueError):
            self.orders.apply_checkout('evt_bad',self.session('cs_1',second['id'],4000))
        self.assertEqual(self.orders.summary(self.order)['paid_cents'],0)

    def test_manual_income_and_reversal_conserve_installment_balances(self):
        first,second=self.plan()
        self.orders.record_payment(self.order['id'],5000,'CRO-1',99)
        self.assertEqual([x['paid_cents'] for x in self.orders.installments(self.order['id'])],[4000,1000])
        payment=self.orders.payments(self.order['id'])[0]
        self.orders.reverse_payment(payment['id'],'Errore di registrazione',99)
        self.assertEqual([x['paid_cents'] for x in self.orders.installments(self.order['id'])],[0,0])
        self.assertEqual(self.orders.summary(self.order)['paid_cents'],0)

    def test_historical_income_is_allocated_without_rewriting_the_ledger(self):
        self.orders.record_payment(self.order['id'],3000,'CRO-OLD',99)
        original=self.orders.payments(self.order['id'])
        self.plan()
        self.assertEqual(self.orders.payments(self.order['id']),original)
        self.assertEqual(self.orders.payable(self.order['id'])['amount_cents'],1000)

    def test_late_stripe_payment_for_manually_settled_tranche_requires_reconciliation(self):
        first,second=self.plan()
        self.orders.save_checkout(self.order['id'],'cs_late',4000,'https://checkout.stripe.com/late',first['id'])
        self.orders.record_payment(self.order['id'],4000,'CRO-1',99)
        with self.assertRaises(ValueError):
            self.orders.apply_checkout('evt_late',self.session('cs_late',first['id'],4000))
        self.assertEqual(self.orders.summary(self.order)['paid_cents'],4000)
        self.assertEqual(self.orders.installments(self.order['id'])[1]['paid_cents'],0)

    def test_milestone_and_date_unlock_only_when_ready(self):
        milestone=self.orders.add_milestone(self.order['id'],'Prima versione','2099-01-01',99)
        part=self.orders.create_installments(self.order['id'],[
            {'title':'Saldo','amount_cents':10000,'milestone_id':milestone['id']}],99)[0]
        self.assertEqual(self.orders.payable(self.order['id'])['amount_cents'],0)
        self.orders.set_milestone(self.order['id'],milestone['id'],True,99)
        self.assertEqual(self.orders.payable(self.order['id'])['installment_id'],part['id'])

    def test_foreign_milestones_and_changes_during_active_checkout_are_rejected(self):
        other=self.orders.create(20,'Altro',10000)
        milestone=self.orders.add_milestone(other['id'],'Altro','2099-01-01',99)
        with self.assertRaises(ValueError):
            self.orders.create_installments(self.order['id'],[{'title':'Saldo','amount_cents':10000,'milestone_id':milestone['id']}],99)
        self.orders.save_checkout(self.order['id'],'cs_open',10000,'https://checkout.stripe.com/open')
        with self.assertRaises(ValueError): self.plan()
        self.orders.expire_checkout('cs_open')
        self.assertEqual(len(self.plan()),2)

    def test_paid_checkout_does_not_clear_an_unrelated_new_attempt(self):
        first,second=self.plan()
        self.store.put('web_checkout_attempts',self.order['id'],{'key':'new-attempt','expires_at':time.time()+3600})
        self.orders.save_checkout(self.order['id'],'cs_old',4000,'https://checkout.stripe.com/old',first['id'],attempt_key='old-attempt')
        self.orders.apply_checkout('evt_old',self.session('cs_old',first['id'],4000))
        self.assertEqual(self.store.get('web_checkout_attempts',self.order['id'])['key'],'new-attempt')

    def test_legacy_checkout_table_is_migrated_without_losing_existing_rows(self):
        legacy=Store(Path(self.tmp.name)/'legacy.sqlite')
        try:
            with legacy.db:
                legacy.db.execute('CREATE TABLE order_checkouts(session_id TEXT PRIMARY KEY,order_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,url TEXT NOT NULL,created REAL NOT NULL)')
                legacy.db.execute('INSERT INTO order_checkouts VALUES(?,?,?,?,?)',('cs_legacy',9,100,'https://checkout.stripe.com/legacy',time.time()))
            orders=Orders(legacy)
            saved=orders.recent_checkout(9)
            self.assertEqual(saved['session_id'],'cs_legacy')
            self.assertIsNone(saved['installment_id'])
            Orders(legacy)
            self.assertEqual(legacy.db.execute('SELECT count(*) FROM order_checkouts').fetchone()[0],1)
        finally:
            legacy.close()
