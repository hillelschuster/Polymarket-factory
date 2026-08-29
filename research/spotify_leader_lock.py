#!/usr/bin/env python3
"""Executable-market side of Spotify cumulative leader-lock research.

Reads public Gamma/CLOB data only. No orders. The output answers a narrow question:
if an external model eventually produces probability p, what price/depth is actually
available after Polymarket taker fees?
"""
import datetime as dt
import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "polymarket-factory-research/1.0"}
CULTURE_TAKER_RATE = 0.05  # Polymarket Fee Structure V2; verify feesEnabled per market.


def get(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def arr(v):
    if isinstance(v, list):
        return v
    try:
        return json.loads(v or "[]")
    except Exception:
        return []


def find_bad_bunny(slug):
    ev = get("https://gamma-api.polymarket.com/events/slug/" + slug)
    for m in ev.get("markets") or []:
        s = ((m.get("groupItemTitle") or "") + " " + (m.get("question") or "")).lower()
        if "bad bunny" in s:
            ids = arr(m.get("clobTokenIds"))
            return ev, m, str(ids[0]) if ids else None
    raise RuntimeError("Bad Bunny market not found")


def book(token):
    try:
        return get("https://clob.polymarket.com/book", {"token_id": token})
    except Exception as ex:
        return {"error": repr(ex)}


def levels(side, reverse=False):
    xs = []
    for x in side or []:
        try:
            xs.append((float(x["price"]), float(x["size"])))
        except Exception:
            pass
    return sorted(xs, reverse=reverse)


def taker_fee_per_share(price, fee_rate=CULTURE_TAKER_RATE):
    return fee_rate * price * (1 - price)


def depth_to(asks, max_price, fees_enabled=True):
    shares = gross_cost = fees = 0.0
    used = []
    for price, size in asks:
        if price > max_price + 1e-12:
            break
        fee = taker_fee_per_share(price) * size if fees_enabled else 0.0
        shares += size
        gross_cost += price * size
        fees += fee
        used.append({"price": price, "size": size, "fee": fee})
    if not shares:
        return None
    all_in = gross_cost + fees
    return {
        "max_ask": max_price,
        "shares": shares,
        "gross_cost": gross_cost,
        "taker_fees": fees,
        "all_in_cost": all_in,
        "avg_price": gross_cost / shares,
        "avg_all_in_per_share": all_in / shares,
        "break_even_probability_if_held": all_in / shares,
        "levels": used,
    }


def ev_grid(depth):
    if not depth:
        return []
    a = depth["avg_all_in_per_share"]
    c = depth["all_in_cost"]
    shares = depth["shares"]
    rows = []
    for p in (0.90, 0.93, 0.95, 0.97, 0.99):
        ev_share = p - a
        rows.append({
            "p": p,
            "ev_per_share": ev_share,
            "expected_dollars": shares * ev_share,
            "expected_roi_on_all_in_capital": (shares * ev_share / c) if c else None,
        })
    return rows


def main():
    # 2025 history remains a useful optional calibration source if CLOB retains it.
    ev25, m25, t25 = find_bad_bunny("top-spotify-artist-2025-146")
    start = int(dt.datetime(2025, 8, 4, tzinfo=dt.timezone.utc).timestamp())
    end = int(dt.datetime(2025, 12, 5, tzinfo=dt.timezone.utc).timestamp())
    histories = {}
    for interval, fid in [("all", 60), ("1d", 60), ("1w", 60)]:
        try:
            histories[interval] = get(
                "https://clob.polymarket.com/prices-history",
                {"market": t25, "startTs": start, "endTs": end, "interval": interval, "fidelity": fid},
            )
        except Exception as ex:
            histories[interval] = {"error": repr(ex)}

    ev26, m26, t26 = find_bad_bunny("top-spotify-artist-2026")
    b26 = book(t26)
    asks = levels(b26.get("asks"))
    bids = levels(b26.get("bids"), reverse=True)

    # Gamma now exposes fee state/schedule per market. If the field is absent, use
    # Culture Fee Structure V2 as the conservative research assumption.
    fees_enabled_raw = m26.get("feesEnabled")
    fees_enabled = fees_enabled_raw is not False
    schedule = m26.get("feeSchedule")

    depth = {}
    for cap in (0.87, 0.88, 0.89, 0.90, 0.91, 0.92):
        d = depth_to(asks, cap, fees_enabled=fees_enabled)
        if d:
            d["ev_grid"] = ev_grid(d)
            depth[f"{cap:.2f}"] = d

    best_ask = asks[0] if asks else None
    best_bid = bids[0] if bids else None
    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fee_assumption": {
            "market_feesEnabled_raw": fees_enabled_raw,
            "market_feeSchedule": schedule,
            "fallback_category": "Culture",
            "fallback_taker_rate": CULTURE_TAKER_RATE,
            "formula": "shares * feeRate * p * (1-p)",
            "note": "Maker fills cost zero protocol fee; this file prices immediate taker execution conservatively.",
        },
        "2025": {
            "event_volume": ev25.get("volume"),
            "market_volume": m25.get("volume"),
            "question": m25.get("question"),
            "token": t25,
            "history": histories,
        },
        "2026": {
            "event_volume": ev26.get("volume"),
            "market_volume": m26.get("volume"),
            "question": m26.get("question"),
            "outcomePrices": m26.get("outcomePrices"),
            "conditionId": m26.get("conditionId"),
            "token": t26,
            "best_ask": best_ask,
            "best_bid": best_bid,
            "asks": asks,
            "bids": bids,
            "depth": depth,
        },
    }
    with open("spotify_leader_lock.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(json.dumps({
        "event_volume": ev26.get("volume"),
        "best_ask": best_ask,
        "best_bid": best_bid,
        "feesEnabled": fees_enabled_raw,
        "feeSchedule": schedule,
        "depth": {k: {x: v[x] for x in ("shares", "all_in_cost", "avg_all_in_per_share", "break_even_probability_if_held")} for k, v in depth.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
