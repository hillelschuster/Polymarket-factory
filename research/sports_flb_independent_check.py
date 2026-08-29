#!/usr/bin/env python3
"""Independent falsification of the claimed Polymarket T-7d sports calibration edge.

External claim to test, not assume:
  MLB/NBA/NFL/NHL game-outcome favorites around 0.55-0.60 at ~7 days before game
  start resolve YES far more often than price implies.

This implementation intentionally does NOT import/reuse the external study code.
Primary discovery comes from Gamma sports metadata and sportsMarketType=moneyline.
Primary historical price comes from the YES token's CLOB price history at or before
T-7d. No post-anchor price is used for bucket selection.

This is a calibration falsification first, not an execution backtest. CLOB historical
prices do not establish historical ask/depth. If a large edge reproduces, a separate
trade/quote execution audit is required before any deployment conclusion.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

OUT = Path("sports_flb_independent_check.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
SPORTS = {"mlb", "nba", "nfl", "nhl"}
START_DATE_MIN = "2025-01-01T00:00:00Z"
MAX_EVENTS_PER_SPORT = 900
MIN_TOTAL_MARKET_VOLUME = 1_000.0
ANCHOR_DAYS = (7, 3, 1)
MAX_PRE_ANCHOR_AGE_HOURS = 24
BUCKETS = ((0.50,0.55),(0.55,0.60),(0.60,0.65),(0.65,0.70),(0.70,0.80),(0.80,0.90))


def get(url, params=None, retries=2):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers=UA)
            with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
        except Exception as ex:
            last=ex;time.sleep(0.15*(i+1))
    raise last


def fnum(x):
    try:return float(x or 0)
    except Exception:return 0.0


def jlist(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except Exception:return []


def ts(x):
    if not x:return None
    try:return int(dt.datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp())
    except Exception:return None


def yes_token(m):
    outs=[str(x).lower() for x in jlist(m.get("outcomes"))]; toks=jlist(m.get("clobTokenIds"))
    if not toks:return None
    try:i=outs.index("yes")
    except ValueError:i=0
    return str(toks[i]) if i<len(toks) else None


def resolved_yes(m):
    outs=[str(x).lower() for x in jlist(m.get("outcomes"))]; ps=jlist(m.get("outcomePrices"))
    if not ps:return None
    try:i=outs.index("yes")
    except ValueError:i=0
    try:p=float(ps[i])
    except Exception:return None
    if p>=0.99:return 1
    if p<=0.01:return 0
    return None


def game_start(ev,m):
    # Explicit sports clocks first; endDate is only a fallback and is flagged.
    for field,obj in (("gameStartTime",m),("eventStartTime",m),("eventStartTime",ev),("endDate",ev),("endDate",m)):
        t=ts(obj.get(field))
        if t:return t,field
    return None,None


def creation_ts(ev,m):
    for field,obj in (("createdAt",m),("creationDate",m),("startDate",m),("createdAt",ev),("creationDate",ev),("startDate",ev)):
        t=ts(obj.get(field))
        if t:return t,field
    return None,None


def fetch_sports_events(sport_code,tag_id):
    rows=[];off=0;errors=[]
    while len(rows)<MAX_EVENTS_PER_SPORT:
        lim=min(100,MAX_EVENTS_PER_SPORT-len(rows))
        params={"limit":lim,"offset":off,"closed":"true","tag_id":tag_id,"order":"end_date","ascending":"false","end_date_min":START_DATE_MIN}
        try:b=get("https://gamma-api.polymarket.com/events",params)
        except Exception as ex:errors.append({"sport":sport_code,"offset":off,"error":repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if len(b)<lim:break
    return rows,errors


def price_before(token,target):
    # Ask for 36h so a 24h stale-price gate can be applied after retrieval.
    try:d=get("https://clob.polymarket.com/prices-history",{"market":token,"startTs":target-36*3600,"endTs":target,"interval":"max","fidelity":30})
    except Exception as ex:return None,{"error":repr(ex)}
    pts=[]
    for p in d.get("history") or []:
        try:
            t=int(p["t"]);pr=float(p["p"])
            if t<=target:pts.append((t,pr))
        except Exception:pass
    if not pts:return None,{"error":"no_pre_anchor_history"}
    t,pr=max(pts,key=lambda z:z[0]);age=(target-t)/3600
    if age>MAX_PRE_ANCHOR_AGE_HOURS:return None,{"error":"stale_pre_anchor_price","age_hours":age}
    return {"timestamp":t,"price":pr,"age_hours":age},None


def wilson(k,n,z=1.96):
    if not n:return (None,None)
    p=k/n;den=1+z*z/n;ctr=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return ctr-half,ctr+half


def summarize(rows):
    out=[]
    for lo,hi in BUCKETS:
        xs=[r for r in rows if lo<=r["price"]<hi]
        if not xs:
            out.append({"bucket":[lo,hi],"n":0});continue
        k=sum(r["resolved_yes"] for r in xs);mp=statistics.mean(r["price"] for r in xs);wr=k/len(xs);ci=wilson(k,len(xs))
        out.append({"bucket":[lo,hi],"n":len(xs),"wins":k,"mean_price":mp,"realized_yes_rate":wr,"calibration_pp":100*(wr-mp),"wilson95":[ci[0],ci[1]]})
    return out


def main():
    errors=[]
    sports_meta=get("https://gamma-api.polymarket.com/sports")
    chosen={}
    for s in sports_meta:
        code=str(s.get("sport") or "").lower()
        if code in SPORTS:
            chosen[code]=s
    missing=sorted(SPORTS-set(chosen))
    if missing:errors.append({"missing_sports_metadata":missing})

    events=[]
    for sport,s in chosen.items():
        tag=s.get("primaryTagId")
        if not tag:
            # Prefer the last specific tag rather than broad sports/category tags.
            parts=[x for x in str(s.get("tags") or "").split(",") if x.strip()]
            tag=parts[-1] if parts else None
        if not tag:
            errors.append({"sport":sport,"error":"no_tag"});continue
        es,errs=fetch_sports_events(sport,tag);errors.extend(errs)
        for ev in es:ev["_sport_code"]=sport
        events.extend(es)

    # Deduplicate events returned through overlapping tags.
    byid={str(e.get("id") or e.get("slug")):e for e in events};events=list(byid.values())
    candidates=[];type_counts=defaultdict(int)
    for ev in events:
        sport=ev.get("_sport_code")
        for m in ev.get("markets") or []:
            mt=str(m.get("sportsMarketType") or "").lower();type_counts[mt]+=1
            if mt!="moneyline":continue
            if fnum(m.get("volume"))<MIN_TOTAL_MARKET_VOLUME:continue
            y=resolved_yes(m);tok=yes_token(m)
            if y is None or not tok:continue
            gs,gs_field=game_start(ev,m);cr,cr_field=creation_ts(ev,m)
            if not gs or not cr:continue
            lifespan=(gs-cr)/86400
            if lifespan<0:continue
            candidates.append({"sport":sport,"event_id":ev.get("id"),"event_slug":ev.get("slug"),"event_title":ev.get("title"),"market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),"market_volume":fnum(m.get("volume")),"yes_token":tok,"resolved_yes":y,"game_start":gs,"game_start_field":gs_field,"creation":cr,"creation_field":cr_field,"lifespan_days":lifespan})

    rows_by_anchor={d:[] for d in ANCHOR_DAYS};price_errors=[]
    for idx,r in enumerate(candidates):
        for days in ANCHOR_DAYS:
            target=r["game_start"]-days*86400
            if r["creation"]>target:continue
            ph,err=price_before(r["yes_token"],target)
            if err:
                # Keep only a bounded diagnostic sample.
                if len(price_errors)<100:price_errors.append({"sport":r["sport"],"market_id":r["market_id"],"anchor_days":days,**err})
                continue
            rows_by_anchor[days].append({**r,"anchor_days":days,"target_ts":target,**ph})
        if idx%100==0:time.sleep(0.02)

    result={}
    for days,rows in rows_by_anchor.items():
        strict=[r for r in rows if r["lifespan_days"]<=14]
        bysport={s:summarize([r for r in strict if r["sport"]==s]) for s in sorted(SPORTS)}
        result[str(days)]={"all_lifespan":summarize(rows),"lifespan_le_14d":summarize(strict),"by_sport_lifespan_le_14d":bysport,"n_prices":len(rows),"n_strict":len(strict)}

    target_rows=[r for r in rows_by_anchor[7] if r["lifespan_days"]<=14 and 0.55<=r["price"]<0.60]
    k=sum(r["resolved_yes"] for r in target_rows);mp=statistics.mean([r["price"] for r in target_rows]) if target_rows else None
    primary={"n":len(target_rows),"wins":k,"mean_price":mp,"realized_yes_rate":k/len(target_rows) if target_rows else None,"calibration_pp":100*(k/len(target_rows)-mp) if target_rows else None,"wilson95":list(wilson(k,len(target_rows))) if target_rows else [None,None],"by_sport":{}}
    for s in sorted(SPORTS):
        xs=[r for r in target_rows if r["sport"]==s];kk=sum(r["resolved_yes"] for r in xs);m=statistics.mean([r["price"] for r in xs]) if xs else None
        primary["by_sport"][s]={"n":len(xs),"wins":kk,"mean_price":m,"realized_yes_rate":kk/len(xs) if xs else None,"calibration_pp":100*(kk/len(xs)-m) if xs else None}

    out={"method":{"independent_implementation":True,"sports":sorted(SPORTS),"sports_market_type":"moneyline","history_price":"last CLOB historical YES price at/before anchor; max 24h stale","anchor":"explicit gameStartTime/eventStartTime preferred; event/market endDate fallback flagged","primary_bucket":[0.55,0.60],"primary_anchor_days":7,"primary_lifespan_max_days":14,"execution_warning":"calibration only; prices-history is not historical executable ask/depth proof"},"inventory":{"sports_metadata_found":sorted(chosen),"events":len(events),"resolved_moneyline_candidates":len(candidates),"sports_market_type_counts":dict(sorted(type_counts.items(),key=lambda z:z[1],reverse=True)[:30])},"primary_test":primary,"anchor_tables":result,"primary_rows":target_rows,"price_error_sample":price_errors,"errors":errors}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"inventory":out["inventory"],"primary_test":primary,"anchor_n":{d:{"prices":result[str(d)]["n_prices"],"strict":result[str(d)]["n_strict"]} for d in ANCHOR_DAYS},"errors":errors[:5],"price_errors":price_errors[:5]},indent=2))

if __name__=="__main__":main()
