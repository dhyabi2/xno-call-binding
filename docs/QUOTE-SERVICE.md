# /quote: fixed-fiat price in, exact XNO amount out, with an expiry

For sellers who price in dollars (inkassat0r4: "NANO floats, so a fixed-fiat micro-price needs an oracle or
re-quoting"; odin-slidphi: pay a quoted amount inside its validity window and be matched with no manual detective work).
`quote_service.py` joins `usd_quote.py` (two feeds, 60 s) and `call_binding.py` (amount tail, one block per order).

```sh
python3 quote_service.py --pay-to nano_YOURADDRESS --port 8403      # binds 127.0.0.1; put your own TLS in front
curl 'http://127.0.0.1:8403/quote?usd_cents=250&quote_id=<hex from usd_quote_id>'
```

```json
{"usd_cents": 250, "price_micro_usd": 319516, "base_amount_raw": "7824334305637276380525544886642",
 "amount_raw": "7824334306949121000000000000000", "tail": 949121, "pay_to": "nano_...",
 "quoted_at": 1793607693, "expires_at": 1793607753, "validity_s": 60, "quote_id": "...", "refusals": {...}}
```

- **Oracle.** Median of two independent feeds; no quote (503) if fewer than two answer or they differ by more than 2 percent.
  The blast radius of a wrong feed is one 60-second quote; settled payments and refunds are never re-priced.
- **Rounding.** Up, so the seller is never short; the tail adds under 1e-9 XNO.
- **Order tag.** `quote_id` is derived by the BUYER from an order key it holds (`usd_quote_id`), so a timeout after
  paying is recoverable: re-derive the id, ask again inside the window and get the **same** quote (idempotent). The tail is
  a PRF of the id, never a counter; a second open quote with a tail already in flight is refused, not hoped away.
- **Refusal semantics** (`QuoteService.settle`, the same verdicts as `call_binding`):

| arrives | verdict | what the seller does |
|---|---|---|
| exact `amount_raw`, block time <= `expires_at` | `matched` / `pending_delivery` | credit once, deliver |
| block time > `expires_at` | `refusable_late` (carries both timestamps) | refuse, refund the same raw amount |
| any other amount, even 1 raw off | `refusable_wrong_amount` (both amounts) | refuse, refund the same raw amount |
| a second exact payment for a credited quote | `duplicate_refund_due` | refund within `refund_window_s` of the duplicate's block time |
| tail owned by no open quote | `unattributed` | credit nobody |

- **Refund** is the same raw amount that was paid, never re-converted: no FX exposure after settlement either way.
- Read-only and keyless: it quotes and it judges blocks someone else sent. Tests: `tests/test_quote_service.py`.
