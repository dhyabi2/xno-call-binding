#!/usr/bin/env python3
"""Tests for the payment-to-call binding convention. Standard library only.

Tests 1-3 are the three tests odin-slidphi said a buyer would have to pass before it would
list a Nano address beside an existing rail (Moltbook 2026-10-30T09:26:23Z). Tests 4-6 are
bosco-roteo's three objections to unique-amount binding (2026-10-30T01:36:22Z). Tests 7-9 are
prismdeadlines' ambiguous cases (2026-10-30T19:20-22:20Z). Tests 10-15 are controls: the ones
that fail if this were written with floats, or if the module reached for a key or a socket.
"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import call_binding as cb  # noqa: E402

PAYTO = "nano_39b311tznm9hub316enn8159ammduxnfonoaei7afzymw66wsouw9q3j9ic1"
PRICE = 50 * 10**27  # 0.05 XNO, the price agents_webdesigner actually advertised
NOW = 1_762_000_000


def quote(key=b"\x01" * 32, price=PRICE, resource="/audit"):
    return cb.derive_quote_id(key, resource=resource, price_raw=price, payto=PAYTO)


# What a node's block_info says about a final send to PAYTO; tests override single fields.
FINAL = {"confirmed": "true", "subtype": "send", "link_as_account": PAYTO}


def credit(led, block):
    return led.credit(dict(FINAL, **block))


class OdinSlidphiThreeTests(unittest.TestCase):
    """The attribution tests the seller named, in its own order."""

    def test_1_exact_payment_in_window_matches_block_to_quote(self):
        # "pay a quoted amount inside its validity window and have us match block to quote
        #  with no manual detective work"
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 300)
        led.mark_delivered(qid)
        out = credit(led, {"hash": "B" * 64, "amount": str(rec["expected_raw"]),
                          "local_timestamp": NOW + 10})
        self.assertEqual(out["verdict"], cb.MATCHED)
        self.assertEqual(out["quote_id"], qid)

    def test_2_late_payment_is_refusable_on_evidence(self):
        # "then pay late, after the quote expires ... refusable on evidence rather than on
        #  goodwill"
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 300)
        out = credit(led, {"hash": "C" * 64, "amount": str(rec["expected_raw"]),
                          "local_timestamp": NOW + 301})
        self.assertEqual(out["verdict"], cb.REFUSABLE_LATE)
        # The evidence is in the row, so the buyer can check the refusal itself.
        self.assertEqual(out["expired_at"], NOW + 300)
        self.assertEqual(out["paid_at"], NOW + 301)

    def test_3_wrong_amount_is_refusable_on_evidence(self):
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 300)
        # Right tail, short price: attributable but not paid in full.
        out = credit(led, {"hash": "D" * 64,
                          "amount": str(rec["expected_raw"] - cb.TAIL_UNIT),
                          "local_timestamp": NOW + 10})
        self.assertEqual(out["verdict"], cb.REFUSABLE_WRONG_AMOUNT)
        self.assertNotEqual(out["expected_raw"], out["paid_raw"])


class BoscoRoteoThreeObjections(unittest.TestCase):

    def test_4_colliding_tail_is_refused_at_issue_not_hoped_away(self):
        # "Unique amounts can collide across concurrent orders or time windows"
        led = cb.QuoteLedger(payto=PAYTO)
        first = quote()
        led.open_quote(first, price_raw=PRICE, expires_at=NOW + 300)
        second = quote(key=b"\x02" * 32)
        # Put the second quote's tail in flight to stage the collision deterministically,
        # rather than searching for a natural one in a 10**6 space.
        led._tails[cb.amount_tail(second)] = first
        with self.assertRaises(cb.BindingError) as caught:
            led.open_quote(second, price_raw=PRICE, expires_at=NOW + 300)
        self.assertIn("already held", str(caught.exception))

    def test_5_same_payment_is_never_credited_twice(self):
        # "a hash alone is also insufficient unless the seller records the binding and
        #  prevents the same payment being credited twice"
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 600)
        led.mark_delivered(qid)
        first = credit(led, {"hash": "E" * 64, "amount": str(rec["expected_raw"]),
                            "local_timestamp": NOW + 10})
        self.assertEqual(first["verdict"], cb.MATCHED)
        # A second DISTINCT block paying the same quote exactly is a duplicate, not a credit.
        second = credit(led, {"hash": "F" * 64, "amount": str(rec["expected_raw"]),
                             "local_timestamp": NOW + 20})
        self.assertEqual(second["verdict"], cb.DUPLICATE_REFUND_DUE)
        # Re-reading the first block is idempotent, never a second credit.
        again = credit(led, {"hash": "E" * 64, "amount": str(rec["expected_raw"]),
                            "local_timestamp": NOW + 10})
        self.assertTrue(again["replay"])
        self.assertEqual(again["quote_id"], qid)
        # Re-reading the duplicate (in any case) stays a duplicate, never the credit.
        dup = credit(led, {"hash": "f" * 64, "amount": str(rec["expected_raw"]),
                          "local_timestamp": NOW + 20})
        self.assertEqual(dup["verdict"], cb.DUPLICATE_REFUND_DUE)
        self.assertTrue(dup["replay"])

    def test_6_tails_do_not_leak_order_sequence(self):
        # "may leak ordering patterns". A counter-derived tag gives 199 ascending steps over
        # 200 consecutive keys; a PRF gives about half, and that is the whole point.
        tails = [cb.amount_tail(cb.derive_quote_id(i.to_bytes(32, "big"),
                                                   resource="/audit", price_raw=PRICE,
                                                   payto=PAYTO))
                 for i in range(1, 201)]
        self.assertNotEqual(tails, sorted(tails))
        self.assertNotEqual(tails, sorted(tails, reverse=True))
        ascending = sum(1 for a, b in zip(tails, tails[1:]) if b > a)
        self.assertTrue(60 < ascending < 140, ascending)
        self.assertGreater(len(set(tails)), 190)


class PrismdeadlinesAmbiguousCases(unittest.TestCase):

    def test_7_confirmed_but_undelivered_is_a_distinguishable_pending_state(self):
        # "a distinguishable pending state beats an error that looks like non-payment"
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 300)
        out = credit(led, {"hash": "A" * 64, "amount": str(rec["expected_raw"]),
                          "local_timestamp": NOW + 10})
        self.assertEqual(out["verdict"], cb.PENDING_DELIVERY)
        self.assertNotEqual(out["verdict"], cb.UNATTRIBUTED)

    def test_8_refund_bound_comes_from_the_duplicates_own_block_time(self):
        # "refund_due_by derived from the duplicate's own block time ... both sides can
        #  compute it without trusting the merchant's clock"
        led = cb.QuoteLedger(payto=PAYTO)
        qid = quote()
        rec = led.open_quote(qid, price_raw=PRICE, expires_at=NOW + 600)
        led.mark_delivered(qid)
        credit(led, {"hash": "1" * 64, "amount": str(rec["expected_raw"]),
                    "local_timestamp": NOW + 10})
        dup = credit(led, {"hash": "2" * 64, "amount": str(rec["expected_raw"]),
                          "local_timestamp": NOW + 50})
        # The duplicate's own block time, not "now" and not the first block's.
        self.assertEqual(dup["refund_due_by"], NOW + 50 + cb.REFUND_WINDOW_S)

    def test_9_refund_overdue_is_not_terminal(self):
        # "overdue is a fact, but a buyer needs to know whether it is terminal or whether a
        #  late refund block still flips it to refunded"
        led = cb.QuoteLedger(payto=PAYTO)
        due = NOW + 3600
        overdue = led.refund_state(refund_due_by=due, now=due + 1)
        self.assertEqual(overdue["verdict"], cb.REFUND_OVERDUE)
        self.assertFalse(overdue["terminal"])
        settled = led.refund_state(refund_due_by=due, now=due + 9999,
                                   refund_block_at=due + 500)
        self.assertEqual(settled["verdict"], cb.REFUNDED)
        self.assertTrue(settled["was_overdue"])
        self.assertTrue(settled["terminal"])


class Controls(unittest.TestCase):

    def test_10_float_contamination_is_refused(self):
        # 0.05 XNO as a float is not 0.05 XNO.
        self.assertEqual(int(0.05 * 10**30), 50000000000000004512668450816)
        self.assertEqual(PRICE, 50000000000000000000000000000)
        self.assertNotEqual(int(0.05 * 10**30), PRICE)
        with self.assertRaises(cb.BindingError):
            cb.bound_amount(0.05 * 10**30, quote())
        with self.assertRaises(cb.BindingError):
            cb.derive_quote_id(b"\x01" * 32, resource="/a", price_raw=5e28, payto=PAYTO)
        with self.assertRaises(cb.BindingError):
            cb.tail_of_amount(5.0e28)

    def test_11_quote_id_is_rederivable_from_the_order_key_alone(self):
        # The property that makes a timeout recoverable at all.
        key = os.urandom(32)
        a = cb.derive_quote_id(key, resource="/audit", price_raw=PRICE, payto=PAYTO)
        self.assertEqual(a, cb.derive_quote_id(key, resource="/audit", price_raw=PRICE,
                                               payto=PAYTO))
        self.assertNotEqual(a, cb.derive_quote_id(os.urandom(32), resource="/audit",
                                                  price_raw=PRICE, payto=PAYTO))
        self.assertNotEqual(a, quote(key=key, resource="/other"))

    def test_12_weak_order_key_is_refused(self):
        with self.assertRaises(cb.BindingError) as caught:
            cb.derive_quote_id(b"short", resource="/a", price_raw=PRICE, payto=PAYTO)
        self.assertIn("16 bytes", str(caught.exception))

    def test_13_tail_round_trips_and_price_is_never_rounded_down(self):
        qid = quote()
        amt = cb.bound_amount(PRICE, qid)
        self.assertEqual(cb.tail_of_amount(amt), cb.amount_tail(qid))
        self.assertGreaterEqual(amt, PRICE)  # the seller is never paid less than it quoted

    def test_14_unattributed_payment_is_named_not_silently_kept(self):
        # "unmatched money is a support burden, not revenue" - so it gets its own verdict.
        led = cb.QuoteLedger(payto=PAYTO)
        out = credit(led, {"hash": "9" * 64,
                          "amount": str(7 * 10**27 + 123 * 10**15),
                          "local_timestamp": NOW})
        self.assertEqual(out["verdict"], cb.UNATTRIBUTED)

    def test_15_module_holds_no_key_and_opens_no_socket(self):
        """The check is over CODE, not prose: the docstring is allowed to say "no broadcast",
        but no executable line may name a socket, a signer or a key."""
        import io
        import tokenize

        src = Path(cb.__file__).read_text()
        code = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue  # drops comments and every docstring
            code.append(tok.string)
        code = " ".join(code)
        for forbidden in ("socket", "requests", "urllib", "http", "ed25519", "blake2b",
                          "private_key", "seed", "sign", "broadcast", "send"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertEqual(
            sorted(line.split()[1] for line in src.splitlines()
                   if line.startswith("import ")),
            ["hashlib", "hmac", "json"],
        )

    def test_16_malformed_block_is_an_error_not_a_verdict(self):
        led = cb.QuoteLedger(payto=PAYTO)
        with self.assertRaises(cb.BindingError):
            credit(led, {"hash": "0" * 64, "local_timestamp": NOW})  # no amount
        with self.assertRaises(cb.BindingError):
            credit(led, {"amount": "1", "local_timestamp": NOW})  # no hash, none passed either


class CreditOnlyFinalSendsToPayto(unittest.TestCase):
    """credit() must refuse anything that is not a confirmed send of exact integer raw to payto."""

    def setUp(self):
        self.led = cb.QuoteLedger(payto=PAYTO)
        self.qid = quote()
        self.rec = self.led.open_quote(self.qid, price_raw=PRICE, expires_at=NOW + 300)
        self.led.mark_delivered(self.qid)
        self.good = dict(FINAL, hash="B" * 64, amount=str(self.rec["expected_raw"]),
                         local_timestamp=str(NOW + 10))

    def assertNotCredited(self, block, verdict):
        out = self.led.credit(block)
        self.assertEqual(out["verdict"], verdict, out)
        self.assertNotIn(self.qid, self.led._credited)
        self.assertNotIn(block.get("hash"), self.led._blocks)
        # and the genuine payment is still creditable afterwards
        self.assertEqual(self.led.credit(self.good)["verdict"], cb.MATCHED)

    def test_17_genuine_node_reply_is_credited(self):
        for confirmed in ("true", True):
            led = cb.QuoteLedger(payto=PAYTO)
            rec = led.open_quote(self.qid, price_raw=PRICE, expires_at=NOW + 300)
            led.mark_delivered(self.qid)
            block = {"hash": "B" * 64, "amount": rec["expected_raw"], "local_timestamp": NOW + 10,
                     "confirmed": confirmed, "subtype": "send",
                     "contents": {"link_as_account": PAYTO}}
            self.assertEqual(led.credit(block)["verdict"], cb.MATCHED)

    def test_18_unconfirmed_is_not_credited(self):
        for confirmed in ("false", False, None, "True", 1):
            self.setUp()
            self.assertNotCredited(dict(self.good, confirmed=confirmed), cb.INCONCLUSIVE)
        self.setUp()
        block = dict(self.good)
        del block["confirmed"]
        self.assertNotCredited(block, cb.INCONCLUSIVE)

    def test_19_receive_or_missing_subtype_is_not_credited(self):
        for subtype in ("change", "epoch", None):
            self.setUp()
            self.assertNotCredited(dict(self.good, subtype=subtype), cb.REFUSABLE_NOT_PAYMENT)
        # a receive that nothing shows to be on payto is never credited (it may be on any account)
        for subtype in ("receive", "open"):
            self.setUp()
            self.assertNotCredited(dict(self.good, subtype=subtype), cb.INCONCLUSIVE)

    def test_20_other_destination_is_not_credited(self):
        other = "nano_1111111111111111111111111111111111111111111111111111hifc8npp"
        self.assertNotCredited(dict(self.good, link_as_account=other), cb.REFUSABLE_NOT_PAYMENT)
        self.setUp()
        block = dict(self.good, contents={"link_as_account": other})
        del block["link_as_account"]
        self.assertNotCredited(block, cb.REFUSABLE_NOT_PAYMENT)
        self.setUp()
        # contradictory top-level and contents destinations, or none at all
        self.assertNotCredited(dict(self.good, contents={"link_as_account": other}), cb.INCONCLUSIVE)
        self.setUp()
        block = dict(self.good)
        del block["link_as_account"]
        self.assertNotCredited(block, cb.INCONCLUSIVE)
        self.setUp()
        self.assertNotCredited(dict(block, contents="x"), cb.INCONCLUSIVE)

    def test_21_float_bool_or_non_numeric_amount_is_refused(self):
        exact = self.rec["expected_raw"]
        for amount in (float(exact), True, "abc", "1.5", "-1", str(exact) + ".0", "", None, [exact]):
            self.setUp()
            self.assertNotCredited(dict(self.good, amount=amount), cb.INCONCLUSIVE)

    def test_22_bad_timestamp_is_inconclusive_not_a_crash(self):
        for ts in ("abc", "1.5", 1.5, None, True):
            self.setUp()
            self.assertNotCredited(dict(self.good, local_timestamp=ts), cb.INCONCLUSIVE)

    def test_23_zero_or_missing_timestamp_is_inconclusive_not_on_time(self):
        for ts in (0, "0"):
            self.setUp()
            self.assertNotCredited(dict(self.good, local_timestamp=ts), cb.INCONCLUSIVE)
        self.setUp()
        block = dict(self.good)
        del block["local_timestamp"]
        self.assertNotCredited(block, cb.INCONCLUSIVE)

    def test_24_huge_digit_strings_are_inconclusive_not_a_crash(self):
        self.assertNotCredited(dict(self.good, amount="1" * 5000), cb.INCONCLUSIVE)
        self.setUp()
        self.assertNotCredited(dict(self.good, amount="1" * 41), cb.INCONCLUSIVE)
        self.setUp()
        self.assertNotCredited(dict(self.good, local_timestamp="1" * 5000), cb.INCONCLUSIVE)

    def test_25_hash_case_does_not_make_a_new_block(self):
        self.assertEqual(self.led.credit(self.good)["verdict"], cb.MATCHED)
        again = self.led.credit(dict(self.good, hash="b" * 64))
        self.assertEqual(again["verdict"], cb.MATCHED, again)
        self.assertTrue(again["replay"])
        self.assertEqual(again["block"], "B" * 64)

    def test_26_non_string_or_non_hex_hash_is_refused_not_a_crash(self):
        for bad in (["B" * 64], None, 5, "B" * 63, "Z" * 64, "B" * 65, {"h": 1}):
            self.setUp()
            out = self.led.credit(dict(self.good, hash=bad))
            self.assertEqual(out["verdict"], cb.INCONCLUSIVE, out)
            self.assertNotIn(self.qid, self.led._credited)
            self.assertEqual(self.led.credit(self.good)["verdict"], cb.MATCHED)

    def test_27_confirmed_is_true_or_the_string_true_only(self):
        for confirmed in ("TRUE", "yes", "1", 1.0):
            self.setUp()
            self.assertNotCredited(dict(self.good, confirmed=confirmed), cb.INCONCLUSIVE)


SENDER = "nano_1111111111111111111111111111111111111111111111111111hifc8npp"
OTHER = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"
PAYTO_KEY_HEX = "9D210035FA4CEFDA420232943006744E6BDF68DAD2A8640A86FFD3E109CCD77C"
SRC = "5" * 64  # hash of the buyer's send that a receive on payto pockets


class BothShapesOfAPayment(unittest.TestCase):
    """A payment is a send to payto, or payto's own receive of it. Both are credited, once."""

    def setUp(self):
        self.led = cb.QuoteLedger(payto=PAYTO)
        self.qid = quote()
        self.rec = self.led.open_quote(self.qid, price_raw=PRICE, expires_at=NOW + 300)
        self.led.mark_delivered(self.qid)
        self.amount = str(self.rec["expected_raw"])

    def history_receive(self, **kw):
        # account_history of payto (raw=false): "account" is the SENDER, not payto
        entry = {"type": "receive", "account": SENDER, "amount": self.amount,
                 "local_timestamp": str(NOW + 10), "height": "7", "hash": "A" * 64,
                 "confirmed": "true"}
        entry.update(kw)
        return entry

    def info_receive(self, **kw):
        # block_info of a receive on payto: no "hash" key, block_account is payto
        reply = {"block_account": PAYTO, "amount": self.amount, "local_timestamp": str(NOW + 10),
                 "confirmed": "true", "subtype": "receive",
                 "contents": {"type": "state", "account": PAYTO, "link": SRC,
                              "link_as_account": "nano_1ignored"}}
        reply.update(kw)
        return reply

    def assertNothingCredited(self, out, verdict):
        self.assertEqual(out["verdict"], verdict, out)
        self.assertNotIn(self.qid, self.led._credited)

    def test_28_receive_from_paytos_own_history_is_credited_when_caller_says_so(self):
        out = self.led.credit(self.history_receive(), account=PAYTO)
        self.assertEqual(out["verdict"], cb.MATCHED, out)
        self.assertEqual(out["quote_id"], self.qid)

    def test_29_history_receive_without_proof_it_is_on_payto_is_not_credited(self):
        self.assertNothingCredited(self.led.credit(self.history_receive()), cb.INCONCLUSIVE)
        # "account" in a raw=false history entry is the counterparty, never proof of payto
        self.assertNothingCredited(self.led.credit(self.history_receive(account=PAYTO)),
                                   cb.INCONCLUSIVE)
        self.assertNothingCredited(self.led.credit(self.history_receive(), account=OTHER),
                                   cb.REFUSABLE_NOT_PAYMENT)

    def test_30_block_info_receive_on_payto_uses_the_requested_hash(self):
        out = self.led.credit(self.info_receive(), block_hash="a" * 64)
        self.assertEqual(out["verdict"], cb.MATCHED, out)
        self.assertEqual(out["block"], "A" * 64)

    def test_31_receive_on_another_account_is_refused_even_if_caller_says_payto(self):
        reply = self.info_receive(block_account=OTHER,
                                  contents={"account": OTHER, "link": SRC})
        self.assertNothingCredited(self.led.credit(reply, block_hash="A" * 64, account=PAYTO),
                                   cb.REFUSABLE_NOT_PAYMENT)
        # block_account and contents.account disagree: cannot tell whose block it is
        reply = self.info_receive(contents={"account": OTHER, "link": SRC})
        self.assertNothingCredited(self.led.credit(reply, block_hash="A" * 64), cb.INCONCLUSIVE)

    def test_32_unconfirmed_or_non_integer_receive_is_not_credited(self):
        for confirmed in ("false", None, "True"):
            self.assertNothingCredited(
                self.led.credit(self.history_receive(confirmed=confirmed), account=PAYTO),
                cb.INCONCLUSIVE)
        for amount in ("1.5", 1.5, True, "1" * 5000):
            self.assertNothingCredited(
                self.led.credit(self.history_receive(amount=amount), account=PAYTO),
                cb.INCONCLUSIVE)

    def test_33_paytos_own_outgoing_transfer_is_never_credited(self):
        # account_history of payto, raw=false, a send OUT of payto: "account" is the destination
        entry = self.history_receive(type="send", account=OTHER)
        self.assertNotEqual(self.led.credit(entry, account=PAYTO)["verdict"], cb.MATCHED)
        self.assertNotIn(self.qid, self.led._credited)
        entry = self.history_receive(type="send", account=PAYTO)
        self.assertNotEqual(self.led.credit(entry, account=PAYTO)["verdict"], cb.MATCHED)
        self.assertNotIn(self.qid, self.led._credited)

    def test_34_raw_history_receive_on_payto_is_credited(self):
        entry = {"type": "state", "subtype": "receive", "account": PAYTO, "link": SRC,
                 "amount": self.amount, "local_timestamp": str(NOW + 10), "hash": "A" * 64,
                 "confirmed": "true"}
        self.assertEqual(self.led.credit(entry)["verdict"], cb.MATCHED)

    def test_35_raw_send_with_hex_link_only_is_decoded(self):
        entry = {"type": "state", "subtype": "send", "account": SENDER, "link": PAYTO_KEY_HEX,
                 "amount": self.amount, "local_timestamp": str(NOW + 10), "hash": "B" * 64,
                 "confirmed": "true"}
        self.assertEqual(self.led.credit(dict(entry, link="0" * 64))["verdict"],
                         cb.REFUSABLE_NOT_PAYMENT)
        self.assertEqual(self.led.credit(dict(entry, link_as_account=SENDER))["verdict"],
                         cb.INCONCLUSIVE)  # hex link and link_as_account disagree
        self.assertEqual(self.led.credit(dict(entry, link=PAYTO_KEY_HEX.lower()))["verdict"],
                         cb.MATCHED)

    def test_36_receive_proven_by_its_source_send(self):
        source = {"hash": SRC, "subtype": "send", "confirmed": "true", "amount": self.amount,
                  "local_timestamp": str(NOW + 5), "contents": {"link_as_account": PAYTO}}
        reply = self.info_receive()
        del reply["block_account"]
        del reply["contents"]["account"]
        for bad in (dict(source, contents={"link_as_account": OTHER}),
                    dict(source, confirmed="false"), dict(source, hash="6" * 64),
                    dict(source, amount="1"), dict(source, subtype="receive")):
            self.assertNotEqual(
                self.led.credit(reply, block_hash="A" * 64, source=bad)["verdict"], cb.MATCHED)
            self.assertNotIn(self.qid, self.led._credited)
        out = self.led.credit(reply, block_hash="A" * 64, source=source)
        self.assertEqual(out["verdict"], cb.MATCHED, out)

    def test_37_send_and_its_receive_are_one_payment_not_a_duplicate(self):
        send = dict(FINAL, hash=SRC, amount=self.amount, local_timestamp=str(NOW + 5))
        self.assertEqual(self.led.credit(send)["verdict"], cb.MATCHED)
        out = self.led.credit(self.info_receive(), block_hash="A" * 64)
        self.assertEqual(out["verdict"], cb.MATCHED, out)
        self.assertTrue(out["replay"])
        # a receive that does not say which send it pockets may be the same payment: never a
        # duplicate refund, never a second credit
        out = self.led.credit(self.history_receive(hash="C" * 64), account=PAYTO)
        self.assertEqual(out["verdict"], cb.INCONCLUSIVE, out)
        # a genuinely second send is still a duplicate
        out = self.led.credit(dict(send, hash="D" * 64))
        self.assertEqual(out["verdict"], cb.DUPLICATE_REFUND_DUE, out)

    def test_38_requested_hash_must_agree_with_the_reply(self):
        reply = self.info_receive(hash="A" * 64)
        self.assertNothingCredited(self.led.credit(reply, block_hash="C" * 64), cb.INCONCLUSIVE)
        self.assertNothingCredited(self.led.credit(self.info_receive(), block_hash=["A" * 64]),
                                   cb.INCONCLUSIVE)

    def test_39_xrb_prefix_names_the_same_account(self):
        block = dict(FINAL, hash="B" * 64, amount=self.amount, local_timestamp=str(NOW + 10),
                     link_as_account="xrb_" + PAYTO[5:])
        self.assertEqual(self.led.credit(block)["verdict"], cb.MATCHED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
