#!/usr/bin/env python3
"""Minimal math model for Spotify Wrapped cumulative leader-lock research.

Consumes spotify_reconstruction.json. It deliberately does NOT invent a calibrated
win probability. First validate the stream proxy against prior official Wrapped
orders; then the same data can support a conservative probability layer.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

RECON = Path("spotify_reconstruction.json")
OUT = Path("spotify_model.json")
WEIGHTS = (0.0, 0.10, 0.25, 0.50)
CUTOFFS = (
    dt.date(2026, 11, 10),
    dt.date(2026, 11, 15),
    dt.date(2026, 11, 20),
)


def weighted(rec: dict, w: float, prefix: str = ""):
    lead = rec.get(prefix + "lead")
    feat = rec.get(prefix + "feature")
    if lead is None:
        return None
    return float(lead) + w * float(feat or 0.0)


def rank(scores: dict[str, float]):
    return [name for name, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


def official_accuracy(actual: list[str], predicted: list[str]):
    common = [x for x in actual if x in predicted]
    if not common:
        return {"exact_positions": 0, "n": 0, "exact_order": False}
    pred = [x for x in predicted if x in common]
    return {
        "exact_positions": sum(a == b for a, b in zip(common, pred)),
        "n": len(common),
        "exact_order": common == pred,
    }


def days_between(current_date: dt.date, cutoff: dt.date):
    return max(1, (cutoff - current_date).days)


def historical_validation(data: dict):
    result = {}
    official = data.get("official_order") or {}
    for year_s, artists in (data.get("historical_validation") or {}).items():
        year = int(year_s)
        by_w = {}
        for w in WEIGHTS:
            scores = {}
            for name, rec in artists.items():
                d = rec.get("jan_to_nov_delta")
                if not d:
                    continue
                s = weighted(d, w)
                if s is not None:
                    scores[name] = s
            pred = rank(scores)
            actual = official.get(str(year)) or official.get(year) or []
            by_w[str(w)] = {
                "scores": scores,
                "predicted_order": pred,
                "official_order": actual,
                "accuracy": official_accuracy(actual, pred),
            }
        result[year_s] = by_w
    return result


def current_date_from_data(data: dict):
    dates = []
    for rec in (data.get("ytd_2026") or {}).values():
        s = rec.get("current_page_date")
        if not s:
            continue
        try:
            dates.append(dt.datetime.strptime(s, "%Y/%m/%d").date())
        except ValueError:
            pass
    return max(dates) if dates else dt.datetime.now(dt.timezone.utc).date()


def current_analysis(data: dict):
    ytd = data.get("ytd_2026") or {}
    current = data.get("current") or {}
    asof = current_date_from_data(data)
    out = {"asof": asof.isoformat(), "weights": {}}

    for w in WEIGHTS:
        scores = {}
        daily = {}
        for name, rec in ytd.items():
            s = weighted(rec, w)
            if s is not None:
                scores[name] = s
            d = rec.get("current_daily") or (current.get(name) or {}).get("daily") or {}
            ds = weighted(d, w)
            if ds is not None:
                daily[name] = ds
        order = rank(scores)
        row = {"ytd_scores": scores, "current_daily_scores": daily, "order": order, "cutoffs": {}}
        if not order:
            row["status"] = "no_reconstructed_ytd_data"
            out["weights"][str(w)] = row
            continue
        leader = order[0]
        row["leader"] = leader
        for cutoff in CUTOFFS:
            days = days_between(asof, cutoff)
            c = {"days_left": days, "challengers": {}}
            for challenger in order[1:]:
                deficit = scores[leader] - scores[challenger]
                leader_daily = daily.get(leader)
                ch_daily = daily.get(challenger)
                required_advantage = deficit / days
                rec = {
                    "deficit": deficit,
                    "required_daily_advantage": required_advantage,
                    "leader_current_daily": leader_daily,
                    "challenger_current_daily": ch_daily,
                }
                if leader_daily is not None:
                    req_ch = leader_daily + required_advantage
                    rec["required_challenger_daily_if_leader_flat"] = req_ch
                    if ch_daily and ch_daily > 0:
                        rec["required_vs_current_multiple"] = req_ch / ch_daily
                        rec["current_daily_advantage"] = ch_daily - leader_daily
                        rec["projected_cutoff_margin_at_current_rates"] = (
                            deficit - (ch_daily - leader_daily) * days
                        )
                c["challengers"][challenger] = rec
            row["cutoffs"][cutoff.isoformat()] = c
        out["weights"][str(w)] = row
    return out


def calibration_summary(hist: dict):
    rows = {}
    for w in WEIGHTS:
        key = str(w)
        tested = 0
        exact_orders = 0
        positions = 0
        n_positions = 0
        for yr in hist.values():
            r = yr.get(key) or {}
            a = r.get("accuracy") or {}
            if a.get("n", 0):
                tested += 1
                exact_orders += int(bool(a.get("exact_order")))
                positions += int(a.get("exact_positions", 0))
                n_positions += int(a.get("n", 0))
        rows[key] = {
            "years_tested": tested,
            "exact_order_years": exact_orders,
            "position_accuracy": positions / n_positions if n_positions else None,
        }
    return rows


def main():
    if not RECON.exists():
        raise SystemExit(f"missing {RECON}; run spotify_reconstruct.py first")
    data = json.loads(RECON.read_text(encoding="utf-8"))
    hist = historical_validation(data)
    current = current_analysis(data)
    calibration = calibration_summary(hist)

    usable_2026 = any((r.get("order") or []) for r in current["weights"].values())
    usable_hist_years = max((v["years_tested"] for v in calibration.values()), default=0)
    status = {
        "reconstruction_usable_2026": usable_2026,
        "historical_years_usable": usable_hist_years,
        "probability_status": "UNCALIBRATED",
        "reason": (
            "Probability intentionally withheld until historical proxy validation and a remaining-differential distribution are adequate."
        ),
    }
    out = {
        "status": status,
        "calibration": calibration,
        "historical_validation": hist,
        "current_2026": current,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "calibration": calibration, "current_2026": current}, indent=2))


if __name__ == "__main__":
    main()
