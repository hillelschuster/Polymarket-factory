#!/usr/bin/env python3
"""Feasibility audit for repeated opening-weekend box-office alpha.

Question only: did the eventual winning bracket remain materially below $1 late on
Sunday in resolved standard 3-day events? This is NOT a strategy backtest because it
uses the eventual winner to inspect market responsiveness. If there is no late price
room, external-state reconstruction is not worth doing. Research only.
"""
from __future__ import annotations
import datetime as dt,json,re,time,urllib.parse,urllib.request
from pathlib import Path

INV=Path("boxoffice_weekend_inventory.json")
OUT=Path("boxoffice_late_price_audit.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}
MONTH={m:i for i,m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"],1)}
CLOCKS_UTC=(16,17,18,19,20,21,22,23)

def get(url,params=None,timeout=25):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:return json.load(r)

def parse_date(raw,end_date):
    if not raw:return None
    # Capture first and optional second month plus end day from strings like
    # 3-day opening weekend (July 31 - August 2) or (October 4 - 6).
    m=re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})",raw,re.I)
    if not m:return None
    names={k.lower():v for k,v in MONTH.items()}
    m1=names[m.group(1).lower()];d1=int(m.group(2));m2=names[(m.group(3) or m.group(1)).lower()];d2=int(m.group(4))
    try:ey=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).year
    except:ey=2026
    year=ey
    # If weekend ends in Dec but event resolution/end date is Jan, use previous year.
    try:end_month=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).month
    except:end_month=m2
    if end_month==1 and m2==12:year=ey-1
    return dt.date(year,m2,d2)

def winning_yes_market(ev):
    wins=[]
    for m in ev.get("markets") or []:
        prices=m.get("outcomePrices") or []
        try:yes=float(prices[0])
        except:continue
        ids=m.get("clobTokenIds") or []
        if yes>.999 and ids:
            wins.append(m)
    return wins

def ph(token,start,end):
    try:return (get("https://clob.polymarket.com/prices-history",{"market":token,"startTs":int(start.timestamp()),"endTs":int(end.timestamp()),"interval":"all","fidelity":1}).get("history") or [])
    except Exception as ex:return {"error":repr(ex)}

def nearest_after(hist,ts,max_minutes=75):
    pts=[]
    for x in hist:
        try:t=int(x["t"]);p=float(x["p"])
        except:continue
        if t>=ts and t<=ts+max_minutes*60:pts.append((t,p))
    return min(pts,key=lambda z:z[0]) if pts else None

def nearest_before(hist,ts,max_minutes=75):
    pts=[]
    for x in hist:
        try:t=int(x["t"]);p=float(x["p"])
        except:continue
        if t<=ts and t>=ts-max_minutes*60:pts.append((t,p))
    return max(pts,key=lambda z:z[0]) if pts else None

def main():
    data=json.loads(INV.read_text())
    rows=[]
    for ev in data.get("events") or []:
        if not ev.get("closed") or ev.get("weekend_type")!="3-day":continue
        day=parse_date(ev.get("weekend_dates_raw"),ev.get("endDate"))
        wins=winning_yes_market(ev)
        if not day or not wins:continue
        # One event can contain exactly one winning bracket; if metadata says otherwise preserve all.
        start=dt.datetime.combine(day,dt.time(0),tzinfo=dt.timezone.utc)-dt.timedelta(hours=8)
        end=dt.datetime.combine(day+dt.timedelta(days=1),dt.time(8),tzinfo=dt.timezone.utc)
        for wm in wins:
            token=str((wm.get("clobTokenIds") or [""])[0])
            h=ph(token,start,end)
            rec={
                "event_title":ev.get("title"),"event_slug":ev.get("slug"),"event_volume":ev.get("volume"),
                "weekend_end":day.isoformat(),"market_question":wm.get("question"),"market_label":wm.get("groupItemTitle"),
                "market_volume":wm.get("volume"),"token":token,"event_endDate":ev.get("endDate"),
            }
            if isinstance(h,dict):rec["history_error"]=h["error"];rows.append(rec);continue
            rec["history_points"]=len(h)
            if h:
                rec["first_point"]={"t":min(int(x["t"]) for x in h),"p":float(min(h,key=lambda x:int(x["t"]))["p"])}
                rec["last_point"]={"t":max(int(x["t"]) for x in h),"p":float(max(h,key=lambda x:int(x["t"]))["p"])}
            clocks={}
            for hour in CLOCKS_UTC:
                t=int(dt.datetime.combine(day,dt.time(hour),tzinfo=dt.timezone.utc).timestamp())
                a=nearest_after(h,t);b=nearest_before(h,t)
                clocks[str(hour)]=({"after_t":a[0],"after_p":a[1]} if a else {})|({"before_t":b[0],"before_p":b[1]} if b else {})
            rec["clocks_utc"]=clocks
            rows.append(rec)
            time.sleep(.02)
    # Deduplicate strike sets/movie groups by event title normalization only for summary.
    def key(r):
        s=(r["event_title"] or "").lower()
        s=re.sub(r"\s*\((?:even )?(?:higher|lower) (?:strikes|brackets)\)\s*"," ",s)
        s=re.sub(r"\s+cont\.?\s*$","",s)
        return re.sub(r"\s+"," ",s).strip()
    # At each clock summarize one observation per unique movie: choose highest-volume event set.
    by={}
    for r in rows:
        k=key(r)
        if k not in by or float(r.get("event_volume") or 0)>float(by[k].get("event_volume") or 0):by[k]=r
    uniq=list(by.values())
    summary={"audited_market_rows":len(rows),"unique_movie_groups":len(uniq),"clock_summary":{}}
    for hour in CLOCKS_UTC:
        vals=[]
        for r in uniq:
            c=(r.get("clocks_utc") or {}).get(str(hour),{})
            p=c.get("after_p") if c.get("after_p") is not None else c.get("before_p")
            if p is not None:vals.append(float(p))
        if vals:
            sv=sorted(vals);n=len(vals)
            summary["clock_summary"][str(hour)]={
                "n":n,"mean_winner_price":sum(vals)/n,"median_winner_price":sv[n//2],
                "winner_lt_0_95":sum(p<.95 for p in vals),"winner_lt_0_90":sum(p<.90 for p in vals),
                "winner_lt_0_80":sum(p<.80 for p in vals),"winner_lt_0_70":sum(p<.70 for p in vals),
                "min":min(vals),"max":max(vals),
            }
    out={"note":"Feasibility only; eventual winner is used, so this is NOT a no-lookahead backtest. Historical CLOB history is price data, not reconstructed executable ask; add execution buffer before any profitability claim.","summary":summary,"unique_rows":uniq,"all_rows":rows}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary,"examples":[{"event":r["event_title"],"weekend_end":r["weekend_end"],"winner":r["market_label"] or r["market_question"],"volume":r["event_volume"],"clocks":r.get("clocks_utc")} for r in sorted(uniq,key=lambda x:float(x.get("event_volume") or 0),reverse=True)[:20]]},indent=2))
if __name__=="__main__":main()
