# State-Constraint Alpha — empirical results, 2026-08-29

## Bottom line

**The generic thesis is not validated as a profitable strategy.**

Public cumulative state + finite remaining opportunity is useful information, but the evidence so far says Polymarket usually incorporates the easy constraint quickly enough that the constraint itself is **not alpha**.

Do not build a production bot from this framework now.

The only surviving research version requires a **second inefficiency** in addition to state constraint: resolver opacity, non-obvious weighting, fragmented source data, measurable reporting/repricing lag, or another reason the crowd should systematically mis-map state to payout probability.

---

## 1. Deterministic finite-opportunity lock — NBA win totals

Tested the strongest possible version first: once remaining games make OVER/UNDER mathematically certain, look for stale Polymarket value.

Reconstruction:
- 30 team markets
- 1,230 regular-season games
- every team reconciled to 82 games
- 30 deterministic states reached

Historical stale-price audit:
- +10 minutes: zero opportunities below 98c
- +30 minutes: zero
- +2 hours: zero
- +6 hours: zero

**Verdict: killed.** The obvious deterministic state lock was repriced efficiently in this sample.

---

## 2. Opening-weekend box office — probabilistic state constraint

This was the best broad historical substrate because the family is large and liquid:
- 56 discovered events
- 54 resolved/closed
- about $59.1M aggregate historical volume

The chronological box-office model did not produce useful profitability.

Recovered historical result:
- simple range model: 8 signals, 5 correct, 7 with an observed entry
- at the executable subset used in the prior audit: 3 trades, 1 win / 2 losses
- equal-$100 PnL: approximately **-$173.19**
- ROI on deployed capital: approximately **-57.7%**

A front-loading refinement only reduced mean absolute weekend forecast error from about **3.57% to 3.41%**. That is far too small to rescue the economics and is not justification for model tuning.

**Verdict: killed in its current form.** Do not spend more research budget optimizing this version.

---

## 3. YouTube public-view trajectories — strongest state signal, weak economics

### Dataset

Expanded inventory:
- 196 view-related events discovered
- 188 closed
- about $117.76M aggregate volume
- 83 events with an exact YouTube video ID in source/rules
- 27 exact-video groups
- 15 exact-video groups with multiple horizons
- 68 events inside those multi-horizon groups

Strict identity rules were necessary. Exact video ID alone was not trusted when Polymarket text showed a copied/reused URL with a different explicit video title. One same-video group with mutually incompatible day-3 resolved brackets was rejected rather than repaired.

Clean transition backtest:
- 14 usable exact-ID + explicit-title groups
- 1 rejected conflicting group
- 38 resolved transition observations

### Conservative tail-exclusion model

Method:
- use only an already-resolved earlier horizon from the exact same video;
- train transition-ratio envelopes only on other videos whose target horizons had resolved before the decision;
- minimum 3 prior videos for the full-support envelope;
- signal only a target bracket completely outside the historical forecast envelope;
- evaluate NO, not a point forecast;
- current Culture taker-fee coefficient 0.05 applied as forward-cost stress.

Signal result:
- 20 conservative tail-bracket signals
- 11 target horizon-events
- 5 independent target videos
- **0 signaled brackets won**

So the state model did identify losing tails correctly in this small chronological sample.

### But profitability is the problem

Strict execution audit:
- first-fill search limited to <=120 minutes after the decision;
- trade must remain >=6 hours before target market close/resolution as an anti-hindsight guard;
- 10 stale/late raw fill slots rejected.

At forward all-in cost caps:
- <=80c: **0** qualifying opportunities
- <=85c: **0**
- <=90c: **0**
- <=95c: **1**

The single <=95c case:
- video: `Which Stranger Would You Chain Yourself To For $250,000?`
- transition: day 6 -> week 1
- signal: NO on `60M+`
- observed taker BUY price: 92c
- stressed all-in cost: about **92.37c**
- observed size: **66.66 shares**, about **$61.33** notional
- result: win
- theoretical equal-$100 ROI at that price: about **+8.26%**

That is **one tiny executable event**. It is not evidence of repeatable alpha and capacity was trivial in the observed print.

