# Spotify Top Artist 2026 — cumulative leader-lock research

Objective: determine whether the Polymarket `Top Spotify Artist 2026` market materially understates the probability of the eventual Spotify Wrapped global top artist. Profitability only; no live trading from this research code.

## Resolver facts

Polymarket resolves to the artist Spotify officially lists as its top artist for 2026, typically in Spotify Wrapped.

Spotify's own 2025 methodology says:
- Wrapped uses listening from Jan 1 through **mid-November**, not Dec 31.
- Top Artists use a **weighted stream count**: primary artists receive more weight than secondary/featured artists.
- A stream/listen counts after >30 seconds.

Primary sources:
- https://newsroom.spotify.com/2025-12-05/wrapped-methodology-explained/
- https://newsroom.spotify.com/2025-12-03/wrapped-top-artists-songs-albums-podcasts-audiobooks/
- https://polymarket.com/event/top-spotify-artist-2026

## Why an edge could exist

The market may reason from fame, releases and current daily streams while underweighting the finite-horizon arithmetic:

1. a large accumulated YTD lead already exists;
2. only ~2.5 months remain before the likely Wrapped cutoff;
3. a challenger must outperform the leader by `deficit / days_remaining` every day;
4. that required differential can be compared with observed/historical daily stream differentials and release spikes.

This becomes attractive only when the challenger catch-up path is empirically extreme while Polymarket still sells the leader well below the corresponding probability.

## Minimal score proxy

Spotify does not publish the exact featured-artist weight. Use a stress family, not a guessed constant:

`score_i(w) = YTD_lead_i + w * YTD_feature_i`

where primary/lead weight is normalized to 1 and `w` is tested over a range such as 0.00, 0.10, ..., 0.50. The proxy is acceptable only if it reproduces historical Wrapped rankings reasonably across 2023–2025 from point-in-time data.

For each challenger `j` against leader `L`:

`deficit_j(w) = score_L(w) - score_j(w)`

For cutoff date `T` and current date `t`:

`days_left = T - t`

Required average daily advantage:

`required_diff_j(w,T) = deficit_j(w) / days_left`

Observed current daily advantage:

`current_diff_j(w) = daily_lead_j + w*daily_feature_j - daily_lead_L - w*daily_feature_L`

Catch-up multiple:

`catchup_multiple = required_diff / max(current_diff, small_positive_value)`

A large multiple is not itself a probability. It is a diagnostic showing how much the current regime must change.

## Probability model — only after data is trustworthy

Keep it simple. Use historical daily/weekly differentials and event/release spikes to simulate the remaining cumulative differential.

Base candidate approach:
1. reconstruct daily or weekly score differentials for top artists;
2. bootstrap historical blocks to preserve momentum/autocorrelation;
3. explicitly inject known future release scenarios where relevant;
4. run conservative cutoff dates (e.g. Nov 10 / Nov 15 / Nov 20);
5. compute `P(any challenger finishes above leader)`;
6. apply a model-error haircut rather than pretending Spotify's hidden weighting is known.

The output that matters is a conservative probability floor, not the mean estimate.

## Trading math

For YES purchased at ask `a` with per-share taker fee `f(a)`:

`all_in = a + f(a) + slippage`

If model probability is `p` and held to resolution:

`EV/share = p - all_in`

`ROI_on_capital = (p - all_in) / all_in`

Do not trade merely because `p > all_in`. Require a large model-risk margin.

Initial research gate:
- conservative `p_floor >= 0.95`
- executable all-in average price `<= 0.89`
- enough depth for dollars to matter
- historical proxy validation passes
- known-release stress tests do not break the floor

This is a research threshold, not a permanent strategy parameter.

## Current evidence (2026-08-29)

Official methodology is confirmed. Current public Kworb data approximately shows:
- Bad Bunny: 38.1M daily lead streams
- Drake: 42.5M daily lead streams
- Taylor Swift: 45.9M daily lead streams
- The Weeknd: 30.5M daily lead streams
- Ariana Grande: 35.1M daily lead streams
- Travis Scott: only ~10.3M daily lead despite very high all-credit daily streams; most of the current total is feature credit.

This is exactly why raw all-credit streams are unsafe for this market.

The last executable Polymarket snapshot obtained in research showed Bad Bunny ~87c best ask with meaningful depth through ~89–90c. Refresh every research run; do not hard-code it as current truth.

## Evidence still missing

The decisive missing variable is independent **2026 YTD weighted/lead accumulation**. Polymarket's AI context claimed a large Bad Bunny lead, but that is not accepted as evidence.

We therefore need point-in-time source reconstruction:
- archived Kworb/ChartMasters artist totals near Jan 1, 2026;
- current totals;
- ideally archived mid-Nov snapshots for 2023–2025 to validate the proxy against official Wrapped rankings.

## Implementation plan — no infrastructure until earned

1. `spotify_reconstruct.py`: fetch current Kworb totals and Wayback point-in-time snapshots; produce YTD lead/feature deltas and historical validation data.
2. `spotify_model.py`: pure math over the reconstructed JSON; stress `w`, cutoff date, daily-rate shocks and simple bootstrap if enough history exists.
3. Extend `spotify_leader_lock.py` only for current Polymarket executable book/depth and EV calculations.
4. If and only if the historical proxy + conservative probability floor pass: create a tiny shadow recorder for daily source snapshots and Polymarket book prices.
5. No live order code until shadow evidence exists.

## Kill conditions

Kill/deprioritize if any of these holds:
- archived reconstruction is too incomplete to establish YTD positions independently;
- proxy ranking does not reproduce prior official Wrapped leaders/order;
- plausible Spotify weighting ranges frequently change the 2026 leader;
- known challenger release scenarios pull conservative probability below ~95%;
- executable all-in PM price rises enough that expected ROI is trivial;
- depth is too small for meaningful dollar EV.
