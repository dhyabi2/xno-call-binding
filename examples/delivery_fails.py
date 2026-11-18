#!/usr/bin/env python3
"""Settlement and delivery, judged separately: one quote, four cases, one JSON record each.

Run it: python3 examples/delivery_fails.py   (standard library only, offline, deterministic)

The quote binds the sha256 of the content the buyer is paying for: the hash is part of the
quoted `resource`, so it is inside the quote id the buyer re-derives from its order key. Each
record then has three sections that are checked independently of one another:

  binding     the quote id and the exact bound amount (pure arithmetic, buyer can redo it)
  settlement  what the payment block says (block_info in production) and the ledger's verdict
  delivery    sha256 of the bytes actually delivered, recomputed here, against the bound hash

Crediting never waits for mark_delivered: every payment is credited first, and the delivery
check runs afterwards over the delivered bytes. Only a delivery that passes is marked delivered.

`provenance` names, for every field, who it rests on:
  buyer-recomputed  the buyer computes it itself from bytes and keys it holds
  chain-read        read from a public Nano node's block in production; in THIS example the block
                    records are constructed fixtures, not node replies
  seller-supplied   only the seller's word
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from xno_call_binding import call_binding as cb  # noqa: E402

PAYTO = "nano_39b311tznm9hub316enn8159ammduxnfonoaei7afzymw66wsouw9q3j9ic1"
PRICE = 50 * 10**27                 # 0.05 XNO
OPENED = 1_762_000_000
EXPIRES = OPENED + 300
ORDER_KEY = b"\x11" * 32            # fixed so the output is deterministic; a buyer uses os.urandom(32)

# The content the quote is for (the cited text span), and an altered copy of it.
PROMISED = "Nano blocks carry no memo field, so a payment cannot name its order on-chain.".encode()
ALTERED = "Nano blocks carry a memo field, so a payment can name its order on-chain.".encode()
PROMISED_SHA256 = hashlib.sha256(PROMISED).hexdigest()
RESOURCE = "/evidence/span?sha256=" + PROMISED_SHA256

FIXTURE_NOTE = ("block records below are constructed fixtures, not node replies; "
                "in production each settlement field is read with block_info from a public Nano node")

B = "buyer-recomputed"
C = "chain-read"
S = "seller-supplied"
PROVENANCE = {
    "binding.resource": S,
    "binding.expected_sha256": S,
    "binding.quote_id": B,
    "binding.expected_raw": B,
    "settlement.block": C,
    "settlement.amount_raw": C,
    "settlement.local_timestamp": C,
    "settlement.confirmed": C,
    "settlement.destination": C,
    "settlement.exact_amount": B,
    "settlement.in_window": B,
    "settlement.ledger_verdict": B,
    "settlement.status": B,
    "delivery.delivered_bytes": S,
    "delivery.expected_sha256": S,
    "delivery.recomputed_sha256": B,
    "delivery.status": B,
    "entitlement.fulfilled": B,
    "entitlement.entitlements_granted": B,
    "entitlement.refund_due": B,
    "entitlement.refund_due_by": B,
    "entitlement.refunded": C,
}


def quote_id():
    return cb.derive_quote_id(ORDER_KEY, resource=RESOURCE, price_raw=PRICE, payto=PAYTO)


def block(hash_hex, amount_raw, at):
    """A constructed block_info-shaped record of a confirmed send to PAYTO (a fixture)."""
    return {"hash": hash_hex, "amount": str(amount_raw), "local_timestamp": str(at),
            "confirmed": "true", "subtype": "send", "link_as_account": PAYTO}


def check_delivery(expected_sha256, delivered):
    """Buyer-side check over the delivered UTF-8 bytes; independent of any payment."""
    if delivered is None:
        return None, "pending_delivery"
    got = hashlib.sha256(delivered).hexdigest()
    return got, ("delivered" if got == expected_sha256 else "failed")


def settlement_section(blk, verdict, expected_raw):
    amount = int(blk["amount"])
    at = int(blk["local_timestamp"])
    if verdict["verdict"] in (cb.PENDING_DELIVERY, cb.MATCHED) and not verdict.get("replay"):
        status = cb.MATCHED            # exact, in window, confirmed, first claim: credited
    else:
        status = verdict["verdict"]
    return {
        "block": blk["hash"],
        "amount_raw": blk["amount"],
        "local_timestamp": at,
        "confirmed": blk["confirmed"] == "true",
        "destination": blk["link_as_account"],
        "exact_amount": amount == expected_raw,
        "in_window": OPENED <= at <= EXPIRES,
        "ledger_verdict": verdict["verdict"],
        "status": status,
    }


def run_case(case, title, delivered, duplicate=False):
    qid = quote_id()
    led = cb.QuoteLedger(payto=PAYTO, clock=lambda: OPENED)
    rec = led.open_quote(qid, price_raw=PRICE, expires_at=EXPIRES, opened_at=OPENED)
    expected_raw = rec["expected_raw"]

    # Settlement first, with no mark_delivered beforehand.
    first_blk = block("A1" * 32, expected_raw, OPENED + 12)
    first = led.credit(first_blk, quote_id=qid)
    blk, verdict = first_blk, first
    if duplicate:
        blk = block("D4" * 32, expected_raw, OPENED + 60)
        verdict = led.credit(blk, quote_id=qid)

    # Delivery, judged on its own over the bytes the seller handed over.
    recomputed, dstatus = check_delivery(PROMISED_SHA256, delivered)
    if dstatus == "delivered":
        led.mark_delivered(qid)

    settlement = settlement_section(blk, verdict, expected_raw)
    credited_once = first["verdict"] in (cb.PENDING_DELIVERY, cb.MATCHED)
    if verdict["verdict"] == cb.DUPLICATE_REFUND_DUE:
        refund_due, refund_due_by = True, verdict["refund_due_by"]
    elif settlement["status"] == cb.MATCHED and dstatus == "failed":
        # paid, but the delivered content is not what was bound: owed back unless redelivered
        refund_due, refund_due_by = True, int(blk["local_timestamp"]) + led.refund_window_s
    else:
        refund_due, refund_due_by = False, None
    return {
        "case": case,
        "title": title,
        "block_records": "constructed fixture (offline), not a node reply",
        "binding": {
            "resource": RESOURCE,
            "expected_sha256": PROMISED_SHA256,
            "quote_id": qid,
            "expected_raw": str(expected_raw),
        },
        "settlement": settlement,
        "delivery": {
            "delivered_bytes": None if delivered is None else len(delivered),
            "expected_sha256": PROMISED_SHA256,
            "recomputed_sha256": recomputed,
            "status": dstatus,
        },
        "entitlement": {
            # the one order is fulfilled only if paid once AND the bound content was delivered
            "fulfilled": credited_once and dstatus == "delivered",
            "entitlements_granted": 1 if credited_once else 0,
            "refund_due": refund_due,
            "refund_due_by": refund_due_by,
            "refunded": False,         # true only once a refund block is read from the chain
        },
        "provenance": PROVENANCE,
    }


CASES = [
    ("A", "payment matches, delivered content fails its hash", ALTERED, False),
    ("B", "payment matches, no content delivered", None, False),
    ("C", "payment matches, content hash matches", PROMISED, False),
    ("D", "duplicate exact payment after a matched, delivered one", PROMISED, True),
]


def records():
    return [run_case(*c) for c in CASES]


def main():
    print("delivery_fails: 1 quote, 4 cases; settlement and delivery judged separately")
    print("note:", FIXTURE_NOTE)
    for r in records():
        print(json.dumps(r, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
