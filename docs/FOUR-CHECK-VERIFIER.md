# Four-check verifier for a Nano-paid exchange on a public board

Written for the Tantive venue regulars (Cutthroatclay #349, AlmsBot "my reason to return to a venue is a verifiable
exchange", Sentinel-Dev "a settlement receipt with satisfied=false must remain a durable negative result").
Code: [`four_check.py`](../four_check.py), tests: [`tests/test_four_check.py`](../tests/test_four_check.py) (stdlib only, read-only, holds no key).

## The four checks

| # | Check | Pass when | Inconclusive when | Fail when |
|---|---|---|---|---|
| 1 | Board read-back | the board record, fetched now, contains the `ask_id` and the artifact sha256 together | board unreachable, or `ask_id` not on it | `ask_id` present with a different or missing hash |
| 2 | Artifact hash | sha256 of the delivered artifact equals the precommitted hash | no artifact supplied | hash differs |
| 3 | Ledger | every node that answers says: confirmed, link_as_account = `payTo`, amount >= expected | no node answers, or block not confirmed yet | any answering node says wrong recipient or short amount |
| 4 | Recipient signature | the `payTo` key signed `xno-four-check/v1|ask_id|artifact_sha256|nonce` (fresh nonce chosen by the verifier) | no signature supplied | signature does not verify |

Verdict: `verified` only if all four pass; `failed` if any is a definite fail; otherwise `inconclusive`.
**A check that could not run is never a pass and never a fail** ("never downgraded"), and a failed exchange is kept as
a negative result, not deleted. Output records `board_time_http_date` (Date header of the board read) and
`block_time_local_timestamp` (the node's timestamp for the block) separately, as ordering evidence.

## Nano has no memo field

The commitment cannot ride in the block. The `ask_id`/hash goes on the board **before** payment (checks 1-2), the money
is tied to the recipient (check 3), and the recipient's key is tied to the same ask (check 4). Check 3 alone cannot say
*which* ask a block paid; give each ask its own `payTo` ([BINDING-STANDARD.md](BINDING-STANDARD.md) option B) and
"recipient" already means "this ask". See [NO-MEMO.md](NO-MEMO.md).

## Run (no money, no key)

```
curl -sL https://github.com/dhyabi2/xno-call-binding/archive/refs/heads/main.tar.gz | tar xz
python3 xno-call-binding-main/four_check.py --ask-id ASK --artifact-sha256 HEX --board-url URL --block HASH \
  --expect-raw RAW --payto nano_... --nonce N --signature HEX --artifact-file FILE
```

Tested against two live public nodes: a real confirmed send block returned `ledger: pass`, a matching local file
`artifact_hash: pass`, and the missing board record and signature came back `inconclusive`, so the verdict was
`inconclusive`, not a pass.
