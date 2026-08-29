#!/usr/bin/env python3
"""Discover economically relevant recent Polymarket state-constrained event groups.

Research-only. Public Gamma reads; no orders. We intentionally scan the highest-
volume 2024+ event universe first: profitability/capacity matters more than an
exhaustive archive containing tiny pre-CLOB markets.
"""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request
from collections import Counter
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}; OUT=Path("state_market_candidates.json")
RECENT_MIN="2024-01-01T00:00:00Z"
FAMILY_PATTERNS={
 "public_counter":[r"\bviews?\b",r"\bsubscribers?\b",r"\bfollowers?\b",r"\bdownloads?\b"],
 "streaming":[r"spotify",r"most[- ]streamed",r"top spotify",r"\bstreams?\b"],
 "box_office":[r"highest[- ]grossing",r"box office",r"domestic gross",r"calendar gross",r"gross more",r"gross between"],
 "medals":[r"most medals",r"medal count",r"gold medals",r"athlete to win the most medals",r"3rd most medals"],
 "sports_stat_leader":[r"scoring leader",r"yards leader",r"runs leader",r"home runs leader",r"rbis? leader",r"wins leader",r"strikeouts? leader",r"touchdowns? leader",r"assists? leader",r"rebounds? leader",r"saves? leader",r"top scorer",r"top goalscorer",r"golden boot",r"most goals",r"most passing yards",r"most rushing yards",r"most receiving yards",r"most touchdowns",r"most runs",r"most home runs",r"most wins",r"most points scored",r"most total goals"],
}
FINITE_WORDS=re.compile(r"first \d+ (?:hours?|days?|weeks?)|regular season|calendar year|after .* hours?|december 31|wrapped|olympics|world cup|by [A-Z][a-z]+ \d+|by .*\d{4}",re.I)
OBJECTIVE_SOURCE=re.compile(r"resolution source|official information|youtube|spotify|box office mojo|the-numbers|mlb|nfl|nba|fifa|uefa|olympic",re.I)

def get_json(url,params=None,timeout=30):
 if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
 req=urllib.request.Request(url,headers=UA); last=None
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
  except Exception as ex:
   last=ex
   if attempt<2:time.sleep(.5*(attempt+1))
 raise last

def texts(ev):
 core=[ev.get("title") or "",ev.get("slug") or ""]; rules=[ev.get("description") or "",ev.get("resolutionSource") or ""]
 for m in ev.get("markets") or []:
  core.append(m.get("question") or ""); rules.extend([m.get("description") or "",m.get("resolutionSource") or ""])
 return "\n".join(core),"\n".join(rules)

def classify(core,rules):
 scores={fam:sum(1 for p in pats if re.search(p,core,re.I)) for fam,pats in FAMILY_PATTERNS.items()}
 scores={k:v for k,v in scores.items() if v}
 if not scores:return None,0,scores
 fam=max(scores,key=scores.get); score=scores[fam]*2
 if any(re.search(p,core.split("\n",1)[0],re.I) for p in FAMILY_PATTERNS[fam]):score+=2
 joined=core+"\n"+rules
 if FINITE_WORDS.search(joined):score+=2
 if OBJECTIVE_SOURCE.search(joined):score+=1
 return fam,score,scores

def compact(ev,fam,score,scores):
 ms=[]
 for m in ev.get("markets") or []:
  ms.append({"id":m.get("id"),"slug":m.get("slug"),"question":m.get("question"),"volume":m.get("volume"),"endDate":m.get("endDate"),"closed":m.get("closed"),"outcomePrices":m.get("outcomePrices"),"clobTokenIds":m.get("clobTokenIds"),"enableOrderBook":m.get("enableOrderBook")})
 return {"id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),"family":fam,"score":score,"family_scores":scores,"closed":ev.get("closed"),"active":ev.get("active"),"volume":ev.get("volume"),"liquidity":ev.get("liquidity"),"creationDate":ev.get("creationDate"),"startDate":ev.get("startDate"),"endDate":ev.get("endDate"),"markets":ms}

def fetch_universe(closed,max_events):
 found=[]; limit=100; err=None
 for offset in range(0,max_events,limit):
  params={"closed":str(closed).lower(),"limit":limit,"offset":offset,"order":"volume","ascending":"false","start_date_min":RECENT_MIN}
  try:rows=get_json("https://gamma-api.polymarket.com/events",params)
  except Exception as ex:err={"offset":offset,"error":repr(ex)};break
  if not isinstance(rows,list) or not rows:break
  for ev in rows:
   core,rules=texts(ev); fam,score,scores=classify(core,rules)
   if fam and score>=5:found.append(compact(ev,fam,score,scores))
  if len(rows)<limit:break
  time.sleep(.04)
 return found,err

def dedupe(rows):
 d={}
 for r in rows:
  k=str(r.get("id") or r.get("slug"))
  if k not in d or r["score"]>d[k]["score"]:d[k]=r
 return list(d.values())

def main():
 closed_rows,closed_error=fetch_universe(True,2000); active_rows,active_error=fetch_universe(False,2000)
 rows=dedupe(closed_rows+active_rows); rows.sort(key=lambda r:(float(r.get("volume") or 0),r["score"]),reverse=True)
 fc=Counter(r["family"] for r in rows); cc=Counter(r["family"] for r in rows if r.get("closed"))
 clob_closed={fam:sum(1 for r in rows if r["family"]==fam and r.get("closed") and any(m.get("enableOrderBook") and m.get("clobTokenIds") for m in r["markets"])) for fam in fc}
 vol={fam:sum(float(r.get("volume") or 0) for r in rows if r["family"]==fam) for fam in fc}
 out={"method":"highest-volume 2024+ events first; deterministic classifier; manual rule/state audit required before PnL testing","recent_min":RECENT_MIN,"scanned_limits":{"closed":2000,"active":2000},"errors":{"closed":closed_error,"active":active_error},"candidate_count":len(rows),"family_counts":dict(fc),"closed_family_counts":dict(cc),"closed_with_clob_family_counts":clob_closed,"volume_by_family":vol,"candidates":rows[:750]}
 OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
 top={fam:[{"title":r["title"],"slug":r["slug"],"closed":r.get("closed"),"volume":r.get("volume"),"score":r["score"]} for r in rows if r["family"]==fam][:20] for fam in fc}
 print(json.dumps({"candidate_count":len(rows),"family_counts":dict(fc),"closed_family_counts":dict(cc),"closed_with_clob_family_counts":clob_closed,"volume_by_family":vol,"top":top,"errors":out["errors"]},indent=2))
if __name__=="__main__":main()
