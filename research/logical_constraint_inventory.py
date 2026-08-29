#!/usr/bin/env python3
"""Inventory conservative Polymarket logical-constraint families.

Research question: do independently traded binaries encode monotonic payoff relations
that are *not* the ordinary NegRisk mutually-exclusive basket identity?

This is discovery only. It deliberately prefers false negatives to semantic false
positives. Historical execution is tested in a separate script.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = {"User-Agent": "polymarket-factory-research/1.0"}
OUT = Path("logical_constraint_inventory.json")

# Keep the scan economically relevant and bounded for GitHub Actions.
MAX_CLOSED_EVENTS = 4000
MAX_ACTIVE_EVENTS = 1500
MIN_EVENT_VOLUME = 1_000.0

HIGH_WORDS = (
    "at least", "more than", "greater than", "above", "over", "exceed", "exceeds",
    "reach", "reaches", "hit", "hits", "or more", "or higher", "or above",
)
LOW_WORDS = (
    "at most", "less than", "fewer than", "below", "under", "or less", "or lower",
    "or below",
)

# Units where a larger numeric threshold has a clear ordering. We also permit no
# explicit unit when the same normalized question supplies the semantics.
UNIT_RE = r"(?:%|bps?|basis points?|[kmb]|thousand|million|billion|trillion|votes?|seats?|points?|goals?|wins?|losses?|runs?|yards?|touchdowns?|medals?|delegates?|mentions?|posts?|tweets?|views?|streams?|downloads?|subscribers?|members?|days?|hours?|minutes?|seconds?)?"
NUM_RE = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
CURRENCY_RE = r"[$€£]?"

# Comparator before threshold: "above $100k", "at least 50 seats".
PRE_RE = re.compile(
    rf"(?P<cmp>at\s+least|at\s+most|more\s+than|less\s+than|fewer\s+than|greater\s+than|above|over|below|under|exceeds?|reaches?|hits?)\s+"
    rf"(?P<currency>{CURRENCY_RE})\s*(?P<num>{NUM_RE})\s*(?P<unit>{UNIT_RE})",
    re.I,
)
# Threshold before comparator: "$100k or higher", "50 or more".
POST_RE = re.compile(
    rf"(?P<currency>{CURRENCY_RE})\s*(?P<num>{NUM_RE})\s*(?P<unit>{UNIT_RE})\s+"
    rf"(?P<cmp>or\s+more|or\s+higher|or\s+above|or\s+less|or\s+lower|or\s+below)",
    re.I,
)


def get(url: str, params: dict | None = None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def fnum(x) -> float:
    try:
        return float(x or 0)
    except Exception:
        return 0.0


def decode_json_list(x):
    if isinstance(x, list):
        return x
    if not x:
        return []
    try:
        y = json.loads(x)
        return y if isinstance(y, list) else []
    except Exception:
        return []


def canonical_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def scale_num(raw: str, unit: str) -> float:
    v = float(raw.replace(",", ""))
    u = canonical_spaces(unit)
    if u in ("k", "thousand"):
        v *= 1_000
    elif u in ("m", "million"):
        v *= 1_000_000
    elif u in ("b", "billion"):
        v *= 1_000_000_000
    elif u == "trillion":
        v *= 1_000_000_000_000
    return v


def direction(cmp_text: str) -> str | None:
    c = canonical_spaces(cmp_text)
    if c in HIGH_WORDS:
        return "GE"
    if c in LOW_WORDS:
        return "LE"
    return None


def parse_threshold(question: str):
    q = canonical_spaces(question)
    matches = list(PRE_RE.finditer(q)) + list(POST_RE.finditer(q))
    # Ambiguous questions with multiple threshold expressions are rejected.
    if len(matches) != 1:
        return None
    m = matches[0]
    d = direction(m.group("cmp"))
    if not d:
        return None
    unit = canonical_spaces(m.group("unit"))
    currency = m.group("currency") or ""
    value = scale_num(m.group("num"), unit)
    # Preserve unit/currency class to prevent apples-to-oranges grouping.
    unit_class = currency + (unit or "unitless")
    repl = f" <{d}:{unit_class}> "
    template = canonical_spaces(q[: m.start()] + repl + q[m.end() :])
    return {
        "direction": d,
        "threshold": value,
        "raw_threshold": m.group("num"),
        "unit": unit,
        "currency": currency,
        "template": template,
        "match": m.group(0),
    }


def fetch_events(active: bool, closed: bool, cap: int):
    rows = []
    offset = 0
    low_volume_streak = 0
    errors = []
    while len(rows) < cap:
        limit = min(100, cap - len(rows))
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "order": "volume",
            "ascending": "false",
        }
        try:
            batch = get("https://gamma-api.polymarket.com/events", params)
        except Exception as ex:
            errors.append({"offset": offset, "error": repr(ex)})
            break
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        batch_max = max((fnum(e.get("volume")) for e in batch), default=0)
        if batch_max < MIN_EVENT_VOLUME:
            low_volume_streak += 1
        else:
            low_volume_streak = 0
        # Two consecutive fully-low-volume pages are enough for this screening pass.
        if low_volume_streak >= 2:
            break
        time.sleep(0.01)
    return rows, errors


def market_record(ev, m, parsed):
    token_ids = decode_json_list(m.get("clobTokenIds"))
    outcomes = decode_json_list(m.get("outcomes"))
    yes_idx = next((i for i, x in enumerate(outcomes) if str(x).lower() == "yes"), 0)
    no_idx = next((i for i, x in enumerate(outcomes) if str(x).lower() == "no"), 1)
    return {
        "event_id": ev.get("id"),
        "event_slug": ev.get("slug"),
        "event_title": ev.get("title"),
        "event_volume": fnum(ev.get("volume")),
        "event_neg_risk": bool(ev.get("negRisk") or ev.get("enableNegRisk")),
        "market_id": m.get("id"),
        "condition_id": m.get("conditionId"),
        "question": m.get("question"),
        "slug": m.get("slug"),
        "volume": fnum(m.get("volume")),
        "liquidity": fnum(m.get("liquidity")),
        "active": bool(m.get("active")),
        "closed": bool(m.get("closed")),
        "start_date": m.get("startDate"),
        "end_date": m.get("endDate"),
        "resolution_source": m.get("resolutionSource"),
        "description": m.get("description"),
        "yes_token": token_ids[yes_idx] if yes_idx < len(token_ids) else None,
        "no_token": token_ids[no_idx] if no_idx < len(token_ids) else None,
        **parsed,
    }


def main():
    closed, err_closed = fetch_events(False, True, MAX_CLOSED_EVENTS)
    active, err_active = fetch_events(True, False, MAX_ACTIVE_EVENTS)

    by_id = {}
    for ev in closed + active:
        key = str(ev.get("id") or ev.get("slug"))
        if key not in by_id or fnum(ev.get("volume")) > fnum(by_id[key].get("volume")):
            by_id[key] = ev

    parsed_markets = []
    for ev in by_id.values():
        if fnum(ev.get("volume")) < MIN_EVENT_VOLUME:
            continue
        for m in ev.get("markets") or []:
            p = parse_threshold(m.get("question") or "")
            if p:
                parsed_markets.append(market_record(ev, m, p))

    # Highest-confidence family: same event + exact normalized threshold template.
    groups = defaultdict(list)
    for r in parsed_markets:
        groups[(str(r["event_id"]), r["template"], r["direction"], r["currency"], r["unit"])].append(r)

    ladders = []
    pairs = []
    for key, rows in groups.items():
        distinct = sorted({r["threshold"] for r in rows})
        if len(distinct) < 2:
            continue
        # Reject duplicate threshold definitions inside a supposed ladder; they often
        # indicate heterogeneous semantics hidden by text normalization.
        counts = {x: sum(r["threshold"] == x for r in rows) for x in distinct}
        if any(c != 1 for c in counts.values()):
            continue
        rows = sorted(rows, key=lambda r: r["threshold"])
        ladder = {
            "event_id": rows[0]["event_id"],
            "event_slug": rows[0]["event_slug"],
            "event_title": rows[0]["event_title"],
            "event_volume": rows[0]["event_volume"],
            "event_neg_risk": rows[0]["event_neg_risk"],
            "template": rows[0]["template"],
            "direction": rows[0]["direction"],
            "thresholds": distinct,
            "markets": rows,
        }
        ladders.append(ladder)
        for a, b in zip(rows, rows[1:]):
            # For GE: high threshold B is subset of low threshold A, requiring
            # P_yes(B) <= P_yes(A). For LE: low threshold A is subset of high B,
            # also requiring P_yes(A) <= P_yes(B).
            if a["direction"] == "GE":
                superset, subset = a, b
            else:
                subset, superset = a, b
            pairs.append({
                "event_id": a["event_id"],
                "event_slug": a["event_slug"],
                "event_title": a["event_title"],
                "event_volume": a["event_volume"],
                "event_neg_risk": a["event_neg_risk"],
                "template": a["template"],
                "direction": a["direction"],
                "superset": superset,
                "subset": subset,
                "identity": "P(subset) <= P(superset)",
                "arb_if": "ask_yes(superset) + ask_no(subset) < 1 after costs",
            })

    ladders.sort(key=lambda x: (x["event_volume"], len(x["markets"])), reverse=True)
    pairs.sort(key=lambda x: x["event_volume"], reverse=True)

    # Expose non-NegRisk separately: these are more interesting because the venue is
    # less likely to have a protocol conversion enforcing the relation.
    non_neg = [x for x in ladders if not x["event_neg_risk"]]
    out = {
        "method": {
            "scope": "top-volume active and closed Gamma events",
            "max_closed_events": MAX_CLOSED_EVENTS,
            "max_active_events": MAX_ACTIVE_EVENTS,
            "min_event_volume": MIN_EVENT_VOLUME,
            "constraint": "same-event exact normalized threshold template only",
            "note": "discovery only; prices are not tested here",
        },
        "scan": {
            "unique_events": len(by_id),
            "events_above_volume_floor": sum(fnum(e.get("volume")) >= MIN_EVENT_VOLUME for e in by_id.values()),
            "parsed_threshold_markets": len(parsed_markets),
            "ladders": len(ladders),
            "non_negrisk_ladders": len(non_neg),
            "adjacent_constraint_pairs": len(pairs),
        },
        "errors": err_closed + err_active,
        "ladders": ladders,
        "non_negrisk_ladders": non_neg,
        "pairs": pairs,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "scan": out["scan"],
        "top_non_negrisk": [
            {
                "event_id": x["event_id"],
                "title": x["event_title"],
                "volume": x["event_volume"],
                "direction": x["direction"],
                "thresholds": x["thresholds"],
                "markets": len(x["markets"]),
            }
            for x in non_neg[:20]
        ],
        "errors": out["errors"][:5],
    }, indent=2))


if __name__ == "__main__":
    main()
