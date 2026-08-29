#!/usr/bin/env python3
"""Focused inventory of Polymarket opening-weekend box-office event groups.

Search broadly, then fetch full Gamma event payloads and collapse extra strike sets
for the same movie/weekend into one independent event group. Research only.
"""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request
from collections import Counter,defaultdict
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}
OUT=Path("boxoffice_weekend_inventory.json")
QUERIES=["opening weekend box office","5-day opening weekend box office","4-day opening weekend box office"]

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)

def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or "[]")
    except:return []

def compact(ev):
    ms=[]
    for m in ev.get("markets") or []:
        ms.append({
            "id":m.get("id"),"conditionId":m.get("conditionId"),"slug":m.get("slug"),
            "question":m.get("question"),"groupItemTitle":m.get("groupItemTitle"),
            "description":m.get("description"),"resolutionSource":m.get("resolutionSource"),
            "volume":float(m.get("volume") or 0),"endDate":m.get("endDate"),"closed":m.get("closed"),
            "outcomes":arr(m.get("outcomes")),"outcomePrices":arr(m.get("outcomePrices")),
            "clobTokenIds":arr(m.get("clobTokenIds")),"enableOrderBook":m.get("enableOrderBook"),
        })
    return {
        "id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),
        "description":ev.get("description"),"resolutionSource":ev.get("resolutionSource"),
        "volume":float(ev.get("volume") or sum(m["volume"] for m in ms)),
        "liquidity":float(ev.get("liquidity") or 0),"closed":ev.get("closed"),"active":ev.get("active"),
        "creationDate":ev.get("creationDate"),"startDate":ev.get("startDate"),"endDate":ev.get("endDate"),
        "markets":ms,
    }

def rules_text(r):
    return "\n".join([r.get("description") or ""]+[m.get("description") or "" for m in r["markets"]])

def group_key(title):
    s=(title or "").lower().replace("“",'"').replace("”",'"').replace("'","")
    # Remove strike-set suffixes; keep 3/4/5-day distinction when explicit.
    s=re.sub(r"\s*\((?:even )?(?:higher|lower) (?:strikes|brackets)\)\s*"," ",s)
    s=re.sub(r"\s*\((?:higher|lower) strikes\)\s*"," ",s)
    s=re.sub(r"\s+"," ",s).strip()
    return s

def infer_weekend_type(r):
    txt=(r.get("title") or "")+"\n"+rules_text(r)
    low=txt.lower()
    if "5-day" in low:return "5-day"
    if "4-day" in low:return "4-day"
    if "3-day" in low:return "3-day"
    # Standard opening weekend is Fri-Sun; leave as standard-unconfirmed if rules omit label.
    return "standard-unconfirmed"

def infer_dates(r):
    txt=rules_text(r)
    # Preserve raw snippets rather than guessing date years.
    pats=[
        r"(?:3|4|5)-day opening weekend\s*\(([^\)]{5,50})\)",
        r"opening weekend\s*\(([^\)]{5,50})\)",
        r"(?:weekend|opening weekend)[^\n]{0,80}?(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\s*[-–]\s*(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+)?\d{1,2}",
    ]
    for p in pats:
        m=re.search(p,txt,re.I)
        if m:return m.group(0)
    return None

def fetch_full(slug):
    return get("https://gamma-api.polymarket.com/events/slug/"+urllib.parse.quote(slug,safe="-"))

def main():
    seeds={}; errors=[]; raw_shapes=[]
    for q in QUERIES:
        for status in ("resolved","active"):
            for page in range(0,20):
                params={"q":q,"events_status":status,"limit_per_type":50,"page":page,"keep_closed_markets":1,"search_tags":"false","search_profiles":"false"}
                try:resp=get("https://gamma-api.polymarket.com/public-search",params)
                except Exception as ex:
                    errors.append({"stage":"search","q":q,"status":status,"page":page,"error":repr(ex)});break
                if page==0:raw_shapes.append({"q":q,"status":status,"keys":list(resp) if isinstance(resp,dict) else None,"hasMore":resp.get("hasMore") if isinstance(resp,dict) else None})
                rows=(resp.get("events") or []) if isinstance(resp,dict) else []
                if not rows:break
                for ev in rows:
                    text=((ev.get("title") or "")+" "+(ev.get("slug") or "")).lower()
                    if "opening weekend" in text and ("box office" in text or "box-office" in text):
                        seeds[str(ev.get("id") or ev.get("slug"))]=ev
                if not resp.get("hasMore"):break
                time.sleep(.02)
    full=[]
    for i,ev in enumerate(seeds.values()):
        slug=ev.get("slug")
        try:r=compact(fetch_full(slug))
        except Exception as ex:
            errors.append({"stage":"enrich","slug":slug,"error":repr(ex)});r=compact(ev)
        r["weekend_type"]=infer_weekend_type(r);r["weekend_dates_raw"]=infer_dates(r);r["group_key"]=group_key(r["title"])
        full.append(r)
        if i%10==0:time.sleep(.05)
    full.sort(key=lambda x:x["volume"],reverse=True)
    groups=defaultdict(list)
    for r in full:groups[r["group_key"]].append(r)
    independent=[]
    for key,rs in groups.items():
        independent.append({
            "group_key":key,"titles":[r["title"] for r in rs],"slugs":[r["slug"] for r in rs],
            "weekend_types":sorted(set(r["weekend_type"] for r in rs)),"event_sets":len(rs),
            "closed":all(bool(r.get("closed")) for r in rs),"total_volume":sum(r["volume"] for r in rs),
            "end_dates":sorted(set(str(r.get("endDate")) for r in rs)),"weekend_dates_raw":sorted(set(str(r.get("weekend_dates_raw")) for r in rs)),
        })
    independent.sort(key=lambda x:x["total_volume"],reverse=True)
    summary={
        "search_events":len(full),"independent_groups":len(independent),
        "closed_independent_groups":sum(g["closed"] for g in independent),
        "closed_groups_ge_10k":sum(g["closed"] and g["total_volume"]>=10000 for g in independent),
        "weekend_types":dict(Counter(r["weekend_type"] for r in full)),
        "total_volume":sum(r["volume"] for r in full),
    }
    out={"summary":summary,"errors":errors,"raw_shapes":raw_shapes,"groups":independent,"events":full}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary,"groups":independent[:80],"errors":errors[:15]},indent=2))
if __name__=="__main__":main()
