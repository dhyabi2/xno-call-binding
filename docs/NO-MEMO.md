# Nano has no memo field: three ways to bind a payment to an order, and what each costs

A Nano state block carries: account, previous, representative, balance, link (destination for a send), work, signature.
There is **no memo, reference or note field**. The one free 32-byte slot is `representative`, and it is meant for voting.
A confirmed send proves that an amount reached an account; it does not say what for. So a seller must bind the order some other way.
(To Cutthroatclay, who asked for a "rail-side memo/representative field to commit to the same value": the representative field
can carry a commitment, see option 4 below, but it needs the buyer to sign a custom block and is the least supported.)

| Binding | How | Good | Bad |
|---|---|---|---|
| 1. Unique amount | order price plus a tiny tag in the low digits | no extra account, any wallet | two orders can collide; a payer can overpay into another order; amounts are visible and guessable; **fallback only** |
| 2. Per-order address (recommended) | seller derives one receive address per order from its own seed | no ambiguity; works with any wallet; replay of a block hash is useless | one account open per order (feeless, needs PoW); seller sweeps afterwards |
| 3. Signed pre-record | seller signs, and publishes before payment, a record `{ask_id, payTo, amount, artifact_hash, expiry}` | anyone can check the promise existed before the money moved; pairs with 2 | a record does not bind money by itself; it needs 1, 2 or 4 beneath it |
| 4. Representative commitment | buyer sets `representative` to an account encoding `SHA256(order|payTo|price)` | single fixed `payTo` is possible | buyer must sign a custom state block; wallets rarely expose the field |

Recommended stack: **2 + 3**, then verify with [four_check.py](../four_check.py). Reference code for 1, 2 and 4:
[`binding_options.py`](../binding_options.py); standard text: [BINDING-STANDARD.md](BINDING-STANDARD.md).

Related correction for anyone listening for events (april_cyberdeck): a confirmed `send` is already final; the payee's
`receive` block only pockets it, so do not wait for the receive. Do check amount and destination of that send; a hash alone proves nothing.
