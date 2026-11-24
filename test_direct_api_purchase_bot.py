"""Offline checks. Does not contact Juice Shop or create actual orders."""
import argparse
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error, parse

import direct_api_purchase_bot as bot


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeShop:
    def __init__(self, drop_checkout=False, placeholder=False):
        self.stock = {1: 10, 2: 12}
        self.basket = {}
        self.orders = {}
        self.calls = []
        self.drop_checkout = drop_checkout
        self.placeholder = placeholder

    def open(self, req, timeout):
        method, path = req.get_method(), parse.urlsplit(req.full_url).path
        body = json.loads(req.data) if req.data else {}
        self.calls.append((method, path))
        if path == '/rest/products/search':
            return Response({'data': [{'id': x, 'name': f'Product {x}'} for x in self.stock]})
        if path == '/api/Quantitys':
            return Response({'data': [{'ProductId': x, 'quantity': q, 'limitPerUser': 1}
                                      for x, q in self.stock.items()]})
        if path == '/api/Users':
            return Response({'data': {'id': 1}})
        if path == '/rest/user/login':
            return Response({'authentication': {'token': 'offline-test', 'bid': 1}})
        if path == '/rest/basket/1' and method == 'GET':
            return Response({'data': {'Products': [{'id': x, 'BasketItem': {'quantity': q}}
                                                  for x, q in self.basket.items()]}})
        if path == '/api/BasketItems' and method == 'POST':
            self.basket[body['ProductId']] = body['quantity']
            return Response({'data': body})
        if path == '/rest/basket/1/checkout' and method == 'POST':
            oid = f'test-{len(self.orders) + 1}'
            self.orders[oid] = {'orderId': oid, 'products': [
                {'id': x, 'quantity': q} for x, q in self.basket.items()]}
            for x, q in self.basket.items():
                self.stock[x] -= q
            self.basket.clear()
            if self.drop_checkout:
                raise ConnectionResetError('response lost after order creation')
            return Response({'orderConfirmation': oid})
        if path.startswith('/rest/track-order/'):
            oid = path.rsplit('/', 1)[-1]
            return Response({'data': [{'orderId': oid}] if self.placeholder else [self.orders[oid]]})
        raise AssertionError((method, path))


class BotTests(unittest.TestCase):
    def args(self, directory):
        return argparse.Namespace(base_url='http://127.0.0.1:3000', runs=3, items=2,
                                  product_ids=None, delay=0, timeout=20, output=directory)

    def test_sequential_orders_verified_and_credentials_saved(self):
        shop = FakeShop()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bot.request, 'build_opener', return_value=shop), \
                contextlib.redirect_stdout(io.StringIO()):
            summary = bot.run(self.args(tmp))
            self.assertEqual(summary['verified_orders'], 3)
            self.assertEqual(summary['verified_units'], 6)
            self.assertEqual(shop.stock, {1: 7, 2: 9})
            self.assertEqual(shop.calls.count(('POST', '/rest/basket/1/checkout')), 3)
            folder = next(Path(tmp).iterdir())
            account = json.loads((folder / 'credentials.json').read_text())
            self.assertTrue(account['account_created'])
            self.assertTrue(account['password'])
            self.assertNotIn(account['password'], (folder / 'requests.csv').read_text())
            self.assertEqual(len(list((folder / 'orders').iterdir())), 3)

    def test_lost_checkout_response_is_not_replayed(self):
        shop = FakeShop(drop_checkout=True)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bot.request, 'build_opener', return_value=shop), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(bot.BotError):
                bot.run(self.args(tmp))
            self.assertEqual(len(shop.orders), 1)
            self.assertEqual(shop.calls.count(('POST', '/rest/basket/1/checkout')), 1)
            folder = next(Path(tmp).iterdir())
            state = json.loads((folder / 'checkout_state.json').read_text())
            self.assertEqual(state['state'], 'OUTCOME_UNKNOWN')
            self.assertIn('ORDER_OUTCOME_UNKNOWN', (folder / 'attempts.csv').read_text())

    def test_id_only_placeholder_does_not_count_as_verified_order(self):
        shop = FakeShop(placeholder=True)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bot.request, 'build_opener', return_value=shop), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(bot.BotError):
                bot.run(self.args(tmp))
            folder = next(Path(tmp).iterdir())
            summary = json.loads((folder / 'summary.json').read_text())
            self.assertEqual(summary['confirmed_orders'], 1)
            self.assertEqual(summary['verified_orders'], 0)
            self.assertEqual(len(shop.orders), 1)

    def test_read_reset_retries_and_records_each_request(self):
        rows = []
        api = bot.API('http://127.0.0.1:3000', rows.append)
        with patch.object(api.opener, 'open', side_effect=[ConnectionResetError(), Response({'data': []})]), \
                patch.object(bot.time, 'sleep'):
            self.assertEqual(api.get('/read'), {'data': []})
        self.assertEqual([r['retry'] for r in rows], [0, 1])
        self.assertEqual(rows[0]['outcome'], 'NETWORK_ERROR_RETRYING')

    def test_http_rate_limit_is_not_retried(self):
        api = bot.API('http://127.0.0.1:3000', lambda row: None)
        with patch.object(api.opener, 'open', side_effect=error.HTTPError(
                'http://127.0.0.1:3000/read', 429, 'Too many requests', {}, None)) as opened:
            with self.assertRaisesRegex(bot.BotError, 'HTTP 429'):
                api.get('/read')
        self.assertEqual(opened.call_count, 1)

    def test_insufficient_stock_rejected_before_purchase(self):
        args = self.args('unused')
        args.product_ids = '1'
        with self.assertRaisesRegex(bot.BotError, '2 units; 3 required'):
            bot.choose_products([{'id': 1}], {1: {'quantity': 2}}, args)

    def test_wrong_product_order_does_not_pass_verification(self):
        class Stub:
            def get(self, path):
                return {'data': [{'orderId': 'test-1', 'products': [{'id': 2, 'quantity': 1}]}]}
        with self.assertRaises(bot.BotError):
            bot.check_order(Stub(), 'test-1', Counter({1: 1}))

    def test_only_loopback_targets_accepted(self):
        self.assertEqual(bot.local_url('http://localhost:3000/'), 'http://localhost:3000')
        for url in ['http://example.com', 'https://localhost', 'http://localhost.evil.test',
                    'http://localhost:3000/path', 'http://user@localhost:3000']:
            with self.subTest(url=url), self.assertRaises(argparse.ArgumentTypeError):
                bot.local_url(url)


if __name__ == '__main__':
    unittest.main()
