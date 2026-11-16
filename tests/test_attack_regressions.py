#!/usr/bin/env python3
"""Regression tests for the attacks found in review 1114 at 968e18d. Each one used to credit a
payment twice, credit a payment made before its quote, or return `matched` for someone else's
payment. Every one must now fail closed. Standard library only; every node reply is mocked here,
nothing touches a network, and nothing is signed or sent.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xno_call_binding import call_binding as cb  # noqa: E402
from xno_call_binding import quote_service as qs  # noqa: E402
from xno_call_binding.binding_options import account_to_pubkey, pubkey_to_account  # noqa: E402

PAYTO = "nano_39b311tznm9hub316enn8159ammduxnfonoaei7afzymw66wsouw9q3j9ic1"
BUYER = pubkey_to_account(b"\x09" * 32)
OTHER = pubkey_to_account(b"\x07" * 32)
FEEDS = [lambda: 0.32, lambda: 0.325]
CREDITED = (cb.MATCHED, cb.PENDING_DELIVERY)
PRICE = 50 * 10**27
NOW = 1_762_000_000

# The victim's quote id (fixed key) and a quote id ground offline to carry the same tail: any
# 32-128 lowercase hex is accepted, and about 10**6 tries find one (cb.amount_tail is checked below).
VICTIM_QID = qs.usd_quote_id(b"v" * 32, resource="/api/x", usd_cents=250, payto=PAYTO)
GROUND_QID = "000000000000000000000000000e6462"
S = "5E" * 32   # the victim's send
R = "7A" * 32   # pay_to's receive of it


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def led_with_quote(key=b"\x01" * 32, expires=NOW + 300, opened_at=None):
    led = cb.QuoteLedger(payto=PAYTO, clock=lambda: NOW)
    qid = cb.derive_quote_id(key, resource="/audit", price_raw=PRICE, payto=PAYTO)
    rec = led.open_quote(qid, price_raw=PRICE, expires_at=expires, opened_at=opened_at)
    return led, qid, rec


def send(h, amount, ts=NOW + 10, **kw):
    b = {"hash": h, "amount": str(amount), "local_timestamp": ts, "confirmed": "true",
         "subtype": "send", "link_as_account": PAYTO}
    b.update(kw)
    return b


class Finding1PaymentCreditedTwice(unittest.TestCase):
    def test_ground_tail_is_real(self):
        self.assertEqual(cb.amount_tail(GROUND_QID), cb.amount_tail(VICTIM_QID))

    def test_payment_dated_before_the_quote_is_refusable_early(self):
        led, qid, rec = led_with_quote(opened_at=NOW)
        v = led.credit(send("A" * 64, rec["expected_raw"], ts=1))
        self.assertEqual(v["verdict"], cb.REFUSABLE_EARLY, v)
        self.assertNotIn(qid, led._credited)
        v = led.credit(send("A" * 64, rec["expected_raw"], ts=NOW - 1))
        self.assertEqual(v["verdict"], cb.REFUSABLE_EARLY, v)
        self.assertEqual(v["opened_at"], NOW)
        # the boundary second and later are inside the window
        self.assertIn(led.credit(send("A" * 64, rec["expected_raw"], ts=NOW))["verdict"], CREDITED)

    def test_opened_at_defaults_to_the_ledger_clock(self):
        led = cb.QuoteLedger(payto=PAYTO, clock=lambda: NOW + 50)
        qid = cb.derive_quote_id(b"\x02" * 32, resource="/a", price_raw=PRICE, payto=PAYTO)
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 300)
        self.assertEqual(rec["opened_at"], NOW + 50)
        self.assertEqual(led.credit(send("A" * 64, rec["expected_raw"], ts=NOW + 49))["verdict"],
                         cb.REFUSABLE_EARLY)
        for bad in (0, -1, True, 1.5, "1"):
            with self.assertRaises(cb.BindingError):
                led.open_quote(cb.derive_quote_id(os.urandom(32), resource="/a", price_raw=PRICE,
                                                  payto=PAYTO),
                               price_raw=PRICE, expires_at=NOW + 300, opened_at=bad)

    def test_quote_service_uses_quoted_at_as_the_lower_bound(self):
        clock = Clock(1_790_000_000)
        s = qs.QuoteService(PAYTO, FEEDS, clock=clock)
        q = s.quote(250, VICTIM_QID)
        early = {"amount": q["amount_raw"], "local_timestamp": str(q["quoted_at"] - 1),
                 "confirmed": "true", "subtype": "send", "contents": {"link_as_account": PAYTO}}
        self.assertEqual(s.settle(early, block_hash=S)["verdict"], cb.REFUSABLE_EARLY)
        self.assertIn(cb.REFUSABLE_EARLY, qs.REFUSALS)

    def test_raw_false_receive_without_its_send_hash_is_not_credited(self):
        clock = Clock(1_790_000_000)
        s = qs.QuoteService(PAYTO, FEEDS, clock=clock)
        q = s.quote(250, VICTIM_QID)
        entry = {"type": "receive", "account": BUYER, "hash": R, "amount": q["amount_raw"],
                 "local_timestamp": str(clock.t + 5), "confirmed": "true"}
        v = s.settle(entry, account=PAYTO)
        self.assertEqual(v["verdict"], cb.INCONCLUSIVE, v)
        self.assertNotIn(VICTIM_QID, s.ledger._credited)
        for bad in ("5E" * 31, ["5E" * 32], 5):
            self.assertEqual(s.settle(entry, account=PAYTO, source_hash=bad)["verdict"],
                             cb.INCONCLUSIVE)

    def test_victims_send_is_never_recredited_to_a_ground_quote_after_release(self):
        """The reviewer's scenario: the victim's payment is settled from pay_to's raw=false history,
        the victim's tail is swept, an attacker opens a ground quote_id with the same tail and
        settles the victim's SEND. It must not be credited to the attacker."""
        clock = Clock(1_790_000_000)
        s = qs.QuoteService(PAYTO, FEEDS, clock=clock)
        q1 = s.quote(250, VICTIM_QID)
        receive_entry = {"type": "receive", "account": BUYER, "hash": R, "amount": q1["amount_raw"],
                         "local_timestamp": str(clock.t + 5), "confirmed": "true"}
        v1 = s.settle(receive_entry, account=PAYTO, source_hash=S)
        self.assertEqual(v1["verdict"], cb.PENDING_DELIVERY)
        self.assertEqual(v1["quote_id"], VICTIM_QID)
        s.ledger.mark_delivered(VICTIM_QID)

        clock.t += 60 + cb.REFUND_WINDOW_S + 10    # the victim's tail is swept on the next quote()
        q2 = s.quote(250, GROUND_QID)
        self.assertEqual(q2["amount_raw"], q1["amount_raw"])
        send_block_info = {"amount": q1["amount_raw"], "local_timestamp": str(1_790_000_005),
                           "confirmed": "true", "subtype": "send", "block_account": BUYER,
                           "contents": {"account": BUYER, "link_as_account": PAYTO}}
        v2 = s.settle(send_block_info, block_hash=S, quote_id=GROUND_QID)
        self.assertEqual(v2["verdict"], cb.REFUSABLE_OTHER_QUOTE, v2)
        self.assertNotIn(GROUND_QID, s.ledger._credited)
        # without quote_id= it is a replay of the victim's payment, never a credit to the attacker
        v3 = s.settle(send_block_info, block_hash=S)
        self.assertTrue(v3["replay"])
        self.assertEqual(v3["quote_id"], VICTIM_QID)
        self.assertNotIn(GROUND_QID, s.ledger._credited)
        # and pay_to's receive re-read is the same payment too
        v4 = s.settle(receive_entry, account=PAYTO, source_hash=S, quote_id=GROUND_QID)
        self.assertEqual(v4["verdict"], cb.REFUSABLE_OTHER_QUOTE, v4)

    def test_old_send_replayed_into_a_fresh_ledger_is_refusable_early(self):
        """After a restart the in-memory ledger is empty; the quoted_at bound still refuses it."""
        clock = Clock(1_790_000_000 + 2 * cb.REFUND_WINDOW_S)
        s = qs.QuoteService(PAYTO, FEEDS, clock=clock)
        q = s.quote(250, GROUND_QID)
        old_send = {"amount": q["amount_raw"], "local_timestamp": "1790000005", "confirmed": "true",
                    "subtype": "send", "contents": {"link_as_account": PAYTO}}
        self.assertEqual(s.settle(old_send, block_hash=S)["verdict"], cb.REFUSABLE_EARLY)
        self.assertNotIn(GROUND_QID, s.ledger._credited)

    def test_credited_payment_is_remembered_after_close_quote(self):
        led, qid, rec = led_with_quote()
        self.assertIn(led.credit(send(S, rec["expected_raw"]))["verdict"], CREDITED)
        led.close_quote(qid)
        self.assertEqual(led._blocks[S], qid)

    def test_raw_false_receive_then_send_same_ledger(self):
        led, qid, rec = led_with_quote()
        amt = rec["expected_raw"]
        rf = {"hash": "CD" * 32, "amount": str(amt), "local_timestamp": NOW + 20, "confirmed": "true",
              "type": "receive", "account": OTHER}
        self.assertEqual(led.credit(rf, account=PAYTO)["verdict"], cb.INCONCLUSIVE)
        self.assertEqual(led.credit(rf, account=PAYTO, source_hash="AB" * 32)["verdict"],
                         cb.PENDING_DELIVERY)
        v = led.credit(send("AB" * 32, amt))
        self.assertTrue(v["replay"], v)
        self.assertEqual(v["quote_id"], qid)
        # a genuinely different send is a duplicate to refund, not a credit
        self.assertEqual(led.credit(send("EF" * 32, amt))["verdict"], cb.DUPLICATE_REFUND_DUE)
        # a raw=false receive whose send is named only by the caller is never a refundable duplicate
        rf2 = dict(rf, hash="11" * 32)
        v = led.credit(rf2, account=PAYTO, source_hash="22" * 32)
        self.assertEqual(v["verdict"], cb.INCONCLUSIVE, v)
        self.assertNotIn("22" * 32, led._blocks)


