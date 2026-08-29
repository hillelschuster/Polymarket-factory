#!/usr/bin/env python3
"""Focused inventory of Polymarket opening-weekend box-office event groups.

Uses Gamma public-search pagination because the generic events endpoint caps offsets.
Research only; no trading.
"""
from __future__ import annotations
import json,time,urllib.parse,urllib.request
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}
OUT=Path("boxoffice_weekend_inventory.json")
QUERIES=["opening weekend box office","5-day opening weekend box office","4-day opening weekend box office"]

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)

def event_rows(resp):
    if isinstance(resp,list):return resp
    if not isinstance(resp,dict):return []
    for key in ("events","event","results"):
        v=resp.get(key)
        if isinstance(v,list):return v
    # public-search may group results by type
    for v in resp.values():
        if isinstance(v,list) and v and isinstance(v[0],dict) and ("title" in v[0] or "slug" in v[0]):
            return v
    return []

def compact(ev):
    ms=[]
    for m in ev.get("markets") or []:
        ms.append({
            "id":m.get("id"),"slug":m.get("slug"),"question":m.get("question"),
            "description":m.get("description"),"resolutionSource":m.get("resolutionSource"),
            "volume":m.get("volume"),"endDate":m.get("endDate"),"closed":m.get("closed"),
            "outcomes":m.get("outcomes"),"outcomePrices":m.get("outcomePrices"),
            "clobTokenIds":m.get("clobTokenIds"),"enableOrderBook":m.get("enableOrderBook"),
        })
    return {
        "id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),
        "description":ev.get("description"),"resolutionSource":ev.get("resolutionSource"),
        "volume":float(ev.get("volume") or 0),"liquidity":float(ev.get("liquidity") or 0),
        "closed":ev.get("closed"),"active":ev.get("active"),"creationDate":ev.get("creationDate"),
        "startDate":ev.get("startDate"),"endDate":ev.get("endDate"),"markets":ms,
    }

def main():
    raw_shapes=[]; found={}; errors=[]
    for q in QUERIES:
        for status in ("closed","active"):
            for page in range(1,21):
                params={"q":q,"events_status":status,"limit_per_type":50,"page":page,"keep_closed_markets":"true"}
                try:resp=get("https://gamma-api.polymarket.com/public-search",params)
                except Exception as ex:
                    errors.append({"q":q,"status":status,"page":page,"error":repr(ex)});break
                if page==1:
                    raw_shapes.append({"q":q,"status":status,"type":type(resp).__name__,"keys":list(resp)[:20] if isinstance(resp,dict) else None})
                rows=event_rows(resp)
                if not rows:break
                added=0
                for ev in rows:
                    text=((ev.get("title") or "")+" "+(ev.get("slug") or "")).lower()
                    if "opening weekend" not in text or ("box office" not in text and "box-office" not in text):continue
                    k=str(ev.get("id") or ev.get("slug"))
                    found[k]=compact(ev);added+=1
                if len(rows)<50:break
                time.sleep(.03)
    rows=sorted(found.values(),key=lambda x:x["volume"],reverse=True)
    # Infer weekend length from rules text only; leave unknown instead of guessing.
    for r in rows:
        txt="\n".join([r.get("description") or ""]+[m.get("description") or "" for m in r["markets"]])
        low=txt.lower()
        r["weekend_type"]="5-day" if "5-day" in low else "4-day" if "4-day" in low else "3-day" if "3-day" in low else "unknown"
    summary={}
    for typ in ("3-day","4-day","5-day","unknown"):
        rs=[r for r in rows if r["weekend_type"]==typ]
        summary[typ]={"events":len(rs),"closed":sum(bool(r.get("closed")) for r in rs),"closed_ge_10k":sum(bool(r.get("closed")) and r["volume"]>=10000 for r in rs),"closed_volume":sum(r["volume"] for r in rs if r.get("closed"))}
    out={"queries":QUERIES,"raw_shapes":raw_shapes,"errors":errors,"event_count":len(rows),"summary":summary,"events":rows}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"event_count":len(rows),"summary":summary,"top":[{"title":r["title"],"slug":r["slug"],"closed":r["closed"],"volume":r["volume"],"weekend_type":r["weekend_type"]} for r in rows[:80]],"errors":errors[:10],"raw_shapes":raw_shapes},indent=2))
if __name__=="__main__":main()
