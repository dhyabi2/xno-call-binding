# Pull-style payment authorization for Nano: a buyer-signed block bound to a quote

**The objection** (hermesinvinoveritas, a production x402 equities API): "Nano has no smart-contract authorization
surface ... pull-shaped EIP-3009 puts signing duty on her middleware, a sender-pushed XNO send puts the ed25519
signature duty on the BUYER key."

**The answer.** A Nano state block is already a signed authorization, and the proof-of-work on it is *not covered by
the signature*. So the buyer signs, offline and ahead of time, the exact send it is willing to be pulled for. The
seller's middleware never holds a key: it checks the block, adds PoW, and broadcasts. The signing duty stays with
the buyer, as it must; what the middleware gets is the EIP-3009 shape (a signed authorization it can submit).

## The pre-signed block

| field | value |
|---|---|
| `account` | the buyer |
| `previous` | the buyer's **current frontier** |
| `representative` | `commitment_rep_account(order_id, pay_to, amount_raw)` (Option C, `BINDING-STANDARD.md`): the quote is inside the signed bytes |
| `balance` | previous balance minus `amount_raw` |
| `link` | `pay_to`'s public key |
| `signature` | buyer's, over the block hash |
| `work` | absent |

Wire format (what the buyer sends with the request, in place of an `X-PAYMENT` header):

```json
{"v": "xno-presigned-send/v1", "quote_id": "...", "order_id": "...", "pay_to": "nano_...",
 "amount_raw": "7824334306949121000000000000000", "expires_at": 1793607753, "block": { ...state block, no work... }}
```

## What the middleware does (`presigned_send.check_presigned`)

1. Recompute the block hash; verify the signature under the buyer account. Fails: **refuse**.
2. `link` is `pay_to`; `representative` equals the commitment for this order, destination and amount. Fails: **refuse**.
3. Buyer's `account_info` (fetched by the middleware): `balance - block.balance == amount_raw`. Fails: **refuse**.
4. `previous == frontier`. Fails: **stale_frontier** (the buyer's chain moved; not a forgery; the buyer re-signs).
5. `now <= expires_at`. Fails: **expired** (do not broadcast).
6. Otherwise **ready**: the verdict carries the `process` request body. The middleware adds `work` (`work_generate` on
   the block hash; no key involved) and POSTs it, then waits for confirmation and calls `credit` as usual.

It judges only. It has no signing function, no broadcast function and imports only `hashlib`. The hash and
signature code is tested against a real mainnet block (`B749B757...`): it reproduces the chain's own hash and accepts
its signature, and rejects a signature with one bit flipped.

## Honest limits (read these before relying on it)

- **Stale on any other send.** A pre-signed block is valid only while `previous` is the buyer's frontier. Any other
  block on the buyer's chain invalidates it. One outstanding pre-signed send per account per frontier; two quotes
  signed at the same frontier are a fork and only one can confirm. A buyer that pays many sellers needs a separate
  account per purpose (see `nano-wallet-xno/docs/SPEND-WINDOW-ACCOUNT.md`).
- **The block does not expire by itself.** `expires_at` is the *middleware's* promise not to broadcast after it. A leaked
  block stays valid until the buyer's frontier moves. It can only pay `pay_to` the exact amount (any change breaks the
  signature), so the exposure is paying early, not theft; the buyer revokes by publishing any block on its own chain.
- **Delivery.** Broadcasting before delivery is the seller's choice; deliver after confirmation, and a pre-signed block
  gives the seller no way to take the money without the service being expected.
- **Fork race.** Two parties can broadcast different blocks on the same `previous` (the buyer pays elsewhere while the
  seller holds the pre-signed one). Whichever confirms first wins; the loser is a stale block. Wait for confirmation.
- **Not a pull from a balance.** There is no allowance: the money moves only when this one block is processed.

## Comparison with EIP-3009 `transferWithAuthorization`

| | EIP-3009 | pre-signed Nano send |
|---|---|---|
| who signs | buyer (EIP-712) | buyer (ed25519/BLAKE2b, the block itself) |
| who pays gas | middleware | nobody: feeless; middleware pays PoW CPU |
| replay protection | random nonce | the chain: one `previous`, one successor |
| expiry | `validBefore` in the signed data | not in the block: middleware-enforced (above) |
| bound to the quote | in the typed data | in the `representative` commitment |
| reusable allowance | no | no |

Run: `python3 -W ignore -m unittest tests.test_presigned_send`.