class Finding2ReplayForAnotherQuote(unittest.TestCase):
    def test_same_shape_replay_for_another_quote_is_refused(self):
        clock = Clock(1_790_000_000)
        s = qs.QuoteService(PAYTO, FEEDS, clock=clock)
        q1 = s.quote(250, VICTIM_QID)
        blk = {"amount": q1["amount_raw"], "local_timestamp": str(clock.t + 5), "confirmed": "true",
               "subtype": "send", "contents": {"link_as_account": PAYTO}}
        self.assertEqual(s.settle(blk, block_hash=S, quote_id=VICTIM_QID)["verdict"],
                         cb.PENDING_DELIVERY)
        s.ledger.mark_delivered(VICTIM_QID)
        attacker_qid = qs.usd_quote_id(b"a" * 32, resource="/api/x", usd_cents=250, payto=PAYTO)
        s.quote(250, attacker_qid)
        v = s.settle(blk, block_hash=S.lower(), quote_id=attacker_qid)
        self.assertEqual(v["verdict"], cb.REFUSABLE_OTHER_QUOTE, v)
        self.assertFalse(v["credited"])
        self.assertNotIn("quote_id", v)          # never hands out the victim's quote id
        self.assertNotIn(attacker_qid, s.ledger._credited)
        self.assertIn(cb.REFUSABLE_OTHER_QUOTE, qs.REFUSALS)
        # the victim retrying its own lost response still gets matched
        self.assertEqual(s.settle(blk, block_hash=S, quote_id=VICTIM_QID)["verdict"], cb.MATCHED)

    def test_fresh_block_whose_tail_is_another_quotes_is_refused(self):
        led, qid, rec = led_with_quote()
        other = cb.derive_quote_id(b"\x05" * 32, resource="/audit", price_raw=PRICE, payto=PAYTO)
        led.open_quote(other, price_raw=PRICE, expires_at=NOW + 300)
        v = led.credit(send("A" * 64, rec["expected_raw"]), quote_id=other)
        self.assertEqual(v["verdict"], cb.REFUSABLE_OTHER_QUOTE, v)
        self.assertNotIn(qid, led._credited)
        self.assertNotIn("A" * 64, led._blocks)
        self.assertIn(led.credit(send("A" * 64, rec["expected_raw"]), quote_id=qid)["verdict"],
                      CREDITED)


