import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import call_binding as cb
import quote_service as qs

PAYTO = "nano_39b311tznm9hub316enn8159ammduxnfonoaei7afzymw66wsouw9q3j9ic1"
T = [1_790_000_000]
FEEDS = [lambda: 0.32, lambda: 0.325]


def svc(feeds=None):
    return qs.QuoteService(PAYTO, feeds or FEEDS, clock=lambda: T[0])


def qid(key=b"k" * 32, cents=250):
    return qs.usd_quote_id(key, resource="/api/x", usd_cents=cents, payto=PAYTO)


class Quote(unittest.TestCase):
    def setUp(self):
        T[0] = 1_790_000_000

    def test_quote_is_exact_raw_with_expiry_and_never_short(self):
        q = svc().quote(250, qid())
        self.assertEqual(q["expires_at"], T[0] + 60)
        self.assertGreaterEqual(int(q["amount_raw"]) * q["price_micro_usd"] * 100, 250 * 10 ** 6 * 10 ** 30)
        self.assertEqual(cb.tail_of_amount(int(q["amount_raw"])), q["tail"])

    def test_exact_payment_in_window_matches(self):
        s = svc()
        q = s.quote(250, qid())
        v = s.settle({"hash": "A" * 64, "amount": q["amount_raw"], "local_timestamp": q["expires_at"]})
        self.assertIn(v["verdict"], (cb.MATCHED, cb.PENDING_DELIVERY))

    def test_late_is_refusable_with_both_timestamps(self):
        s = svc()
        q = s.quote(250, qid())
        v = s.settle({"hash": "B" * 64, "amount": q["amount_raw"], "local_timestamp": q["expires_at"] + 1})
        self.assertEqual(v["verdict"], cb.REFUSABLE_LATE)
        self.assertEqual((v["expired_at"], v["paid_at"]), (q["expires_at"], q["expires_at"] + 1))

    def test_one_raw_off_is_refusable_wrong_amount(self):
        s = svc()
        q = s.quote(250, qid())
        v = s.settle({"hash": "C" * 64, "amount": str(int(q["amount_raw"]) + 1), "local_timestamp": T[0]})
        self.assertEqual(v["verdict"], cb.REFUSABLE_WRONG_AMOUNT)

    def test_a_second_exact_payment_is_a_duplicate_to_refund(self):
        s = svc()
        q = s.quote(250, qid())
        for h in ("D" * 64, "E" * 64):
            v = s.settle({"hash": h, "amount": q["amount_raw"], "local_timestamp": T[0] + 5})
        self.assertEqual(v["verdict"], cb.DUPLICATE_REFUND_DUE)
        self.assertEqual(v["refund_amount_raw"], q["amount_raw"])

    def test_same_buyer_asking_again_gets_the_same_quote(self):
        s = svc()
        a = s.quote(250, qid())
        T[0] += 10
        self.assertEqual(s.quote(250, qid()), a)

    def test_two_orders_get_different_tails_and_amounts(self):
        s = svc()
        a, b = s.quote(250, qid(b"a" * 32)), s.quote(250, qid(b"b" * 32))
        self.assertNotEqual(a["amount_raw"], b["amount_raw"])

    def test_one_feed_or_wide_spread_gives_no_quote(self):
        with self.assertRaises(RuntimeError):
            svc([lambda: 0.3]).quote(100, qid(cents=100))
        with self.assertRaises(RuntimeError):
            svc([lambda: 0.3, lambda: 0.4]).quote(100, qid(cents=100))

    def test_bad_inputs_are_refused(self):
        s = svc()
        for cents, ident in ((0, qid()), (2.5, qid()), (True, qid()), (250, "ZZ"), (250, "ab"), (10 ** 9, qid())):
            with self.assertRaises(cb.BindingError, msg=str((cents, ident))):
                s.quote(cents, ident)

    def test_buyer_rederives_the_id_and_the_same_amount_after_a_crash(self):
        k = os.urandom(32)
        s = svc()
        q = s.quote(250, qs.usd_quote_id(k, resource="/api/x", usd_cents=250, payto=PAYTO))
        again = s.quote(250, qs.usd_quote_id(k, resource="/api/x", usd_cents=250, payto=PAYTO))
        self.assertEqual(q["amount_raw"], again["amount_raw"])

    def test_the_module_imports_nothing_that_signs_or_sends(self):
        import ast
        with open(qs.__file__) as fh:
            tree = ast.parse(fh.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add(n.module.split(".")[0])
        self.assertEqual(names, {"argparse", "call_binding", "http", "json", "time", "urllib", "usd_quote"})


class Http(unittest.TestCase):
    def test_get_quote_and_errors(self):
        T[0] = 1_790_000_000
        server = ThreadingHTTPServer(("127.0.0.1", 0), qs.make_handler(svc()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_port
        try:
            with urllib.request.urlopen("%s/quote?usd_cents=250&quote_id=%s" % (base, qid())) as r:
                body = json.load(r)
            self.assertEqual(body["pay_to"], PAYTO)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen("%s/quote?usd_cents=2.5&quote_id=%s" % (base, qid()))
            self.assertEqual(e.exception.code, 400)
        finally:
            server.shutdown()

    def test_503_when_feeds_fail(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), qs.make_handler(svc([lambda: 0.3])))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen("http://127.0.0.1:%d/quote?usd_cents=100&quote_id=%s" % (server.server_port, qid(cents=100)))
            self.assertEqual(e.exception.code, 503)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
