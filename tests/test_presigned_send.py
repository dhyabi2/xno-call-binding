import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import _signer
import presigned_send as ps
from binding_options import commitment_rep_account, pubkey_to_account

PAYTO = "nano_39b311tznm9hub316enn8159ammduxnfonoaei7afzymw66wsouw9q3j9ic1"
AMOUNT = 5 * 10 ** 28 + 949121 * 10 ** 15
FRONTIER = "AB" * 32
BALANCE = 3 * 10 ** 30
NOW = 1_790_000_000

# A real mainnet send (rpc.nano.to block_info, 2026-11-02): proves the hash + signature code against the chain itself.
REAL = {"type": "state", "account": "nano_3m8cz87zwxb1y16ob4bzp1eyek78qaig8ktohk7d45b18sh6u9exbowbnekr",
        "previous": "37402FF0B0E37BF00EA892C078BF46F1FD6D3A79650327EB1B64CAA87E197DD4",
        "representative": "nano_1stofnrxuz3cai7ze75o174bpm7scwj9jn3nxsn8ntzg784jf1gzn1jjdkou",
        "balance": "6275108217158176000000000000000",
        "link": "7AA450344121ED8AF805F61F9A534B2E69C2A5C7F0F67A5C3B2E4CDA710FB902",
        "signature": "D136FFC68493F022727B58E14E938CAF90D11B8A8A4755A2378DC0C7D59A4D6A8C25836BBA0BA16F1120CEC22A0CB2D96BDDC118A5DFDB1C1048620EFA63E206"}
REAL_HASH = "B749B757EE750FC9AEA72F33CB429EACCD2ABEC9F2CCF59BF17AFAC304C9A58F"


def make(key=None, **over):
    key = key or os.urandom(32)
    acct = pubkey_to_account(_signer.public_key(key))
    order_id = over.pop("order_id", "ord_" + "1" * 16)
    contents = {"type": "state", "account": acct, "previous": over.pop("previous", FRONTIER),
                "representative": over.pop("rep", commitment_rep_account(order_id, PAYTO, AMOUNT)),
                "balance": str(over.pop("balance", BALANCE - AMOUNT)),
                "link": over.pop("link", ps.account_to_pubkey(PAYTO).hex().upper())}
    sig = _signer.sign(key, ps.block_hash(contents))
    contents["signature"] = sig.hex().upper()
    p = {"v": ps.VERSION, "quote_id": "q" * 32, "order_id": order_id, "pay_to": PAYTO, "amount_raw": str(AMOUNT),
         "expires_at": NOW + 60, "block": contents}
    p.update(over)
    return p, {"frontier": FRONTIER, "balance": str(BALANCE)}, key


class RealChain(unittest.TestCase):
    def test_hash_and_signature_code_agree_with_mainnet(self):
        h = ps.block_hash(REAL)
        self.assertEqual(h.hex().upper(), REAL_HASH)
        self.assertTrue(ps.verify_signature(ps.account_to_pubkey(REAL["account"]), h, bytes.fromhex(REAL["signature"])))

    def test_a_flipped_bit_in_a_real_signature_fails(self):
        sig = bytearray.fromhex(REAL["signature"])
        sig[10] ^= 1
        self.assertFalse(ps.verify_signature(ps.account_to_pubkey(REAL["account"]), ps.block_hash(REAL), bytes(sig)))


class Check(unittest.TestCase):
    def test_a_good_presigned_block_is_ready_and_needs_only_work(self):
        p, info, _ = make()
        r = ps.check_presigned(p, info, now=NOW)
        self.assertEqual(r["verdict"], "ready", r)
        self.assertNotIn("work", r["process_request"]["block"])
        self.assertEqual(r["process_request"]["action"], "process")
        self.assertIn("no signature, no key", r["middleware_adds"])

    def test_every_tampered_field_is_refused(self):
        for field, value in (("balance", str(BALANCE - AMOUNT + 1)), ("link", "00" * 32),
                             ("representative", commitment_rep_account("other", PAYTO, AMOUNT)),
                             ("previous", "CD" * 32)):
            p, info, _ = make()
            p["block"][field] = value  # signature now covers different contents
            self.assertEqual(ps.check_presigned(p, info, now=NOW)["verdict"], "refuse", field)

    def test_signed_to_another_destination_is_refused_even_if_the_signature_is_valid(self):
        other = pubkey_to_account(os.urandom(32))
        p, info, _ = make(link=ps.account_to_pubkey(other).hex().upper())
        r = ps.check_presigned(p, info, now=NOW)
        self.assertEqual(r["verdict"], "refuse")
        self.assertIn("different account", " ".join(r["reasons"]))

    def test_a_block_for_a_different_order_is_not_this_quote(self):
        p, info, _ = make(order_id="ord_aaaaaaaaaaaaaaaa")
        p["order_id"] = "ord_bbbbbbbbbbbbbbbb"
        r = ps.check_presigned(p, info, now=NOW)
        self.assertEqual(r["verdict"], "refuse")
        self.assertIn("commitment", " ".join(r["reasons"]))

    def test_wrong_amount_either_side(self):
        p, info, _ = make(balance=BALANCE - AMOUNT - 1)
        self.assertIn("balance falls by", " ".join(ps.check_presigned(p, info, now=NOW)["reasons"]))
        p, info, _ = make()
        p["amount_raw"] = str(AMOUNT + 1)
        self.assertEqual(ps.check_presigned(p, info, now=NOW)["verdict"], "refuse")

    def test_stale_frontier_is_not_a_forgery(self):
        p, info, _ = make()
        info["frontier"] = "EF" * 32
        r = ps.check_presigned(p, info, now=NOW)
        self.assertEqual(r["verdict"], "stale_frontier")
        self.assertNotIn("process_request", r)

    def test_expired_is_not_broadcast(self):
        p, info, _ = make()
        r = ps.check_presigned(p, info, now=NOW + 61)
        self.assertEqual(r["verdict"], "expired")
        self.assertNotIn("process_request", r)

    def test_float_amounts_and_malformed_input_are_refused_not_raised(self):
        p, info, _ = make()
        p["amount_raw"] = 5e28
        self.assertEqual(ps.check_presigned(p, info, now=NOW)["verdict"], "refuse")
        self.assertEqual(ps.check_presigned({}, info, now=NOW)["verdict"], "refuse")
        p, info, _ = make()
        p["v"] = "other"
        self.assertEqual(ps.check_presigned(p, info, now=NOW)["verdict"], "refuse")

    def test_the_library_cannot_sign_or_send(self):
        import ast
        with open(ps.__file__) as fh:
            tree = ast.parse(fh.read())
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertFalse({"sign", "sign_block", "broadcast", "send", "process"} & names)
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {"hashlib", "binding_options"})

    def test_input_is_not_mutated(self):
        p, info, _ = make()
        before = copy.deepcopy(p)
        ps.check_presigned(p, info, now=NOW)
        self.assertEqual(p, before)


if __name__ == "__main__":
    unittest.main()