class Finding3SourceFromRealBlockInfo(unittest.TestCase):
    def setUp(self):
        self.led, self.qid, self.rec = led_with_quote(expires=1_800_000_000)
        amt = str(self.rec["expected_raw"])
        # block_info of the send: no "hash" key, as a real node returns it
        self.src = {"amount": amt, "local_timestamp": str(NOW + 5), "confirmed": "true",
                    "subtype": "send", "block_account": BUYER,
                    "contents": {"account": BUYER, "link": "", "link_as_account": PAYTO}}
        self.rcv = {"hash": R, "amount": amt, "local_timestamp": str(NOW + 6),
                    "confirmed": "true", "subtype": "receive", "contents": {"link": S}}

    def test_block_info_source_works_with_source_hash(self):
        v = self.led.credit(self.rcv, source=self.src, source_hash=S.lower())
        self.assertEqual(v["verdict"], cb.PENDING_DELIVERY, v)
        self.assertEqual(self.led._credit_key[self.qid], S)

    def test_block_info_source_without_its_hash_stays_inconclusive(self):
        v = self.led.credit(self.rcv, source=self.src)
        self.assertEqual(v["verdict"], cb.INCONCLUSIVE, v)
        self.assertNotIn(self.qid, self.led._credited)

    def test_source_hash_must_agree_with_the_link_and_source(self):
        for kw in ({"source_hash": "6" * 64},
                   {"source_hash": S, "source": dict(self.src, hash="6" * 64)}):
            kw.setdefault("source", self.src)
            v = self.led.credit(self.rcv, **kw)
            self.assertEqual(v["verdict"], cb.INCONCLUSIVE, (kw, v))
            self.assertNotIn(self.qid, self.led._credited)

    def test_bad_source_is_still_refused_with_a_hash(self):
        for bad, verdict in ((dict(self.src, confirmed="false"), cb.INCONCLUSIVE),
                             (dict(self.src, amount="1"), cb.INCONCLUSIVE),
                             (dict(self.src, subtype="receive"), cb.REFUSABLE_NOT_PAYMENT),
                             (dict(self.src, contents={"link_as_account": OTHER}),
                              cb.REFUSABLE_NOT_PAYMENT)):
            v = self.led.credit(self.rcv, source=bad, source_hash=S)
            self.assertEqual(v["verdict"], verdict, (bad, v))
            self.assertNotIn(self.qid, self.led._credited)

    def test_source_hash_on_a_send_must_be_its_own_hash(self):
        b = send(S, self.rec["expected_raw"])
        self.assertEqual(self.led.credit(b, source_hash="6" * 64)["verdict"], cb.INCONCLUSIVE)
        self.assertIn(self.led.credit(b, source_hash=S.lower())["verdict"], CREDITED)


