# Changelog

Nothing has been published to PyPI yet; the version stays 0.1.0 until the first release.

## Unreleased

Every change below refuses more than before or makes a documented feature work; none credits a
payment that was refused before, except the two named under "Now works".

### Security

- A payment could be credited twice: a `raw=false` receive was keyed by its own hash, so after its
  quote's tail was released a later quote holding the same tail (a buyer can grind a quote_id for
  any tail) could be credited with the buyer's send of the same payment. A receive is now keyed by
  the send it pockets and must name it (its `link`, or `source_hash=`); a receive that names no
  send is `inconclusive`. Every credited payment stays remembered for the life of the ledger.
- No lower bound on block time: a block dated before its quote existed was credited.
  `QuoteLedger.open_quote` stores `opened_at` (default: the ledger's `clock`, `time.time`;
  `QuoteService` passes `quoted_at`) and a block dated earlier is the new verdict
  `refusable_early`, never credited.
- A replay of someone else's payment returned `matched` carrying the victim's quote_id.
  `QuoteLedger.credit` and `QuoteService.settle` take `quote_id=`; a block that belongs, or would be
  attributed, to another quote returns the new verdict `refusable_other_quote` (without naming
  that quote).

### Now works

- `credit(source=)` with a real `block_info` reply (which has no `hash` key): pass
  `source_hash=` the send's hash. A hashless source without `source_hash=` stays `inconclusive`.
- `four_check.ledger` / `signature_check` and `finality_facts.facts` treat the legacy `xrb_`
  prefix as the same account as `nano_` (it was a wrong `fail`, never a false pass).

### Docs

- `BINDING-STANDARD.md` no longer says the claim "survives a restart": `QuoteLedger` is in memory
  and its replay protection holds only for the life of the object unless the caller persists it.
  The "same block claimed for another order" row now says `refusable_other_quote`.
- README and `QUOTE-SERVICE.md` describe `opened_at`, `source_hash=`, `quote_id=` and the two new
  verdicts.

### Tests

- `tests/test_attack_regressions.py`: the review-1114 attack scenarios (pre-quote payment, ground
  tail after release, replay for another quote, `source=` from real `block_info`), all now failing
  closed. Every node reply in the suite is mocked; nothing is signed or sent.
