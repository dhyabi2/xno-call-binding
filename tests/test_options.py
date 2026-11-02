import os, sqlite3, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import binding_options as b

class T(unittest.TestCase):
    def test_address_codec_matches_docs_vector(self):
        pub = bytes(32)  # the well-known all-zero (burn) account
        self.assertEqual(b.pubkey_to_account(pub), "nano_1111111111111111111111111111111111111111111111111111hifc8npp")
        self.assertEqual(b.account_to_pubkey(b.pubkey_to_account(pub)), pub)
    def test_bad_checksum_refused(self):
        a = b.pubkey_to_account(bytes(range(32)))
        bad = a[:-1] + ("1" if a[-1] != "1" else "3")
        with self.assertRaises(ValueError): b.account_to_pubkey(bad)
    def test_invoice_index_deterministic_and_unordered(self):
        s = b"s" * 32
        self.assertEqual(b.invoice_index(s, "ord-1"), b.invoice_index(s, "ord-1"))
        idx = [b.invoice_index(s, "o%d" % i) for i in range(200)]
        self.assertEqual(len(set(idx)), 200)
        asc = sum(1 for i in range(199) if idx[i+1] > idx[i])
        self.assertTrue(60 < asc < 140)
    def test_commitment_binds_all_fields(self):
        p = b.pubkey_to_account(bytes(32))
        base = b.order_commitment("o1", p, 5 * 10**28)
        self.assertNotEqual(base, b.order_commitment("o2", p, 5 * 10**28))
        self.assertNotEqual(base, b.order_commitment("o1", p, 5 * 10**28 + 1))
        with self.assertRaises(TypeError): b.order_commitment("o1", p, 0.05)
    def test_tag_rounds_up_and_float_refused(self):
        a = b.tagged_amount(5 * 10**28, "o1", b"k" * 32)
        self.assertGreaterEqual(a, 5 * 10**28)
    def test_ledger_one_to_one(self):
        l = b.Ledger(sqlite3.connect(":memory:"))
        e = 100
        self.assertEqual(l.claim("H1", "o1", 100, 10, 50, e), "matched")
        self.assertEqual(l.claim("H1", "o1", 100, 10, 50, e), "matched")
        self.assertEqual(l.claim("H2", "o1", 100, 11, 50, e), "duplicate_refund_due")
        self.assertEqual(l.claim("H1", "o2", 100, 12, 50, e), "duplicate_refund_due")
        self.assertEqual(l.claim("H3", "o3", 100, 60, 50, e), "refusable_late")
        self.assertEqual(l.claim("H4", "o4", 99, 10, 50, e), "refusable_wrong_amount")
    def test_ledger_persists_across_restart(self):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "l.db")
        c = sqlite3.connect(p); b.Ledger(c).claim("H1", "o1", 1, 1, 9, 1); c.close()
        self.assertEqual(b.Ledger(sqlite3.connect(p)).claim("H1", "o2", 1, 1, 9, 1), "duplicate_refund_due")
if __name__ == "__main__": unittest.main()
