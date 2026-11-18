import contextlib, importlib.util, io, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("delivery_fails", ROOT / "examples" / "delivery_fails.py")
df = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(df)

LABELS = {"buyer-recomputed", "chain-read", "seller-supplied"}
SECTIONS = ("binding", "settlement", "delivery", "entitlement")


class DeliveryJudgedSeparately(unittest.TestCase):
    def setUp(self):
        self.r = {rec["case"]: rec for rec in df.records()}

    def test_a_payment_matches_content_fails(self):
        a = self.r["A"]
        self.assertEqual(a["settlement"]["status"], "matched")
        self.assertTrue(a["settlement"]["exact_amount"] and a["settlement"]["in_window"])
        self.assertEqual(a["delivery"]["status"], "failed")
        self.assertNotEqual(a["delivery"]["recomputed_sha256"], a["delivery"]["expected_sha256"])
        self.assertFalse(a["entitlement"]["fulfilled"])
        self.assertTrue(a["entitlement"]["refund_due"])
        self.assertFalse(a["entitlement"]["refunded"])

    def test_b_no_content_is_pending_delivery(self):
        b = self.r["B"]
        self.assertEqual(b["settlement"]["status"], "matched")
        self.assertEqual(b["settlement"]["ledger_verdict"], "pending_delivery")
        self.assertEqual(b["delivery"]["status"], "pending_delivery")
        self.assertIsNone(b["delivery"]["recomputed_sha256"])
        self.assertFalse(b["entitlement"]["fulfilled"])
        self.assertFalse(b["entitlement"]["refund_due"])

    def test_c_content_matches_is_delivered(self):
        c = self.r["C"]
        self.assertEqual(c["settlement"]["status"], "matched")
        self.assertEqual(c["delivery"]["status"], "delivered")
        self.assertEqual(c["delivery"]["recomputed_sha256"], c["delivery"]["expected_sha256"])
        self.assertTrue(c["entitlement"]["fulfilled"])

    def test_d_duplicate_grants_no_second_entitlement(self):
        d = self.r["D"]
        self.assertEqual(d["settlement"]["status"], "duplicate_refund_due")
        self.assertEqual(d["entitlement"]["entitlements_granted"], 1)
        self.assertTrue(d["entitlement"]["refund_due"])
        self.assertFalse(d["entitlement"]["refunded"])

    def test_credit_does_not_wait_for_delivery(self):
        for rec in self.r.values():
            self.assertIn(rec["settlement"]["ledger_verdict"],
                          ("pending_delivery", "duplicate_refund_due"))

    def test_every_field_has_a_provenance_label(self):
        for rec in self.r.values():
            prov = rec["provenance"]
            self.assertTrue(set(prov.values()) <= LABELS)
            fields = {"%s.%s" % (s, k) for s in SECTIONS for k in rec[s]}
            self.assertEqual(fields, set(prov))
        p = self.r["A"]["provenance"]
        self.assertEqual(p["delivery.recomputed_sha256"], "buyer-recomputed")
        self.assertEqual(p["delivery.expected_sha256"], "seller-supplied")
        self.assertEqual(p["settlement.block"], "chain-read")
        self.assertEqual(p["binding.quote_id"], "buyer-recomputed")

    def test_main_prints_header_and_four_records(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(df.main(), 0)
        lines = buf.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("delivery_fails: 1 quote, 4 cases"))
        self.assertIn("constructed fixtures", lines[1])
        cases = [json.loads(l)["case"] for l in lines[2:]]
        self.assertEqual(cases, ["A", "B", "C", "D"])


if __name__ == "__main__":
    unittest.main()
