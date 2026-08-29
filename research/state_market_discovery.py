#!/usr/bin/env python3
"""Discover Polymarket event groups that plausibly fit the state-constraint thesis.

Research-only. Public Gamma API reads; no orders. The goal is a broad, reproducible
candidate universe before outcomes/models are inspected, not a perfect classifier.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

UA = {"User-Agent": "polymarket-factory-research/1.0"}
OUT = Path("state_market_candidates.json")

FAMILY_PATTERNS = {
    "public_counter": [
        r"\bviews?\b", r"\bsubscribers?\b", r"\bfollowers?\b", r"\bdownloads?\b",
    ],
    "streaming": [
        r"spotify", r"most[- ]streamed", r"top spotify", r"\bstreams?\b",
    ],
    "box_office": [
        r"highest[- ]grossing", r"box office", r"domestic gross", r"calendar gross",
    ],
    "medals": [
        r"most medals", r"medal count", r"athlete to win the most medals", r"3rd most medals",
    ],
    "sports_stat_leader": [
        r"scoring leader", r"yards leader", r"runs leader", r"home runs leader",
        r"wins leader", r"strikeouts? leader", r"touchdowns? leader", r"assists? leader",
        r"rebounds? leader", r"saves? leader", r"top scorer", r"top goalscorer",
        r"golden boot", r"most goals", r"most passing yards", r"most rushing yards",
        r"most receiving yards", r"most touchdowns", r"most runs", r"most home runs",
        r"most wins", r"most points scored", r"most total goals",
    ],
}

# Helps reject ordinary "most likely" / narrative markets that happen to contain "most".
STATE_WORDS = re.compile(
    r"views?|subscribers?|followers?|streams?|gross|box office|medals?|yards?|touchdowns?|"
    r"goals?|home runs?|runs?|wins?|strikeouts?|assists?|rebounds?|saves?|points scored|sales|downloads?",
    re.I,
)
FINITE_WORDS = re.compile(
    r"by .*\d{4}|by .*\d{1,2}:|first \d+ (?:hours?|days?|weeks?)|regular season|"
    r"calendar year|through all .* rounds|after .* hours?|end date|december 31|wrapped|olympics|world cup",
    re.I,
)
OBJECTIVE_SOURCE = re.compile(
    r"resolution source|official information|youtube|spotify|box office mojo|the-numbers|mlb|nfl|nba|fifa|uefa|olympic",
    re.I,
)


def get_json(url: str, params=None, timeout=30):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as ex:
            last = ex
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise last


def event_text(ev: dict) -> str:
    chunks = [ev.get("title") or "", ev.get("description") or "", ev.get("slug") or ""]
    for m in ev.get("markets") or []:
        chunks += [m.get("question") or "", m.get("description") or "", m.get("resolutionSource") or ""]
    return "\n".join(chunks)


def classify(text: str):
    low = text.lower()
    scores = {}
    for family, pats in FAMILY_PATTERNS.items():
        hits = sum(1 for p in pats if re.search(p, low, re.I))
        if hits:
            scores[family] = hits
    if not scores or not STATE_WORDS.search(text):
        return None, 0, scores
    family = max(scores, key=lambda k: scores[k])
    score = scores[family] * 2
    if FINITE_WORDS.search(text):
        score += 2
    if OBJECTIVE_SOURCE.search(text):
        score += 1
    title_line = low.split("\n", 1)[0]
    if any(re.search(p, title_line, re.I) for p in FAMILY_PATTERNS[family]):
        score += 2
    return family, score, scores


def compact_event(ev: dict, family: str, score: int, family_scores: dict):
    markets = []
    for m in ev.get("markets") or []:
        markets.append({
            "id": m.get("id"),
            "slug": m.get("slug"),
            "question": m.get("question"),
            "volume": m.get("volume"),
            "endDate": m.get("endDate"),
            "closed": m.get("closed"),
            "outcomePrices": m.get("outcomePrices"),
            "clobTokenIds": m.get("clobTokenIds"),
        })
    return {
        "id": ev.get("id"),
        "slug": ev.get("slug"),
        "title": ev.get("title"),
        "family": family,
        "score": score,
        "family_scores": family_scores,
        "closed": ev.get("closed"),
        "active": ev.get("active"),
        "volume": ev.get("volume"),
        "liquidity": ev.get("liquidity"),
        "startDate": ev.get("startDate"),
        "endDate": ev.get("endDate"),
        "markets": markets,
    }


def fetch_universe(closed: bool, max_events: int):
    found = []
    limit = 100
    for offset in range(0, max_events, limit):
        params = {"closed": str(closed).lower(), "limit": limit, "offset": offset}
        try:
            rows = get_json("https://gamma-api.polymarket.com/events", params)
        except Exception as ex:
            return found, {"offset": offset, "error": repr(ex)}
        if not isinstance(rows, list) or not rows:
            break
        for ev in rows:
            text = event_text(ev)
            family, score, scores = classify(text)
            if family and score >= 5:
                found.append(compact_event(ev, family, score, scores))
        if len(rows) < limit:
            break
        time.sleep(0.05)
    return found, None


def dedupe(rows):
    best = {}
    for r in rows:
        key = str(r.get("id") or r.get("slug"))
        if key not in best or r["score"] > best[key]["score"]:
            best[key] = r
    return list(best.values())


def main():
    closed_rows, closed_error = fetch_universe(True, 6000)
    active_rows, active_error = fetch_universe(False, 2000)
    rows = dedupe(closed_rows + active_rows)
    rows.sort(key=lambda r: (r["score"], float(r.get("volume") or 0)), reverse=True)

    family_counts = Counter(r["family"] for r in rows)
    family_closed = Counter(r["family"] for r in rows if r.get("closed"))
    volume_by_family = {}
    for fam in family_counts:
        volume_by_family[fam] = sum(float(r.get("volume") or 0) for r in rows if r["family"] == fam)

    out = {
        "method": "deterministic broad text/rule classifier; candidates require manual rule/state audit before backtest",
        "scanned_limits": {"closed": 6000, "active": 2000},
        "errors": {"closed": closed_error, "active": active_error},
        "candidate_count": len(rows),
        "family_counts": dict(family_counts),
        "closed_family_counts": dict(family_closed),
        "volume_by_family": volume_by_family,
        "candidates": rows[:750],
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    top = {}
    for fam in family_counts:
        top[fam] = [
            {"title": r["title"], "slug": r["slug"], "closed": r.get("closed"), "volume": r.get("volume"), "score": r["score"]}
            for r in rows if r["family"] == fam
        ][:15]
    print(json.dumps({
        "candidate_count": len(rows),
        "family_counts": dict(family_counts),
        "closed_family_counts": dict(family_closed),
        "volume_by_family": volume_by_family,
        "top": top,
        "errors": out["errors"],
    }, indent=2))


if __name__ == "__main__":
    main()
