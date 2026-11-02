import hashlib, json, sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import four_check as fc, _signer
from binding_options import pubkey_to_account

SECRET = b"\x07" * 32
PAYTO = pubkey_to_account(_signer.public_key(SECRET))
ART = b"the artifact"
H = hashlib.sha256(ART).hexdigest()
ASK, NONCE, RAW = "ask-42", "n-1", "1000000000000000000000000"


def sig(ask=ASK, h=H, nonce=NONCE):
    return _signer.sign(SECRET, fc.statement(ask, h, nonce)).hex()


def reply(**kw):
    r = {"confirmed": "true", "amount": RAW, "local_timestamp": "1790000000", "contents": {"link_as_account": PAYTO}}
    r.update(kw); return r


class T(unittest.TestCase):
    def test_all_pass(self):
        self.assertEqual(fc.board_readback("x %s y %s" % (ASK, H), ASK, H)[0], "pass")
        self.assertEqual(fc.artifact_match(H, ART)[0], "pass")
        self.assertEqual(fc.ledger([reply()], PAYTO, RAW)[0], "pass")
        self.assertEqual(fc.signature_check(PAYTO, ASK, H, NONCE, sig())[0], "pass")
        self.assertEqual(fc.combine([("pass", "")] * 4), "verified")

    def test_missing_is_inconclusive_never_pass_never_fail(self):
        self.assertEqual(fc.board_readback(None, ASK, H)[0], "inconclusive")
        self.assertEqual(fc.artifact_match(H, None)[0], "inconclusive")
        self.assertEqual(fc.ledger([{"error": "x"}], PAYTO, RAW)[0], "inconclusive")
        self.assertEqual(fc.signature_check(PAYTO, ASK, H, NONCE, None)[0], "inconclusive")
        self.assertEqual(fc.combine([("pass", ""), ("inconclusive", ""), ("pass", ""), ("pass", "")]), "inconclusive")

    def test_mismatch_is_fail_and_is_not_downgraded(self):
        self.assertEqual(fc.artifact_match(H, b"other")[0], "fail")
        self.assertEqual(fc.board_readback("x %s y" % ASK, ASK, H)[0], "fail")
        self.assertEqual(fc.ledger([reply(amount="1")], PAYTO, RAW)[0], "fail")
        self.assertEqual(fc.ledger([reply(contents={"link_as_account": "nano_x"})], PAYTO, RAW)[0], "fail")
        self.assertEqual(fc.signature_check(PAYTO, "ask-43", H, NONCE, sig())[0], "fail")
        self.assertEqual(fc.combine([("pass", ""), ("fail", ""), ("inconclusive", ""), ("pass", "")]), "failed")

    def test_unconfirmed_is_not_a_pass(self):
        self.assertEqual(fc.ledger([reply(confirmed="false")], PAYTO, RAW)[0], "inconclusive")

    def test_one_dissenting_node_fails(self):
        self.assertEqual(fc.ledger([reply(), reply(amount="1")], PAYTO, RAW)[0], "fail")

    def test_signature_from_other_key_fails(self):
        other = _signer.sign(b"\x08" * 32, fc.statement(ASK, H, NONCE)).hex()
        self.assertEqual(fc.signature_check(PAYTO, ASK, H, NONCE, other)[0], "fail")

    def test_run_end_to_end_with_fake_fetch(self):
        class A: pass
        a = A(); a.board_url = "http://b"; a.ask_id = ASK; a.artifact_sha256 = H; a.block = "AB"; a.expect_raw = RAW
        a.payto = PAYTO; a.nonce = NONCE; a.signature = sig(); a.artifact_file = None; a.node = ["n1", "n2"]
        def fetch(url, body=None):
            if url == "http://b": return ("%s %s" % (ASK, H)).encode(), "Mon, 02 Nov 2026 10:00:00 GMT"
            return json.dumps(reply()).encode(), None
        out = fc.run(a, fetch)
        self.assertEqual(out["checks"]["artifact_hash"][0], "inconclusive")  # no file given -> never a pass
        self.assertEqual(out["verdict"], "inconclusive")
        self.assertEqual(out["block_time_local_timestamp"], "1790000000")
        self.assertEqual(out["board_time_http_date"], "Mon, 02 Nov 2026 10:00:00 GMT")


if __name__ == "__main__":
    unittest.main()
