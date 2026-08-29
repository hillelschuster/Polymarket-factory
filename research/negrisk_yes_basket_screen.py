#!/usr/bin/env python3
"""Screen Polymarket non-augmented NegRisk YES-basket underrounds.

LIVE uses current CLOB best asks/depth. Fees are fetched only when raw sum(YES asks)<1,
because nonnegative fees cannot rescue a raw overround. HISTORICAL uses hourly CLOB
price history only as a candidate screen, never as executable-fill proof.
"""
from __future__ import annotations
import datetime as dt,json,urllib.parse,urllib.request
from pathlib import Path
UA={"User-Agent":"polymarket-factory-research/1.0"};OUT=Path("negrisk_yes_basket_screen.json")
MAX_CLOSED_SCAN=2500;MAX_ACTIVE_SCAN=1200;MAX_HIST_EVENTS=60;MAX_LIVE_EVENTS=80;MAX_OUTCOMES=20;MIN_EVENT_VOLUME=10_000.0;HIST_LOOKBACK_DAYS=7;HIST_FIDELITY_MIN=60

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:return json.load(r)
def fnum(x):
    try:return float(x or 0)
    except:return 0.0
def jlist(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []
def iso_ts(x):
    if not x:return None
    try:return int(dt.datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp())
    except:return None
def fetch_events(active,closed,cap):
    rows=[];errs=[];off=0
    while len(rows)<cap:
        try:b=get("https://gamma-api.polymarket.com/events",{"limit":min(100,cap-len(rows)),"offset":off,"active":str(active).lower(),"closed":str(closed).lower(),"order":"volume","ascending":"false"})
        except Exception as ex:errs.append({"offset":off,"error":repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if max((fnum(e.get("volume")) for e in b),default=0)<MIN_EVENT_VOLUME:break
    return rows,errs
def yes_token(m):
    outs=[str(x).lower() for x in jlist(m.get("outcomes"))];t=jlist(m.get("clobTokenIds"))
    if not t:return None
    try:i=outs.index("yes")
    except:i=0
    return str(t[i]) if i<len(t) else None
def eligible(ev):
    ms=ev.get("markets") or []
    return bool(ev.get("negRisk") or ev.get("enableNegRisk")) and not bool(ev.get("negRiskAugmented")) and fnum(ev.get("volume"))>=MIN_EVENT_VOLUME and 2<=len(ms)<=MAX_OUTCOMES and all(yes_token(m) for m in ms)
def rec(ev):
    return {"event_id":ev.get("id"),"slug":ev.get("slug"),"title":ev.get("title"),"volume":fnum(ev.get("volume")),"liquidity":fnum(ev.get("liquidity")),"active":bool(ev.get("active")),"closed":bool(ev.get("closed")),"negRisk":True,"negRiskAugmented":False,"endDate":ev.get("endDate"),"closedTime":ev.get("closedTime"),"markets":[{"id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),"groupItemTitle":m.get("groupItemTitle"),"volume":fnum(m.get("volume")),"liquidity":fnum(m.get("liquidity")),"yes_token":yes_token(m),"endDate":m.get("endDate"),"closedTime":m.get("closedTime")} for m in ev.get("markets") or []]}
def best_ask(tok):
    b=get("https://clob.polymarket.com/book",{"token_id":tok});xs=[]
    for a in b.get("asks") or []:
        try:xs.append((float(a["price"]),float(a["size"])))
        except:pass
    return min(xs,key=lambda x:x[0]) if xs else None
def fee(cid):
    try:return fnum((get(f"https://clob.polymarket.com/clob-markets/{cid}").get("fd") or {}).get("r"))
    except:return 0.0
def live_probe(ev):
    r=rec(ev);legs=[];errs=[]
    for m in r["markets"]:
        try:ba=best_ask(m["yes_token"])
        except Exception as ex:ba=None;errs.append({"condition_id":m["condition_id"],"error":repr(ex)})
        if not ba:return {**r,"complete":False,"reason":"missing_yes_ask","errors":errs}
        p,s=ba;legs.append({**m,"ask":p,"ask_size":s})
    raw=sum(x["ask"] for x in legs);shares=min(x["ask_size"] for x in legs)
    if raw>=1:return {**r,"complete":True,"legs":legs,"sum_best_ask":raw,"sum_fee_per_basket_share":0.0,"sum_all_in":raw,"gross_edge_per_basket_share":1-raw,"net_edge_per_basket_share":1-raw,"best_level_capturable_shares":shares,"best_level_net_profit_usd":0.0,"fee_skipped":"raw_sum>=1","errors":errs}
    sf=0.0
    for x in legs:
        fr=fee(x["condition_id"]);fp=fr*x["ask"]*(1-x["ask"]);x["fee_rate"]=fr;x["fee_per_share"]=fp;sf+=fp
    all_in=raw+sf
    return {**r,"complete":True,"legs":legs,"sum_best_ask":raw,"sum_fee_per_basket_share":sf,"sum_all_in":all_in,"gross_edge_per_basket_share":1-raw,"net_edge_per_basket_share":1-all_in,"best_level_capturable_shares":shares,"best_level_net_profit_usd":shares*max(0,1-all_in),"errors":errs}
def hist(ev):
    r=rec(ev);ends=[iso_ts(r.get("closedTime")),iso_ts(r.get("endDate"))]
    for m in r["markets"]:ends += [iso_ts(m.get("closedTime")),iso_ts(m.get("endDate"))]
    end=max((x for x in ends if x),default=None)
    if not end:return {**r,"usable":False,"reason":"no_end"}
    start=end-HIST_LOOKBACK_DAYS*86400;series={};errs=[]
    for m in r["markets"]:
        try:h=get("https://clob.polymarket.com/prices-history",{"market":m["yes_token"],"startTs":start,"endTs":end,"interval":"max","fidelity":HIST_FIDELITY_MIN}).get("history") or []
        except Exception as ex:h=[];errs.append({"token":m["yes_token"],"error":repr(ex)})
        hm={}
        for p in h:
            try:t=int(p["t"]);pr=float(p["p"]);hh=t//3600
            except:continue
            if hh not in hm or t>hm[hh][0]:hm[hh]=(t,pr)
        series[m["yes_token"]]=hm
    if any(not x for x in series.values()):return {**r,"usable":False,"reason":"empty_history","errors":errs}
    common=set.intersection(*(set(x) for x in series.values()));pts=[]
    for hh in sorted(common):
        s=sum(series[m["yes_token"]][hh][1] for m in r["markets"]);t=max(series[m["yes_token"]][hh][0] for m in r["markets"]);pts.append({"t":t,"hours_to_close":(end-t)/3600,"sum_yes_history_price":s,"gross_screen_edge":1-s})
    under=[x for x in pts if x["sum_yes_history_price"]<1]
    return {**r,"usable":bool(pts),"screen_only":True,"screen_warning":"prices-history is not executable historical ask/depth proof","common_hour_points":len(pts),"underround_hours":len(under),"min_sum_yes":min((x["sum_yes_history_price"] for x in pts),default=None),"max_gross_screen_edge":max((x["gross_screen_edge"] for x in pts),default=None),"best_points":sorted(under,key=lambda x:x["sum_yes_history_price"])[:12],"errors":errs}
def main():
    cr,ec=fetch_events(False,True,MAX_CLOSED_SCAN);ar,ea=fetch_events(True,False,MAX_ACTIVE_SCAN);closed=sorted((e for e in cr if eligible(e)),key=lambda e:fnum(e.get("volume")),reverse=True);active=sorted((e for e in ar if eligible(e)),key=lambda e:fnum(e.get("volume")),reverse=True)
    live=[live_probe(e) for e in active[:MAX_LIVE_EVENTS]];hs=[hist(e) for e in closed[:MAX_HIST_EVENTS]];cl=[x for x in live if x.get("complete")];pos=[x for x in cl if fnum(x.get("net_edge_per_basket_share"))>0];hu=[x for x in hs if x.get("usable")];h2=[x for x in hu if x.get("min_sum_yes") is not None and x["min_sum_yes"]<=.98]
    out={"method":{"non_augmented_only":True,"max_outcomes":MAX_OUTCOMES,"min_event_volume":MIN_EVENT_VOLUME,"historical_lookback_days":HIST_LOOKBACK_DAYS,"historical_is_screen_only":True},"inventory":{"eligible_closed_found":len(closed),"eligible_active_found":len(active),"historical_events_screened":len(hs),"live_events_probed":len(live)},"live_summary":{"complete_baskets":len(cl),"raw_underrounds":sum(x.get("sum_best_ask",99)<1 for x in cl),"positive_after_current_taker_fees":len(pos),"best":sorted(cl,key=lambda x:x.get("sum_all_in",99))[:20]},"historical_summary":{"usable_events":len(hu),"events_with_screen_sum_le_0_98":len(h2),"best":sorted(hu,key=lambda x:x.get("min_sum_yes") if x.get("min_sum_yes") is not None else 99)[:30]},"historical_events":hs,"live_events":live,"errors":ec+ea}
    OUT.write_text(json.dumps(out,indent=2));print(json.dumps({"inventory":out["inventory"],"live":{"complete":len(cl),"raw_under":sum(x.get("sum_best_ask",99)<1 for x in cl),"positive":len(pos),"top":[{"id":x["event_id"],"title":x["title"],"sum":round(x["sum_all_in"],6),"shares":round(x["best_level_capturable_shares"],3),"profit":round(x["best_level_net_profit_usd"],4)} for x in sorted(cl,key=lambda x:x["sum_all_in"])[:10]]},"historical":{"usable":len(hu),"screen_le_0_98":len(h2),"top":[{"id":x["event_id"],"title":x["title"],"min_sum":x["min_sum_yes"],"under_hours":x["underround_hours"]} for x in sorted(hu,key=lambda x:x["min_sum_yes"])[:12]]},"errors":out["errors"][:5]},indent=2))
if __name__=="__main__":main()