class ReviewerCreditProbes(unittest.TestCase):
    """The reviewer's non-credit probes (test_attack_credit.py), kept as regressions."""

    def test_unconfirmed_variants(self):
        for c in ("false", "True", 1, None, ["true"], "TRUE"):
            led, qid, rec = led_with_quote()
            v = led.credit(send("A" * 64, rec["expected_raw"], confirmed=c))
            self.assertNotIn(v["verdict"], CREDITED, (c, v))

    def test_other_destination_variants(self):
        led, qid, rec = led_with_quote()
        b = send("A" * 64, rec["expected_raw"])
        del b["link_as_account"]
        b["link"] = account_to_pubkey(OTHER).hex()
        self.assertEqual(led.credit(b)["verdict"], cb.REFUSABLE_NOT_PAYMENT)
        b = send("B" * 64, rec["expected_raw"], contents={"link": account_to_pubkey(OTHER).hex()})
        self.assertEqual(led.credit(b)["verdict"], cb.INCONCLUSIVE)
        b = send("C" * 64, rec["expected_raw"], contents={"link_as_account": OTHER})
        self.assertEqual(led.credit(b)["verdict"], cb.INCONCLUSIVE)
        b = send("D" * 64, rec["expected_raw"], contents={"link_as_account": 5})
        self.assertEqual(led.credit(b)["verdict"], cb.INCONCLUSIVE)
        b = send("E" * 64, rec["expected_raw"], link_as_account=PAYTO.upper())
        self.assertNotIn(led.credit(b)["verdict"], CREDITED)

    def test_receive_not_on_payto(self):
        led, qid, rec = led_with_quote()
        base = {"hash": "A" * 64, "amount": str(rec["expected_raw"]), "local_timestamp": NOW + 10,
                "confirmed": "true"}
        self.assertEqual(led.credit(dict(base, type="receive", account=PAYTO))["verdict"],
                         cb.INCONCLUSIVE)
        v = led.credit(dict(base, subtype="receive", block_account=OTHER), account=PAYTO)
        self.assertEqual(v["verdict"], cb.REFUSABLE_NOT_PAYMENT)
        v = led.credit(dict(base, type="state", subtype="receive", account=OTHER, link="1" * 64),
                       account=PAYTO)
        self.assertEqual(v["verdict"], cb.REFUSABLE_NOT_PAYMENT)
        v = led.credit(dict(base, subtype="receive", block_account=PAYTO,
                            contents={"account": "xrb_" + OTHER[5:]}))
        self.assertEqual(v["verdict"], cb.INCONCLUSIVE)
        v = led.credit(dict(base, type="receive"), account=OTHER)
        self.assertEqual(v["verdict"], cb.REFUSABLE_NOT_PAYMENT)

    def test_source_lie_needs_matching_link(self):
        led, qid, rec = led_with_quote()
        rcv = {"hash": "A" * 64, "amount": str(rec["expected_raw"]), "local_timestamp": NOW + 10,
               "confirmed": "true", "type": "receive"}
        fake_src = send("B" * 64, rec["expected_raw"])
        # a receive with no link is not tied to any source, whatever hash the caller names
        self.assertEqual(led.credit(rcv, source=fake_src)["verdict"], cb.INCONCLUSIVE)
        self.assertEqual(led.credit(rcv, source=fake_src, source_hash="B" * 64)["verdict"],
                         cb.INCONCLUSIVE)
        rcv2 = dict(rcv, link="C" * 64)
        self.assertEqual(led.credit(rcv2, source=fake_src)["verdict"], cb.INCONCLUSIVE)
        self.assertEqual(led.credit(rcv2, source=send("C" * 64, rec["expected_raw"],
                                                      confirmed="false"))["verdict"],
                         cb.INCONCLUSIVE)
        self.assertEqual(led.credit(rcv2, source=send("C" * 64, rec["expected_raw"],
                                                      link_as_account=OTHER))["verdict"],
                         cb.REFUSABLE_NOT_PAYMENT)
        self.assertNotIn(qid, led._credited)

    def test_replay_hash_case_prefix_link_forms(self):
        led, qid, rec = led_with_quote()
        amt = rec["expected_raw"]
        s = "ab" * 32
        self.assertEqual(led.credit(send(s, amt))["verdict"], cb.PENDING_DELIVERY)
        forms = [
            send(s.upper(), amt),
            send(s, amt, link_as_account="xrb_" + PAYTO[5:]),
            dict({k: x for k, x in send(s, amt).items() if k != "link_as_account"},
                 link=account_to_pubkey(PAYTO).hex()),
        ]
        for f in forms:
            v = led.credit(f)
            self.assertTrue(v["replay"], v)
            self.assertEqual(v["quote_id"], qid)
        r = {"hash": "CD" * 32, "amount": str(amt), "local_timestamp": NOW + 20, "confirmed": "true",
             "type": "state", "subtype": "receive", "account": PAYTO, "link": s.lower()}
        self.assertTrue(led.credit(r)["replay"])
        bi = {"amount": str(amt), "local_timestamp": NOW + 20, "confirmed": "true", "subtype": "receive",
              "block_account": "xrb_" + PAYTO[5:], "contents": {"account": PAYTO, "link": s.upper()}}
        self.assertTrue(led.credit(bi, block_hash="cd" * 32)["replay"])
        led2, qid2, rec2 = led_with_quote()
        self.assertEqual(led2.credit(r)["verdict"], cb.PENDING_DELIVERY)
        self.assertTrue(led2.credit(send(s.upper(), amt))["replay"])

    def test_timestamps_and_expiry(self):
        for ts in (0, "0", None, -1, "abc", 1.5, True, "1" * 50):
            led, qid, rec = led_with_quote()
            v = led.credit(send("A" * 64, rec["expected_raw"], ts=ts))
            self.assertEqual(v["verdict"], cb.INCONCLUSIVE, (ts, v))
        led, qid, rec = led_with_quote()
        self.assertEqual(led.credit(send("A" * 64, rec["expected_raw"], ts=NOW + 301))["verdict"],
                         cb.REFUSABLE_LATE)

    def test_malformed_no_crash(self):
        led, qid, rec = led_with_quote()
        amt = str(rec["expected_raw"])
        for src in (5, "x", [1], {"hash": ["a"]}, {"hash": "C" * 64, "contents": "s"},
                    {"hash": "C" * 64, "amount": "1" * 5000, "confirmed": "true",
                     "subtype": "send", "link_as_account": PAYTO}):
            r = {"hash": "B" * 64, "amount": amt, "local_timestamp": NOW, "confirmed": "true",
                 "type": "receive", "link": "C" * 64}
            self.assertNotIn(led.credit(r, source=src)["verdict"], CREDITED)
            self.assertNotIn(led.credit(r, source=src, source_hash="C" * 64)["verdict"], CREDITED)
        r = {"hash": "B" * 64, "amount": amt, "local_timestamp": NOW, "confirmed": "true",
             "type": "receive"}
        self.assertNotIn(led.credit(r, account=["x"])["verdict"], CREDITED)
        self.assertNotIn(led.credit(r, account=PAYTO, source_hash={"a": 1})["verdict"], CREDITED)
        self.assertNotIn(qid, led._credited)


if __name__ == "__main__":
    unittest.main(verbosity=2)
