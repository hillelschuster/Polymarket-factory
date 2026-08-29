#!/usr/bin/env python3
"""Probe current executable monotonicity violations from logical_constraint_inventory.

For a proven payoff relation subset ⊂ superset:
  YES(superset) + NO(subset) pays at least $1 in every state.
So an immediately executable basket is structurally profitable iff its all-in ask cost
is < $1, subject to semantic/rules correctness and simultaneous fill risk.

This script uses current CLOB books and current per-market fee parameters. It does
NOT call a pair deployable merely because price < 1: candidates still require a
rules/resolution audit because the relation was inferred from market text.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

IN = Path("logical_constraint_inventory.json")
OUT = Path("logical_constraint_live_probe.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
MAX_PAIRS = 800


def get(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def fnum(x):
    try:
        return float(x or 0)
    except Exception:
        return 0.0


def best_ask(book):
    vals = []
    for a in book.get("asks") or []:
        try:
            vals.append((float(a["price"]), float(a["size"])))
        except Exception:
            pass
    return min(vals, key=lambda x: x[0]) if vals else None


def fee_rate(condition_id, cache):
    if not condition_id:
        return 0.0
    if condition_id not in cache:
        try:
            d = get(f"https://clob.polymarket.com/clob-markets/{condition_id}")
            cache[condition_id] = fnum((d.get("fd") or {}).get("r"))
        except Exception:
            cache[condition_id] = 0.0
    return cache[condition_id]


def token_ask(token, book_cache):
    if not token:
        return None
    if token not in book_cache:
        try:
            book_cache[token] = best_ask(get("https://clob.polymarket.com/book", {"token_id": token}))
        except Exception:
            book_cache[token] = None
    return book_cache[token]


def leg(m, side, book_cache, fee_cache):
    token = m.get("yes_token") if side == "YES" else m.get("no_token")
    ba = token_ask(token, book_cache)
    if not ba:
        return None
    p, size = ba
    r = fee_rate(m.get("condition_id"), fee_cache)
    fee = r * p * (1.0 - p)
    return {
        "side": side,
        "condition_id": m.get("condition_id"),
        "market_id": m.get("market_id"),
        "question": m.get("question"),
        "token": token,
        "ask": p,
        "ask_size": size,
        "fee_rate": r,
        "fee_per_share": fee,
        "all_in_per_share": p + fee,
    }


def main():
    inv = json.loads(IN.read_text(encoding="utf-8"))
    candidates = []
    seen = set()
    for p in inv.get("pairs") or []:
        sup, sub = p.get("superset") or {}, p.get("subset") or {}
        if not (sup.get("active") and sub.get("active")):
            continue
        if sup.get("closed") or sub.get("closed"):
            continue
        k = (sup.get("condition_id"), sub.get("condition_id"))
        if None in k or k in seen:
            continue
        seen.add(k)
        candidates.append(p)
    candidates.sort(key=lambda x: fnum(x.get("event_volume")), reverse=True)
    candidates = candidates[:MAX_PAIRS]

    book_cache, fee_cache = {}, {}
    probes, errors = [], []
    for p in candidates:
        sup, sub = p["superset"], p["subset"]
        a = leg(sup, "YES", book_cache, fee_cache)
        b = leg(sub, "NO", book_cache, fee_cache)
        if not a or not b:
            errors.append({
                "event_id": p.get("event_id"),
                "superset": sup.get("question"),
                "subset": sub.get("question"),
                "error": "missing executable ask",
            })
            continue
        raw = a["ask"] + b["ask"]
        fees = a["fee_per_share"] + b["fee_per_share"]
        all_in = raw + fees
        shares = min(a["ask_size"], b["ask_size"])
        probes.append({
            "event_id": p.get("event_id"),
            "event_slug": p.get("event_slug"),
            "event_title": p.get("event_title"),
            "event_volume": fnum(p.get("event_volume")),
            "event_neg_risk": bool(p.get("event_neg_risk")),
            "template": p.get("template"),
            "direction": p.get("direction"),
            "superset_threshold": sup.get("threshold"),
            "subset_threshold": sub.get("threshold"),
            "superset_question": sup.get("question"),
            "subset_question": sub.get("question"),
            "superset_resolution_source": sup.get("resolution_source"),
            "subset_resolution_source": sub.get("resolution_source"),
            "leg_yes_superset": a,
            "leg_no_subset": b,
            "raw_cost": raw,
            "fee_cost": fees,
            "all_in_cost": all_in,
            "minimum_payoff": 1.0,
            "net_edge_per_share": 1.0 - all_in,
            "top_level_common_shares": shares,
            "top_level_max_net_profit": max(0.0, 1.0 - all_in) * shares,
            "requires_rules_audit": all_in < 1.0,
        })

    probes.sort(key=lambda x: x["all_in_cost"])
    positive = [x for x in probes if x["all_in_cost"] < 1.0]
    positive_1c = [x for x in probes if x["all_in_cost"] <= 0.99]
    positive_2c = [x for x in probes if x["all_in_cost"] <= 0.98]
    out = {
        "method": {
            "identity": "subset implies superset; YES(superset)+NO(subset) pays >= $1",
            "pricing": "current CLOB best asks",
            "fees": "current per-condition fd.r * p * (1-p)",
            "capacity": "minimum top-of-book ask size across both legs",
            "semantic_gate": "every sub-$1 candidate requires manual/explicit rules verification",
            "max_pairs": MAX_PAIRS,
        },
        "summary": {
            "active_pairs_considered": len(candidates),
            "complete_executable_pairs": len(probes),
            "all_in_below_1": len(positive),
            "all_in_at_or_below_0_99": len(positive_1c),
            "all_in_at_or_below_0_98": len(positive_2c),
            "best_all_in": probes[0]["all_in_cost"] if probes else None,
            "best_top_level_profit": max((x["top_level_max_net_profit"] for x in positive), default=0.0),
        },
        "positive_candidates": positive,
        "best_50": probes[:50],
        "errors": errors,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "summary": out["summary"],
        "positive": [
            {
                "event_id": x["event_id"],
                "title": x["event_title"],
                "superset": x["superset_question"],
                "subset": x["subset_question"],
                "cost": round(x["all_in_cost"], 6),
                "edge": round(x["net_edge_per_share"], 6),
                "shares": round(x["top_level_common_shares"], 3),
                "profit": round(x["top_level_max_net_profit"], 4),
            }
            for x in positive[:20]
        ],
        "errors": errors[:5],
    }, indent=2))


if __name__ == "__main__":
    main()
