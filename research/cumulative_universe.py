#!/usr/bin/env python3
"""Discover repeated Polymarket market classes suitable for cumulative-state alpha.

Research only. Public Gamma API. No trading and no source-state reconstruction yet.
The purpose is pragmatic: estimate how many independent, liquid, historically
reconstructible candidate events exist before building a backtest.
"""
from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

BASE = "https://gamma-api.polymarket.com/events"
UA = {"User-Agent": "polymarket-factory-research/1.0"}
LIMIT = 500
MAX_EVENTS = 30000
MIN_VOLUME = 1000.0

# Narrow enough to avoid calling every binary market "cumulative", broad enough to
# discover recurring templates we have not anticipated.
FAMILIES = {
    "streaming_views_charts": [
        r"spotify", r"stream(?:ed|s|ing)?", r"youtube", r"\bviews?\b",
        r"billboard", r"download", r"chart", r"most[- ]watched",
    ],
    "box_office_sales": [
        r"box office", r"gross(?:ing)?", r"highest[- ]grossing", r"ticket sales",
        r"units sold", r"copies sold", r"sales total",
    ],
    "sports_season_totals": [
        r"regular season", r"season wins?", r"win total", r"\bwins?\b.*season",
        r"season.*\bwins?\b", r"goals? scored", r"home runs?", r"touchdowns?",
        r"strikeouts?", r"assists?", r"points? scored", r"scoring title",
        r"most goals", r"most points", r"most wins", r"statistical leader",
    ],
    "election_accumulation": [
        r"delegates?", r"electoral votes?", r"house seats?", r"senate seats?",
        r"seats? won", r"seat count", r"popular vote total", r"electoral college",
    ],
    "running_counts_rankings": [
        r"most .* in 20\d\d", r"top .* 20\d\d", r"#1 .* 20\d\d",
        r"number of .* by", r"how many .* by", r"total .* by",
        r"most .* by", r"highest .* by", r"leader .* by",
    ],
}

# Common false-positive structures that do not represent accumulated state.
EXCLUDE = [
    r"price of", r"above \$", r"below \$", r"between \$", r"market cap",
    r"mentions?", r"say .* during", r"tweet", r"truth social posts?",
    r"temperature", r"rainfall", r"snowfall", r"earthquake",
    r"game \d", r"match winner", r"moneyline", r"spread", r"first half",
]


def get(params):
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def event_text(e):
    parts = [e.get("title") or "", e.get("subtitle") or "", e.get("description") or ""]
    for m in e.get("markets") or []:
        parts.extend([m.get("question") or "", m.get("description") or "", m.get("groupItemTitle") or ""])
    return " ".join(parts).lower()


def classify(text):
    families = []
    reasons = []
    for family, pats in FAMILIES.items():
        hits = [p for p in pats if re.search(p, text, re.I)]
        if hits:
            families.append(family)
            reasons.extend(hits[:3])
    exclusions = [p for p in EXCLUDE if re.search(p, text, re.I)]
    return families, reasons, exclusions


def main():
    raw = []
    offset = 0
    while len(raw) < MAX_EVENTS:
        batch = get({
            "closed": "true",
            "limit": LIMIT,
            "offset": offset,
            "order": "volume",
            "ascending": "false",
        })
        if not batch:
            break
        raw.extend(batch)
        offset += len(batch)
        print(f"fetched={len(raw)}", flush=True)
        if len(batch) < LIMIT:
            break

    rows = []
    for e in raw:
        text = event_text(e)
        families, reasons, exclusions = classify(text)
        volume = num(e.get("volume"))
        if not families or volume < MIN_VOLUME:
            continue
        # Exclusion is a warning rather than a hard delete because an event can contain
        # both a valid season-total market and unrelated game markets.
        rows.append({
            "id": e.get("id"),
            "slug": e.get("slug"),
            "title": e.get("title"),
            "category": e.get("category"),
            "subcategory": e.get("subcategory"),
            "startDate": e.get("startDate"),
            "endDate": e.get("endDate"),
            "volume": volume,
            "market_count": len(e.get("markets") or []),
            "families": families,
            "match_reasons": reasons,
            "exclusion_warnings": exclusions,
        })

    rows.sort(key=lambda x: x["volume"], reverse=True)
    by_family = defaultdict(list)
    for row in rows:
        for f in row["families"]:
            by_family[f].append(row)

    summary = {
        "closed_events_scanned": len(raw),
        "min_event_volume": MIN_VOLUME,
        "candidate_events": len(rows),
        "family_counts": {f: len(v) for f, v in by_family.items()},
        "family_volume": {f: round(sum(r["volume"] for r in v), 2) for f, v in by_family.items()},
        "category_counts": dict(Counter((r.get("category") or "unknown") for r in rows)),
        "top_by_family": {
            f: [
                {k: r[k] for k in ("id", "slug", "title", "volume", "startDate", "endDate", "exclusion_warnings")}
                for r in v[:25]
            ]
            for f, v in by_family.items()
        },
    }

    with open("cumulative_universe.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "events": rows}, f, indent=2)
    with open("cumulative_universe.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "id", "slug", "title", "category", "subcategory", "startDate", "endDate",
            "volume", "market_count", "families", "match_reasons", "exclusion_warnings",
        ])
        w.writeheader()
        for r in rows:
            rr = dict(r)
            for k in ("families", "match_reasons", "exclusion_warnings"):
                rr[k] = " | ".join(rr[k])
            w.writerow(rr)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
