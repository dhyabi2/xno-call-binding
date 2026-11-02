# USD-pegged, settle-at-quote pricing for XNO

Objection (DeskCrew, kevinautomaton): bounties, credits and prices are dollar-denominated, so
paying in a floating asset moves pricing, refunds and revenue splits, and an exchange-rate oracle
is a new trust boundary.

Answer: the price never floats. Exposure to the rate lasts only for the quote window.

1. **Price fixed in USD cents** (an integer). Catalogue, bounty and split math stay in USD.
2. **Quote at request time.** The seller turns cents into raw XNO from the median of **two
   independent public feeds** (`usd_quote.py` uses CoinGecko and KuCoin; any two will do). It
   refuses to quote if fewer than two feeds answer or they differ by more than 2%.
   The conversion rounds **up**, so the seller is never short.
3. **60-second validity.** The quote carries `quoted_at` and `expires_at = quoted_at + 60`.
   A payment whose block time is after `expires_at` is `refusable_late`; one for a different raw
   amount is `refusable_wrong_amount`. Bind the quote to the payment with the order account in
   `BINDING-STANDARD.md` (Option B).
4. **Settle at the quote.** The payment settles at the quoted rate. The seller records
   `usd_cents`, `price_micro_usd` and `amount_raw`; revenue splits (for example 85/15) are
   computed from USD cents, not from the XNO later on.
5. **Refund = the same raw amount returned.** No conversion at refund time, so neither side has
   FX exposure after settlement: the buyer gets back exactly what it sent (a refund is itself a
   feeless send).
6. **The oracle's blast radius is one quote.** A wrong feed can mis-price a single 60 s quote; it
   cannot change a settled payment, a refund, or any earlier order. The two-feed median and the
   spread refusal bound even that.

Run it: `python3 usd_quote.py 250` quotes $2.50 live (read-only, two HTTPS GETs). Measured on
2026-11-02: feeds 0.324708 and 0.32 USD/XNO, median 0.322354, `amount_raw`
7755448978452260558268239264908 (about 7.755 XNO). Offline tests: `tests/test_usd_quote.py`.

Stable-value holders who never want XNO exposure at all can convert the received XNO to a
stablecoin the same minute; that is a treasury choice, independent of the quote.
