import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ap2_nano_mandate as M

ADDR = "nano_3aysuejus8iy1hhw6doc7syzg1aaa6hgpec91xcc36mf6hp6thy7u6ymkgfm"
H = "AB" * 32

class T(unittest.TestCase):
    def test_unpaid_draft_checks_and_has_no_hash(self):
        m = M.build("m", ADDR, 10**26, "R1"); self.assertEqual(M.check(m), [])
        self.assertEqual(m["payment_mandate_contents"]["payment_response"]["details"]["settlement"]["state"], "unpaid")
    def test_paid_needs_hash(self):
        m = M.build("m", ADDR, 10**26, "R1", H); self.assertEqual(M.check(m), [])
        m["payment_mandate_contents"]["payment_response"]["details"]["payload"] = {}
        self.assertIn("paid mandate needs a 64-hex block_hash", M.check(m))
    def test_bad_address_and_amount(self):
        with self.assertRaises(ValueError): M.build("m", ADDR[:-1] + "z", 1, "R")
        with self.assertRaises(ValueError): M.build("m", ADDR, 0, "R")
        with self.assertRaises(ValueError): M.build("m", ADDR, 1, "R", "xyz")
    def test_exact_amount_is_a_string_of_raw(self):
        m = M.build("m", ADDR, 10**26 + 7, "R")
        self.assertEqual(m["payment_mandate_contents"]["payment_response"]["details"]["accepted"]["amount"], str(10**26 + 7))
    def test_wrong_network_flagged(self):
        m = M.build("m", ADDR, 5, "R")
        m["payment_mandate_contents"]["payment_response"]["details"]["accepted"]["network"] = "eip155:8453"
        self.assertIn("accepted.network must be nano:mainnet", M.check(m))
    def test_cli_check_roundtrip(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); json.dump(M.build("m", ADDR, 5, "R", H), f); f.close()
        self.assertEqual(M.main(["--check", f.name]), 0)

if __name__ == "__main__": unittest.main()
