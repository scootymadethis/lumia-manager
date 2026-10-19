import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import test_web as fixtures


class WebSupportTests(unittest.TestCase):
    setUp=fixtures.WebTests.setUp
    tearDown=fixtures.WebTests.tearDown
    login=fixtures.WebTests.login
    csrf=fixtures.WebTests.csrf

    def post(self,number,reason='Errore al caricamento del server, allego i passaggi.'):
        return self.client.post(f'/orders/{number}/support',data={'csrf':self.csrf(),'reason':reason},headers={'origin':'https://manager.example'})

    def test_support_links_own_order_and_reuses_ticket_on_duplicate_submit(self):
        order=self.orders.create(10,'Server cliente',10000)
        async def create(guild,member,kind,fields):
            ticket=self.store.reserve_ticket(member.id,kind,fields)
            self.store.update_ticket(ticket['id'],state='open',channel=4321)
            return self.store.ticket(ticket['id'])
        cog=SimpleNamespace(create_ticket=AsyncMock(side_effect=create))
        self.bot.get_cog=lambda _:cog
        self.login(10)
        self.assertEqual(self.post(order['id']).status_code,303)
        self.assertEqual(self.post(order['id']).status_code,303)
        cog.create_ticket.assert_awaited_once()
        ticket=self.store.tickets()[0]
        self.assertEqual(ticket['kind'],'support')
        self.assertEqual(ticket['fields']['Ordine'],f'LM-{order["id"]:04d}')
        self.assertEqual(ticket['fields']['Area clienti'],f'https://manager.example/orders/{order["id"]}')
        self.assertIn('https://discord.com/channels/1/4321',self.client.get(f'/orders/{order["id"]}').text)
        self.login(20)
        self.assertEqual(self.post(order['id']).status_code,404)

    def test_staff_cannot_impersonate_customer_and_outage_keeps_order(self):
        order=self.orders.create(10,'Server cliente',10000)
        self.login(99)
        self.assertEqual(self.post(order['id']).status_code,403)
        self.login(10)
        self.assertEqual(self.post(order['id'],'breve').status_code,400)
        self.assertEqual(self.post(order['id']).status_code,503)
        self.assertEqual(self.store.tickets(),[])
        self.assertEqual(self.orders.get(order['id'])['total_cents'],10000)
