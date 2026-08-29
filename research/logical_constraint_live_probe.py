#!/usr/bin/env python3
"""Probe current executable monotonicity violations from logical_constraint_inventory.

For proven subset ⊂ superset, YES(superset)+NO(subset) pays at least $1.
Only raw ask baskets below $1 can possibly be arbitrage, so fee lookups are deferred
until after that cheap screen. Every surviving candidate still requires rules audit.
"""
from __future__ import annotations
import json,urllib.parse,urllib.request
from pathlib import Path
IN=Path("logical_constraint_inventory.json"); OUT=Path("logical_constraint_live_probe.json")
UA={"User-Agent":"polymarket-factory-research/1.0"}; MAX_PAIRS=800

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20) as r:return json.load(r)
def fnum(x):
    try:return float(x or 0)
    except:return 0.0
def best_ask(book):
    xs=[]
    for a in book.get("asks") or []:
        try:xs.append((float(a["price"]),float(a["size"])))
        except:pass
    return min(xs,key=lambda x:x[0]) if xs else None
def token_ask(token,cache):
    if not token:return None
    if token not in cache:
        try:cache[token]=best_ask(get("https://clob.polymarket.com/book",{"token_id":token}))
        except:cache[token]=None
    return cache[token]
def fee_rate(cid,cache):
    if not cid:return 0.0
    if cid not in cache:
        try:cache[cid]=fnum((get(f"https://clob.polymarket.com/clob-markets/{cid}").get("fd") or {}).get("r"))
        except:cache[cid]=0.0
    return cache[cid]

def main():
    inv=json.loads(IN.read_text()); pairs=[]; seen=set()
    for p in inv.get("pairs") or []:
        a,b=p.get("superset") or {},p.get("subset") or {}; k=(a.get("condition_id"),b.get("condition_id"))
        if not(a.get("active") and b.get("active")) or a.get("closed") or b.get("closed") or None in k or k in seen:continue
        seen.add(k);pairs.append(p)
    pairs=sorted(pairs,key=lambda x:fnum(x.get("event_volume")),reverse=True)[:MAX_PAIRS]
    bc={};fc={};probes=[];errors=[];raw_sub1=0
    for p in pairs:
        sup,sub=p["superset"],p["subset"]
        aa=token_ask(sup.get("yes_token"),bc); bb=token_ask(sub.get("no_token"),bc)
        if not aa or not bb:
            errors.append({"event_id":p.get("event_id"),"error":"missing ask"});continue
        pa,sa=aa;pb,sb=bb;raw=pa+pb
        # Fees are nonnegative; raw >= 1 is conclusively dead and needs no fee calls.
        if raw>=1:
            probes.append({"event_id":p.get("event_id"),"event_title":p.get("event_title"),"raw_cost":raw,"all_in_cost":raw,"fee_skipped":"raw_cost>=1","net_edge_per_share":1-raw})
            continue
        raw_sub1+=1
        ra=fee_rate(sup.get("condition_id"),fc);rb=fee_rate(sub.get("condition_id"),fc)
        fa=ra*pa*(1-pa);fb=rb*pb*(1-pb);all_in=raw+fa+fb;shares=min(sa,sb)
        probes.append({
            "event_id":p.get("event_id"),"event_slug":p.get("event_slug"),"event_title":p.get("event_title"),"event_volume":fnum(p.get("event_volume")),"event_neg_risk":bool(p.get("event_neg_risk")),"template":p.get("template"),"direction":p.get("direction"),
            "superset_threshold":sup.get("threshold"),"subset_threshold":sub.get("threshold"),"superset_question":sup.get("question"),"subset_question":sub.get("question"),"superset_resolution_source":sup.get("resolution_source"),"subset_resolution_source":sub.get("resolution_source"),
            "leg_yes_superset":{"ask":pa,"ask_size":sa,"fee_rate":ra,"fee_per_share":fa,"token":sup.get("yes_token"),"condition_id":sup.get("condition_id")},
            "leg_no_subset":{"ask":pb,"ask_size":sb,"fee_rate":rb,"fee_per_share":fb,"token":sub.get("no_token"),"condition_id":sub.get("condition_id")},
            "raw_cost":raw,"fee_cost":fa+fb,"all_in_cost":all_in,"minimum_payoff":1.0,"net_edge_per_share":1-all_in,"top_level_common_shares":shares,"top_level_max_net_profit":max(0,1-all_in)*shares,"requires_rules_audit":all_in<1,
        })
    probes.sort(key=lambda x:x["all_in_cost"]); pos=[x for x in probes if x["all_in_cost"]<1]
    out={"method":{"identity":"YES(superset)+NO(subset) pays >=1","pricing":"current CLOB best asks","fees":"fd.r*p*(1-p), only fetched for raw sub-$1 baskets","semantic_gate":"sub-$1 candidates require rules verification"},"summary":{"active_pairs_considered":len(pairs),"complete_pairs":len(probes),"raw_below_1":raw_sub1,"all_in_below_1":len(pos),"all_in_at_or_below_0_99":sum(x["all_in_cost"]<=.99 for x in probes),"all_in_at_or_below_0_98":sum(x["all_in_cost"]<=.98 for x in probes),"best_all_in":probes[0]["all_in_cost"] if probes else None,"best_top_level_profit":max((x.get("top_level_max_net_profit",0) for x in pos),default=0)},"positive_candidates":pos,"best_50":probes[:50],"errors":errors}
    OUT.write_text(json.dumps(out,indent=2));print(json.dumps({"summary":out["summary"],"positive":[{"id":x["event_id"],"title":x.get("event_title"),"superset":x.get("superset_question"),"subset":x.get("subset_question"),"cost":round(x["all_in_cost"],6),"shares":round(x.get("top_level_common_shares",0),3),"profit":round(x.get("top_level_max_net_profit",0),4)} for x in pos[:20]],"errors":errors[:5]},indent=2))
if __name__=="__main__":main()
