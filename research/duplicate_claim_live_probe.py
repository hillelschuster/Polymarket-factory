#!/usr/bin/env python3
"""Scan active Polymarket for exact semantic duplicate claims with separate books.

This deliberately starts with a very strict identity definition:
- same normalized question;
- same normalized description/rules;
- same normalized resolution source;
- same end-date / horizon text;
- different condition IDs.

For identical binary claims A and B, either basket
    YES(A) + NO(B)
or YES(B) + NO(A)
pays exactly $1 if the claims truly resolve identically.

Gamma bestAsk/bestBid is used only to prefilter possible inversions. Exact CLOB asks,
depth and current fee parameters verify survivors. Any survivor still gets an explicit
rules audit before it is called arbitrage.
"""
from __future__ import annotations
import json,re,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

OUT=Path("duplicate_claim_live_probe.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}
MAX_ACTIVE_EVENTS=2500;MIN_EVENT_VOLUME=500.0;MAX_GROUP=20

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:return json.load(r)
def fnum(x):
    try:return float(x or 0)
    except:return 0.0
def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []
def canon(x):return re.sub(r"\s+"," ",str(x or "").strip().lower())
def tokens(m):
    o=[str(x).lower() for x in jl(m.get("outcomes"))];t=jl(m.get("clobTokenIds"))
    try:yi=o.index("yes")
    except ValueError:yi=0
    try:ni=o.index("no")
    except ValueError:ni=1
    return (str(t[yi]) if yi<len(t) else None,str(t[ni]) if ni<len(t) else None)
def px(x):
    try:return float(x)
    except:return None

def fetch_active():
    rows=[];errs=[];off=0
    while len(rows)<MAX_ACTIVE_EVENTS:
        lim=min(100,MAX_ACTIVE_EVENTS-len(rows))
        try:b=get("https://gamma-api.polymarket.com/events",{"limit":lim,"offset":off,"active":"true","closed":"false","order":"volume","ascending":"false"})
        except Exception as ex:errs.append({"offset":off,"error":repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if max((fnum(e.get("volume")) for e in b),default=0)<MIN_EVENT_VOLUME:break
    return rows,errs
def signature(ev,m):
    q=canon(m.get("question"));d=canon(m.get("description"));src=canon(m.get("resolutionSource") or ev.get("resolutionSource"));end=canon(m.get("endDate") or ev.get("endDate"));
    if not q or not d:return None
    return (q,d,src,end)
def rec(ev,m):
    y,n=tokens(m)
    return {"event_id":ev.get("id"),"event_slug":ev.get("slug"),"event_title":ev.get("title"),"event_volume":fnum(ev.get("volume")),"market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),"description":m.get("description"),"resolution_source":m.get("resolutionSource") or ev.get("resolutionSource"),"end_date":m.get("endDate") or ev.get("endDate"),"yes_token":y,"no_token":n,"best_bid_yes_gamma":px(m.get("bestBid")),"best_ask_yes_gamma":px(m.get("bestAsk"))}
def best_ask(tok,cache):
    if tok in cache:return cache[tok]
    try:
        b=get("https://clob.polymarket.com/book",{"token_id":tok});xs=[]
        for a in b.get("asks") or []:
            try:xs.append((float(a["price"]),float(a["size"])))
            except:pass
        cache[tok]=min(xs,key=lambda z:z[0]) if xs else None
    except:cache[tok]=None
    return cache[tok]
def fee(cid,cache):
    if not cid:return 0.0
    if cid not in cache:
        try:cache[cid]=fnum((get(f"https://clob.polymarket.com/clob-markets/{cid}").get("fd") or {}).get("r"))
        except:cache[cid]=0.0
    return cache[cid]
def verify(a,b,books,fees):
    # basket YES(a)+NO(b)
    ay=best_ask(a["yes_token"],books);bn=best_ask(b["no_token"],books)
    if not ay or not bn:return None
    py,sy=ay;pn,sn=bn;raw=py+pn;fa=fb=0.0
    if raw<1:
        ra=fee(a["condition_id"],fees);rb=fee(b["condition_id"],fees);fa=ra*py*(1-py);fb=rb*pn*(1-pn)
    allin=raw+fa+fb;shares=min(sy,sn)
    return {"long_yes":a,"long_no":b,"raw_cost":raw,"fee_cost":fa+fb,"all_in_cost":allin,"net_edge_per_share":1-allin,"common_top_size":shares,"top_level_max_net_profit":max(0,1-allin)*shares,"requires_rules_audit":allin<1}
def main():
    events,errs=fetch_active();groups=defaultdict(list)
    for ev in events:
        for m in ev.get("markets") or []:
            if not(m.get("active") and not m.get("closed")):continue
            s=signature(ev,m)
            if not s:continue
            r=rec(ev,m)
            if r["condition_id"] and r["yes_token"] and r["no_token"]:groups[s].append(r)
    dup=[]
    for sig,rs in groups.items():
        ids={r["condition_id"] for r in rs}
        evs={str(r["event_id"]) for r in rs}
        if len(ids)<2 or len(rs)>MAX_GROUP:continue
        # Most interesting are genuinely separate event/condition listings.
        dup.append({"signature":sig,"markets":rs,"condition_ids":len(ids),"event_ids":len(evs)})
    # Gamma inversion prefilter in both directions.
    inv=[]
    for g in dup:
        rs=g["markets"]
        for i,a in enumerate(rs):
            for j,b in enumerate(rs):
                if i==j or a["condition_id"]==b["condition_id"]:continue
                ask=a.get("best_ask_yes_gamma");bid=b.get("best_bid_yes_gamma")
                if ask is not None and bid is not None and ask<bid:
                    inv.append((a,b))
    # Dedup directional pairs.
    seen=set();uniq=[]
    for a,b in inv:
        k=(a["condition_id"],b["condition_id"])
        if k not in seen:seen.add(k);uniq.append((a,b))
    books={};fees={};verified=[]
    for a,b in uniq:
        v=verify(a,b,books,fees)
        if v:verified.append(v)
    verified.sort(key=lambda x:x["all_in_cost"]);pos=[x for x in verified if x["all_in_cost"]<1]
    out={"method":{"identity":"exact normalized question+description+resolution source+end date","prefilter":"Gamma YES ask(A) < YES bid(B)","verification":"CLOB YES(A)+NO(B) asks, top depth, current fees","semantic_gate":"rules audit remains required"},"summary":{"active_events_scanned":len(events),"exact_duplicate_groups":len(dup),"groups_across_multiple_events":sum(g["event_ids"]>1 for g in dup),"gamma_directional_inversions":len(uniq),"clob_verified":len(verified),"all_in_positive":len(pos),"best_all_in":verified[0]["all_in_cost"] if verified else None,"best_top_level_profit":max((x["top_level_max_net_profit"] for x in pos),default=0.0)},"positive_candidates":pos,"duplicate_groups":sorted(dup,key=lambda g:max((r["event_volume"] for r in g["markets"]),default=0),reverse=True)[:100],"verified_inversions":verified,"errors":errs}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8");print(json.dumps({"summary":out["summary"],"positive":[{"yes_event":x["long_yes"]["event_title"],"no_event":x["long_no"]["event_title"],"question":x["long_yes"]["question"],"all_in":round(x["all_in_cost"],6),"shares":round(x["common_top_size"],3),"profit":round(x["top_level_max_net_profit"],4)} for x in pos[:20]],"errors":errs[:5]},indent=2))
if __name__=="__main__":main()
