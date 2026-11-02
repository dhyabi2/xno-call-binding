"""A /quote endpoint for sellers: a fixed-fiat price turned into an exact XNO amount, with an expiry.

Asked for by inkassat0r4 ("NANO floats, so a fixed-fiat micro-price needs an oracle or re-quoting") and
odin-slidphi (pay a quoted amount inside its validity window and be matched with no manual detective work).
It joins the two halves already in this repo: usd_quote.py (price in USD cents, median of two feeds, 60 s
window, refuses on one feed or a wide spread) and call_binding.py (an unordered per-order amount tail, one
block to one order, late and wrong-amount refusals on evidence).

    GET /quote?usd_cents=250&resource=/api/x&quote_id=<opaque hex>
    -> {usd_cents, price_micro_usd, base_amount_raw, amount_raw, tail, pay_to, quoted_at, expires_at,
        quote_id, refusals: {...}}      # amount_raw is the exact raw the buyer must send

Read-only and keyless: it quotes and it judges blocks someone else already sent (`settle`). It has no code
path that signs, sends or holds a key. The two price feeds are the only network use and are injectable.

quote_id is opaque and buyer-derived (`usd_quote_id`), so a timeout after paying is recoverable: the buyer
re-derives the id and the exact amount from its order key. A second open quote whose tail is already in flight
is refused (409) rather than hoped away.
"""
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import call_binding as cb
import usd_quote as uq

REFUSALS = {
    cb.REFUSABLE_LATE: "block confirmed after expires_at: refuse, refund the same raw amount to the sender",
    cb.REFUSABLE_WRONG_AMOUNT: "amount differs from amount_raw (even by 1 raw): refuse, refund the same raw amount",
    cb.DUPLICATE_REFUND_DUE: "a second exact payment for a quote already credited: refund within refund_window_s",
    cb.UNATTRIBUTED: "no open quote owns this tail: not credited to anyone",
}


def usd_quote_id(order_key: bytes, *, resource: str, usd_cents: int, payto: str) -> str:
    """The id a buyer derives BEFORE the amount is known (the raw price depends on the live feed)."""
    if not isinstance(usd_cents, int) or isinstance(usd_cents, bool) or usd_cents <= 0:
        raise cb.BindingError("usd_cents must be a positive int")
    return cb.derive_quote_id(order_key, resource="%s|usd_cents=%d" % (resource, usd_cents),
                              price_raw=usd_cents, payto=payto)


class QuoteService:
    def __init__(self, payto, feeds, clock=time.time, max_cents=10_000_00):
        self.payto, self.feeds, self.clock, self.max_cents = payto, feeds, clock, max_cents
        self.ledger = cb.QuoteLedger(payto=payto)
        self._usd = {}  # quote_id -> the quote dict, for the refund semantics

    def quote(self, usd_cents, quote_id):
        if not isinstance(quote_id, str) or not (32 <= len(quote_id) <= 128) or \
                any(c not in "0123456789abcdef" for c in quote_id):
            raise cb.BindingError("quote_id must be 32-128 lowercase hex characters, derived from your order key")
        if not isinstance(usd_cents, int) or isinstance(usd_cents, bool) or not (0 < usd_cents <= self.max_cents):
            raise cb.BindingError("usd_cents must be a positive int up to %d" % self.max_cents)
        self._sweep()
        if quote_id in self._usd:  # idempotent: the same buyer re-asking inside the window gets the SAME quote
            return dict(self._usd[quote_id])
        q = uq.quote(usd_cents, self.feeds, now=self.clock())
        rec = self.ledger.open_quote(quote_id, price_raw=int(q["amount_raw"]), expires_at=q["expires_at"])
        out = {"quote_id": quote_id, "usd_cents": usd_cents, "price_micro_usd": q["price_micro_usd"],
               "base_amount_raw": q["amount_raw"], "amount_raw": str(rec["expected_raw"]), "tail": rec["tail"],
               "pay_to": self.payto, "quoted_at": q["quoted_at"], "expires_at": q["expires_at"],
               "validity_s": uq.VALIDITY_S, "refusals": REFUSALS,
               "refund": "the same raw amount that was paid, never re-converted"}
        self._usd[quote_id] = out
        return dict(out)

    def settle(self, block):
        """Judge a block someone already sent: {hash, amount, local_timestamp}. Nothing is sent or signed."""
        return self.ledger.credit(block)

    def _sweep(self):
        """Release tails of quotes that expired unpaid, so the tail space does not fill up."""
        now = int(self.clock())
        for qid, q in list(self._usd.items()):
            if q["expires_at"] + cb.REFUND_WINDOW_S < now:
                self.ledger.close_quote(qid)
                del self._usd[qid]


def make_handler(service):
    class H(BaseHTTPRequestHandler):
        def _send(self, status, obj):
            body = json.dumps(obj, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path != "/quote":
                return self._send(404, {"error": "GET /quote?usd_cents=<int>&quote_id=<hex>"})
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                cents = int(q.get("usd_cents", ""))
                self._send(200, service.quote(cents, q.get("quote_id", "")))
            except (ValueError, cb.BindingError) as e:  # BindingError is a ValueError
                self._send(400, {"error": str(e)})
            except RuntimeError as e:  # fewer than two feeds, or they disagree: no quote
                self._send(503, {"error": str(e)})

        def log_message(self, *a):
            pass
    return H


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="quote_service")
    ap.add_argument("--pay-to", required=True)
    ap.add_argument("--port", type=int, default=8403)
    a = ap.parse_args(argv)
    svc = QuoteService(a.pay_to, [uq.feed_coingecko, uq.feed_kucoin])
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(svc)).serve_forever()


if __name__ == "__main__":
    main()
