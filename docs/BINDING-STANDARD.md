# Nano payment-to-order binding standard (v1)

A Nano block has no memo. A confirmed send proves that an amount reached an account and nothing
about which order it paid for. A seller needs three guarantees before it releases a response:

1. **Bound** - the block belongs to exactly one issued order, and to the party that asked.
2. **Single-use** - one block credits one order once, and the claim survives a restart.
3. **Recoverable** - a lost response, a late payment or a duplicate has a defined outcome.

This document gives three ways to bind, ranks them, and says which one to ship. Reference
helpers and test vectors: `binding_options.py`, `tests/test_options.py` (stdlib only, no key).

## Recommendation

| Rank | Option | Use it when |
|---|---|---|
| **1 (recommended)** | **B. Per-order invoice account** | the seller controls a wallet seed (it must, to receive) and can derive accounts by index |
| 2 | **C. Order commitment in the representative field** | a single fixed payTo is required and the buyer can sign custom state blocks |
| 3 (fallback only) | **A. Unique-amount tag** | no other option is possible; never as the only key (flaws below) |

Whatever option is used, the **seller ledger rules** at the end are mandatory.

## Option B - one invoice account per order (recommended)

1. Seller derives `index = HMAC-SHA256(master_secret, "xno-binding/v1/invoice|" + order_id)[:4]`
   (`binding_options.invoice_index`) and derives the account at that index from its own wallet.
   `order_id` is **opaque and random** (>= 128 bits), never a counter.
2. The 402 / quote returns that account as `payTo` and the exact price in raw.
3. Any receive on that account is for that order, by construction. A block cannot be credited to
   a different order because it was never sent to a different account. Amount collisions between
   concurrent orders are impossible; the sequence of orders is not visible in amounts or in
   account order.
4. After settlement the seller sweeps the funds to its treasury. The seller's own key does the
   sweep; the buyer needs nothing new.
5. Bind the requester: the order id doubles as the claim secret. A retry for a lost response
   must present `order_id`; a block hash alone is never accepted as the proof (block hashes are
   public and anyone can replay somebody else's).

Costs: one account open per order (feeless; needs the seller's PoW), and the receive minimum
applies. Accounts of expired unpaid orders are simply never used again; if funds arrive late the
verdict is `refusable_late` and the refund goes back to the sender shown in the block.

## Option C - order commitment in the representative field

A Nano state block carries a `representative`. A send block may set it to any 32-byte value.

1. `commitment = SHA256("xno-binding/v1/rep|" + order_id + "|" + payTo + "|" + price_raw)`
   (`binding_options.order_commitment`), encoded as a `nano_` account
   (`commitment_rep_account`).
2. Buyer signs a send block of exactly `price_raw` to `payTo` with `representative = that account`.
3. Seller reads `block_info` on any public node: it checks `contents.link_as_account == payTo`,
   `amount == price_raw`, `contents.representative == commitment_rep_account(...)`, and then
   claims the block hash in its ledger.

The commitment is signed by the buyer and covers order, destination and price, so the block binds
to the order with no amount games. Caveats: the buyer's own voting weight points at a non-existent
representative until it sends a `change` block (wallets must expose the field), and the check is
only as good as `block_info` of a confirmed block, so wait for confirmation.

## Option A - unique-amount tag (fallback only)

Low-order raw digits of the amount carry a per-order tag (`binding_options.tagged_amount`; the
helper rounds the price up to a tag unit so the seller is never short). **Do not use the tag as the
primary key.** Flaws, each demonstrated by reviewers of live code:

- **Collisions.** Tags are short (say 6 digits). Two concurrent orders for the same price can
  draw the same tag; the second payment matches the first order. A seller must refuse to open a
  second quote with a tag already in flight, and still cannot protect a buyer who pays an
  amount for a sibling order.
- **No one-to-one assignment.** If the verdict is "an unclaimed confirmed block of the right amount
  exists", two sends of the same amount are both "right"; one payment can be credited to two
  orders, or two payments to one. The unit of record must be `block hash -> order`, not amount.
- **Ordering leak.** A tag derived from a counter or a timestamp (or monotone in creation order)
  publishes the seller's order sequence and volume on a public ledger. Tags must be a PRF of an
  opaque id.
- **Not bound to the requester.** Anyone who sees the amount on the ledger can present the same
  block hash for a different request unless the proof also needs the order secret.
- **In-memory replay set.** The claim set must be persistent with a window; a restart that
  forgets claims lets every old block be replayed.

If A is the only choice: random (not sequential) tag, tag-in-flight refusal, `order_id -> block
hash` recorded at settle time with a UNIQUE constraint on the block hash, and the order secret
required on the retry.

## Seller ledger rules (mandatory, all options)

`binding_options.Ledger` is a reference (sqlite, `block_hash` PRIMARY KEY, UNIQUE `order_id`).

| Case | Verdict | Rule |
|---|---|---|
| Right order, right amount, block time <= expiry | `matched` | record `block_hash -> order_id` once |
| Same block read again for the same order | `matched` | idempotent, no second credit |
| Second block for an order already credited | `duplicate_refund_due` | refund the later block to its sender, never credit |
| Same block claimed for another order | `duplicate_refund_due` | refused; claim stays with the first |
| Block time after `expires_at` | `refusable_late` | refund; evidence is both timestamps |
| Amount != expected raw (short or over) | `refusable_wrong_amount` | refund; evidence is expected and paid |
| Confirmed but response not delivered | `pending_delivery` | keep distinct from "unpaid"; retry with `order_id` |

Always: integer raw only (`1 XNO = 10**30`; refuse floats), use the **block's** time for window
checks, wait for confirmation, bound node lookups (timeout, response size), and refuse plain-HTTP
non-loopback RPC endpoints.

## Test vectors

All reproducible with `python3 -c` against `binding_options.py`.

```
payTo (all-zero key, burn account)  nano_1111111111111111111111111111111111111111111111111111hifc8npp
price_raw                           50000000000000000000000000000   (0.05 XNO)
order_id                            order-0001

Option C  order_commitment(...).hex()
  86e75a339b908cc926a478c1a0e5eb5dd6fc612c1d3251eb661faa78135c36cf
Option C  commitment_rep_account(...)
  nano_iumonewuk48ekbo6h51t3shddqdhrrbe5ns75tu85yo9i6tw8u9igehj4ozj

Option B  invoice_index(master_secret = 0x01 * 32, order_id)
  order-0001 -> 1000236334
  order-0002 -> 1553440120

Option A  tagged_amount(price_raw, "order-0001", secret = 0x02 * 32)   (fallback only)
  50798831000000000000000000000
```

Refusal vectors are in `tests/test_options.py::test_ledger_one_to_one` (late, wrong amount,
duplicate, idempotent re-read) and `test_ledger_persists_across_restart`.
