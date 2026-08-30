#!/usr/bin/env python3
"""Current Polymarket liquidity-reward economics screen.

Purpose: rank *current* reward markets for a low-capital, single-sided,
near-band-edge quoting experiment. This is a screening primitive, NOT a PnL
backtest and NOT an APR claim.

Data:
- official public GET /rewards/markets/current reward configuration;
- Gamma market metadata;
- current CLOB books for both outcome tokens.

Method:
1. Fetch all current reward markets.
2. Keep a union of the highest absolute pools and highest pool/min-size ratios.
3. Fetch metadata + both token books.
4. Merge the YES and NO books into YES-price coordinates.
5. Compute the documented size-cutoff-adjusted midpoint using rewards_min_size.
6. Approximate current visible reward competition by applying the official
   distance scoring function to the *aggregated visible book*. Maker identities
   are unavailable, so this is a competition proxy, not the exact denominator.
7. Simulate one min-size bid on the cheaper outcome one tick inside the reward
   band. Inside 10%-90%, single-sided score is divided by 3 per official rules.
8. Report reward-share proxy, capital, queue ahead, volatility/volume context,
   and transparent risk flags.

No orders are placed.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("liquidity_reward_live_screen.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
MAX_REWARD_PAGES = 30
GAMMA_CHUNK = 20
BOOK_BATCH = 100
TOP_POOL = 180
TOP_DENSITY = 220
MIN_POOL = 2.0


def request_json(url: str, params=None, *, method="GET", body=None, retries=3):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    data = None if body is None else json.dumps(body).encode()
    headers = dict(UA)
    if data is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as ex:
            last = ex
            time.sleep(0.2 * (i + 1))
    raise last


def fnum(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def jlist(x):
    if isinstance(x, list):
        return x
    try:
        y = json.loads(x) if x else []
        return y if isinstance(y, list) else []
    except Exception:
        return []


def fetch_rewards():
    cursor = ""
    seen = {}
    errors = []
    pages = 0
    while cursor != "LTE=" and pages < MAX_REWARD_PAGES:
        try:
            d = request_json(f"{CLOB}/rewards/markets/current", {"next_cursor": cursor})
        except Exception as ex:
            errors.append({"page": pages, "cursor": cursor, "error": repr(ex)})
            break
        rows = d.get("data") or []
        if not rows:
            break
        for r in rows:
            cid = str(r.get("condition_id") or "")
            if cid and cid not in seen:
                seen[cid] = r
        cursor = d.get("next_cursor") or "LTE="
        pages += 1
    return list(seen.values()), errors, pages


def fetch_gamma(condition_ids):
    out = {}
    errors = []
    for i in range(0, len(condition_ids), GAMMA_CHUNK):
        chunk = condition_ids[i:i + GAMMA_CHUNK]
        params = [("condition_ids", c) for c in chunk] + [("limit", str(len(chunk) + 5))]
        try:
            rows = request_json(f"{GAMMA}/markets", params)
        except Exception as ex:
            errors.append({"chunk": i // GAMMA_CHUNK, "error": repr(ex)})
            continue
        for g in rows if isinstance(rows, list) else []:
            cid = str(g.get("conditionId") or "")
            if cid:
                out[cid] = g
        time.sleep(0.03)
    return out, errors


def fetch_books(token_ids):
    out = {}
    errors = []
    for i in range(0, len(token_ids), BOOK_BATCH):
        chunk = token_ids[i:i + BOOK_BATCH]
        try:
            rows = request_json(f"{CLOB}/books", method="POST", body=[{"token_id": t} for t in chunk])
        except Exception as ex:
            errors.append({"chunk": i // BOOK_BATCH, "error": repr(ex)})
            continue
        if isinstance(rows, list):
            for b in rows:
                aid = str(b.get("asset_id") or "")
                if aid:
                    out[aid] = b
        time.sleep(0.03)
    return out, errors


def levels(book, side):
    xs = []
    for z in (book or {}).get(side) or []:
        try:
            p = float(z["price"]); s = float(z["size"])
            if 0 < p < 1 and s > 0:
                xs.append((p, s))
        except Exception:
            pass
    return xs


def merge_yes_book(yes_book, no_book):
    """Return aggregated YES-coordinate bids/asks.

    YES bids stay bids. NO asks transform to YES bids at 1-q.
    YES asks stay asks. NO bids transform to YES asks at 1-q.
    """
    bids = defaultdict(float); asks = defaultdict(float)
    for p, s in levels(yes_book, "bids"):
        bids[round(p, 6)] += s
    for q, s in levels(no_book, "asks"):
        bids[round(1 - q, 6)] += s
    for p, s in levels(yes_book, "asks"):
        asks[round(p, 6)] += s
    for q, s in levels(no_book, "bids"):
        asks[round(1 - q, 6)] += s
    return sorted(bids.items(), reverse=True), sorted(asks.items())


def cutoff_price(levels_sorted, min_size):
    c = 0.0
    for p, s in levels_sorted:
        c += s
        if c >= min_size:
            return p
    return None


def score_side(levels_sorted, mid, v):
    if v <= 0:
        return 0.0
    q = 0.0
    for p, size in levels_sorted:
        dist = abs(p - mid)
        if dist <= v + 1e-12:
            q += ((v - dist) / v) ** 2 * size
    return q


def qmin_proxy(qbid, qask, mid):
    if 0.10 <= mid <= 0.90:
        return max(min(qbid, qask), max(qbid, qask) / 3.0)
    return min(qbid, qask)


def classify(g):
    tags = []
    for ev in g.get("events") or []:
        for t in ev.get("tags") or []:
            if isinstance(t, dict): tags.append(str(t.get("slug") or t.get("label") or "").lower())
            else: tags.append(str(t).lower())
    text = " ".join([str(g.get("category") or ""), str(g.get("question") or ""), str(g.get("slug") or ""), " ".join(tags)]).lower()
    if any(k in text for k in ("geopolit", "iran", "israel", "gaza", "ukraine", "russia", "ceasefire", "invad", "strike")):
        return "geopolitics"
    if any(k in text for k in ("temperature", "weather", "rainfall", "snowfall", "hurricane")):
        return "weather"
    if g.get("sportsMarketType") or any(k in text for k in ("sports", "mlb", "nfl", "nba", "nhl", "soccer", "tennis")):
        return "sports"
    if any(k in text for k in ("fed", "interest rate", "cpi", "inflation", "gdp", "unemployment")):
        return "macro"
    if any(k in text for k in ("bitcoin", "ethereum", "crypto", "btc", "eth", "solana")):
        return "crypto"
    return str(g.get("category") or "other").lower() or "other"


def parse_market(cid, reward, g, books):
    toks = [str(x) for x in jlist(g.get("clobTokenIds"))]
    outs = [str(x) for x in jlist(g.get("outcomes"))]
    if len(toks) != 2:
        return None
    yes_tok, no_tok = toks[0], toks[1]
    yb, nb = books.get(yes_tok), books.get(no_tok)
    if not yb or not nb:
        return None

    min_size = fnum(reward.get("rewards_min_size"))
    max_spread_c = fnum(reward.get("rewards_max_spread"))
    pool = fnum(reward.get("total_daily_rate"))
    if min_size <= 0 or max_spread_c <= 0 or pool <= 0:
        return None
    v = max_spread_c / 100.0

    bids, asks = merge_yes_book(yb, nb)
    adj_bid = cutoff_price(bids, min_size)
    adj_ask = cutoff_price(asks, min_size)
    if adj_bid is None or adj_ask is None or adj_ask <= adj_bid:
        return None
    mid = (adj_bid + adj_ask) / 2
    if not (0 < mid < 1):
        return None

    qbid = score_side(bids, mid, v)
    qask = score_side(asks, mid, v)
    comp = qmin_proxy(qbid, qask, mid)

    ticks = [fnum((yb or {}).get("tick_size"), 0), fnum((nb or {}).get("tick_size"), 0)]
    ticks = [x for x in ticks if x > 0]
    tick = min(ticks) if ticks else 0.001

    # Capital-efficient single-sided quote on cheaper outcome, one tick inside band.
    if not (0.10 <= mid <= 0.90):
        single_score = 0.0
        quote_outcome = None
        quote_price = None
        queue_ahead = None
        queue_at = None
    else:
        cheap_yes = mid <= 0.5
        cheap_mid = mid if cheap_yes else 1 - mid
        quote_price = cheap_mid - v + tick
        if quote_price <= 0 or quote_price >= cheap_mid:
            return None
        s = cheap_mid - quote_price
        raw_s = ((v - s) / v) ** 2 * min_size
        single_score = raw_s / 3.0
        quote_outcome = outs[0] if cheap_yes and outs else (outs[1] if len(outs) > 1 else ("YES" if cheap_yes else "NO"))
        own_book = yb if cheap_yes else nb
        own_bids = sorted(levels(own_book, "bids"), reverse=True)
        queue_ahead = sum(sz for p, sz in own_bids if p > quote_price + 1e-12)
        queue_at = sum(sz for p, sz in own_bids if abs(p - quote_price) <= 1e-12)

    reward_proxy = pool * single_score / (comp + single_score) if single_score > 0 else 0.0
    capital = min_size * quote_price if quote_price else None
    roi_proxy = reward_proxy / capital if capital and capital > 0 else 0.0
    queue_cover = queue_ahead / min_size if queue_ahead is not None and min_size else 0.0

    day_change = abs(fnum(g.get("oneDayPriceChange")))
    vol24 = fnum(g.get("volume24hr") or g.get("volume24hrClob"))
    cat = classify(g)
    risk_flags = []
    if cat == "geopolitics": risk_flags.append("geopolitics_external_sample_toxic")
    if day_change >= 0.05: risk_flags.append("price_moved_5pct_plus_1d")
    if vol24 >= 100_000: risk_flags.append("high_24h_flow")
    if queue_cover < 1: risk_flags.append("less_than_one_min_order_ahead")
    if mid < 0.10 or mid > 0.90: risk_flags.append("two_sided_required")

    # Transparent heuristic only: reward/capital, queue shelter, and price stability.
    shelter = min(3.0, 1.0 + max(0.0, queue_cover) / 5.0)
    stability = 1.0 / (1.0 + 10.0 * day_change)
    toxicity = 0.10 if cat == "geopolitics" else 1.0
    screen_score = roi_proxy * shelter * stability * toxicity

    return {
        "condition_id": cid,
        "market_id": g.get("id"),
        "question": g.get("question"),
        "slug": g.get("slug"),
        "category_screen": cat,
        "event_title": ((g.get("events") or [{}])[0] or {}).get("title") if g.get("events") else None,
        "pool_per_day": pool,
        "min_size": min_size,
        "max_spread_cents": max_spread_c,
        "mid_size_filtered": mid,
        "adjusted_bid": adj_bid,
        "adjusted_ask": adj_ask,
        "tick": tick,
        "visible_q_bid": qbid,
        "visible_q_ask": qask,
        "visible_qmin_proxy": comp,
        "quote_outcome": quote_outcome,
        "quote_price": quote_price,
        "single_min_order_qmin": single_score,
        "reward_per_day_proxy": reward_proxy,
        "required_capital": capital,
        "reward_to_capital_proxy": roi_proxy,
        "queue_ahead_shares": queue_ahead,
        "queue_at_quote_shares": queue_at,
        "queue_cover_min_orders": queue_cover,
        "volume_24h": vol24,
        "abs_one_day_price_change": day_change,
        "fees_enabled": bool(g.get("feesEnabled")),
        "fee_schedule": g.get("feeSchedule"),
        "sports_market_type": g.get("sportsMarketType"),
        "game_start_time": g.get("gameStartTime"),
        "end_date": g.get("endDate"),
        "risk_flags": risk_flags,
        "screen_score": screen_score,
    }


def main():
    rewards, reward_errors, pages = fetch_rewards()
    usable = [r for r in rewards if fnum(r.get("total_daily_rate")) >= MIN_POOL and fnum(r.get("rewards_min_size")) > 0]
    by_pool = sorted(usable, key=lambda r: fnum(r.get("total_daily_rate")), reverse=True)[:TOP_POOL]
    by_density = sorted(usable, key=lambda r: fnum(r.get("total_daily_rate")) / max(fnum(r.get("rewards_min_size")), 1), reverse=True)[:TOP_DENSITY]
    selected = {}
    for r in by_pool + by_density:
        selected[str(r.get("condition_id"))] = r

    gamma, gamma_errors = fetch_gamma(list(selected))
    token_ids = []
    for cid, g in gamma.items():
        for t in jlist(g.get("clobTokenIds")):
            token_ids.append(str(t))
    books, book_errors = fetch_books(list(dict.fromkeys(token_ids)))

    rows = []
    parse_errors = []
    for cid, reward in selected.items():
        g = gamma.get(cid)
        if not g:
            continue
        try:
            r = parse_market(cid, reward, g, books)
            if r:
                rows.append(r)
        except Exception as ex:
            if len(parse_errors) < 50:
                parse_errors.append({"condition_id": cid, "error": repr(ex)})

    rows.sort(key=lambda x: x["screen_score"], reverse=True)
    non_geo = [r for r in rows if r["category_screen"] != "geopolitics"]
    low_risk = [r for r in non_geo if not any(f in r["risk_flags"] for f in ("price_moved_5pct_plus_1d", "high_24h_flow", "less_than_one_min_order_ahead", "two_sided_required"))]

    pools = [fnum(r.get("total_daily_rate")) for r in rewards]
    total_capacity = sum(pools)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "reward_source": "public /rewards/markets/current",
            "book_source": "current CLOB /books for both outcome tokens",
            "midpoint": "size-cutoff-adjusted on merged YES/NO book",
            "quote": "one min-size bid on cheaper outcome, one tick inside reward band",
            "competition_warning": "visible_qmin_proxy uses aggregated public book; maker-level identities are unavailable, so reward_per_day_proxy is not exact earnings",
            "fill_warning": "single snapshot only; queue ahead and 1d move are context, not an adverse-selection model",
        },
        "landscape": {
            "reward_pages": pages,
            "reward_markets": len(rewards),
            "configured_daily_capacity": total_capacity,
            "median_pool": sorted(pools)[len(pools)//2] if pools else None,
            "markets_pool_ge_50": sum(p >= 50 for p in pools),
            "markets_pool_ge_200": sum(p >= 200 for p in pools),
            "selected_for_books": len(selected),
            "gamma_resolved": len(gamma),
            "books_resolved": len(books),
            "fully_scored": len(rows),
            "low_risk_non_geopolitics": len(low_risk),
        },
        "top_low_risk": low_risk[:50],
        "top_non_geopolitics": non_geo[:75],
        "top_all": rows[:100],
        "errors": {
            "rewards": reward_errors,
            "gamma": gamma_errors,
            "books": book_errors,
            "parse": parse_errors,
        },
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "landscape": out["landscape"],
        "top_low_risk": [
            {"q": r["question"], "cat": r["category_screen"], "pool": round(r["pool_per_day"],2),
             "capital": round(r["required_capital"],2) if r["required_capital"] else None,
             "reward_proxy": round(r["reward_per_day_proxy"],4),
             "roi_proxy": round(r["reward_to_capital_proxy"],4),
             "queue_x": round(r["queue_cover_min_orders"],1), "move1d": round(r["abs_one_day_price_change"],4)}
            for r in low_risk[:20]
        ],
        "errors": {k: v[:3] for k,v in out["errors"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