The tighter q10/q90 version had:
- 7 signals
- 4 target events
- 3 videos
- 0 signal mistakes
- **zero** observed opportunities <=95c in the strict two-hour audit.

### Central-bin / velocity-decay model

Before adding price complexity, tested a simple chronological model:

`next_increment = previous_increment * median(prior-video decay)`

Minimum 3 prior independent training videos, exact consecutive 24h horizons.

Result:
- 11 OOS predictions
- 4 independent target videos
- exact winning-bracket hits: **3/11 = 27.3%**
- mean distance to winning interval when accounting for hits: about **0.51M views**
- median distance: about **0.47M**

The trajectories are predictable to roughly the neighborhood, but not accurately enough for the narrow strike bins.

**Verdict:**
- tail exclusion is mechanically useful;
- Polymarket already prices almost all of it near certainty;
- the only economically interesting historical print is one small case;
- central-bin forecasting is not strong enough to justify price backtesting or model tuning.

Do not promote this family.

---

## 4. Spotify monthly markets do not create the missing validation sample

The apparent repeated 2026 monthly `Top Spotify artist` family is **not the same mechanism** as annual Wrapped most-streamed-artist markets.

Monthly rules resolve on the artist with the highest public **monthly-listener count at a specified timestamp**. That metric can rise and fall and is a snapshot, not a monotone cumulative stream total.

Therefore February/March/April/etc. cannot be counted as independent historical repetitions of the annual Spotify state-constraint thesis.

Annual Spotify remains an isolated/small-N family with resolver-weighting uncertainty. It may still be an individual trade candidate, but a win cannot validate a general strategy.

---

## Cross-family evidence

| Family | Independent evidence | State model | Executable economics | Status |
|---|---:|---|---|---|
| NBA deterministic win-total locks | 30 team markets | Exact deterministic | No stale value <98c | **Killed** |
| Opening-weekend box office | 25 OOS in prior model / 56-family universe | Forecast weak/moderate | Materially negative tested PnL | **Killed** |
| YouTube multi-horizon views | 5 OOS target videos in priced tail test | Tail exclusion strong | One ~$61 print <95c; none <90c | **Not profitable evidence** |
| Spotify annual artist | ~one relevant current case + very few years | Potentially strong but resolver-weight uncertain | Current market can have edge if weighted state is proven | **Individual research only** |

The evidence does **not** support the broad statement:

> finite-horizon cumulative markets are systematically underpriced by Polymarket.

It supports a narrower statement:

> finite-horizon cumulative state can generate high-confidence probability information, but profit exists only if some additional market inefficiency prevents that information from already being embedded in executable prices.

---

## Research decision

### Kill

Do not build:
- generic deterministic-lock scanner;
- generic cumulative-count bot;
- YouTube central-bin predictor;
- more box-office tuning;
- large Monte Carlo/ML framework around this thesis.

### Preserve

Keep the generic state-constraint code as a **screening primitive**, not a strategy. It can cheaply answer:
- what outcomes are mechanically impossible or extremely implausible?
- what catch-up is required?
- is Polymarket charging almost $1 already, or is there actually room for EV?

### Only reopen a family when there is a second mechanism

Examples worth investigation only if repeated history exists:
1. **Resolver/model opacity** — public raw state is easy, but payout scoring/weighting is non-obvious and can be reconstructed better than market participants.
2. **Fragmented state** — decisive cumulative information requires combining several public sources and Polymarket appears to lag the aggregation.
3. **Measurable source-to-price latency** — repeated historical evidence that a source update remains tradeable for long enough after realistic execution costs.
4. **Structural cross-market inconsistency** — multiple contracts encode mutually constraining cumulative states and executable prices violate those constraints.

The burden is now higher: **state constraint alone is not a reason to research a market further.** There must be a plausible second source of mispricing and enough independent events to test it.

## Current recommendation

**No capital and no production build from the generalized thesis.**

Spotify/Bad Bunny can remain a separate one-trade research candidate if resolver-aligned weighting is proven, but it must not be presented as validation of `state-constraint alpha`.
