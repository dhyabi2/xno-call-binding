# Nano in an AP2 PaymentMandate

A merchant agent that speaks AP2 (IntentMandate -> CartMandate -> PaymentMandate) and demands a PaymentMandate can be paid in XNO if its cart offers a Nano method. Field mapping, read from `ap2/models/mandate.py` and `payment_request.py`:

| AP2 field | Nano value |
|---|---|
| `PaymentRequest.method_data[].supported_methods` | `https://www.x402.org/` (same id x402 already uses) |
| `method_data[].data` | `{x402Version:2, scheme:"exact", network:"nano:mainnet", asset:"XNO", payTo:"nano_...", amount:"<integer raw>", settlement:"block_hash"}` (see `examples/ap2_nano_payment_method.py`) |
| `PaymentMandateContents.payment_response.method_name` | same `https://www.x402.org/` |
| `payment_response.details` | `{accepted: <the method data above>, payload: {block_hash: "<64 hex>"}, settlement: {...}}` |
| `payment_details_total.amount` | `{currency:"XNO", value:<float>}`, display only: AP2 uses a float, XNO needs 30 digits, so the exact amount is the integer-raw string in `accepted.amount` |
| `user_authorization` | not forged here; AP2 expects an SD-JWT from the user's credential provider. Null in a draft |

Merchant side: re-read the block by `block_hash` from a public node and check the recipient is `payTo` and the amount equals `accepted.amount` (`nano-settlement-verify`). Bind it to the order with `call_binding.py`; a block carries no memo.

Honest limit: the superpa.ge test cart is $1 USDC on arc-testnet. A Nano PaymentMandate is only valid against a cart whose `method_data` lists `nano:mainnet`. This tool builds the mandate; it cannot make that merchant list Nano.

Try (no key, no network): `python3 ap2_nano_mandate.py --merchant example --pay-to nano_3aysuejus8iy1hhw6doc7syzg1aaa6hgpec91xcc36mf6hp6thy7u6ymkgfm --raw 100000000000000000000000000` prints an UNPAID DRAFT; add `--block-hash <64hex>` from a payment you made yourself (nano-pay402) for a paid one. `--check file.json` validates any mandate.
