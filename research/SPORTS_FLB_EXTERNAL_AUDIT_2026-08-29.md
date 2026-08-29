# Sports T-7d favorite/longshot claim — external-method audit

Date: 2026-08-29

## Decision

**Do not treat the published +25.8pp T-7d sports result as validated alpha.**

The strongest component of that result, MLB, is materially contaminated by a clock-definition bug acknowledged later in the source repository itself. The result must be rebuilt from `gameStartTime` (or another verified event-start clock), using only information available before the intended entry time, before it can justify capital or further execution work.

This does **not** prove there is no sports edge. It invalidates the main historical evidence currently supporting the very large claimed edge.

## Source under audit

External repository:
- `sturzael/polymarket-edge-research`
- historical calibration code: `experiments/e16_calibration_study/05_fixed_time_calibration.py`
- historical synthesis: `experiments/e23_stratification/SYNTHESIS.md`
- later clock-fix commit: `628574b0d2b52594aca67c63777a90e38f8adb25`

Headline claim in that research:
- sports YES price bucket 0.55-0.60 around “T-7d”
- pooled deep sample: n=120, realized YES rate 83.3%, about +25.8 percentage points versus bucket midpoint
- MLB reportedly the strongest sport, n=54 and roughly +36.9pp
- game-outcome subset reportedly drove the effect

## Critical reconstruction

The historical calibration code defines:

```text
target_ts = end_date - 7 days
window = target_ts +/- 12 hours
price = VWAP of trades inside that full 24-hour window
```

The source repository later explicitly documented that for MLB:

```text
endDate = gameStartTime + 7 days
```

and fixed its live/forward scanner because using `endDate` had produced post-game MLB “zombies”. The commit reports roughly 129/398 recent sports forward snapshots (~32%) were polluted before the fix.

For MLB, substituting the documented clock relationship into the historical formula gives:

```text
target_ts
= endDate - 7d
= (gameStartTime + 7d) - 7d
= gameStartTime
```

Therefore the supposed **T-7d MLB historical price is centered on game start, not seven days before game start.**

Because the code then uses `target +/- 12h`, its price statistic can include trades up to **12 hours after game start**. That is future information relative to any genuine pre-game T-7d strategy and may include substantial in-game or post-game information.

## Why this can manufacture the reported S-curve

A centered window around game time is mechanically outcome-correlated:

- eventual winners tend to move upward toward 1 as decisive information arrives;
- eventual losers tend to move downward toward 0;
- averaging pre-game and later trades can leave intermediate VWAPs such as 0.55-0.60 while selecting disproportionately eventual winners;
- the mirror image occurs below 0.50.

That produces exactly the kind of strong favorite/longshot-looking calibration curve reported by the study without requiring a tradeable T-7d inefficiency.

The study's 0.45-0.50 control bucket being approximately calibrated does not fix this clock problem. The issue is that the price window itself can contain future game information relative to the claimed entry horizon.

## Additional methodological issues

1. **Not a point-in-time executable entry.** The historical price is a 24-hour VWAP centered around the target. A trader cannot know or execute the future half of that VWAP at the target timestamp.
2. **Universe classification is heuristic.** The baseline sports categories are inferred from slug/question regexes; a later sub-category classifier is also slug-based. This is useful research tooling, but weaker than Gamma's explicit sports metadata and `sportsMarketType`.
3. **No completed forward validation found in the repository.** The repo's latest commits are from 2026-04-22. A 30-day forward validator was started, then the MLB clock pollution was discovered. No later committed result was found rebuilding the historical headline with the corrected clock or completing the advertised forward validation.

## Required independent test

Our independent check must use:

1. Gamma sports metadata, not heuristic category assignment;
2. `sportsMarketType=moneyline` for the initial clean game-outcome test;
3. `gameStartTime` / verified event-start clock, never `endDate` when it is a settlement clock;
4. price at or **before** the intended T-7d timestamp — no centered future window;
5. resolved independent games;
6. explicit sample size and per-sport decomposition;
7. only after calibration survives: historical executable-trade / spread / depth audit and then forward paper validation.

## Current ranking implication

The external sports claim was initially attractive because +20-30pp would dominate most other routes. After this audit, it is downgraded from a potential high-priority edge to a **high-priority falsification target**.

- If the corrected game-clock test still shows a large repeated edge, promote it aggressively and audit execution.
- If it collapses, kill the T-7d FLB route; do not tune around the contaminated historical result.
