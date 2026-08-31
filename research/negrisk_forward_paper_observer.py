#!/usr/bin/env python3
"""Forward paper observer for short-dated complete NegRisk YES baskets.

This is the forward-validation layer for the strongest current thesis. It never
places orders. Discovery, event semantics and fee coefficients are cached once;
the hot path repeatedly batch-fetches current books and depth-scores every event
whose scheduled end is within 30 days.

An opportunity is logged only if the full depth optimum remains positive after
current taker-fee stress. A stricter `actionable_paper` flag requires:
- scheduled end <= 30 days;
- net edge >= 0.50%;
- modeled locked dollar profit >= $1;
- at least two consecutive positive snapshots.

The two-snapshot gate intentionally sacrifices some speed to reduce one-read
artifacts. Production execution, if ever authorized separately, should re-read
all legs immediately before submission and use all-or-nothing execution controls.
No credentials or funded actions are used here.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import negrisk_hotloop_benchmark as hot
import negrisk_fast_depth_observer as base

OUT = Path("negrisk_forward_paper_observer.json")
SHORT_DAYS = 30
LOOPS = 120
SLEEP_SECONDS = 0.20
MIN_EDGE = 0.005
MIN_PROFIT_USD = 1.0
REQUIRE_CONSECUTIVE = 2


def ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def event_rec(ev):
    r = base.event_rec(ev)
    r["endDate"] = ev.get("endDate")
    r["end_ts"] = ts(ev.get("endDate"))
    return r


def prime_fees(recs):
    cache = {}
    errs = []
    for e in recs:
        for m in e["markets"]:
            cid = m.get("condition_id")
            if not cid or cid in cache:
                continue
            try:
                cache[cid] = base.fee_rate(m)
            except Exception as ex:
                cache[cid] = 0.05
                errs.append({"condition_id": cid, "error": repr(ex), "fallback": 0.05})
    return cache, errs


def score_one(e, books, fee_cache, now):
    legs = []
    for m in e["markets"]:
        lv = base.asks(books.get(m["yes_token"]))
        if not lv:
            return None
        legs.append({
            **m, "asks": lv, "best_ask": lv[0][0], "best_size": lv[0][1],
            "fee_rate": fee_cache.get(m.get("condition_id"), 0.05),
        })
    raw = sum(x["best_ask"] for x in legs)
    rec = {
        "event_id": e["event_id"], "title": e["title"], "slug": e["slug"],
        "n_legs": len(legs), "sum_best_yes_asks": raw,
        "hours_to_scheduled_end": (e["end_ts"] - now) / 3600 if e.get("end_ts") else None,
        "raw_underround": raw < 1,
    }
    if raw >= 1:
        return rec
    opt = base.optimize_depth(legs)
    rec["depth_optimum"] = opt
    rec["positive_after_fees"] = bool(opt and opt["net_profit"] > 0)
    if opt and opt["capital_required"] > 0 and rec["hours_to_scheduled_end"] and rec["hours_to_scheduled_end"] > 0:
        days = rec["hours_to_scheduled_end"] / 24
        rec["simple_annualized_scheduled_end_upper_bound"] = (
            opt["net_profit"] / opt["capital_required"] * 365 / days
        )
    return rec


def main():
    start_wall = time.time()
    t0 = time.monotonic()
    events, discovery_errors = base.fetch_active_events()
    discovery_seconds = time.monotonic() - t0
    now = time.time()
    recs = []
    for ev in events:
        if not base.eligible(ev):
            continue
        r = event_rec(ev)
        if r["end_ts"] and 0 < r["end_ts"] - now <= SHORT_DAYS * 86400:
            recs.append(r)
    recs.sort(key=lambda r: r["end_ts"])
    tokens = list(dict.fromkeys(m["yes_token"] for e in recs for m in e["markets"]))
    fee_cache, fee_errors = prime_fees(recs)

    histories = defaultdict(list)
    loops = []
    episodes = []
    active_episode = {}
    for i in range(LOOPS):
        cycle_t0 = time.monotonic()
        books, errors, book_seconds, requests = hot.concurrent_books(tokens)
        stamp = time.time()
        rows = []
        for e in recs:
            r = score_one(e, books, fee_cache, stamp)
            if not r:
                continue
            opt = r.get("depth_optimum") or {}
            positive = bool(r.get("positive_after_fees"))
            histories[e["event_id"]].append(positive)
            consecutive = 0
            for z in reversed(histories[e["event_id"]]):
                if not z:
                    break
                consecutive += 1
            r["consecutive_positive_snapshots"] = consecutive
            r["actionable_paper"] = bool(
                positive
                and consecutive >= REQUIRE_CONSECUTIVE
                and num(opt.get("net_edge_per_share")) >= MIN_EDGE
                and num(opt.get("net_profit")) >= MIN_PROFIT_USD
            )
            if positive:
                rows.append(r)
                eid = e["event_id"]
                if eid not in active_episode:
                    active_episode[eid] = {
                        "event_id": eid, "title": e["title"], "start_cycle": i,
                        "start_time": stamp, "snapshots": 0, "max_net_profit": 0,
                        "max_edge": 0, "actionable_snapshots": 0,
                    }
                ep = active_episode[eid]
                ep["snapshots"] += 1
                ep["max_net_profit"] = max(ep["max_net_profit"], num(opt.get("net_profit")))
                ep["max_edge"] = max(ep["max_edge"], num(opt.get("net_edge_per_share")))
                ep["actionable_snapshots"] += int(r["actionable_paper"])
            else:
                eid = e["event_id"]
                if eid in active_episode:
                    ep = active_episode.pop(eid)
                    ep["end_cycle"] = i - 1
                    ep["end_time"] = stamp
                    ep["duration_seconds"] = ep["end_time"] - ep["start_time"]
                    episodes.append(ep)
        loops.append({
            "i": i, "timestamp": stamp, "book_seconds": book_seconds,
            "cycle_seconds": time.monotonic() - cycle_t0, "requests": requests,
            "books": len(books), "errors": errors,
            "positive": rows,
        })
        time.sleep(SLEEP_SECONDS)

    end_stamp = time.time()
    for eid, ep in active_episode.items():
        ep["end_cycle"] = LOOPS - 1
        ep["end_time"] = end_stamp
        ep["duration_seconds"] = ep["end_time"] - ep["start_time"]
        ep["still_open_at_end"] = True
        episodes.append(ep)

    secs = [x["book_seconds"] for x in loops]
    positives = [r for x in loops for r in x["positive"]]
    actionable = [r for r in positives if r.get("actionable_paper")]
    near = []
    for x in loops:
        # Keep only positives in full detail; near misses are summarized from raw
        # basket sums where available in future versions.
        pass
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": {
            "short_days": SHORT_DAYS, "loops": LOOPS, "sleep_seconds": SLEEP_SECONDS,
            "min_edge": MIN_EDGE, "min_profit_usd": MIN_PROFIT_USD,
            "consecutive_snapshots_required": REQUIRE_CONSECUTIVE,
            "books_batched_parallel": True, "fees_cached": True, "no_orders": True,
            "warning": "scheduled end is not guaranteed capital-release time; this is paper observation only",
        },
        "inventory": {
            "active_events_fetched": len(events), "short_complete_events": len(recs),
            "tokens": len(tokens), "fee_coefficients": len(fee_cache),
        },
        "timing": {
            "discovery_seconds": discovery_seconds,
            "median_book_seconds": statistics.median(secs) if secs else None,
            "min_book_seconds": min(secs) if secs else None,
            "max_book_seconds": max(secs) if secs else None,
            "wall_seconds": time.time() - start_wall,
        },
        "summary": {
            "positive_snapshots": len(positives), "actionable_paper_snapshots": len(actionable),
            "positive_events": len({x["event_id"] for x in positives}),
            "actionable_events": len({x["event_id"] for x in actionable}),
            "episodes": len(episodes),
        },
        "episodes": sorted(episodes, key=lambda x: x["max_net_profit"], reverse=True),
        "actionable_examples": sorted(actionable, key=lambda x: x["depth_optimum"]["net_profit"], reverse=True)[:50],
        "positive_examples": sorted(positives, key=lambda x: x["depth_optimum"]["net_profit"], reverse=True)[:80],
        "loop_errors": [{"i": x["i"], "errors": x["errors"]} for x in loops if x["errors"]],
        "errors": {"discovery": discovery_errors, "fees": fee_errors},
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "inventory": out["inventory"], "timing": out["timing"], "summary": out["summary"],
        "episodes": out["episodes"][:15],
        "actionable": [{
            "event": x["title"], "hours": x["hours_to_scheduled_end"],
            "profit": x["depth_optimum"]["net_profit"], "edge": x["depth_optimum"]["net_edge_per_share"],
            "capital": x["depth_optimum"]["capital_required"],
            "consecutive": x["consecutive_positive_snapshots"],
        } for x in out["actionable_examples"][:15]],
    }, indent=2))


def num(x):
    try:
        return float(x or 0)
    except Exception:
        return 0.0


if __name__ == "__main__":
    main()
