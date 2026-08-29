# Spotify Top Artist 2026 — cumulative leader-lock alpha

Objective: determine whether Bad Bunny YES in Polymarket's `Top Spotify Artist 2026` market has positive **real dollar EV** after protocol fees, depth and model risk. Research only; no order code.

## 1. Resolver

Polymarket resolves to Spotify's official 2026 global Top Artist, expected through Spotify Wrapped.

Spotify's published methodology matters more than generic stream charts:
- Wrapped uses listening from Jan 1 through roughly **mid-November**, not Dec 31.
- Top Artists use a **weighted stream count**: primary artists receive more weight than secondary/featured artists.
- Spotify does not publish the feature weight.

Primary references:
- https://newsroom.spotify.com/2025-12-05/wrapped-methodology-explained/
- https://newsroom.spotify.com/2025-12-03/wrapped-top-artists-songs-albums-podcasts-audiobooks/
- https://polymarket.com/event/top-spotify-artist-2026

Consequence: raw all-credit streams are trajectory evidence, **not the resolver score**.

## 2. Economic thesis

This is not a music-opinion trade.

The mechanism is:

`cumulative moat + shrinking time + bounded challenger catch-up => winner becomes more certain before PM fully prices the lock`

The trade exists only if the resolver-aligned Bad Bunny lead is large enough that plausible Drake/Taylor release shocks cannot erase it before the cutoff, while executable PM asks still imply materially lower probability.

## 3. Observed 2026 all-credit trajectory

Third-party Musical Moments (`@MMoments001`) snapshots give an independently tracked cumulative series:

| Date | Bad Bunny | Drake | BB lead |
|---|---:|---:|---:|
| 2026-02-19 | 4.211B | 2.614B | 1.597B |
| 2026-03-26 | 7.122B | 4.415B | 2.706B |
| 2026-05-21 | 10.579B | 8.127B | 2.452B |
| 2026-05-28 | 11.019B | 8.803B | 2.216B |
| 2026-08-20 | 15.720B | 13.950B | 1.770B |

Important regimes:
- Feb19→Mar26: BB **expanded** lead by ~1.110B in 35d (~31.7M/day net). This interval contains the Feb 8 Super Bowl effect and demonstrates that BB can generate a very large positive shock.
- Mar26→May21: Drake catch-up ~4.54M/day.
- May21→May28: Drake catch-up ~33.77M/day for seven days.
- May28→Aug20: Drake catch-up ~5.31M/day.

The May shock followed Drake's May 15 release of **three albums / 43 tracks** (`Iceman`, `Habibti`, `Maid of Honour`). Treat it as an observed severe release shock, not the normal regime.

## 4. Current resolver-relevant composition

Current Kworb artist pages split daily streams into lead vs feature credit. Latest research snapshot:

Bad Bunny:
- total 56.42M/day
- lead 37.74M/day
- feature 18.68M/day

Drake:
- total 58.13M/day
- lead 42.48M/day
- feature 15.65M/day

Drake minus BB:
- all-credit: +1.72M/day
- lead-only: +4.75M/day
- feature: **-3.03M/day**

If Spotify's unknown feature weight is `w` with lead normalized to 1:

`daily_catchup(w) = 4.748M - 3.033M*w`

So lower feature weighting hurts BB's estimated starting moat but simultaneously slows Drake's future weighted catch-up. Both effects must be coupled.

## 5. Weight uncertainty

Model family:

`score_i(w) = YTD_lead_i + w * YTD_feature_i`

Do **not** guess `w`.

Until YTD lead/feature composition is reconstructed, `spotify_stress.py` uses today's feature shares as a deliberately labelled stress proxy. With the Aug20 all-credit 1.77B gap, that proxy produces approximately:

| w | proxy BB starting moat |
|---:|---:|
| 0.00 | 0.320B |
| 0.10 | 0.465B |
| 0.25 | 0.682B |
| 0.50 | 1.045B |
| 0.75 | 1.407B |
| 1.00 | 1.770B |

These are **not reconstructed Spotify scores**. They answer a narrower question: how low can the resolver-aligned moat plausibly be before the trade stops working?

## 6. Hard survival thresholds

For an Aug20 state and a Nov15 cutoff, the minimum starting resolver-aligned BB lead required to survive deterministic Drake catch-up paths is approximately:

- current lead-only differential for all remaining days: **0.413B**
- observed post-May average catch-up: **0.462B**
- repeat the observed May triple-album shock for 7d, then normal: **0.661B**
- 14d at 20M/day, then normal: **0.668B**
- 7d at an intentionally extreme 50M/day, then normal: **0.775B**

