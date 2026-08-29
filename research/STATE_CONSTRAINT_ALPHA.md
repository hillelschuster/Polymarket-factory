# State-Constraint Alpha — general Polymarket thesis

## Objective

Find a **repeatable** Polymarket edge in markets whose final outcome is increasingly constrained by a public, cumulative state and a finite amount of remaining opportunity.

Spotify 2026 is only one example. It is not evidence of alpha by itself.

The strategy is valid only if one fixed framework produces positive net expectancy across many distinct event groups, ideally across multiple domains.

## Qualifying market definition

A market belongs in this research universe only when all of the following are true:

1. **Observable state** — the decisive variable can be observed from an external public source before resolution.
2. **Finite horizon** — the final time or remaining opportunities are known or tightly bounded.
3. **State constraint** — current state mechanically restricts the possible final outcomes. Prefer monotone counts that cannot decrease.
4. **Objective resolver** — the resolution rule maps cleanly to the measured state.
5. **Repeatability** — the market type occurs repeatedly, or the same generic model applies to many independent events.
6. **Executable prices** — historical/current CLOB data are available enough to evaluate asks, fees, slippage and capacity.

Exclude ordinary elections/news markets where uncertainty merely declines with time but there is no measurable cumulative state.

## Core subclasses

### A. Monotone count / bracket markets — highest priority

One scalar count only increases until a fixed deadline.

Examples:
- YouTube video views after 24/48/72/96/120/144/168 hours.
- subscriber/follower milestones by a date.
- cumulative box-office gross thresholds.
- other view/download/sales/count brackets with a public counter.

State: `X(t)`.
Final bracket `k`: `[a_k, b_k)`.

`P(k | t) = P(a_k <= X(t) + ΔX(t,T) < b_k)`

Hard information exists immediately:
- if `X(t) >= b_k`, bracket `k` is impossible when `X` is monotone;
- if `X(t) >= a_k`, the lower bound has already been crossed;
- the remaining growth required to cross the next boundary is explicit.

This is the cleanest version of the thesis and can sometimes produce deterministic elimination rather than forecasting alpha.

### B. Cumulative leader races — high priority

Multiple competitors accumulate the same count/statistic.

Examples:
- MLB home runs / runs / wins / strikeouts leaders.
- NFL passing/rushing/receiving yard or touchdown leaders.
- NBA scoring leader.
- soccer Golden Boot / tournament goals.
- Olympic medal leaders.
- Spotify annual artist/song/album leader.
- calendar-year domestic box-office leader.

For current leader `L` and challenger `j`:

`margin_j(t) = X_L(t) - X_j(t)`

Remaining catch-up:

`C_j = ΔX_j(t,T) - ΔX_L(t,T)`

Leader probability:

`P(L wins) = P(max_j C_j < margin_j(t), after tie-break rules)`

The generic edge is not "leader is ahead". It is that Polymarket may misprice the relationship between **current margin, remaining opportunities and the empirical distribution of catch-up**.

### C. Finite-opportunity elimination — special high-confidence subset

Some markets have a literal upper bound on remaining opportunity.

Examples can include medal tables, tournament counts, or explicitly bounded remaining games/events.

For challenger `j`, if:

`current_j + max_remaining_j < current_leader`

then `j` is mechanically eliminated (subject to the exact resolution/tie rules).

If executable Polymarket prices still assign material value to an eliminated outcome, this is closer to arbitrage and needs much less statistical inference.

## Why the market could be inefficient

Potential mechanisms to test, not assume:

1. Traders anchor on preseason/base-rate narratives and update cumulative state too slowly.
2. Prices reflect the current leader but not the shrinking distribution of remaining catch-up.
3. Many users reason from average pace rather than the tail event needed to overcome a large existing margin.
4. Public counters/stat feeds update faster than Polymarket liquidity reprices.
5. Multi-outcome markets diffuse attention across many contracts and can leave dominated tails stale.
6. In short-horizon bracket markets, state may cross a boundary while old quotes remain in the book.

The thesis fails if executable prices already incorporate these constraints efficiently after fees.

## Correct unit of evidence

Do **not** count multiple timestamps or multiple outcome tokens from one event as independent wins.

Primary independent unit: **event group**.

Examples:
- one MrBeast video trajectory = one event group even if Polymarket has day-2/day-3/day-6 markets;
- one MLB stat category-season = one event group;
- one Spotify year/category = one event group;
- one Olympic medal competition = one event group.

Within-event timestamps are useful for estimating execution and calibration, but not for inflating sample size.

Report results both:
- by event group;
- by family/domain;
- pooled only after the grouped results are shown.

## Backtest protocol

### 1. Discover before looking at outcomes

Use deterministic text/rule filters over the historical Polymarket event universe to build the candidate set. Save that universe before fitting a model.

This reduces cherry-picking of memorable winners.

### 2. Reconstruct point-in-time external state

At each historical decision timestamp use only information that existed then.

