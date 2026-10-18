import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lumia.core import Store
from lumia.orders import Orders, to_cents


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.sqlite')
        self.orders = Orders(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_money_is_exact_and_invalid_amounts_are_rejected(self):
        self.assertEqual(to_cents('129,90'), 12990)
        self.assertEqual(to_cents('0.01'), 1)
        for amount in ('-1', '1.001', 'NaN', '1e3', '1,000.00', '', ' 5 ', '1000001'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                to_cents(amount)

    def test_customers_see_only_their_orders_and_quotes_need_acceptance(self):
        first = self.orders.create(10, 'Server FiveM', 25000)
        other = self.orders.create(20, 'Plugin Minecraft', 9000)
        self.assertEqual([x['id'] for x in self.orders.list_for(10)], [first['id']])
        self.assertEqual(len(self.orders.list_for(30, staff=True)), 2)
        self.orders.update(first['id'], 'preventivo', 99)
        with self.assertRaises(ValueError):
            self.orders.accept(first['id'], 20)
        accepted = self.orders.accept(first['id'], 10)
        self.assertEqual(accepted['stage'], 'confermato')
        self.assertEqual(self.orders.summary(accepted)['paid_cents'], 0)
        self.assertEqual(self.orders.audit(first['id'])[-1]['actor'], 10)
        self.assertIsNotNone(self.orders.get(other['id']))

    def test_duplicate_payments_are_atomic_and_overpayments_are_rejected(self):
        order = self.orders.create(10, 'Sito', 10000)
        def record(_):
            return self.orders.record_payment(order['id'], 6000, 'bonifico-42', 99)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(record, range(8))), 1)
        self.assertEqual(self.orders.summary(order)['due_cents'], 4000)
        with self.assertRaisesRegex(ValueError, 'residuo'):
            self.orders.record_payment(order['id'], 4001, 'extra', 99)
        with self.assertRaises(ValueError):
            self.orders.record_payment(order['id'], 5000, 'bonifico-42', 99)
        self.orders.record_payment(order['id'], 4000, 'saldo', 99)
        self.assertEqual(self.orders.summary(order)['due_cents'], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db:
                self.store.db.execute('DELETE FROM order_payments')
        self.assertEqual(len(self.orders.payments(order['id'])), 2)

    def test_checkout_credit_requires_matching_session_amount_and_is_idempotent(self):
        order = self.orders.create(10, 'Progetto', 10000)
        self.orders.save_checkout(order['id'], 'cs_123', 10000, 'https://checkout.stripe.com/pay/test')
        bad = dict(id='cs_123', amount_total=9999, currency='eur', payment_status='paid', metadata={'order_id': str(order['id'])})
        with self.assertRaises(ValueError):
            self.orders.apply_checkout('evt_bad', bad)
        self.assertEqual(self.orders.summary(order)['paid_cents'], 0)
        good = dict(bad, amount_total=10000)
        self.assertTrue(self.orders.apply_checkout('evt_123', good))
        self.assertFalse(self.orders.apply_checkout('evt_123', good))
        self.assertFalse(self.orders.apply_checkout('evt_second', good))
        self.assertEqual(self.orders.summary(order)['paid_cents'], 10000)

    def test_milestones_are_persistent_and_statuses_validated(self):
        order = self.orders.create(10, 'Progetto', 30000)
        milestone = self.orders.add_milestone(order['id'], 'Prototipo UI', '2026-11-01', 99)
        self.orders.set_milestone(order['id'], milestone['id'], True, 99)
        self.assertTrue(self.orders.milestones(order['id'])[0]['done'])
        with self.assertRaises(ValueError):
            self.orders.update(order['id'], 'paid', 99)
        with self.assertRaises(ValueError):
            self.orders.add_milestone(order['id'], 'Test', 'domani', 99)

    def test_manual_reversal_restores_due_once_and_keeps_original_immutable(self):
        order = self.orders.create(10, 'Rettifica incasso', 10000)
        self.orders.record_payment(order['id'], 9000, 'errore-9000', 99)
        payment = self.orders.payments(order['id'])[0]
        self.assertTrue(self.orders.reverse_payment(payment['id'], 'Importo inserito per errore', 99))
        self.assertFalse(self.orders.reverse_payment(payment['id'], 'Invio ripetuto', 99))
        self.assertEqual(self.orders.summary(order), {'paid_cents': 0, 'due_cents': 10000})
        original = self.orders.payments(order['id'])[0]
        self.assertEqual(original['amount_cents'], 9000)
        self.assertEqual(original['reversal_reason'], 'Importo inserito per errore')
        self.assertEqual(original['reversed_by'], 99)
        self.assertIsNotNone(original['reversed_at'])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db:
                self.store.db.execute('DELETE FROM order_payment_reversals')
        self.orders.record_payment(order['id'], 1000, 'importo-corretto', 99)
        self.assertEqual(self.orders.summary(order)['due_cents'], 9000)

    def test_manual_reversal_cannot_reverse_stripe_or_omit_reason(self):
        order = self.orders.create(10, 'Rettifiche protette', 10000)
        self.orders.record_payment(order['id'], 5000, 'cs_verified', 0, provider='stripe', event_id='evt_verified')
        payment = self.orders.payments(order['id'])[0]
        with self.assertRaisesRegex(ValueError, 'Stripe'):
            self.orders.reverse_payment(payment['id'], 'Non consentito', 99)
        self.orders.record_payment(order['id'], 1000, 'bonifico', 99)
        manual = self.orders.payments(order['id'])[0]
        with self.assertRaises(ValueError):
            self.orders.reverse_payment(manual['id'], '', 99)
        self.assertEqual(self.orders.summary(order)['paid_cents'], 6000)


if __name__ == '__main__':
    unittest.main()
