#!/usr/bin/env python3
"""Audit whether closed state-constrained events have usable historical CLOB prices.

Reads state_market_candidates.json. For each closed event, probes at most three
representative markets (winner if identifiable + highest-volume markets). This is a
feasibility audit, not a backtest and not trading code.
"""
from __future__ import annotations
import datetime as dt,json,urllib.parse,urllib.request,time
from pathlib import Path
from collections import defaultdict

SRC=Path("state_market_candidates.json"); OUT=Path("state_clob_history_audit.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}

def arr(v):
 if isinstance(v,list):return v
 try:return json.loads(v or "[]")
 except:return []

def get(url,params=None,timeout=25):
 if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
 with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:return json.load(r)

def ts(s):
 if not s:return None
 try:return int(dt.datetime.fromisoformat(str(s).replace("Z","+00:00")).timestamp())
 except:return None

def market_volume(m):
 try:return float(m.get("volume") or 0)
 except:return 0.0

def resolved_yes(m):
 p=arr(m.get("outcomePrices"))
 try:return len(p)>=2 and float(p[0])>.999 and float(p[1])<.001
 except:return False

def representatives(ev):
 ms=[m for m in ev.get("markets") or [] if m.get("enableOrderBook") and len(arr(m.get("clobTokenIds")))>=2]
 if not ms:return []
 picked=[]
 winners=[m for m in ms if resolved_yes(m)]
 if winners:picked.append(max(winners,key=market_volume))
 for m in sorted(ms,key=market_volume,reverse=True):
  if m not in picked:picked.append(m)
  if len(picked)>=3:break
 return picked

def probe_market(ev,m):
 ids=arr(m.get("clobTokenIds")); token=str(ids[0])
 start=ts(ev.get("startDate") or ev.get("creationDate"))
 end=ts(m.get("endDate") or ev.get("endDate"))
 if start is None or end is None:return {"market_id":m.get("id"),"question":m.get("question"),"token":token,"error":"missing time bounds"}
 # Wider bounds catch pre-open/late-resolution rows. Use max interval first; if it
 # returns nothing, retry explicit bounds/fidelity.
 start-=86400; end+=3*86400
 rec={"market_id":m.get("id"),"question":m.get("question"),"token":token,"market_volume":m.get("volume"),"resolved_yes":resolved_yes(m),"start":start,"end":end}
 try:
  j=get("https://clob.polymarket.com/prices-history",{"market":token,"startTs":start,"endTs":end,"fidelity":60})
  h=j.get("history") or []
  rec["points"]=len(h)
  if h:
   rec["first_t"]=h[0].get("t");rec["last_t"]=h[-1].get("t");rec["first_p"]=h[0].get("p");rec["last_p"]=h[-1].get("p")
 except Exception as ex:rec["error"]=repr(ex);rec["points"]=0
 return rec

def main():
 data=json.loads(SRC.read_text()); events=[e for e in data.get("candidates") or [] if e.get("closed")]
 rows=[]
 for ev in events:
  probes=[]
  for m in representatives(ev):
   probes.append(probe_market(ev,m));time.sleep(.05)
  usable=sum(1 for p in probes if (p.get("points") or 0)>=3)
  rows.append({"event_id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),"family":ev.get("family"),"volume":ev.get("volume"),"representative_markets":len(probes),"usable_market_histories":usable,"usable_event":usable>0,"probes":probes})
 by=defaultdict(lambda:{"closed_events":0,"usable_events":0,"volume_closed":0.0,"volume_usable":0.0})
 for r in rows:
  b=by[r["family"]];b["closed_events"]+=1;b["volume_closed"]+=float(r.get("volume") or 0)
  if r["usable_event"]:b["usable_events"]+=1;b["volume_usable"]+=float(r.get("volume") or 0)
 out={"definition":"usable event = at least one representative YES token with >=3 historical CLOB price points","events":rows,"by_family":dict(by),"totals":{"closed_events":len(rows),"usable_events":sum(r["usable_event"] for r in rows)}}
 OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
 print(json.dumps({"totals":out["totals"],"by_family":out["by_family"],"unusable":[{"family":r["family"],"title":r["title"]} for r in rows if not r["usable_event"]]},indent=2))
if __name__=="__main__":main()
