#!/usr/bin/env python3
"""Feasibility audit using actual public trade prints for resolved 3-day box-office events.

This deliberately uses the eventual winning bracket ONLY to ask whether there was
price room after Sunday public information. It is not a strategy backtest and cannot
establish alpha. Trade timestamps come from Polymarket Data API; seconds/minutes of
settlement lag are irrelevant for the hourly windows used here.
"""
from __future__ import annotations
import datetime as dt,json,re,time,urllib.parse,urllib.request
from pathlib import Path

INV=Path("boxoffice_weekend_inventory.json")
OUT=Path("boxoffice_sunday_trade_audit.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}
MONTH={m.lower():i for i,m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"],1)}
CLOCKS=(15,16,17,18,19,20,21,22,23)

def get(url,params=None,timeout=30):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)

def parse_dates(raw,end_date):
    if not raw:return None
    m=re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})",raw,re.I)
    if not m:return None
    m1=MONTH[m.group(1).lower()]; d1=int(m.group(2)); m2=MONTH[(m.group(3) or m.group(1)).lower()]; d2=int(m.group(4))
    ey=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).year
    y1=y2=ey
    # End-date metadata is normally resolution date immediately after weekend.
    em=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).month
    if em==1 and m2==12:y1=y2=ey-1
    if m2<m1:y2=y1+1
    try:return dt.date(y1,m1,d1),dt.date(y2,m2,d2)
    except:return None

def winning_markets(ev):
    out=[]
    for m in ev.get("markets") or []:
        try:yes=float((m.get("outcomePrices") or [None])[0])
        except:continue
        ids=m.get("clobTokenIds") or []
        cid=m.get("conditionId")
        if yes>.999 and ids and cid:
            out.append((m,str(ids[0]),str(cid)))
    return out

def fetch_trades(cid,start,end):
    try:
        return get("https://data-api.polymarket.com/trades",{
            "market":cid,"start":int(start.timestamp()),"end":int(end.timestamp()),
            "limit":10000,"offset":0,"takerOnly":"true"
        })
    except Exception as ex:return {"error":repr(ex)}

def yes_trades(rows,token):
    out=[]
    if not isinstance(rows,list):return out
    for x in rows:
        if str(x.get("asset"))!=token:continue
        try:out.append((int(x["timestamp"]),float(x["price"]),float(x.get("size") or 0),x.get("side")))
        except:pass
    out.sort()
    return out

def around(ts,clock,max_minutes=45):
    lo=clock-max_minutes*60;hi=clock+max_minutes*60
    candidates=[x for x in ts if lo<=x[0]<=hi]
    if not candidates:return None
    x=min(candidates,key=lambda z:abs(z[0]-clock))
    return {"t":x[0],"p":x[1],"size":x[2],"side":x[3],"delta_min":(x[0]-clock)/60}

def normalize_title(s):
    s=(s or "").lower()
    s=re.sub(r"\s*\((?:even )?(?:higher|lower) (?:strikes|brackets)\)\s*"," ",s)
    s=re.sub(r"\s+cont\.?\s*$","",s)
    return re.sub(r"\s+"," ",s).strip()

def main():
    inv=json.loads(INV.read_text())
    rows=[]
    for ev in inv.get("events") or []:
        if not ev.get("closed") or ev.get("weekend_type")!="3-day":continue
        dates=parse_dates(ev.get("weekend_dates_raw"),ev.get("endDate"))
        wins=winning_markets(ev)
        if not dates or not wins:continue
        first,last=dates
        # Keep only literal 3-calendar-day windows; malformed/extended rules wait for later handling.
        if (last-first).days!=2:continue
        sunday=last
        start=dt.datetime.combine(sunday,dt.time(12),tzinfo=dt.timezone.utc)
        end=dt.datetime.combine(sunday+dt.timedelta(days=1),dt.time(6),tzinfo=dt.timezone.utc)
        for m,token,cid in wins:
            raw=fetch_trades(cid,start,end)
            rec={"event_title":ev.get("title"),"event_slug":ev.get("slug"),"event_volume":ev.get("volume"),"sunday":sunday.isoformat(),"market_question":m.get("question"),"market_label":m.get("groupItemTitle"),"market_volume":m.get("volume"),"conditionId":cid,"yes_token":token}
            if isinstance(raw,dict):rec["error"]=raw.get("error");rows.append(rec);continue
            trades=yes_trades(raw,token);rec["yes_trade_count"]=len(trades)
            if trades:
                rec["first_yes_trade"]={"t":trades[0][0],"p":trades[0][1]};rec["last_yes_trade"]={"t":trades[-1][0],"p":trades[-1][1]}
            clocks={}
            for h in CLOCKS:
                clock=int(dt.datetime.combine(sunday,dt.time(h),tzinfo=dt.timezone.utc).timestamp())
                v=around(trades,clock)
                if v:clocks[str(h)]=v
            rec["clocks_utc"]=clocks;rows.append(rec);time.sleep(.015)
    # one independent movie/weekend observation: highest-volume strike set with a winner trade
    by={}
    for r in rows:
        key=(normalize_title(r["event_title"]),r["sunday"])
        prev=by.get(key)
        score=(bool(r.get("clocks_utc")),float(r.get("event_volume") or 0))
        pscore=(bool(prev.get("clocks_utc")),float(prev.get("event_volume") or 0)) if prev else (-1,-1)
        if prev is None or score>pscore:by[key]=r
    uniq=list(by.values())
    summary={"market_rows":len(rows),"unique_movie_weekends":len(uniq),"clock_summary":{}}
    for h in CLOCKS:
        vals=[]
        for r in uniq:
            v=(r.get("clocks_utc") or {}).get(str(h))
            if v:vals.append(float(v["p"]))
        if not vals:continue
        s=sorted(vals);n=len(s)
        summary["clock_summary"][str(h)]={"n":n,"mean":sum(s)/n,"median":s[n//2],"lt_0_95":sum(p<.95 for p in s),"lt_0_90":sum(p<.90 for p in s),"lt_0_80":sum(p<.80 for p in s),"lt_0_70":sum(p<.70 for p in s),"min":min(s),"max":max(s)}
    out={"note":"Feasibility only: uses eventual winning bracket, so NOT a backtest. Prices are actual public trade prints, not guaranteed executable asks at decision time. Hourly windows make small Data API settlement timestamp lag immaterial.","summary":summary,"unique_rows":uniq,"all_rows":rows}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary,"examples":[{"event":r["event_title"],"sunday":r["sunday"],"winner":r.get("market_label") or r.get("market_question"),"volume":r.get("event_volume"),"yes_trade_count":r.get("yes_trade_count"),"clocks":r.get("clocks_utc")} for r in sorted(uniq,key=lambda x:float(x.get("event_volume") or 0),reverse=True)[:25]]},indent=2))
if __name__=="__main__":main()
