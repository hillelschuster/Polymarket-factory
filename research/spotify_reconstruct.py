#!/usr/bin/env python3
"""Reconstruct Spotify YTD lead/feature streams from public point-in-time Kworb pages.

Research only. No trading. Current pages are fetched from Kworb; historical anchors
come from the Internet Archive. The script is intentionally small and fast-failing:
2026 anchors are attempted only for the serious current contenders, then historical
validation runs only if the current reconstruction is viable.
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
    "Bruno Mars": "0du5cEVh5yTK9QJze8zA0C",
    "The Weeknd": "1Xyo4u8uXC1ZmMpatF05PJ",
    "Ariana Grande": "66CXWjxzNUsdJxJ2JdwvnR",
    "Travis Scott": "0Y5tJX1MQlPlqiwlOH1tJY",
    "Billie Eilish": "6qqNVTkY8uBg9cP3Jd7DAH",
    "Justin Bieber": "1uNFoZAHBGtllmzznpCI3s",
}
ANCHOR_2026 = ("Bad Bunny", "Drake", "Taylor Swift", "Bruno Mars")
HISTORICAL_CORE = ("Taylor Swift", "Bad Bunny", "The Weeknd", "Drake")

# Official Spotify global order. These four reorder across years, which makes them
# a useful proxy-validation set instead of merely checking the eventual winner.
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
            self.row.append(html_lib.unescape(" ".join("".join(self.cell).split())))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def request_text(url: str, params=None, timeout=12, attempts=1) -> str:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as ex:
            last = ex
            if attempt + 1 < attempts:
                time.sleep(0.5)
    raise last


def request_json(url: str, params=None, timeout=10):
    return json.loads(request_text(url, params, timeout=timeout, attempts=1))


def num(s):
    if s is None:
        return None
    m = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", str(s))
    return float(m.group(0).replace(",", "")) if m else None


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
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", page)).split())
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
            return {"url": url, **parse_kworb(request_text(url, timeout=15, attempts=2))}
        except Exception as ex:
            errors.append(f"{url}: {ex!r}")
    raise RuntimeError("; ".join(errors))


def wayback_nearest(artist_id: str, target: dt.date):
    """Ask Wayback's availability API for one nearest snapshot, then parse it."""
    target_url = kworb_url(artist_id)
    stamp = target.strftime("%Y%m%d")
    errors = []
    for original in (target_url, kworb_url(artist_id, "www.kworb.net")):
        try:
            j = request_json(
                "https://archive.org/wayback/available",
                {"url": original, "timestamp": stamp},
                timeout=8,
            )
            c = (j.get("archived_snapshots") or {}).get("closest") or {}
            if not c.get("available"):
                errors.append({"original": original, "error": "no available snapshot"})
                continue
            ts = str(c.get("timestamp") or "")
            archived = str(c.get("url") or "").replace("http://", "https://")
            # id_ asks Wayback for the original payload without toolbar rewriting.
            if "/web/" in archived and "id_/" not in archived:
                archived = re.sub(r"(/web/\d+)(/)", r"\1id_\2", archived, count=1)
            stats = parse_kworb(request_text(archived, timeout=12, attempts=1))
            snap_date = dt.datetime.strptime(ts[:8], "%Y%m%d").date() if len(ts) >= 8 else None
            return {
                "target_date": target.isoformat(),
                "snapshot_date": snap_date.isoformat() if snap_date else None,
                "distance_days": abs((snap_date - target).days) if snap_date else None,
                "timestamp": ts,
                "original": original,
                "archive_url": archived,
                "stats": stats,
            }
        except Exception as ex:
            errors.append({"original": original, "error": repr(ex)})
    return {"target_date": target.isoformat(), "error": "no parseable nearest Wayback snapshot", "errors": errors}


def delta_stats(anchor: dict, current_or_archive: dict):
    try:
        a = anchor["stats"]["streams"]
        b = current_or_archive["streams"] if "streams" in current_or_archive else current_or_archive["stats"]["streams"]
    except Exception:
        return None
    return {
        k: float(b[k]) - float(a[k])
        for k in ("total", "lead", "solo", "feature")
        if a.get(k) is not None and b.get(k) is not None
    }


def main():
    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_note": "Kworb is third-party public data; Wayback snapshots are audit inputs, not official Spotify data.",
        "current": {},
        "jan1_2026": {},
        "ytd_2026": {},
        "historical_validation": {},
        "official_order": OFFICIAL_ORDER,
    }

    # Current data are cheap; collect a slightly wider field to avoid overlooking an outsider.
    for name, artist_id in ARTISTS.items():
        try:
            out["current"][name] = current_stats(artist_id)
        except Exception as ex:
            out["current"][name] = {"error": repr(ex)}

    # Expensive archive work only for the four economically relevant current outcomes.
    for name in ANCHOR_2026:
        cur = out["current"].get(name) or {}
        if "streams" not in cur:
            continue
        jan = wayback_nearest(ARTISTS[name], dt.date(2026, 1, 1))
        out["jan1_2026"][name] = jan
        d = delta_stats(jan, cur)
        if d:
            out["ytd_2026"][name] = {
                **d,
                "anchor_snapshot_date": jan.get("snapshot_date"),
                "anchor_distance_days": jan.get("distance_days"),
                "current_page_date": cur.get("page_date"),
                "current_daily": cur.get("daily"),
            }

    # Historical validation only if the archive path proved viable for current data.
    if len(out["ytd_2026"]) >= 2:
        for year in (2023, 2024, 2025):
            yr = {}
            for name in HISTORICAL_CORE:
                artist_id = ARTISTS[name]
                jan = wayback_nearest(artist_id, dt.date(year, 1, 1))
                nov = wayback_nearest(artist_id, dt.date(year, 11, 15))
                rec = {"jan": jan, "nov": nov}
                if "stats" in jan and "stats" in nov:
                    rec["jan_to_nov_delta"] = {
                        k: float(nov["stats"]["streams"][k]) - float(jan["stats"]["streams"][k])
                        for k in ("total", "lead", "solo", "feature")
                    }
                yr[name] = rec
            out["historical_validation"][str(year)] = yr

    with open("spotify_reconstruction.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(json.dumps({
        "ytd_2026": out["ytd_2026"],
        "jan_anchor_status": {
            n: {k: r.get(k) for k in ("snapshot_date", "distance_days", "error")}
            for n, r in out["jan1_2026"].items()
        },
        "historical_complete": {
            y: [n for n, r in yr.items() if "jan_to_nov_delta" in r]
            for y, yr in out["historical_validation"].items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
