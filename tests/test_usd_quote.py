import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import usd_quote as u

class T(unittest.TestCase):
    def test_quote_median_roundup_and_window(self):
        q = u.quote(250, [lambda: 0.32, lambda: 0.325], now=1000)
        self.assertEqual(q["price_micro_usd"], 322500)
        self.assertEqual(q["expires_at"], 1060)
        # amount * price must cover the USD price (never short)
        self.assertGreaterEqual(int(q["amount_raw"]) * 322500 * 100, 250 * 10**6 * u.XNO)
    def test_one_feed_refused(self):
        def bad(): raise OSError()
        with self.assertRaises(RuntimeError): u.quote(100, [lambda: 0.3, bad])
    def test_spread_refused(self):
        with self.assertRaises(RuntimeError): u.quote(100, [lambda: 0.30, lambda: 0.35])
    def test_float_cents_refused(self):
        with self.assertRaises(ValueError): u.quote(2.5, [lambda: 0.3, lambda: 0.3])
    def test_accept_and_refund(self):
        q = u.quote(250, [lambda: 0.32, lambda: 0.32], now=0)
        a = int(q["amount_raw"])
        self.assertEqual(u.accept(q, a, 60), "settled")
        self.assertEqual(u.accept(q, a, 61), "refusable_late")
        self.assertEqual(u.accept(q, a - 1, 5), "refusable_wrong_amount")
        self.assertEqual(u.refund_raw(q, a), a)
if __name__ == "__main__": unittest.main()
