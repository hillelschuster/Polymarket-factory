#!/usr/bin/env python3
"""Independent falsification of the claimed Polymarket T-7d sports calibration edge.

Claim under test (not assumed): MLB/NBA/NFL/NHL moneyline YES contracts priced
0.55-0.60 about seven days before game start resolve YES far above their quoted rate.

Independent implementation:
- discover leagues from Gamma /sports;
- fetch closed league events by series_id, with tag_id fallback;
- keep sportsMarketType=moneyline and unambiguous 0/1 resolutions;
- anchor to explicit gameStartTime/eventStartTime when available (endDate fallback is
  reported so it can be excluded in interpretation);
- use the last YES-token CLOB historical price at or before the anchor, never after;
- reject historical prices >24h stale;
- report T-7d/T-3d/T-1d calibration and the strict <=14d-lifespan 0.55-0.60 cell.

This is calibration evidence only. Historical CLOB prices are not proof of executable
asks/depth; a positive result must survive a separate trade/quote execution audit.
"""
from __future__ import annotations
import datetime as dt,json,math,statistics,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

OUT=Path("sports_flb_independent_check.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}
SPORTS={"mlb","nba","nfl","nhl"}; MAX_EVENTS_PER_SPORT=900; MIN_VOL=1000.0
ANCHORS=(7,3,1); MAX_STALE_H=24
BUCKETS=((.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,.80),(.80,.90))
CUTOFF_TS=int(dt.datetime(2025,1,1,tzinfo=dt.timezone.utc).timestamp())

def get(url,params=None,retries=2):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    last=None
    for i in range(retries+1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.15*(i+1))
    raise last

def fnum(x):
    try:return float(x or 0)
    except:return 0.0

def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []

def ts(x):
    if not x:return None
    try:return int(dt.datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp())
    except:return None

def token_yes(m):
    o=[str(x).lower() for x in jl(m.get("outcomes"))];t=jl(m.get("clobTokenIds"))
    if not t:return None
    try:i=o.index("yes")
    except ValueError:i=0
    return str(t[i]) if i<len(t) else None

def result_yes(m):
    o=[str(x).lower() for x in jl(m.get("outcomes"))];p=jl(m.get("outcomePrices"))
    if not p:return None
    try:i=o.index("yes")
    except ValueError:i=0
    try:v=float(p[i])
    except:return None
    return 1 if v>=.99 else (0 if v<=.01 else None)

def clock(ev,m):
    for fld,obj in (("gameStartTime",m),("eventStartTime",m),("eventStartTime",ev),("endDate",ev),("endDate",m)):
        v=ts(obj.get(fld))
        if v:return v,fld
    return None,None

def created(ev,m):
    for fld,obj in (("createdAt",m),("creationDate",m),("startDate",m),("createdAt",ev),("creationDate",ev),("startDate",ev)):
        v=ts(obj.get(fld))
        if v:return v,fld
    return None,None

def fetch_page(params):return get("https://gamma-api.polymarket.com/events",params)

def fetch_league(code,meta):
    errors=[];rows=[]
    # Series filtering is the documented sports-specific path. Some old leagues can
    # lack it, so fall back to the primary tag with the smallest possible query.
    selectors=[]
    if meta.get("series"):selectors.append(("series_id",meta.get("series")))
    tag=meta.get("primaryTagId")
    if not tag:
        xs=[x.strip() for x in str(meta.get("tags") or "").split(",") if x.strip()];tag=xs[-1] if xs else None
    if tag:selectors.append(("tag_id",tag))
    for key,val in selectors:
        rows=[];off=0;failed=False
        while len(rows)<MAX_EVENTS_PER_SPORT:
            lim=min(100,MAX_EVENTS_PER_SPORT-len(rows));params={"limit":lim,"offset":off,"closed":"true",key:val}
            try:b=fetch_page(params)
            except Exception as ex:
                errors.append({"sport":code,"selector":key,"value":val,"offset":off,"error":repr(ex)});failed=True;break
            if not isinstance(b,list) or not b:break
            rows.extend(b);off+=len(b)
            if len(b)<lim:break
        if rows and not failed:return rows,errors,key,val
    return rows,errors,None,None

def price_before(tok,target):
    try:d=get("https://clob.polymarket.com/prices-history",{"market":tok,"startTs":target-36*3600,"endTs":target,"interval":"max","fidelity":30})
    except Exception as ex:return None,{"error":repr(ex)}
    pts=[]
    for p in d.get("history") or []:
        try:
            tt=int(p["t"]);pr=float(p["p"])
            if tt<=target:pts.append((tt,pr))
        except:pass
    if not pts:return None,{"error":"no_pre_anchor_history"}
    tt,pr=max(pts,key=lambda z:z[0]);age=(target-tt)/3600
    return ({"timestamp":tt,"price":pr,"age_hours":age},None) if age<=MAX_STALE_H else (None,{"error":"stale_pre_anchor_price","age_hours":age})
def wilson(k,n,z=1.96):
    if not n:return (None,None)
    p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return c-h,c+h
def table(rows):
    out=[]
    for lo,hi in BUCKETS:
        xs=[r for r in rows if lo<=r["price"]<hi]
        if not xs:out.append({"bucket":[lo,hi],"n":0});continue
        n=len(xs);k=sum(r["resolved_yes"] for r in xs);mp=statistics.mean(r["price"] for r in xs);wr=k/n;ci=wilson(k,n)
        out.append({"bucket":[lo,hi],"n":n,"wins":k,"mean_price":mp,"realized_yes_rate":wr,"calibration_pp":100*(wr-mp),"wilson95":list(ci)})
    return out

def main():
    errors=[];meta_all=get("https://gamma-api.polymarket.com/sports");meta={str(x.get("sport") or "").lower():x for x in meta_all if str(x.get("sport") or "").lower() in SPORTS}
    discovery={};events=[]
    for sport in sorted(SPORTS):
        m=meta.get(sport)
        if not m:errors.append({"sport":sport,"error":"sports_metadata_missing"});continue
        es,errs,key,val=fetch_league(sport,m);errors.extend(errs);discovery[sport]={"series":m.get("series"),"primaryTagId":m.get("primaryTagId"),"selector_used":key,"selector_value":val,"raw_events":len(es)}
        for e in es:e["_sport"]=sport
        events.extend(es)
    # filter date client-side; selector endpoints differ in accepted date syntax
    filt=[]
    for e in events:
        end=ts(e.get("endDate")) or ts(e.get("closedTime"))
        if end and end<CUTOFF_TS:continue
        filt.append(e)
    events=list({str(e.get("id") or e.get("slug")):e for e in filt}.values())
    cand=[];types=defaultdict(int);clock_fields=defaultdict(int)
    for e in events:
        for m in e.get("markets") or []:
            typ=str(m.get("sportsMarketType") or "").lower();types[typ]+=1
            if typ!="moneyline" or fnum(m.get("volume"))<MIN_VOL:continue
            y=result_yes(m);tok=token_yes(m);gs,gf=clock(e,m);cr,cf=created(e,m)
            if y is None or not tok or not gs or not cr or gs<cr:continue
            clock_fields[gf]+=1;cand.append({"sport":e.get("_sport"),"event_id":e.get("id"),"event_slug":e.get("slug"),"event_title":e.get("title"),"market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),"market_volume":fnum(m.get("volume")),"yes_token":tok,"resolved_yes":y,"game_start":gs,"clock_field":gf,"creation":cr,"creation_field":cf,"lifespan_days":(gs-cr)/86400})
    by={d:[] for d in ANCHORS};pe=[]
    for i,r in enumerate(cand):
        for d in ANCHORS:
            target=r["game_start"]-d*86400
            if r["creation"]>target:continue
            p,err=price_before(r["yes_token"],target)
            if err:
                if len(pe)<120:pe.append({"sport":r["sport"],"market_id":r["market_id"],"anchor_days":d,**err})
                continue
            by[d].append({**r,"anchor_days":d,"target_ts":target,**p})
        if i and i%150==0:time.sleep(.02)
    tabs={}
    for d,rows in by.items():
        strict=[r for r in rows if r["lifespan_days"]<=14]
        tabs[str(d)]={"all_lifespan":table(rows),"lifespan_le_14d":table(strict),"by_sport_lifespan_le_14d":{s:table([r for r in strict if r["sport"]==s]) for s in sorted(SPORTS)},"n_prices":len(rows),"n_strict":len(strict),"clock_fields":dict(defaultdict(int,((x["clock_field"],sum(1 for r in rows if r["clock_field"]==x["clock_field"])) for x in rows)))}
    target=[r for r in by[7] if r["lifespan_days"]<=14 and .55<=r["price"]<.60];n=len(target);k=sum(r["resolved_yes"] for r in target);mp=statistics.mean([r["price"] for r in target]) if target else None
    primary={"n":n,"wins":k,"mean_price":mp,"realized_yes_rate":k/n if n else None,"calibration_pp":100*(k/n-mp) if n else None,"wilson95":list(wilson(k,n)) if n else [None,None],"by_sport":{}}
    for s in sorted(SPORTS):
        xs=[r for r in target if r["sport"]==s];nn=len(xs);kk=sum(r["resolved_yes"] for r in xs);mm=statistics.mean([r["price"] for r in xs]) if xs else None
        primary["by_sport"][s]={"n":nn,"wins":kk,"mean_price":mm,"realized_yes_rate":kk/nn if nn else None,"calibration_pp":100*(kk/nn-mm) if nn else None}
    out={"method":{"independent":True,"market_type":"moneyline","anchor":"last historical YES price at/before explicit game clock where available","max_stale_hours":MAX_STALE_H,"primary":{"anchor_days":7,"bucket":[.55,.60],"lifespan_max_days":14},"execution_warning":"calibration only; historical price is not executable ask/depth proof"},"discovery":discovery,"inventory":{"events_since_2025":len(events),"resolved_moneyline_candidates":len(cand),"market_type_counts":dict(sorted(types.items(),key=lambda z:z[1],reverse=True)[:30]),"candidate_clock_fields":dict(clock_fields)},"primary_test":primary,"anchor_tables":tabs,"primary_rows":target,"price_error_sample":pe,"errors":errors}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8");print(json.dumps({"discovery":discovery,"inventory":out["inventory"],"primary":primary,"anchor_n":{d:{"prices":tabs[str(d)]["n_prices"],"strict":tabs[str(d)]["n_strict"]} for d in ANCHORS},"errors":errors[:8],"price_errors":pe[:5]},indent=2))
if __name__=="__main__":main()
