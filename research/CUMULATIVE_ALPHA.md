# General cumulative-state / finite-horizon alpha

## Objective

Test whether Polymarket systematically misprices markets whose outcome is progressively constrained by a public cumulative state and finite remaining opportunities.

Spotify 2026 is only one example. It has essentially zero evidentiary value by itself for validating a strategy.

## Core mechanism

At historical decision time `t`, for leader `L`, challenger `j`, and resolver cutoff `T`:

`moat_j(t) = state_L(t) - state_j(t)`

`remaining = T - t`  (or games / releases / states / other resolver-relevant opportunities left)

`required_catchup_j = moat_j / remaining`

The relevant probability is:

`P_j = P(future net catchup_j > moat_j | information available at t)`

and approximately:

`p_leader = 1 - P(any relevant challenger catches leader)`

This is useful only when a conservative estimate of `p_leader` materially exceeds the executable Polymarket all-in price.

## Eligible market classes

Only repeated, resolver-aligned classes count.

1. **Streaming / views / charts**: annual Spotify leaders, video/view-count races, chart/download totals.
2. **Box office / sales**: annual or period box-office leaders and cumulative public sales metrics.
3. **Sports cumulative state**: season wins/points/goals/statistical leaders where remaining games bound the catch-up path.
4. **Election accumulation**: delegates, seats, electoral votes or other already-awarded cumulative units when the resolver is explicit.
5. **Other running public counts**: any repeated market whose outcome is a cumulative observable statistic with a fixed cutoff.

Exclude markets where the visible running count is not resolver-aligned, the resolver is subjective, or one late administrative/rule event can dominate the cumulative process.

## Validation standard

A strategy is NOT validated because the leader wins.

Validation requires repeated point-in-time decisions across independent markets/events. Each historical observation must use only information available at that time:

- resolver-aligned cumulative state;
- remaining opportunities/time;
- historical or hard-bound future catch-up capacity;
- Polymarket price available at that time;
- realistic fees/slippage or a conservative cost proxy;
- eventual resolution.

No final-state leakage. No tuning separate thresholds per market family merely to manufacture winners.

Initial evidence target:

- >=30 genuinely independent qualifying decisions before treating the rule as statistically interesting;
- preferably 50-100+ decisions across several families;
- report event-level clustering so many snapshots from one event do not pretend to be independent trades.

## Fixed diagnostics

For every candidate snapshot:

- `moat`
- `remaining_units`
- `required_catchup_rate`
- `recent_catchup_rate`
- historical catch-up distribution / hard maximum where available
- `stress_ratio = moat / hostile_future_catchup`
- executable PM ask / VWAP
- fees
- `p_floor` only if enough historical state exists to estimate it honestly
- `edge_floor = p_floor - all_in_price`

The research must preserve raw quantities even when no probability can be defended.

## Minimal rule family to test

Do not start with ML. Test a small family of rules that can generalize across domains.

### Rule A — empirical catch-up quantile

Estimate the distribution of cumulative net catch-up over a horizon equal to the remaining units from historical point-in-time increments.

`p_floor = 1 - P_historical(catchup > moat)`

Use a conservative upper confidence bound on catch-up probability when sample size is thin.

### Rule B — stress-multiple bound

Let `Q99_R` be the 99th-percentile historical catch-up over the remaining horizon, or an intentionally hostile deterministic stress when the sample is sparse.

Candidate only if:

`moat >= k * Q99_R`

for fixed `k` values tested globally (for example 1.0 / 1.25 / 1.5), then compare eventual outcome and PM price.

### Rule C — hard remaining-capacity bound

Some domains have a physical/logical maximum future catch-up. If `max_possible_catchup < moat`, the outcome is locked except for resolver/rule risk. These are especially valuable because the statistical burden is lower.

## Profitability accounting

For a YES purchased at executable average ask `a`:

`fee_per_share = fee_rate * a * (1-a)` when fees apply.

`all_in = a + fee_per_share + slippage`

`EV/share = p_floor - all_in`

`ROI = EV/share / all_in`

Current Polymarket documentation confirms fees are market/category specific and should be read per market; makers pay no trading fee and takers pay according to the market fee schedule. Never hard-code one global rate. Price history can be queried from the CLOB `/prices-history` endpoint, but historical midpoint/last-price data are not equivalent to executable ask and must be discounted accordingly.

## Backtest unit

The primary statistical unit is the **market/event**, not every time snapshot.

A market may generate many candidate timestamps. To prevent pseudo-replication, evaluate:

1. first time the fixed entry rule triggers;
2. optionally one later scale-in under a separately fixed rule;
3. one final PnL per independent market.

Also report snapshot-level calibration, but never use snapshot count as the main number of independent bets.

## Research sequence

1. Build a broad historical Polymarket universe and classify potentially cumulative markets.
2. Audit a sample manually to estimate classifier precision and discover recurring families.
3. For the families with public historical state data, reconstruct point-in-time state.
4. Apply one simple rule family without family-specific optimization.
5. Add conservative historical Polymarket prices and current fee logic.
6. Measure net PnL/ROI, hit rate, calibration, event count, drawdown, frequency and capacity.
7. Only if repeated evidence survives, add a prospective shadow scanner.

## Kill conditions

Kill the general thesis if:

- very few repeated markets have reconstructible point-in-time state;
- apparent edge disappears once prices are aligned to the same historical time;
- performance comes from one domain/year/event;
- reasonable fees/slippage erase the edge;
- fixed thresholds fail out of sample;
- the profitable sample is mostly effectively deterministic 98-99c outcomes with poor capital efficiency;
- capacity/frequency is too low to matter in dollars.

## Current status

Spotify is retained only as case study #1. No live-trading code is justified. The next decisive task is discovering and quantifying the historical market universe.