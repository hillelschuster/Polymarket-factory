#!/usr/bin/env python3
"""Multi-event historical replication of complete NegRisk YES-basket underrounds.

Goal: determine whether the 2024 Presidency+Popular Vote case was isolated.

Pipeline
1. Discover high-volume closed, non-augmented NegRisk events with an explicit YES
   token for every outcome market.
2. Screen the last 72h before close using 10-minute YES price history. This is
   candidate discovery only, never executable proof.
3. For events whose sampled YES sum fell below 98.5c, fetch the public taker trade
   tape around the best sampled timestamp.
4. Require observed BUYs of YES in every leg inside 10/30/60/120 second windows.
5. Separately search for a *single wallet* completing all legs within those windows.
6. Stress each reconstructed basket with current category taker fees where a
   conservative category can be inferred; unknown category defaults to 5%.

Observed trades near each other still do not prove simultaneous hidden L2 depth,
but repeated all-leg and same-wallet sequences across independent events are much
stronger evidence than midpoint/history artifacts.

No orders are placed.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

OUT = Path("negrisk_multi_event_replication.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com/trades"

MAX_CLOSED_EVENTS = 1800
MAX_SCREEN_EVENTS = 90
MAX_CANDIDATES = 18
MAX_OUTCOMES = 10
MIN_VOLUME = 25_000.0
HISTORY_HOURS = 72
HISTORY_FIDELITY_MIN = 10
SCREEN_SUM = 0.985
TRADE_RADIUS_SECONDS = 30 * 60
TRADE_LIMIT = 500
MAX_OFFSET = 9500
WINDOWS = (10, 30, 60, 120)


def req(url, params=None, retries=3):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as ex:
            last = ex
            time.sleep(.15 * (i + 1))
    raise last


def num(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def jl(x):
    if isinstance(x, list):
        return x
    try:
        y = json.loads(x) if x else []
        return y if isinstance(y, list) else []
    except Exception:
        return []


def iso_ts(x):
    if not x:
        return None
    try:
        return int(dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def yes_info(m):
    outs = [str(x).casefold() for x in jl(m.get("outcomes"))]
    toks = [str(x) for x in jl(m.get("clobTokenIds"))]
    try:
        idx = outs.index("yes")
    except ValueError:
        return None
    if idx >= len(toks):
        return None
    return idx, toks[idx]


def fetch_closed():
    rows, errs, off = [], [], 0
    while len(rows) < MAX_CLOSED_EVENTS:
        lim = min(100, MAX_CLOSED_EVENTS - len(rows))
        try:
            b = req(GAMMA + "/events", {
                "limit": lim, "offset": off, "closed": "true",
                "order": "volume", "ascending": "false",
            })
        except Exception as ex:
            errs.append({"offset": off, "error": repr(ex)})
            break
        if not isinstance(b, list) or not b:
            break
        rows.extend(b)
        off += len(b)
        if len(b) < lim:
            break
    return rows, errs


def eligible(ev):
    ms = ev.get("markets") or []
    if not (ev.get("negRisk") or ev.get("enableNegRisk")):
        return False
    if ev.get("negRiskAugmented"):
        return False
    if num(ev.get("volume")) < MIN_VOLUME or not (2 <= len(ms) <= MAX_OUTCOMES):
        return False
    return all(yes_info(m) is not None for m in ms)


def category_rate(ev):
    text = " ".join([
        str(ev.get("category") or ""), str(ev.get("title") or ""), str(ev.get("slug") or "")
    ]).casefold()
    # Current 2026 fee coefficients. Geopolitics is fee free.
    if any(k in text for k in ("iran", "israel", "gaza", "ukraine", "russia", "ceasefire", "war", "strike")):
        return 0.0, "geopolitics"
    if any(k in text for k in ("president", "election", "senate", "house", "governor", "nominee", "vote")):
        return 0.04, "politics"
    if any(k in text for k in ("bitcoin", "ethereum", "crypto", "btc", "eth", "solana")):
        return 0.07, "crypto"
    if any(k in text for k in ("nfl", "nba", "mlb", "nhl", "soccer", "tennis", "match", "game", "wins?")):
        return 0.05, "sports"
    return 0.05, "other_conservative"


def event_close(ev):
    xs = [iso_ts(ev.get("closedTime")), iso_ts(ev.get("endDate"))]
    for m in ev.get("markets") or []:
        xs += [iso_ts(m.get("closedTime")), iso_ts(m.get("endDate"))]
    return max((x for x in xs if x), default=None)


def screen_event(ev):
    end = event_close(ev)
    if not end:
        return None
    start = end - HISTORY_HOURS * 3600
    series = {}
    errs = []
    markets = []
    for m in ev.get("markets") or []:
        yi = yes_info(m)
        if not yi:
            return None
        yes_idx, tok = yi
        try:
            h = req(CLOB + "/prices-history", {
                "market": tok, "startTs": start, "endTs": end,
                "interval": "max", "fidelity": HISTORY_FIDELITY_MIN,
            }).get("history") or []
        except Exception as ex:
            h = []
            errs.append({"condition_id": m.get("conditionId"), "error": repr(ex)})
        hm = {}
        for z in h:
            try:
                t = int(z["t"]); p = float(z["p"])
                bucket = t // (HISTORY_FIDELITY_MIN * 60)
                if bucket not in hm or t > hm[bucket][0]:
                    hm[bucket] = (t, p)
            except Exception:
                pass
        if not hm:
            return None
        series[tok] = hm
        markets.append({
            "condition_id": m.get("conditionId"), "question": m.get("question"),
            "groupItemTitle": m.get("groupItemTitle"), "yes_token": tok,
            "yes_outcome_index": yes_idx,
        })
    common = set.intersection(*(set(x) for x in series.values()))
    points = []
    for b in common:
        legs = []
        for m in markets:
            t, p = series[m["yes_token"]][b]
            legs.append({"condition_id": m["condition_id"], "t": t, "price": p})
        s = sum(x["price"] for x in legs)
        points.append({
            "t": max(x["t"] for x in legs), "sum_yes": s,
            "hours_to_close": (end - max(x["t"] for x in legs)) / 3600,
        })
    if not points:
        return None
    best = min(points, key=lambda x: x["sum_yes"])
    return {
        "event_id": ev.get("id"), "title": ev.get("title"), "slug": ev.get("slug"),
        "volume": num(ev.get("volume")), "end_ts": end, "markets": markets,
        "best_history": best, "screen_pass": best["sum_yes"] < SCREEN_SUM,
        "history_points": len(points), "errors": errs,
    }


def fetch_tape(condition_id, yes_idx, start, end):
    raw = []
    offset = 0
    oldest = None
    reached = False
    errs = []
    while offset <= MAX_OFFSET:
        try:
            b = req(DATA, {
                "market": condition_id, "takerOnly": "true",
                "limit": TRADE_LIMIT, "offset": offset,
            })
        except Exception as ex:
            errs.append({"offset": offset, "error": repr(ex)})
            break
        if not isinstance(b, list) or not b:
            break
        raw.extend(b)
        ts = []
        for x in b:
            try:
                ts.append(int(x.get("timestamp") or 0))
            except Exception:
                pass
        if ts:
            oldest = min(ts) if oldest is None else min(oldest, min(ts))
            if oldest <= start:
                reached = True
                break
        if len(b) < TRADE_LIMIT:
            break
        offset += TRADE_LIMIT
        time.sleep(.02)
    rows = []
    for x in raw:
        try:
            if str(x.get("side") or "").upper() != "BUY":
                continue
            if int(x.get("outcomeIndex")) != yes_idx:
                continue
            t = int(x["timestamp"]); p = float(x["price"]); sz = float(x.get("size") or 0)
            if start <= t <= end and 0 < p < 1 and sz > 0:
                rows.append({
                    "t": t, "price": p, "size": sz,
                    "wallet": x.get("proxyWallet"), "tx": x.get("transactionHash"),
                })
        except Exception:
            pass
    uniq = {(x["tx"], x["t"], x["price"], x["size"], x["wallet"]): x for x in rows}
    return sorted(uniq.values(), key=lambda x: x["t"]), {
        "raw_rows": len(raw), "oldest": oldest, "reached_start": reached,
        "last_offset": min(offset, MAX_OFFSET), "errors": errs,
    }


def fee_per_share(rate, p):
    return rate * p * (1 - p)


def pooled_sequences(by_leg, width, rate):
    times = sorted({x["t"] for rows in by_leg.values() for x in rows})
    out = {}
    for s in times:
        e = s + width
        chosen = {}
        for name, rows in by_leg.items():
            xs = [x for x in rows if s <= x["t"] <= e]
            if not xs:
                break
            chosen[name] = min(xs, key=lambda x: x["price"])
        if len(chosen) != len(by_leg):
            continue
        raw = sum(x["price"] for x in chosen.values())
        all_in = raw + sum(fee_per_share(rate, x["price"]) for x in chosen.values())
        if all_in >= 1:
            continue
        lo = min(x["t"] for x in chosen.values()); hi = max(x["t"] for x in chosen.values())
        common = min(x["size"] for x in chosen.values())
        k = tuple((n, chosen[n]["tx"], chosen[n]["t"]) for n in sorted(chosen))
        rec = {
            "raw_sum": raw, "all_in_sum_current_fee_stress": all_in,
            "net_edge_per_share": 1 - all_in, "span_seconds": hi - lo,
            "common_observed_size": common, "net_profit_at_common_size": (1 - all_in) * common,
            "legs": chosen,
        }
        if k not in out or rec["all_in_sum_current_fee_stress"] < out[k]["all_in_sum_current_fee_stress"]:
            out[k] = rec
    return sorted(out.values(), key=lambda x: (x["all_in_sum_current_fee_stress"], x["span_seconds"]))


def wallet_sequences(by_leg, width, rate):
    wallets = set.intersection(*[
        {x["wallet"] for x in rows if x.get("wallet")} for rows in by_leg.values()
    ]) if by_leg else set()
    out = []
    for w in wallets:
        sub = {k: [x for x in rows if x.get("wallet") == w] for k, rows in by_leg.items()}
        xs = pooled_sequences(sub, width, rate)
        for x in xs:
            x = dict(x)
            x["wallet"] = w
            out.append(x)
    return sorted(out, key=lambda x: (x["all_in_sum_current_fee_stress"], x["span_seconds"]))


def audit_candidate(c, ev):
    center = int(c["best_history"]["t"])
    start = center - TRADE_RADIUS_SECONDS
    end = center + TRADE_RADIUS_SECONDS
    by = {}
    coverage = {}
    for i, m in enumerate(c["markets"]):
        name = str(m.get("groupItemTitle") or m.get("question") or i)
        rows, cov = fetch_tape(m["condition_id"], m["yes_outcome_index"], start, end)
        by[name] = rows
        coverage[name] = cov
    rate, cat = category_rate(ev)
    pooled = {str(w): pooled_sequences(by, w, rate) for w in WINDOWS}
    wallet = {str(w): wallet_sequences(by, w, rate) for w in WINDOWS}
    return {
        **c, "fee_stress_rate": rate, "fee_category": cat,
        "trade_radius_seconds": TRADE_RADIUS_SECONDS,
        "coverage": coverage, "leg_trade_counts": {k: len(v) for k, v in by.items()},
        "pooled": pooled, "same_wallet": wallet,
        "summary": {
            "pooled_counts": {str(w): len(pooled[str(w)]) for w in WINDOWS},
            "same_wallet_counts": {str(w): len(wallet[str(w)]) for w in WINDOWS},
            "best_pooled_30s": pooled["30"][0] if pooled["30"] else None,
            "best_same_wallet_30s": wallet["30"][0] if wallet["30"] else None,
        },
    }


def main():
    events, discover_errs = fetch_closed()
    elig = sorted([e for e in events if eligible(e)], key=lambda e: num(e.get("volume")), reverse=True)[:MAX_SCREEN_EVENTS]
    screened = []
    screen_errs = []
    for i, ev in enumerate(elig):
        try:
            r = screen_event(ev)
            if r:
                screened.append((r, ev))
        except Exception as ex:
            screen_errs.append({"event_id": ev.get("id"), "error": repr(ex)})
        time.sleep(.02)
    candidates = [(r, ev) for r, ev in screened if r["screen_pass"]]
    candidates.sort(key=lambda z: (z[0]["best_history"]["sum_yes"], -z[0]["volume"]))
    candidates = candidates[:MAX_CANDIDATES]
    audited = []
    for r, ev in candidates:
        try:
            audited.append(audit_candidate(r, ev))
        except Exception as ex:
            audited.append({**r, "audit_error": repr(ex)})
    independent_with_pooled = [x for x in audited if any((x.get("summary") or {}).get("pooled_counts", {}).get(str(w), 0) for w in WINDOWS)]
    independent_with_wallet = [x for x in audited if any((x.get("summary") or {}).get("same_wallet_counts", {}).get(str(w), 0) for w in WINDOWS)]
    out = {
        "method": {
            "screen_events": MAX_SCREEN_EVENTS, "history_hours": HISTORY_HOURS,
            "history_fidelity_min": HISTORY_FIDELITY_MIN, "screen_sum": SCREEN_SUM,
            "trade_windows_seconds": list(WINDOWS), "current_fee_stress": True,
            "warning": "historical marks nominate windows only; trade reconstruction is the evidence gate",
        },
        "inventory": {
            "closed_events_fetched": len(events), "eligible_screened": len(elig),
            "usable_history": len(screened), "screen_candidates": len(candidates),
            "audited": len(audited), "independent_events_with_pooled_underround": len(independent_with_pooled),
            "independent_events_with_same_wallet_underround": len(independent_with_wallet),
        },
        "audited": audited,
        "screen_top": [r for r, _ in sorted(screened, key=lambda z: z[0]["best_history"]["sum_yes"])[:40]],
        "errors": {"discovery": discover_errs, "screen": screen_errs},
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "inventory": out["inventory"],
        "events": [{
            "title": x.get("title"), "history_sum": (x.get("best_history") or {}).get("sum_yes"),
            "hours_to_close": (x.get("best_history") or {}).get("hours_to_close"),
            "pooled": (x.get("summary") or {}).get("pooled_counts"),
            "same_wallet": (x.get("summary") or {}).get("same_wallet_counts"),
            "best30": ((x.get("summary") or {}).get("best_pooled_30s") or {}).get("all_in_sum_current_fee_stress"),
            "best_wallet30": ((x.get("summary") or {}).get("best_same_wallet_30s") or {}).get("all_in_sum_current_fee_stress"),
        } for x in audited],
        "errors": {k: v[:4] for k, v in out["errors"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
