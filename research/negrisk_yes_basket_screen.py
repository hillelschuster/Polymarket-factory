#!/usr/bin/env python3
"""Screen Polymarket NegRisk YES-basket underrounds.

Why this exists:
- In a non-augmented NegRisk event exactly one listed market should resolve YES.
- Therefore one YES share of every outcome pays exactly $1 at resolution.
- If the executable cost of the complete YES basket is < $1 after taker fees, the
  payoff is deterministic, but capital may be locked until resolution because the
  NegRisk adapter primarily exposes the opposite conversion direction.

This script has two deliberately separated layers:
1) LIVE: current CLOB best asks + depth + current per-market fee curve. This is the
   only layer that calls an opportunity executable now.
2) HISTORICAL SCREEN: hourly CLOB price-history sums in the final 7 days. Those
   prices are screening data, not historical executable bid/ask proof.

Augmented NegRisk events are excluded because outcome definitions can change.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "polymarket-factory-research/1.0"}
OUT = Path("negrisk_yes_basket_screen.json")

MAX_CLOSED_SCAN = 2500
MAX_ACTIVE_SCAN = 1200
MAX_HIST_EVENTS = 120
MAX_LIVE_EVENTS = 120
MAX_OUTCOMES = 30
MIN_EVENT_VOLUME = 10_000.0
HIST_LOOKBACK_DAYS = 7
HIST_FIDELITY_MIN = 60


def request_json(url: str, params: dict | None = None, body=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    data = None
    headers = dict(UA)
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def fnum(x) -> float:
    try:
        return float(x or 0)
    except Exception:
        return 0.0


def jlist(x):
    if isinstance(x, list):
        return x
    if not x:
        return []
    try:
        y = json.loads(x)
        return y if isinstance(y, list) else []
    except Exception:
        return []


def iso_ts(x):
    if not x:
        return None
    try:
        s = str(x).replace("Z", "+00:00")
        return int(dt.datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def fetch_events(active: bool, closed: bool, cap: int):
    rows, errors = [], []
    offset = 0
    while len(rows) < cap:
        limit = min(100, cap - len(rows))
        try:
            batch = request_json("https://gamma-api.polymarket.com/events", {
                "limit": limit,
                "offset": offset,
                "active": str(active).lower(),
                "closed": str(closed).lower(),
                "order": "volume",
                "ascending": "false",
            })
        except Exception as ex:
            errors.append({"offset": offset, "error": repr(ex)})
            break
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if max((fnum(e.get("volume")) for e in batch), default=0) < MIN_EVENT_VOLUME:
            break
        time.sleep(0.005)
    return rows, errors


def yes_token(m):
    outcomes = [str(x).lower() for x in jlist(m.get("outcomes"))]
    toks = jlist(m.get("clobTokenIds"))
    if not toks:
        return None
    try:
        i = outcomes.index("yes")
    except ValueError:
        i = 0
    return str(toks[i]) if i < len(toks) else None


def eligible(ev):
    if not bool(ev.get("negRisk") or ev.get("enableNegRisk")):
        return False
    if bool(ev.get("negRiskAugmented")):
        return False
    if fnum(ev.get("volume")) < MIN_EVENT_VOLUME:
        return False
    ms = ev.get("markets") or []
    if not (2 <= len(ms) <= MAX_OUTCOMES):
        return False
    if any(not yes_token(m) for m in ms):
        return False
    return True


def event_record(ev):
    ms = ev.get("markets") or []
    return {
        "event_id": ev.get("id"),
        "slug": ev.get("slug"),
        "title": ev.get("title"),
        "volume": fnum(ev.get("volume")),
        "liquidity": fnum(ev.get("liquidity")),
        "active": bool(ev.get("active")),
        "closed": bool(ev.get("closed")),
        "negRisk": bool(ev.get("negRisk") or ev.get("enableNegRisk")),
        "negRiskAugmented": bool(ev.get("negRiskAugmented")),
        "endDate": ev.get("endDate"),
        "closedTime": ev.get("closedTime"),
        "markets": [
            {
                "id": m.get("id"),
                "condition_id": m.get("conditionId"),
                "question": m.get("question"),
                "groupItemTitle": m.get("groupItemTitle"),
                "volume": fnum(m.get("volume")),
                "liquidity": fnum(m.get("liquidity")),
                "yes_token": yes_token(m),
                "endDate": m.get("endDate"),
                "closedTime": m.get("closedTime"),
            }
            for m in ms
        ],
    }


def get_book(token):
    return request_json("https://clob.polymarket.com/book", {"token_id": token})


def best_ask(book):
    asks = book.get("asks") or []
    parsed = []
    for a in asks:
        try:
            parsed.append((float(a["price"]), float(a["size"])))
        except Exception:
            pass
    return min(parsed, key=lambda x: x[0]) if parsed else None


def fee_rate(condition_id):
    if not condition_id:
        return 0.0
    try:
        info = request_json(f"https://clob.polymarket.com/clob-markets/{condition_id}")
        fd = info.get("fd") or {}
        return fnum(fd.get("r"))
    except Exception:
        return 0.0


def live_probe(ev):
    rec = event_record(ev)
    legs, errors = [], []
    for m in rec["markets"]:
        try:
            ba = best_ask(get_book(m["yes_token"]))
        except Exception as ex:
            ba = None
            errors.append({"condition_id": m["condition_id"], "stage": "book", "error": repr(ex)})
        if not ba:
            return {**rec, "complete": False, "errors": errors, "reason": "missing_yes_ask"}
        p, size = ba
        r = fee_rate(m["condition_id"])
        fee_per_share = r * p * (1.0 - p)
        legs.append({
            "condition_id": m["condition_id"],
            "question": m["question"],
            "yes_token": m["yes_token"],
            "ask": p,
            "ask_size": size,
            "fee_rate": r,
            "fee_per_share": fee_per_share,
            "all_in_per_share": p + fee_per_share,
        })
    sum_ask = sum(x["ask"] for x in legs)
    sum_fee = sum(x["fee_per_share"] for x in legs)
    all_in = sum_ask + sum_fee
    size = min(x["ask_size"] for x in legs)
    return {
        **rec,
        "complete": True,
        "legs": legs,
        "sum_best_ask": sum_ask,
        "sum_fee_per_basket_share": sum_fee,
        "sum_all_in": all_in,
        "gross_edge_per_basket_share": 1.0 - sum_ask,
        "net_edge_per_basket_share": 1.0 - all_in,
        "best_level_capturable_shares": size,
        "best_level_net_profit_usd": size * max(0.0, 1.0 - all_in),
        "errors": errors,
    }


def price_history(token, start_ts, end_ts):
    d = request_json("https://clob.polymarket.com/prices-history", {
        "market": token,
        "startTs": start_ts,
        "endTs": end_ts,
        "interval": "max",
        "fidelity": HIST_FIDELITY_MIN,
    })
    return d.get("history") or []


def hist_screen(ev):
    rec = event_record(ev)
    end_candidates = [iso_ts(rec.get("closedTime")), iso_ts(rec.get("endDate"))]
    for m in rec["markets"]:
        end_candidates.extend([iso_ts(m.get("closedTime")), iso_ts(m.get("endDate"))])
    end_ts = max((x for x in end_candidates if x), default=None)
    if not end_ts:
        return {**rec, "usable": False, "reason": "no_end_timestamp"}
    start_ts = end_ts - HIST_LOOKBACK_DAYS * 86400

    series, errors = {}, []
    for m in rec["markets"]:
        try:
            hist = price_history(m["yes_token"], start_ts, end_ts)
        except Exception as ex:
            errors.append({"token": m["yes_token"], "error": repr(ex)})
            hist = []
        # One value per clock hour; retain the latest sample inside that hour.
        hmap = {}
        for p in hist:
            try:
                t = int(p["t"]); price = float(p["p"])
            except Exception:
                continue
            h = t // 3600
            if h not in hmap or t > hmap[h][0]:
                hmap[h] = (t, price)
        series[m["yes_token"]] = hmap

    if any(not x for x in series.values()):
        return {**rec, "usable": False, "reason": "one_or_more_empty_histories", "errors": errors}
    common = set.intersection(*(set(x.keys()) for x in series.values()))
    points = []
    for h in sorted(common):
        vals = [series[m["yes_token"]][h][1] for m in rec["markets"]]
        s = sum(vals)
        t = max(series[m["yes_token"]][h][0] for m in rec["markets"])
        points.append({
            "t": t,
            "hours_to_close": (end_ts - t) / 3600.0,
            "sum_yes_history_price": s,
            "gross_screen_edge": 1.0 - s,
        })

    under = [x for x in points if x["sum_yes_history_price"] < 1.0]
    stats = {}
    for cap in (0.99, 0.98, 0.97, 0.95):
        xs = [x for x in points if x["sum_yes_history_price"] <= cap]
        stats[str(cap)] = {
            "hours": len(xs),
            "first_hours_to_close": max((x["hours_to_close"] for x in xs), default=None),
            "last_hours_to_close": min((x["hours_to_close"] for x in xs), default=None),
        }
    return {
        **rec,
        "usable": bool(points),
        "screen_only": True,
        "screen_warning": "CLOB prices-history is not historical executable ask/depth proof",
        "common_hour_points": len(points),
        "underround_hours": len(under),
        "min_sum_yes": min((x["sum_yes_history_price"] for x in points), default=None),
        "max_gross_screen_edge": max((x["gross_screen_edge"] for x in points), default=None),
        "threshold_stats": stats,
        "best_points": sorted(under, key=lambda x: x["sum_yes_history_price"])[:12],
        "errors": errors,
    }


def main():
    closed_raw, ec = fetch_events(False, True, MAX_CLOSED_SCAN)
    active_raw, ea = fetch_events(True, False, MAX_ACTIVE_SCAN)
    closed = sorted((e for e in closed_raw if eligible(e)), key=lambda e: fnum(e.get("volume")), reverse=True)
    active = sorted((e for e in active_raw if eligible(e)), key=lambda e: fnum(e.get("volume")), reverse=True)

    live = []
    for ev in active[:MAX_LIVE_EVENTS]:
        live.append(live_probe(ev))
        time.sleep(0.005)

    hist = []
    for ev in closed[:MAX_HIST_EVENTS]:
        hist.append(hist_screen(ev))
        time.sleep(0.005)

    complete_live = [x for x in live if x.get("complete")]
    live_positive = [x for x in complete_live if fnum(x.get("net_edge_per_basket_share")) > 0]
    hist_usable = [x for x in hist if x.get("usable")]
    hist_2c = [x for x in hist_usable if (x.get("min_sum_yes") is not None and x["min_sum_yes"] <= 0.98)]

    out = {
        "method": {
            "non_augmented_only": True,
            "max_outcomes": MAX_OUTCOMES,
            "min_event_volume": MIN_EVENT_VOLUME,
            "historical_lookback_days": HIST_LOOKBACK_DAYS,
            "historical_fidelity_minutes": HIST_FIDELITY_MIN,
            "historical_is_screen_only": True,
        },
        "inventory": {
            "eligible_closed_found": len(closed),
            "eligible_active_found": len(active),
            "historical_events_screened": len(hist),
            "live_events_probed": len(live),
        },
        "live_summary": {
            "complete_baskets": len(complete_live),
            "positive_after_current_taker_fees": len(live_positive),
            "best": sorted(complete_live, key=lambda x: x.get("sum_all_in", 99))[:20],
        },
        "historical_summary": {
            "usable_events": len(hist_usable),
            "events_with_screen_sum_le_0_98": len(hist_2c),
            "best": sorted(hist_usable, key=lambda x: x.get("min_sum_yes") if x.get("min_sum_yes") is not None else 99)[:30],
        },
        "historical_events": hist,
        "live_events": live,
        "errors": ec + ea,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "inventory": out["inventory"],
        "live": {
            "complete": len(complete_live),
            "positive": len(live_positive),
            "top": [
                {"id": x["event_id"], "title": x["title"], "sum_all_in": round(x["sum_all_in"], 6), "shares": round(x["best_level_capturable_shares"], 3), "profit": round(x["best_level_net_profit_usd"], 4)}
                for x in sorted(complete_live, key=lambda x: x["sum_all_in"])[:10]
            ],
        },
        "historical": {
            "usable": len(hist_usable),
            "screen_le_0_98": len(hist_2c),
            "top": [
                {"id": x["event_id"], "title": x["title"], "volume": round(x["volume"], 0), "min_sum": x["min_sum_yes"], "under_hours": x["underround_hours"]}
                for x in sorted(hist_usable, key=lambda x: x["min_sum_yes"])[:12]
            ],
        },
        "errors": out["errors"][:5],
    }, indent=2))


if __name__ == "__main__":
    main()
