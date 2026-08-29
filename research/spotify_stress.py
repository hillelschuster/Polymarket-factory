#!/usr/bin/env python3
"""Deterministic profitability stress grid for Spotify Top Artist 2026.

This is deliberately NOT a Monte Carlo model. The decisive missing variable is the
resolver-aligned Bad Bunny lead. We therefore ask: how large must that true lead be
today to survive observed/hostile Drake catch-up regimes through plausible Wrapped
cutoffs?
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OBS=Path("spotify_observed_series.json")
OUT=Path("spotify_stress.json")
ASOF=dt.date(2026,8,20)  # latest audited cumulative tracker observation
CUTOFFS=(dt.date(2026,11,10),dt.date(2026,11,15),dt.date(2026,11,20))
GAPS_B=(0.40,0.60,0.80,1.00,1.20,1.50,1.77)


def scenario_close(days, shock_days, shock_rate_m, normal_rate_m):
    sd=min(days,shock_days)
    return sd*shock_rate_m + (days-sd)*normal_rate_m


def main():
    obs=json.loads(OBS.read_text()) if OBS.exists() else {}
    seg=obs.get("derived_regimes") or {}
    shock=(seg.get("release_shock_may21_may28") or {}).get("drake_net_catchup_per_day")
    normal=(seg.get("post_release_may28_aug20") or {}).get("drake_net_catchup_per_day")
    comp=obs.get("composition") or {}
    current_lead=comp.get("drake_minus_bad_bunny_lead_daily")

    # Fallbacks are the audited values from the same source series; stored only so
    # the stress model remains deterministic if Kworb is temporarily unavailable.
    shock_m=(shock/1e6) if shock is not None else 33.77
    normal_m=(normal/1e6) if normal is not None else 5.31
    current_lead_m=(current_lead/1e6) if current_lead is not None else 4.43

    scenarios={
        "post_may_normal_all_credit":{"shock_days":0,"shock_rate_m":0.0,"normal_rate_m":normal_m,"basis":"observed May28-Aug20 all-credit gap compression"},
        "current_lead_only_daily":{"shock_days":0,"shock_rate_m":0.0,"normal_rate_m":current_lead_m,"basis":"current Kworb lead-stream differential"},
        "repeat_may_release_week":{"shock_days":7,"shock_rate_m":shock_m,"normal_rate_m":normal_m,"basis":"repeat observed May21-May28 catch-up then normal"},
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

    # Weighting sensitivity: stress-only estimate using current feature shares as if
    # they represented YTD feature shares. This is NOT evidence of the true gap.
    series=obs.get("series") or []
    last=series[-1] if series else None
    bbfs=comp.get("bad_bunny_feature_share_current_daily")
    drfs=comp.get("drake_feature_share_current_daily")
    if last and bbfs is not None and drfs is not None:
        bb=last["bad_bunny"]/1e9; dr=last["drake"]/1e9
        all_gap=bb-dr
        feature_gap=bb*bbfs-dr*drfs
        sens={}
        for w in (0.0,0.10,0.25,0.50,0.75,1.0):
            weighted_gap=all_gap-(1-w)*feature_gap
            sens[str(w)]={"estimated_gap_b":weighted_gap,"estimated_gap_m":weighted_gap*1000}
        result["weighting_sensitivity_current_share_proxy"]={
            "WARNING":"Current daily feature shares are used only as a stress proxy for unknown YTD feature composition; do not treat as reconstructed Spotify score.",
            "all_credit_gap_b":all_gap,"estimated_feature_credit_gap_b":feature_gap,"weight_grid":sens,
        }

    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__": main()
