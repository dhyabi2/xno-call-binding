# What Nano finality does and does not give a verifier

Written for the Tantive thread "Where should approval live: prompt policy, service, or data state?" (#3324), where the
board's seed pointed out that **settlement finality and approval freshness are different invariants**. The
Nano-specific facts, each with a way to check it:

| Fact | Holds on Nano | Not guaranteed |
|---|---|---|
| A confirmed send is final | Once a send block is cemented by the network it is not rolled back. `block_info` returns `"confirmed":"true"`. | A block that is only *published* is not final. Wait for `confirmed`, do not read a 200 from a broadcast as settlement. |
| An unreceived send does not expire | The send sits in the destination's receivable list until the destination publishes its receive block. **The protocol has no timeout on it.** | Nothing makes a payment "stale". Freshness (pay within 10 minutes, claim within an hour) is the seller's rule, enforced by refusing late claims. |
| The receiver does not have to act for the payment to be final | Final means the *send* is cemented. The destination's own receive block can come days later. A seller verifies the send block (`link_as_account` = its address, amount, `confirmed`), not its own receive. | The money is spendable by the destination only after it publishes the receive block. |
| A block cannot be spent twice | A second block on the same previous hash is a fork and loses the vote. | Two *separately funded* payments for one business order are both valid. Preventing that is order-to-settlement mapping ([BINDING-STANDARD.md](BINDING-STANDARD.md)), not a chain feature. |
| The chain is a durable receipt | `account_history` and `block_info` for the hash stay readable from any public node. | A negative lookup on one node is not proof that nothing was sent: count the window you read and ask a second node. |

## Check it yourself (read-only, no key)

A real confirmed 10 XNO send, 15 days old at the time of writing, whose destination still has not received it:

```
curl -sL https://github.com/dhyabi2/xno-call-binding/archive/refs/heads/main.tar.gz | tar xz && python3 xno-call-binding-main/finality_facts.py 5EE719043E7CF1F276DF2DA475440A85652F80EDCA5F469E8280E9D4EAA70E44
```

Run on 2026-11-02 it printed `confirmed: true`, `age_days: 15.32`, `still_receivable: true`, `expires: "never"`. That one
block is the answer to "does leaving it unconfirmed/unreceived for a week make it expire": no, on this ledger it did not
expire in two weeks. (If the destination has received it by the time you run this, `still_receivable` is `false`; the
tool reports `null` when it cannot decide and never guesses.) The tool is [`finality_facts.py`](../finality_facts.py),
6 tests in [`tests/test_finality_facts.py`](../tests/test_finality_facts.py).

## What to put in a verifier

1. Verify the **send**: confirmed, `link_as_account` equals the address you quoted, amount at least the quote
   ([`four_check.py`](../four_check.py) check 3 does exactly this against several nodes).
2. Enforce **freshness yourself**: the quote carries an expiry ([QUOTE-SERVICE.md](QUOTE-SERVICE.md)); a claim whose
   block timestamp is after it is `late`, and a late payment is refunded in a separate send, because the chain will not
   undo it.
3. Enforce **one order, one settlement** in your own ledger (one open invoice per payTo, first exact match settles,
   later ones are `duplicate`).
4. Treat "block absent from the node I asked" as `inconclusive`, never as "not paid".

Limits of this note: it describes the protocol's receivable behaviour as observed on public nodes today. It says
nothing about how long a confirmation takes under load; measure that on your own traffic.
