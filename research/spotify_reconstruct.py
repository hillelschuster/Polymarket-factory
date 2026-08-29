#!/usr/bin/env python3
"""Reconstruct Spotify artist YTD lead/feature streams from public point-in-time pages.

Research only. No trading. Uses current Kworb pages plus Internet Archive snapshots.
The output is deliberately raw enough to audit before any probability model uses it.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = {"User-Agent": "polymarket-factory-research/1.0 (+public-data-audit)"}

ARTISTS = {
    "Bad Bunny": "4q3ewBCX7sLwd24euuV69X",
    "Drake": "3TVXtAsR1Inumwj472S9r4",
    "Taylor Swift": "06HL4z0CvFAxyc27GXpf02",
    "The Weeknd": "1Xyo4u8uXC1ZmMpatF05PJ",
    "Ariana Grande": "66CXWjxzNUsdJxJ2JdwvnR",
    "Travis Scott": "0Y5tJX1MQlPlqiwlOH1tJY",
    "Billie Eilish": "6qqNVTkY8uBg9cP3Jd7DAH",
    "Bruno Mars": "0du5cEVh5yTK9QJze8zA0C",
    "Justin Bieber": "1uNFoZAHBGtllmzznpCI3s",
}

# Same four artists occupy Spotify's official global top four in 2023-2025,
# with a different ordering each year. That makes them a clean proxy check.
OFFICIAL_ORDER = {
    2023: ["Taylor Swift", "Bad Bunny", "The Weeknd", "Drake"],
    2024: ["Taylor Swift", "The Weeknd", "Bad Bunny", "Drake"],
    2025: ["Bad Bunny", "Taylor Swift", "The Weeknd", "Drake"],
}


class RowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.in_cell = True
            self.cell = []
        elif tag == "tr":
            self.row = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            text = " ".join("".join(self.cell).split())
            self.row.append(html_lib.unescape(text))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def request_text(url: str, params=None, timeout=35) -> str:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as ex:
            last = ex
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise last


def request_json(url: str, params=None):
    return json.loads(request_text(url, params))


def num(s):
    if s is None:
        return None
    m = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", str(s))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def parse_kworb(page: str) -> dict:
    p = RowParser()
    p.feed(page)
    out = {}
    for row in p.rows:
        if not row:
            continue
        key = row[0].strip().lower()
        if key in {"streams", "daily"} and len(row) >= 5:
            out[key] = {
                "total": num(row[1]),
                "lead": num(row[2]),
                "solo": num(row[3]),
                "feature": num(row[4]),
            }
    text = re.sub(r"<[^>]+>", " ", page)
    text = " ".join(html_lib.unescape(text).split())
    m = re.search(r"Last updated:\s*(\d{4}/\d{2}/\d{2})", text, re.I)
    if m:
        out["page_date"] = m.group(1)
    if "streams" not in out:
        raise ValueError("Kworb Streams row not found")
    return out


def kworb_url(artist_id: str, host="kworb.net") -> str:
    return f"https://{host}/spotify/artist/{artist_id}_songs.html"


def current_stats(artist_id: str):
    errors = []
    for host in ("kworb.net", "www.kworb.net"):
        url = kworb_url(artist_id, host)
        try:
            return {"url": url, **parse_kworb(request_text(url))}
        except Exception as ex:
            errors.append(f"{url}: {ex!r}")
    raise RuntimeError("; ".join(errors))


def cdx_candidates(artist_id: str, start: dt.date, end: dt.date):
    rows = []
    for host in ("kworb.net", "www.kworb.net"):
        target = f"{host}/spotify/artist/{artist_id}_songs.html"
        params = {
            "url": target,
            "from": start.strftime("%Y%m%d"),
            "to": end.strftime("%Y%m%d"),
            "output": "json",
            "fl": "timestamp,original,statuscode,digest",
            "filter": "statuscode:200",
            "collapse": "digest",
        }
        try:
            data = request_json("https://web.archive.org/cdx/search/cdx", params)
            for r in data[1:] if isinstance(data, list) and data else []:
                if len(r) >= 2:
                    rows.append({"timestamp": r[0], "original": r[1], "host_query": host})
        except Exception as ex:
            rows.append({"error": repr(ex), "host_query": host})
    return rows


def closest_archive(artist_id: str, target: dt.date, radius_days=21):
    start = target - dt.timedelta(days=radius_days)
    end = target + dt.timedelta(days=radius_days)
    candidates = cdx_candidates(artist_id, start, end)
    valid = []
    for c in candidates:
        ts = c.get("timestamp")
        if not ts:
            continue
        try:
            d = dt.datetime.strptime(ts[:8], "%Y%m%d").date()
            valid.append((abs((d - target).days), d, c))
        except Exception:
            pass
    valid.sort(key=lambda x: (x[0], x[1]))
    errors = [c for c in candidates if "error" in c]
    for distance, snap_date, c in valid[:5]:
        archived = f"https://web.archive.org/web/{c['timestamp']}id_/{c['original']}"
        try:
            stats = parse_kworb(request_text(archived, timeout=45))
            return {
                "target_date": target.isoformat(),
                "snapshot_date": snap_date.isoformat(),
                "distance_days": distance,
                "timestamp": c["timestamp"],
                "original": c["original"],
                "archive_url": archived,
                "stats": stats,
                "cdx_errors": errors,
            }
        except Exception as ex:
            errors.append({"snapshot": c, "fetch_error": repr(ex)})
    return {
        "target_date": target.isoformat(),
        "error": "no parseable archive snapshot within radius",
        "candidate_count": len(valid),
        "errors": errors,
    }


def delta_stats(a: dict, b: dict):
    """b-a for stream counters."""
    try:
        sa, sb = a["stats"]["streams"], b["streams"] if "streams" in b else b["stats"]["streams"]
    except Exception:
        return None
    return {k: sb.get(k) - sa.get(k) for k in ("total", "lead", "solo", "feature") if sa.get(k) is not None and sb.get(k) is not None}


def main():
    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_note": "Kworb is third-party public data. Archive snapshots can be sparse and are not treated as authoritative Spotify data.",
        "current": {},
        "jan1_2026": {},
        "ytd_2026": {},
        "historical_validation": {},
        "official_order": OFFICIAL_ORDER,
    }

    # Current state and Jan-1 anchors for current contenders.
    for name, artist_id in ARTISTS.items():
        try:
            cur = current_stats(artist_id)
            out["current"][name] = cur
        except Exception as ex:
            out["current"][name] = {"error": repr(ex)}
            continue
        try:
            jan = closest_archive(artist_id, dt.date(2026, 1, 1), 24)
            out["jan1_2026"][name] = jan
            d = delta_stats(jan, cur)
            if d:
                out["ytd_2026"][name] = {
                    **d,
                    "anchor_snapshot_date": jan.get("snapshot_date"),
                    "current_page_date": cur.get("page_date"),
                    "current_daily": cur.get("daily"),
                }
        except Exception as ex:
            out["jan1_2026"][name] = {"error": repr(ex)}
        time.sleep(0.15)

    # Historical proxy check. Use Jan-1 and Nov-15 anchors for the same top four.
    core = list(OFFICIAL_ORDER[2023])
    for year in (2023, 2024, 2025):
        yr = {}
        for name in core:
            artist_id = ARTISTS[name]
            jan = closest_archive(artist_id, dt.date(year, 1, 1), 24)
            nov = closest_archive(artist_id, dt.date(year, 11, 15), 24)
            rec = {"jan": jan, "nov": nov}
            if "stats" in jan and "stats" in nov:
                rec["jan_to_nov_delta"] = {
                    k: nov["stats"]["streams"][k] - jan["stats"]["streams"][k]
                    for k in ("total", "lead", "solo", "feature")
                }
            yr[name] = rec
            time.sleep(0.15)
        out["historical_validation"][str(year)] = yr

    with open("spotify_reconstruction.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    compact = {"ytd_2026": out["ytd_2026"], "archive_errors": {}}
    for name, rec in out["jan1_2026"].items():
        if "error" in rec:
            compact["archive_errors"][name] = rec
    compact["historical_complete"] = {
        y: [name for name, r in yr.items() if "jan_to_nov_delta" in r]
        for y, yr in out["historical_validation"].items()
    }
    print(json.dumps(compact, indent=2))


if __name__ == "__main__":
    main()
