#!/usr/bin/env python3
"""Deterministic profitability stress grid for Spotify Top Artist 2026.

No Monte Carlo, no invented win probability. The main unknown is Spotify's unpublished
featured-artist weight. This script couples that uncertainty to BOTH:
1) the estimated current Bad Bunny moat; and
2) Drake's current weighted daily catch-up rate.

The current-share YTD decomposition remains a stress proxy, not reconstructed truth.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OBS=Path("spotify_observed_series.json")
OUT=Path("spotify_stress.json")
ASOF=dt.date(2026,8,20)
CUTOFFS=(dt.date(2026,11,10),dt.date(2026,11,15),dt.date(2026,11,20))
GAPS_B=(0.40,0.60,0.80,1.00,1.20,1.50,1.77)
WEIGHTS=(0.0,0.10,0.20,0.25,0.30,0.35,0.40,0.50,0.75,1.0)


def scenario_close(days, shock_days, shock_rate_m, normal_rate_m):
    sd=min(days,shock_days)
    return sd*shock_rate_m + (days-sd)*normal_rate_m


def main():
    obs=json.loads(OBS.read_text()) if OBS.exists() else {}
    seg=obs.get("derived_regimes") or {}
    shock=(seg.get("drake_release_shock_may21_may28") or {}).get("drake_net_catchup_per_day")
    normal=(seg.get("post_release_may28_aug20") or {}).get("drake_net_catchup_per_day")
    comp=obs.get("composition") or {}
    lead_diff=comp.get("drake_minus_bad_bunny_lead_daily")
    feature_diff=comp.get("drake_minus_bad_bunny_feature_daily")

    shock_m=(shock/1e6) if shock is not None else 33.77
    normal_m=(normal/1e6) if normal is not None else 5.31
    lead_diff_m=(lead_diff/1e6) if lead_diff is not None else 4.75
    feature_diff_m=(feature_diff/1e6) if feature_diff is not None else -3.03

    scenarios={
        "post_may_normal_all_credit":{"shock_days":0,"shock_rate_m":0.0,"normal_rate_m":normal_m,"basis":"observed May28-Aug20 all-credit gap compression"},
        "current_lead_only_daily":{"shock_days":0,"shock_rate_m":0.0,"normal_rate_m":lead_diff_m,"basis":"current Kworb lead-stream differential"},
        "repeat_may_release_week":{"shock_days":7,"shock_rate_m":shock_m,"normal_rate_m":normal_m,"basis":"repeat observed May21-May28 triple-album shock then post-May normal"},
        "two_week_20m_shock":{"shock_days":14,"shock_rate_m":20.0,"normal_rate_m":normal_m,"basis":"hand stress"},
        "one_week_50m_extreme":{"shock_days":7,"shock_rate_m":50.0,"normal_rate_m":normal_m,"basis":"hand extreme stress"},
    }

    result={"asof":ASOF.isoformat(),"units":"millions of resolver-aligned score unless stated","scenarios":scenarios,"cutoffs":{}}
    for cutoff in CUTOFFS:
        days=(cutoff-ASOF).days
        c={"days_left":days,"scenario_required_starting_gap_m":{},"gap_grid":{}}
        for name,s in scenarios.items():
            close=scenario_close(days,s["shock_days"],s["shock_rate_m"],s["normal_rate_m"])
            c["scenario_required_starting_gap_m"][name]=close
        for gap_b in GAPS_B:
            gap_m=gap_b*1000
            c["gap_grid"][str(gap_b)]={
                name:{"final_margin_m":gap_m-close,"survives":gap_m>close}
                for name,close in c["scenario_required_starting_gap_m"].items()
            }
        result["cutoffs"][cutoff.isoformat()]=c

    # Coupled feature-weight stress proxy. We estimate unknown YTD feature composition
    # from today's feature shares ONLY to identify what needs to be true for the trade;
    # this is not a calibrated Spotify score and must not be presented as one.
    series=obs.get("series") or []
    last=series[-1] if series else None
    bbfs=comp.get("bad_bunny_feature_share_current_daily")
    drfs=comp.get("drake_feature_share_current_daily")
    if last and bbfs is not None and drfs is not None:
        bb=last["bad_bunny"]/1e9; dr=last["drake"]/1e9
        all_gap_b=bb-dr
        feature_gap_b=bb*bbfs-dr*drfs
        coupled={}
        for w in WEIGHTS:
            gap_b=all_gap_b-(1-w)*feature_gap_b
            weighted_current_catchup_m=max(0.0, lead_diff_m + w*feature_diff_m)
            row={
                "estimated_start_gap_b":gap_b,
                "estimated_start_gap_m":gap_b*1000,
                "current_weighted_drake_catchup_m_per_day":weighted_current_catchup_m,
                "cutoffs":{},
            }
            for cutoff in CUTOFFS:
                days=(cutoff-ASOF).days
                current_close=weighted_current_catchup_m*days
                # Deliberately conservative: May release shock is kept at its FULL
                # observed all-credit 33.8M/day even when w<1; only post-shock days use
                # current weighted catch-up. This avoids pretending we know May's
                # lead/feature decomposition.
                repeat_close=scenario_close(days,7,shock_m,weighted_current_catchup_m)
                extreme_close=scenario_close(days,7,50.0,weighted_current_catchup_m)
                row["cutoffs"][cutoff.isoformat()]={
                    "days_left":days,
                    "current_rate_final_margin_m":gap_b*1000-current_close,
                    "repeat_may_full_shock_final_margin_m":gap_b*1000-repeat_close,
                    "one_week_50m_extreme_final_margin_m":gap_b*1000-extreme_close,
                    "survives_current_rate":gap_b*1000>current_close,
                    "survives_repeat_may_full_shock":gap_b*1000>repeat_close,
                    "survives_one_week_50m_extreme":gap_b*1000>extreme_close,
                }
            coupled[str(w)]=row
        result["coupled_weight_proxy"]={
            "WARNING":"Current daily feature shares proxy unknown YTD feature composition. Use this grid to define evidence thresholds, not as a probability forecast.",
            "all_credit_gap_b":all_gap_b,
            "estimated_feature_credit_gap_b":feature_gap_b,
            "formula_start_gap":"all_credit_gap - (1-w)*estimated_feature_credit_gap",
            "formula_current_catchup":"lead_daily_diff + w*feature_daily_diff",
            "weight_grid":coupled,
        }

    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__": main()