For a later Nov20 cutoff, the extreme threshold is ~**0.801B**.

Therefore the empirical target is simple:

> If the actual Spotify-weighted BB moat can be defended as safely above ~0.8B, it survives every deterministic stress currently in the research grid.

That is not the same thing as a 95% win probability. It is the condition under which a calibrated probability model becomes worth building.

## 7. Release risk

Drake's main observed adverse shock is unusually severe: May 15 delivered three albums / 43 tracks at once. Current research did not find another **confirmed** Drake, Taylor Swift or Bad Bunny full-album release scheduled before the likely mid-Nov cutoff in high-quality upcoming-release sources as of Aug29. This is absence of confirmation, not proof that surprise music cannot appear.

Taylor-specific risk remains nonzero because current press contains fan speculation around a new era / anniversary, but no official new-album announcement was found. Surprise releases must therefore remain in stress scenarios.

## 8. Current executable Polymarket economics

Latest factory CLOB snapshot (2026-08-29):
- best ask: 0.88, 351.25 shares
- best bid: 0.86, 1295.96 shares
- event volume: ~$1.56M
- market reports fees enabled
- taker fee schedule: rate 0.05, exponent 1, taker-only

Cumulative immediate taker depth:

| Ask cap | Shares | All-in capital | Avg all-in/share |
|---:|---:|---:|---:|
| 0.88 | 351 | ~$311 | 0.8853 |
| 0.89 | 3,283 | ~$2,934 | 0.8939 |
| 0.90 | 5,940 | ~$5,337 | 0.8986 |
| 0.91 | 8,108 | ~$7,319 | 0.9028 |
| 0.92 | 8,309 | ~$7,505 | 0.9033 |

At `p=0.95`, approximate held-to-resolution EV:
- through 0.89: `(0.95 - 0.8939) * 3283 ~= $184`
- through 0.90: `(0.95 - 0.8986) * 5940 ~= $305`

This is why `p > market price` is not enough. The opportunity only matters if the conservative probability floor is around 95%+.

## 9. Minimal code path

Critical research files only:

1. `spotify_observed_series.py`
   - auditable cumulative tracker observations
   - current Kworb lead/feature composition
   - empirical positive/negative shock regimes

2. `spotify_stress.py`
   - deterministic cutoff/shock thresholds
   - couples feature-weight uncertainty to starting moat and current catch-up
   - no fake Monte Carlo probability

3. `spotify_leader_lock.py`
   - current CLOB asks/bids
   - actual fee schedule
   - cumulative executable depth
   - EV grid conditional on externally justified `p`

Optional / non-critical:
- `spotify_reconstruct.py`: point-in-time archive work if a clean historical source becomes available.
- `spotify_model.py`: intentionally withholds probability until calibration data are adequate.

No database, service, dashboard, framework or live execution code is justified yet.

## 10. Exact next research gate

Highest-value missing evidence:

**Defend a lower bound on the current resolver-aligned BB moat.**

Priorities:
1. Recover historical Musical Moments / equivalent top-artist snapshots near prior Wrapped cutoffs and compare with official Spotify order.
2. Recover point-in-time YTD lead/feature composition if possible; do not spend large engineering effort fighting sparse archives.
3. Continue daily/weekly observed tracker + Kworb composition snapshots from now to cutoff. This prospectively eliminates historical-data ambiguity.
4. Re-audit confirmed Drake/Taylor/BB release announcements before every material probability update.

Only after the moat is defensibly >~0.8B should we fit a simple probability layer using observed regime blocks and one/two release-shock scenarios.

## 11. Trade/build gate

Do **not** build a live bot yet.

Build a tiny shadow recorder only when either:
- resolver-aligned gap is independently reconstructed; or
- enough prospective data accumulate to bound it tightly.

Promote to trade candidate only if all are true:
- conservative `p_floor >= 0.95`
- immediate/maker-adjusted all-in executable price leaves at least ~4-5 percentage points of model edge
- release stress included
- cutoff uncertainty included
- sufficient depth for meaningful dollar EV

## 12. Kill conditions

Kill/deprioritize if:
- plausible resolver weights put BB moat <~0.6B;
- a credible major challenger release makes the <0.8B region likely;
- calibrated p-floor remains <~0.94-0.95;
- PM reprices to a level where net expected ROI becomes trivial;
- independent cumulative tracking turns out not to map consistently enough to Spotify's official result.
