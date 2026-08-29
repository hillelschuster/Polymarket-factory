#!/usr/bin/env python3
"""Audited observed-series math for the 2026 Spotify leader-lock thesis.

No probability model and no trading. This file isolates the few observations that
matter economically: the Bad Bunny/Drake cumulative gap, its expansion/compression
regimes, and current lead-vs-feature stream composition.

Historical YTD observations are third-party Musical Moments (@MMoments001) figures
captured/reposted publicly. Current daily composition comes from Kworb artist pages.
Spotify itself uses a weighted artist stream count, so the all-credit YTD series is
NOT treated as the resolver score.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request
from html.parser import HTMLParser

UA = {"User-Agent": "polymarket-factory-research/1.0"}

# Values are streams, not probabilities. 2026-08-20 is independently visible in a
# public repost credited to @MMoments001. Earlier entries were manually audited from
# dated captures of the same tracker. Keep these inputs few and reviewable.
YTD_ALL_CREDIT = [
    {"date": "2026-02-19", "bad_bunny": 4_210_999_463, "drake": 2_614_409_091, "source": "MMoments001 dated capture"},
    {"date": "2026-03-26", "bad_bunny": 7_121_823_668, "drake": 4_415_340_091, "source": "MMoments001 dated capture"},
    {"date": "2026-05-21", "bad_bunny": 10_579_391_292, "drake": 8_126_972_557, "source": "MMoments001 dated capture"},
    {"date": "2026-05-28", "bad_bunny": 11_019_256_387, "drake": 8_803_247_096, "source": "MMoments001 dated capture"},
    {"date": "2026-08-20", "bad_bunny": 15_720_000_000, "drake": 13_950_000_000, "source": "MMoments001 via public repost"},
]

KWORB = {
    "bad_bunny": "https://kworb.net/spotify/artist/4q3ewBCX7sLwd24euuV69X_songs.html",
    "drake": "https://kworb.net/spotify/artist/3TVXtAsR1Inumwj472S9r4_songs.html",
    "taylor_swift": "https://kworb.net/spotify/artist/06HL4z0CvFAxyc27GXpf02_songs.html",
}


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=[]; self.in_cell=False
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row=[]
        if tag in ("td","th"): self.in_cell=True; self.cell=[]
    def handle_data(self, data):
        if self.in_cell: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split())); self.in_cell=False
        if tag == "tr" and self.row: self.rows.append(self.row); self.row=[]


def number(s):
    m=re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", s or "")
    return float(m.group(0).replace(",","")) if m else None


def kworb_daily(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA), timeout=20) as r:
        html=r.read().decode("utf-8","replace")
    p=Rows(); p.feed(html)
    for row in p.rows:
        if row and row[0].strip().lower()=="daily" and len(row)>=5:
            return {"total":number(row[1]), "lead":number(row[2]), "solo":number(row[3]), "feature":number(row[4])}
    raise ValueError("daily row not found")


def enrich_series():
    rows=[]
    for x in YTD_ALL_CREDIT:
        r=dict(x)
        r["gap_bad_bunny_minus_drake"] = r["bad_bunny"]-r["drake"]
        rows.append(r)
    segments=[]
    for a,b in zip(rows,rows[1:]):
        da=dt.date.fromisoformat(a["date"]); db=dt.date.fromisoformat(b["date"])
        days=(db-da).days
        # Positive => Drake caught up; negative => Bad Bunny expanded his lead.
        compression=a["gap_bad_bunny_minus_drake"]-b["gap_bad_bunny_minus_drake"]
        segments.append({
            "start":a["date"], "end":b["date"], "days":days,
            "gap_start":a["gap_bad_bunny_minus_drake"], "gap_end":b["gap_bad_bunny_minus_drake"],
            "gap_compression":compression,
            "drake_net_catchup_per_day":compression/days,
        })
    return rows,segments


def feature_share(d):
    if not d or not d.get("total"): return None
    return d.get("feature",0.0)/d["total"]


def main():
    series,segments=enrich_series()
    current={}
    for name,url in KWORB.items():
        try: current[name]=kworb_daily(url)
        except Exception as ex: current[name]={"error":repr(ex)}

    bb=current.get("bad_bunny",{}); dr=current.get("drake",{})
    composition={}
    if bb.get("total") and dr.get("total"):
        composition={
            "bad_bunny_feature_share_current_daily":feature_share(bb),
            "drake_feature_share_current_daily":feature_share(dr),
            "drake_minus_bad_bunny_total_daily":dr["total"]-bb["total"],
            "drake_minus_bad_bunny_lead_daily":dr["lead"]-bb["lead"],
            "drake_minus_bad_bunny_feature_daily":dr["feature"]-bb["feature"],
        }

    out={
        "status":"OBSERVED_NOT_RESOLVER_CALIBRATED",
        "method_caveat":"YTD series is third-party all-credit. Spotify ranks Top Artists using an unpublished weighted stream count with primary artists weighted more than featured artists.",
        "series":series,
        "segments":segments,
        "current_kworb_daily":current,
        "composition":composition,
        "derived_regimes":{
            "bad_bunny_positive_shock_feb19_mar26":next((s for s in segments if s["start"]=="2026-02-19"),None),
            "pre_drake_release_mar26_may21":next((s for s in segments if s["start"]=="2026-03-26"),None),
            "drake_release_shock_may21_may28":next((s for s in segments if s["start"]=="2026-05-21"),None),
            "post_release_may28_aug20":next((s for s in segments if s["start"]=="2026-05-28"),None),
        },
    }
    with open("spotify_observed_series.json","w",encoding="utf-8") as f: json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))

if __name__=="__main__": main()
