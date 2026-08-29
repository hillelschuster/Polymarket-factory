#!/usr/bin/env python3
"""Targeted inventory of repeated finite-horizon/state-constraint Polymarket families.

Purpose: rank research families by repeated independent events and dollar capacity.
This does NOT claim alpha. Public Gamma search only; no trading.
"""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request,statistics
from collections import defaultdict
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}
OUT=Path("state_family_inventory.json")

# Narrow queries + title filters reduce the false positives of generic regex scans.
FAMILIES={
    "opening_weekend_box_office":{
        "queries":["opening weekend box office","5-day opening weekend box office","4-day opening weekend box office"],
        "include":[r"opening weekend",r"box office"],
    },
    "youtube_view_counters":{
        "queries":["views on day 1","views in week 1","YouTube views MrBeast","# of views YouTube"],
        "include":[r"views?"],
    },
    "sports_stat_leaders":{
        "queries":["MLB home runs leader","MLB strikeouts leader","MLB wins leader","NBA assists leader","NBA points leader","NFL passing yards leader","NFL rushing yards leader","NFL passing touchdowns leader"],
        "include":[r"leader|most .*?(?:runs|strikeouts|wins|assists|points|yards|touchdowns)"],
    },
    "medal_accumulation":{
        "queries":["most medals Olympics","most gold medals Olympics"],
        "include":[r"medals?"],
    },
    "election_seat_accumulation":{
        "queries":["Senate seats after election","House seats after election","number of seats election"],
        "include":[r"seats?"],
    },
    "annual_public_rankings":{
        "queries":["Top Spotify Artist","highest grossing movie in"],
        "include":[r"spotify|highest grossing"],
    },
}

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)

def text(ev):
    parts=[ev.get("title") or "",ev.get("slug") or ""]
    for m in ev.get("markets") or []:parts.extend([m.get("question") or "",m.get("groupItemTitle") or ""])
    return " ".join(parts).lower()

def vol(ev):
    try:return float(ev.get("volume") or 0)
    except:return 0.0

def matches(ev,pats):
    t=text(ev)
    return all(re.search(p,t,re.I) for p in pats)

def main():
    found=defaultdict(dict); errors=[]
    for family,cfg in FAMILIES.items():
        for q in cfg["queries"]:
            for status in ("resolved","active"):
                for page in range(0,8):
                    params={"q":q,"events_status":status,"limit_per_type":50,"page":page,"keep_closed_markets":1,"search_tags":"false","search_profiles":"false"}
                    try:resp=get("https://gamma-api.polymarket.com/public-search",params)
                    except Exception as ex:
                        errors.append({"family":family,"query":q,"status":status,"page":page,"error":repr(ex)});break
                    rows=(resp.get("events") or []) if isinstance(resp,dict) else []
                    if not rows:break
                    for ev in rows:
                        if not matches(ev,cfg["include"]):continue
                        key=str(ev.get("id") or ev.get("slug"))
                        rec={"id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),"volume":vol(ev),"closed":bool(ev.get("closed")),"active":bool(ev.get("active")),"startDate":ev.get("startDate"),"endDate":ev.get("endDate"),"market_count":len(ev.get("markets") or []),"matched_queries":[]}
                        if key in found[family]:rec=found[family][key]
                        rec["matched_queries"]=sorted(set(rec.get("matched_queries",[])+[q]))
                        found[family][key]=rec
                    if not resp.get("hasMore"):break
                    time.sleep(.01)
    out={"families":{},"errors":errors}
    for family,d in found.items():
        rows=sorted(d.values(),key=lambda x:x["volume"],reverse=True)
        vols=[r["volume"] for r in rows]
        out["families"][family]={
            "events":len(rows),
            "resolved_or_closed":sum(bool(r["closed"]) for r in rows),
            "active":sum(bool(r["active"]) and not bool(r["closed"]) for r in rows),
            "total_volume":sum(vols),
            "median_event_volume":statistics.median(vols) if vols else 0,
            "events_ge_10k":sum(v>=10000 for v in vols),
            "events_ge_100k":sum(v>=100000 for v in vols),
            "events_ge_1m":sum(v>=1000000 for v in vols),
            "top_events":rows[:40],
        }
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    compact={f:{k:v[k] for k in ("events","resolved_or_closed","active","total_volume","median_event_volume","events_ge_10k","events_ge_100k","events_ge_1m")} for f,v in out["families"].items()}
    print(json.dumps({"families":compact,"errors":errors[:10]},indent=2))
if __name__=="__main__":main()
