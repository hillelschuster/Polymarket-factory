#!/usr/bin/env python3
"""Broader inventory of repeatable finite-horizon/state-constrained Polymarket events.

Research only. Scans recent Gamma event history and separates economically distinct
subtypes instead of treating Spotify/box office/sports as one-off examples.
"""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request
from collections import Counter,defaultdict
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}
OUT=Path("state_market_inventory_full.json")
START_MIN="2024-01-01T00:00:00Z"
MAX_EVENTS=12000

# Match titles/questions only. Rules are used for confirmation, not discovery, to
# avoid FAQ/resolution boilerplate creating false positives.
PATTERNS={
 "box_office_opening_weekend":[r"opening weekend box office",r"opening weekend.*gross",r"5-day opening weekend"],
 "box_office_cumulative_total":[r"total domestic gross by",r"domestic gross by",r"gross more than.*by",r"gross between.*by"],
 "box_office_year_leader":[r"highest grossing movie",r"highest-grossing movie",r"third highest grossing movie",r"calendar[- ]year.*gross"],
 "youtube_views":[r"\bviews?\b.*(?:day|week|hour)",r"(?:day|week|hour).*\bviews?\b",r"youtube.*\bviews?\b"],
 "subscriber_follower_threshold":[r"subscribers?.*(?:reach|million|by)",r"followers?.*(?:reach|million|by)"],
 "streaming_leader":[r"top spotify",r"most streamed",r"spotify.*(?:artist|song|album)"],
 "sports_total_leader":[
   r"most passing yards",r"passing yards leader",r"most rushing yards",r"rushing yards leader",
   r"most receiving yards",r"receiving yards leader",r"most passing touchdowns",r"passing touchdowns leader",
   r"home runs leader",r"most home runs",r"rbis? leader",r"runs leader",r"strikeouts? leader",
   r"golden boot",r"top goalscorer",r"most goals(?:\?|$| )",r"most total goals"
 ],
 "medal_leader":[r"most gold medals",r"most medals",r"medal count",r"3rd most medals"],
}

OBJECTIVE_HINTS=re.compile(r"the-numbers|box office mojo|youtube|spotify|official information from the (?:nfl|mlb|nba)|fifa|uefa|olympic|official.*statistics",re.I)
FINITE_HINTS=re.compile(r"opening weekend|first \d+ (?:hours?|days?|weeks?)|regular season|calendar year|by [A-Z][a-z]+ \d+|december 31|wrapped|olympics|world cup",re.I)


def get_json(url,params=None,timeout=30):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers=UA)
    last=None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
        except Exception as ex:
            last=ex
            if attempt<2:time.sleep(.4*(attempt+1))
    raise last


def core_text(ev):
    xs=[ev.get("title") or "",ev.get("slug") or ""]
    xs += [m.get("question") or "" for m in ev.get("markets") or []]
    return "\n".join(xs)


def rule_text(ev):
    xs=[ev.get("description") or "",ev.get("resolutionSource") or ""]
    for m in ev.get("markets") or []:
        xs.extend([m.get("description") or "",m.get("resolutionSource") or ""])
    return "\n".join(xs)


def classify(ev):
    core=core_text(ev); rules=rule_text(ev); title=(ev.get("title") or "")
    hits={fam:sum(bool(re.search(p,core,re.I)) for p in pats) for fam,pats in PATTERNS.items()}
    hits={k:v for k,v in hits.items() if v}
    if not hits:return None,0,hits
    fam=max(hits,key=hits.get)
    score=2*hits[fam]
    if any(re.search(p,title,re.I) for p in PATTERNS[fam]):score+=3
    joined=core+"\n"+rules
    if FINITE_HINTS.search(joined):score+=1
    if OBJECTIVE_HINTS.search(joined):score+=1
    return fam,score,hits


def compact(ev,fam,score,hits):
    markets=[]
    for m in ev.get("markets") or []:
        markets.append({
            "id":m.get("id"),"slug":m.get("slug"),"question":m.get("question"),
            "volume":m.get("volume"),"liquidity":m.get("liquidity"),"endDate":m.get("endDate"),
            "closed":m.get("closed"),"outcomePrices":m.get("outcomePrices"),
            "clobTokenIds":m.get("clobTokenIds"),"enableOrderBook":m.get("enableOrderBook"),
        })
    return {
        "id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),"family":fam,
        "score":score,"hits":hits,"closed":ev.get("closed"),"active":ev.get("active"),
        "volume":float(ev.get("volume") or 0),"liquidity":float(ev.get("liquidity") or 0),
        "creationDate":ev.get("creationDate"),"startDate":ev.get("startDate"),"endDate":ev.get("endDate"),
        "markets":markets,
    }


def scan(closed):
    out=[]; errors=[]; limit=100
    for offset in range(0,MAX_EVENTS,limit):
        params={"closed":str(closed).lower(),"limit":limit,"offset":offset,
                "order":"volume","ascending":"false","start_date_min":START_MIN}
        try:rows=get_json("https://gamma-api.polymarket.com/events",params)
        except Exception as ex:
            errors.append({"offset":offset,"error":repr(ex)});break
        if not isinstance(rows,list) or not rows:break
        for ev in rows:
            fam,score,hits=classify(ev)
            if fam and score>=5:out.append(compact(ev,fam,score,hits))
        if len(rows)<limit:break
        time.sleep(.02)
    return out,errors


def dedupe(rows):
    d={}
    for r in rows:
        k=str(r.get("id") or r.get("slug"))
        if k not in d or r["score"]>d[k]["score"]:d[k]=r
    return list(d.values())


def main():
    closed,ce=scan(True); active,ae=scan(False)
    rows=dedupe(closed+active)
    rows.sort(key=lambda x:(x["volume"],x["score"]),reverse=True)
    by=defaultdict(list)
    for r in rows:by[r["family"]].append(r)
    summary={}
    for fam,rs in by.items():
        closed_rs=[r for r in rs if r.get("closed")]
        liquid_closed=[r for r in closed_rs if r["volume"]>=10_000]
        summary[fam]={
            "events":len(rs),"closed":len(closed_rs),"closed_volume_ge_10k":len(liquid_closed),
            "total_volume":sum(r["volume"] for r in rs),
            "closed_total_volume":sum(r["volume"] for r in closed_rs),
            "median_closed_volume":sorted([r["volume"] for r in closed_rs])[len(closed_rs)//2] if closed_rs else 0,
            "top_closed":[{"title":r["title"],"slug":r["slug"],"volume":r["volume"]} for r in closed_rs[:30]],
            "top_active":[{"title":r["title"],"slug":r["slug"],"volume":r["volume"]} for r in rs if not r.get("closed")][:20],
        }
    result={
        "method":"2024+ Gamma events, up to 12k closed + 12k active ordered by volume; title/question deterministic filters",
        "start_min":START_MIN,"max_events_each":MAX_EVENTS,"errors":{"closed":ce,"active":ae},
        "candidate_count":len(rows),"family_summary":summary,"candidates":rows,
    }
    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({"candidate_count":len(rows),"family_summary":summary,"errors":result["errors"]},indent=2))

if __name__=="__main__":main()
