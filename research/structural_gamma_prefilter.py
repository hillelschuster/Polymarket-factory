#!/usr/bin/env python3
"""Fast live structural-arbitrage screen.

Use Gamma bestAsk/bestBid to cheaply find only *possible* monotonicity inversions,
then hit the CLOB for exact asks/depth/fees on those candidates.

For subset ⊂ superset, the guaranteed basket is:
    YES(superset) + NO(subset) >= $1
Using binary complement mechanics, a necessary raw-price inversion is approximately:
    bestAsk_yes(superset) < bestBid_yes(subset)
Only such pairs are sent to exact CLOB verification.

Candidate relations are conservative:
1. same-event numeric threshold ladders from logical_constraint_inventory.py;
2. same-event explicit `by` / `before` deadline ladders from date_ladder_live_probe.py.

No apparent opportunity is promoted without exact CLOB asks and current fee stress.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# This script is invoked directly as `python research/structural_gamma_prefilter.py`.
# Put its own directory on sys.path so sibling research modules resolve in CI.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from logical_constraint_inventory import parse_threshold, decode_json_list, fnum
from date_ladder_live_probe import parse_question as parse_deadline, year_hint

OUT = Path("structural_gamma_prefilter.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
MAX_ACTIVE_EVENTS = 1800
MIN_EVENT_VOLUME = 1_000.0


def get(url: str, params: dict | None = None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def tokens(m):
    outs = [str(x).lower() for x in decode_json_list(m.get("outcomes"))]
    ts = decode_json_list(m.get("clobTokenIds"))
    try: yi = outs.index("yes")
    except ValueError: yi = 0
    try: ni = outs.index("no")
    except ValueError: ni = 1
    return (
        str(ts[yi]) if yi < len(ts) else None,
        str(ts[ni]) if ni < len(ts) else None,
    )


def px(x):
    try: return float(x)
    except Exception: return None


def market_base(ev, m):
    y, n = tokens(m)
    return {
        "event_id": ev.get("id"),
        "event_slug": ev.get("slug"),
        "event_title": ev.get("title"),
        "event_volume": fnum(ev.get("volume")),
        "event_neg_risk": bool(ev.get("negRisk") or ev.get("enableNegRisk")),
        "market_id": m.get("id"),
        "condition_id": m.get("conditionId"),
        "question": m.get("question"),
        "description": m.get("description"),
        "resolution_source": m.get("resolutionSource") or ev.get("resolutionSource"),
        "best_bid_yes_gamma": px(m.get("bestBid")),
        "best_ask_yes_gamma": px(m.get("bestAsk")),
        "yes_token": y,
        "no_token": n,
    }


def fetch_active():
    rows, errors, off = [], [], 0
    while len(rows) < MAX_ACTIVE_EVENTS:
        lim = min(100, MAX_ACTIVE_EVENTS - len(rows))
        try:
            b = get("https://gamma-api.polymarket.com/events", {
                "limit": lim, "offset": off,
                "active": "true", "closed": "false",
                "order": "volume", "ascending": "false",
            })
        except Exception as ex:
            errors.append({"offset": off, "error": repr(ex)})
            break
        if not isinstance(b, list) or not b:
            break
        rows.extend(b); off += len(b)
        if max((fnum(e.get("volume")) for e in b), default=0) < MIN_EVENT_VOLUME:
            break
    return rows, errors


def numeric_pairs(events):
    groups = defaultdict(list)
    for ev in events:
        if fnum(ev.get("volume")) < MIN_EVENT_VOLUME: continue
        for m in ev.get("markets") or []:
            if not (m.get("active") and not m.get("closed")): continue
            p = parse_threshold(m.get("question") or "")
            if not p: continue
            r = {**market_base(ev, m), **p}
            if not r["yes_token"] or not r["no_token"]: continue
            groups[(str(ev.get("id")), p["template"], p["direction"], p["currency"], p["unit"])].append(r)
    out = []
    for rs in groups.values():
        vals = sorted({r["threshold"] for r in rs})
        if len(vals) < 2: continue
        if any(sum(r["threshold"] == v for r in rs) != 1 for v in vals): continue
        rs = sorted(rs, key=lambda r: r["threshold"])
        for a, b in zip(rs, rs[1:]):
            if a["direction"] == "GE":
                sup, sub = a, b
            else:
                sub, sup = a, b
            out.append({"family": "numeric_threshold", "superset": sup, "subset": sub})
    return out


def deadline_pairs(events):
    groups = defaultdict(list)
    for ev in events:
        if fnum(ev.get("volume")) < MIN_EVENT_VOLUME: continue
        for m in ev.get("markets") or []:
            if not (m.get("active") and not m.get("closed")): continue
            p = parse_deadline(m.get("question") or "", year_hint(ev, m))
            if not p: continue
            r = {**market_base(ev, m), **p}
            if not r["yes_token"] or not r["no_token"]: continue
            groups[(str(ev.get("id")), p["template"])].append(r)
    out = []
    for rs in groups.values():
        ds = [r["deadline"] for r in rs]
        if len(set(ds)) < 2 or len(set(ds)) != len(ds): continue
        srcs = {str(r.get("resolution_source") or "").strip().lower() for r in rs if r.get("resolution_source")}
        if len(srcs) > 1: continue
        rs = sorted(rs, key=lambda r: r["deadline"])
        for early, late in zip(rs, rs[1:]):
            out.append({"family": "deadline_by_before", "superset": late, "subset": early})
    return out


def best_ask(token, cache):
    if token in cache: return cache[token]
    try:
        b = get("https://clob.polymarket.com/book", {"token_id": token})
        xs = []
        for a in b.get("asks") or []:
            try: xs.append((float(a["price"]), float(a["size"])))
            except Exception: pass
        cache[token] = min(xs, key=lambda z: z[0]) if xs else None
    except Exception:
        cache[token] = None
    return cache[token]


def fee_rate(condition_id, cache):
    if not condition_id: return 0.0
    if condition_id not in cache:
        try:
            d = get(f"https://clob.polymarket.com/clob-markets/{condition_id}")
            cache[condition_id] = fnum((d.get("fd") or {}).get("r"))
        except Exception:
            cache[condition_id] = 0.0
    return cache[condition_id]


def verify(pair, books, fees):
    sup, sub = pair["superset"], pair["subset"]
    ay = best_ask(sup["yes_token"], books)
    an = best_ask(sub["no_token"], books)
    if not ay or not an: return None
    py, sy = ay; pn, sn = an
    raw = py + pn
    fy = fn = 0.0
    if raw < 1:
        ry = fee_rate(sup.get("condition_id"), fees)
        rn = fee_rate(sub.get("condition_id"), fees)
        fy = ry * py * (1 - py)
        fn = rn * pn * (1 - pn)
    all_in = raw + fy + fn
    shares = min(sy, sn)
    return {
        "family": pair["family"],
        "event_id": sup["event_id"],
        "event_slug": sup["event_slug"],
        "event_title": sup["event_title"],
        "event_volume": sup["event_volume"],
        "event_neg_risk": sup["event_neg_risk"],
        "superset_question": sup["question"],
        "subset_question": sub["question"],
        "superset_condition_id": sup["condition_id"],
        "subset_condition_id": sub["condition_id"],
        "gamma_ask_superset_yes": sup["best_ask_yes_gamma"],
        "gamma_bid_subset_yes": sub["best_bid_yes_gamma"],
        "clob_ask_superset_yes": py,
        "clob_ask_subset_no": pn,
        "raw_cost": raw,
        "fee_cost": fy + fn,
        "all_in_cost": all_in,
        "net_edge_per_share": 1 - all_in,
        "common_top_size": shares,
        "top_level_max_net_profit": max(0.0, 1 - all_in) * shares,
        "requires_rules_audit": all_in < 1,
    }


def main():
    events, errors = fetch_active()
    pairs = numeric_pairs(events) + deadline_pairs(events)
    inversions = []
    for p in pairs:
        sup, sub = p["superset"], p["subset"]
        a = sup.get("best_ask_yes_gamma"); b = sub.get("best_bid_yes_gamma")
        if a is not None and b is not None and a < b:
            inversions.append(p)
    inversions.sort(key=lambda p: p["superset"]["event_volume"], reverse=True)

    books, fees = {}, {}
    verified = []
    for p in inversions:
        v = verify(p, books, fees)
        if v: verified.append(v)
    verified.sort(key=lambda x: x["all_in_cost"])
    positive = [x for x in verified if x["all_in_cost"] < 1]

    by_family = {}
    for fam in ("numeric_threshold", "deadline_by_before"):
        ps = [p for p in pairs if p["family"] == fam]
        inv = [p for p in inversions if p["family"] == fam]
        vv = [v for v in verified if v["family"] == fam]
        pos = [v for v in positive if v["family"] == fam]
        by_family[fam] = {
            "pairs": len(ps), "gamma_inversions": len(inv),
            "clob_verified": len(vv), "all_in_positive": len(pos),
        }

    out = {
        "method": {
            "relation": "subset implies superset",
            "guaranteed_basket": "YES(superset)+NO(subset) pays >= $1",
            "gamma_prefilter": "bestAsk_yes(superset) < bestBid_yes(subset)",
            "verification": "exact CLOB asks, top-level common size, current fd.r fee stress",
            "semantic_gate": "any all-in < $1 survivor still requires explicit rules audit",
        },
        "summary": {
            "active_events_scanned": len(events),
            "logical_pairs": len(pairs),
            "gamma_inversions": len(inversions),
            "clob_verified_inversions": len(verified),
            "all_in_positive": len(positive),
            "best_all_in": verified[0]["all_in_cost"] if verified else None,
            "best_top_level_profit": max((x["top_level_max_net_profit"] for x in positive), default=0.0),
        },
        "by_family": by_family,
        "positive_candidates": positive,
        "verified_inversions": verified,
        "errors": errors,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "summary": out["summary"],
        "by_family": by_family,
        "positive": [
            {"family": x["family"], "event": x["event_title"],
             "superset": x["superset_question"], "subset": x["subset_question"],
             "all_in": round(x["all_in_cost"], 6),
             "shares": round(x["common_top_size"], 3),
             "profit": round(x["top_level_max_net_profit"], 4)}
            for x in positive[:20]
        ],
        "errors": errors[:5],
    }, indent=2))


if __name__ == "__main__":
    main()
