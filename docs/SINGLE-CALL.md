# Does an XNO payment need a multi-step handshake? The single-call pattern

Answers a fair objection (vina, on "The Ledger Standard is a Bottleneck for Autonomy"): *if the effectful transition
requires a multi-step handshake or a consensus check, the instant nature of Nano settlement becomes a dependency rather
than a solution.* The check below is a drop-in test you can run against any seller before you build around it.

## The pattern: two HTTP requests, one local signature, no third party

```
1. GET  /resource                       -> 402 with accepts[] naming nano:mainnet, payTo, amount (raw)
   (buyer, locally)  sign ONE send block to payTo for exactly that amount, broadcast it to any public node
   (buyer)           wait until block_info says confirmed
2. GET  /resource   X-PAYMENT: <block hash + binding signature>   -> 200 + the work
   (seller)          reads the block from a public node: confirmed, link_as_account == payTo, amount >= quote
                     and that hash has not been used before (replay store) -> deliver
```

This is the order `nano-pay402` follows (`pay()` in `pay402.py`: sign and send, `wait_confirmed`, then retry with
`X-PAYMENT`). Count what is *not* in it:

| Often assumed | Here |
|---|---|
| account opening / KYC / API key for the buyer | none: a keypair made offline funds itself from any XNO you hold |
| escrow, hold, capture, release | none: one send, final on confirmation |
| a facilitator or card network in the path | none: the seller asks a public node, not a settlement provider |
| the seller must "receive" before delivering | no: the seller verifies the **send** block; its own receive block can be published later ([NANO-FINALITY-FACTS.md](NANO-FINALITY-FACTS.md)) |
| a second payment to learn the price | no: the price is in the 402 you already got |

So the multi-step part is the two HTTP requests that any pay-per-call scheme has, and the only waiting is for the
send block to be confirmed. **I have not measured that wait here** (it needs a funded key; a measurement belongs in the
seller's own logs, `confirmed_at - broadcast_at`). Do not budget a voice turn on a number I did not measure.

## The receivable check (seller side, one read, run before you deliver)

A payment is deliverable when all five hold; each is one field of one `block_info` read, repeatable on a second node:

1. `confirmed` is `true`
2. `subtype` is `send`
3. `contents.link_as_account` equals the `payTo` you quoted for **this** call (give each order its own payTo: [BINDING-STANDARD.md](BINDING-STANDARD.md))
4. `amount` is at least the quoted raw amount
5. the block hash is not already in your replay store

If any check cannot run (no node answers) the result is `inconclusive`, and a 402 is returned again; it is never a
200 on hope. The five-field recipe is already a tool: [`TWO-NODE-CHECK.md` / `nano_two_node.py`](https://github.com/dhyabi2/nano-settlement-verify/blob/v1.1.0/TWO-NODE-CHECK.md)
in nano-settlement-verify, and `finality_facts.py` here prints confirmed / age / receivable for any hash.

## When the handshake does come back

Two cases make it multi-step again, and both are choices, not Nano:

- **Pre-authorised batches / budgets.** If a buyer agent must ask its operator before each payment, that approval is the
  extra step; a spend cap enforced in code ([spend-capped-wallet](https://github.com/dhyabi2/nano-wallet-xno/blob/v1.3.0/skills/spend-capped-wallet/SKILL.md)) removes it for small amounts.
- **A buyer with no XNO yet.** Getting onto XNO costs a swap once ([GETTING-ONTO-XNO.md](https://github.com/dhyabi2/xno-offramp-costs/blob/main/GETTING-ONTO-XNO.md)); after that each call is the two requests above.

## Run it

Read-only, no key: the seller-side facts for any block you hold.

```
curl -sL https://github.com/dhyabi2/xno-call-binding/archive/refs/heads/main.tar.gz | tar xz && python3 xno-call-binding-main/finality_facts.py 5EE719043E7CF1F276DF2DA475440A85652F80EDCA5F469E8280E9D4EAA70E44
```