Preferred sources:
- official sports game logs/stat feeds;
- Box Office Mojo / The Numbers daily historical grosses;
- official Olympics/FIFA/league data;
- public counters or archived counter histories;
- third-party stream trackers only when their methodology is understood and timestamped.

If state cannot be reconstructed reliably, that event does not enter the historical PnL sample.

### 3. Use fixed decision clocks

Avoid searching every second for the most profitable hindsight timestamp.

Examples:
- once daily for season/year markets;
- after each completed game/event for sports/tournaments;
- fixed fractions of elapsed time for view-count markets (e.g. 25%, 50%, 75%, 90% of horizon), plus a prospective high-frequency recorder later if warranted.

### 4. Price using executable Polymarket data

For every candidate decision:

`all_in = executable_ask_or_vwap + taker_fee + execution_buffer`

Do not use midpoint as entry price.

If historical order-book depth is unavailable, mark the observation as price-only and exclude it from capacity claims.

### 5. Keep the forecasting model simple

Start with empirical remaining-increment distributions, not ML.

For a leader market:
- estimate each contender's per-opportunity increments from data available to that date;
- bootstrap remaining games/events or use a simple count distribution appropriate to the stat;
- preserve schedule/opportunity count;
- explicitly model injuries/elimination only when known at that timestamp.

For a monotone count market:
- estimate the remaining growth curve from previous comparable trajectories and the current trajectory;
- calculate probability mass in each final bracket;
- retain hard boundary eliminations separately from forecast-based trades.

### 6. Probability floor, not optimistic point estimate

Evaluate a small set of defensible model variants and use:

`p_floor = min(p_variant)`

Trade signal in research:

`edge_floor = p_floor - all_in`

Initial generic gate:

`edge_floor >= 0.05`

This is intentionally simple and can be changed only from training data, not after inspecting holdout outcomes.

### 7. Grouped validation

Minimum useful evidence is not a magic trade count. The target is enough **distinct events** that one outcome cannot dominate the result.

Practical target for promotion from research:
- at least ~20 reconstructable event groups if available;
- preferably 3+ market families;
- no single event contributes >20% of total net PnL;
- positive event-level mean and median PnL/ROI;
- positive results after current fee assumptions and conservative execution buffer;
- hold out the newest events or an entire family/year where feasible.

If history is too short, do not fabricate certainty. Start a prospective recorder and accumulate events.

## Metrics that matter

Profitability first:

- net PnL after fees and execution buffer;
- ROI on deployed capital;
- EV / trade and EV / event group;
- capital-days and annualized capital efficiency;
- fillable dollars at observed depth;
- win rate only as a secondary metric;
- Brier/log-loss for probability calibration;
- max drawdown;
- event-group concentration of PnL;
- performance by family and by time-to-resolution bucket.

A high win rate with 95c entries can lose money. A low-frequency strategy that locks capital for months may also be economically inferior despite positive EV.

## Candidate families ranked for research

### Tier 1 — repeated + reconstructable

1. **Sports cumulative stat leaders** — many event groups; official historical stats; known games/events remaining. Best historical validation substrate.
2. **MrBeast / public counter brackets** — many repeated markets and very strong monotonic constraints; potentially deterministic eliminated brackets. Main difficulty is reconstructing historical per-video counter trajectories, so prospective recording may be especially valuable.

### Tier 2 — strong mechanics, fewer independent events

3. **Short-tournament goal/medal leaders** — finite opportunity, public official state, occasional hard elimination.
4. **Calendar-year box office leader/thresholds** — excellent daily public state and very large Polymarket volume, but only a few independent years/events.

### Tier 3 — useful but resolver/data complications

5. **Spotify annual rankings** — real cumulative mechanics but only a few annual observations and opaque weighted-stream methodology. Keep as one test family, not the strategy.

## Minimal implementation plan

No production bot yet.

1. `state_market_discovery.py` — enumerate historical/current Polymarket events and classify likely state-constrained candidates from titles/rules.
2. Save `state_market_candidates.json` and inspect false positives/coverage.
3. Pick the most reconstructable repeated family first: sports stat leaders.
4. Build one generic event-state schema:
   - event id / family
   - timestamp
   - contender
   - current cumulative value
   - remaining opportunities
   - PM executable price
   - final result
5. Implement one simple leader-race probability engine and replay it across several sports/stat categories.
6. In parallel, create a tiny **prospective** public-counter recorder only if MrBeast/current-counter markets continue to recur.
7. Only after repeated net-positive evidence: create a scanner/shadow trader over live markets.

## Kill / promotion rules

Kill or narrow the thesis if:
- most apparent edge disappears at executable asks/fees;
- performance comes from one event or one hand-picked family;
- point-in-time external state cannot be reconstructed;
- small reasonable model changes reverse profitability;
- the market reprices faster than data can be observed/traded;
- capacity is trivial.

Promote a family when:
- its mechanism is clearly defined;
- historical event-group PnL is repeatedly positive after costs;
- results survive chronological/family holdout where possible;
- current live events can be reconstructed from public state with no special information;
- executable edge is large enough to matter in dollars.
