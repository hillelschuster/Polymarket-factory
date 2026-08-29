#!/usr/bin/env python3
"""Historical audit of deterministic state constraints in NBA team win-total markets.

Target: Polymarket 2025-26 NBA Win Totals (30 team markets).
For each team that ultimately finished UNDER, reconstruct the first completed regular-
season game after which:

    wins_so_far + games_remaining <= line

At that point OVER is mathematically impossible. Polymarket rules explicitly permit
early NO/UNDER resolution in this state. We then inspect actual taker BUY prints on
the certain-side token only after a conservative result-public time (scheduled tip +
5 hours), and at additional 10m/30m/2h/6h delays. This makes seconds-scale chain/
match timestamp ambiguity irrelevant to any claimed slow stale-price opportunity.

Research only. No orders.
"""
from __future__ import annotations
import datetime as dt
import json,re,time,urllib.parse,urllib.request
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0"}
OUT=Path("nba_win_total_elimination.json")
EVENT_SLUG="nba-win-totals-over-or-under"
SEASON=2026
REG_SEASON_GAMES=82
CONSERVATIVE_GAME_HOURS=5
DELAYS_MIN=(0,10,30,120,360)
CURRENT_SPORTS_FEE_RATE=0.05  # current Aug-2026 help-center schedule; historical fees may have been lower.

def get(url,params=None,timeout=30):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:return json.load(r)

def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or "[]")
    except:return []

def norm(s):return re.sub(r"[^a-z0-9]+"," ",(s or "").lower()).strip()
def iso(s):return dt.datetime.fromisoformat(str(s).replace("Z","+00:00"))
def fee(p):return CURRENT_SPORTS_FEE_RATE*p*(1-p)

def espn_teams():
    j=get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",{"limit":100})
    rows=j["sports"][0]["leagues"][0]["teams"]
    out=[]
    for x in rows:
        t=x.get("team") or x
        out.append({"id":str(t.get("id")),"displayName":t.get("displayName"),"shortDisplayName":t.get("shortDisplayName"),"abbreviation":t.get("abbreviation")})
    return out

def find_team(market,teams):
    txt=norm(" ".join([str(market.get("question") or ""),str(market.get("groupItemTitle") or "")]))
    hits=[]
    for t in teams:
        for key in ("displayName","shortDisplayName"):
            n=norm(t.get(key))
            if n and n in txt:hits.append((len(n),t))
    return max(hits,key=lambda z:z[0])[1] if hits else None

def parse_line(market):
    txt=" ".join([str(market.get("question") or ""),str(market.get("groupItemTitle") or "")])
    pats=[r"more than\s+([0-9]+(?:\.[0-9]+)?)",r"over\s+([0-9]+(?:\.[0-9]+)?)",r"([0-9]+\.5)\+?"]
    for p in pats:
        m=re.search(p,txt,re.I)
        if m:return float(m.group(1))
    return None

def schedule(team_id):
    return get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule",{"season":SEASON,"seasontype":2})

def completed_record(team_id):
    j=schedule(team_id); games=[];wins=0
    for ev in j.get("events") or []:
        comp=(ev.get("competitions") or [{}])[0]
        status=(comp.get("status") or ev.get("status") or {}).get("type") or {}
        if not bool(status.get("completed")):continue
        competitors=comp.get("competitors") or []
        me=next((c for c in competitors if str((c.get("team") or {}).get("id"))==str(team_id)),None)
        if not me:continue
        # schedule endpoint is regular-season scoped; count completed official games only.
        win=bool(me.get("winner"))
        wins+=int(win)
        start=iso(ev.get("date"))
        games.append({"event_id":ev.get("id"),"date":ev.get("date"),"start":start,"win":win,"wins_after":wins,"games_after":len(games)+1,"name":ev.get("name")})
    games.sort(key=lambda x:x["start"])
    # Recompute chronological wins because API ordering is not guaranteed.
    wins=0
    for i,g in enumerate(games,1):wins+=int(g["win"]);g["wins_after"]=wins;g["games_after"]=i
    return games

def elimination(games,line):
    for g in games:
        rem=max(0,REG_SEASON_GAMES-g["games_after"])
        max_wins=g["wins_after"]+rem
        if max_wins<=line:
            return {**g,"remaining_after":rem,"max_possible_wins":max_wins,"line":line,"ready_utc":g["start"]+dt.timedelta(hours=CONSERVATIVE_GAME_HOURS)}
    return None

def trades(condition_id,start,end):
    try:
        j=get("https://data-api.polymarket.com/trades",{"market":condition_id,"start":int(start.timestamp()),"end":int(end.timestamp()),"limit":10000,"offset":0,"takerOnly":"true"})
        return j if isinstance(j,list) else []
    except Exception:return []

def certain_token(market):
    outs=[str(x).lower() for x in arr(market.get("outcomes"))]; ids=[str(x) for x in arr(market.get("clobTokenIds"))]
    if len(ids)<2:return None,None
    # These markets are YES/NO; the certain UNDER state is NO. Also support literal Over/Under.
    for wanted in ("no","under"):
        if wanted in outs:
            i=outs.index(wanted);return ids[i],outs[i]
    return ids[1],outs[1] if len(outs)>1 else "index1"

def first_buy_after(rows,token,ts):
    xs=[]
    for x in rows:
        if str(x.get("asset"))!=str(token) or str(x.get("side") or "").upper()!="BUY":continue
        try:t=int(x["timestamp"]);p=float(x["price"]);sz=float(x.get("size") or 0)
        except:continue
        if t>=int(ts.timestamp()):xs.append((t,p,sz))
    if not xs:return None
    t,p,sz=min(xs,key=lambda z:z[0]);cost=p+fee(p)
    return {"timestamp":t,"price":p,"size":sz,"delay_from_requested_min":(t-int(ts.timestamp()))/60,"current_fee_per_share":fee(p),"all_in_current_fee":cost,"locked_profit_per_share_current_fee":1-cost,"roi_on_cost_current_fee":(1-cost)/cost if cost>0 else None}

def main():
    ev=get("https://gamma-api.polymarket.com/events/slug/"+EVENT_SLUG); teams=espn_teams(); results=[]; errors=[]
    markets=ev.get("markets") or []
    for idx,m in enumerate(markets):
        team=find_team(m,teams); line=parse_line(m); token,outcome=certain_token(m)
        if not team or line is None or not token:
            errors.append({"market":m.get("question"),"team":team,"line":line,"token":token});continue
        try:games=completed_record(team["id"])
        except Exception as ex:
            errors.append({"market":m.get("question"),"team":team,"error":repr(ex)});continue
        elim=elimination(games,line)
        try:prices=[float(x) for x in arr(m.get("outcomePrices"))]
        except:prices=[]
        under_resolved=(len(prices)>1 and prices[1]>.999)
        rec={"team":team,"market_id":m.get("id"),"conditionId":m.get("conditionId"),"question":m.get("question"),"groupItemTitle":m.get("groupItemTitle"),"line":line,"market_volume":float(m.get("volume") or 0),"outcomes":arr(m.get("outcomes")),"outcomePrices":arr(m.get("outcomePrices")),"certain_token":token,"certain_outcome":outcome,"completed_games":len(games),"final_wins":sum(int(g["win"]) for g in games),"under_resolved":under_resolved,"elimination":None,"post_elimination":{}}
        if elim:
            ee=dict(elim);ee["start"]=ee["start"].isoformat();ee["ready_utc"]=ee["ready_utc"].isoformat();rec["elimination"]=ee
            ready=iso(ee["ready_utc"]); tr=trades(str(m.get("conditionId")),ready,ready+dt.timedelta(hours=72))
            for dm in DELAYS_MIN:
                rec["post_elimination"][f"after_{dm}m"]=first_buy_after(tr,token,ready+dt.timedelta(minutes=dm))
            # Count clear stale certain-side buys after conservative +10m, split by economically meaningful prices.
            clear=[]
            cutoff=ready+dt.timedelta(minutes=10)
            for x in tr:
                if str(x.get("asset"))!=str(token) or str(x.get("side") or "").upper()!="BUY":continue
                try:t=int(x["timestamp"]);p=float(x["price"]);sz=float(x.get("size") or 0)
                except:continue
                if t>=int(cutoff.timestamp()):clear.append({"t":t,"p":p,"size":sz})
            rec["clear_stale_buys_after_10m"]={"n":len(clear),"lt_99":sum(x["p"]<.99 for x in clear),"lt_98":sum(x["p"]<.98 for x in clear),"lt_95":sum(x["p"]<.95 for x in clear),"min_price":min((x["p"] for x in clear),default=None),"max_size_at_lt98":max((x["size"] for x in clear if x["p"]<.98),default=None)}
        results.append(rec);time.sleep(.02)
    eligible=[r for r in results if r.get("elimination") and r.get("under_resolved")]
    def opp(delay="after_10m",cap=.98):
        xs=[]
        for r in eligible:
            p=(r.get("post_elimination") or {}).get(delay)
            if p and p["price"]<=cap:xs.append({"team":r["team"]["displayName"],"line":r["line"],"elimination_ready":r["elimination"]["ready_utc"],"price":p["price"],"size":p["size"],"all_in_current_fee":p["all_in_current_fee"],"locked_profit_per_share_current_fee":p["locked_profit_per_share_current_fee"],"roi_on_cost_current_fee":p["roi_on_cost_current_fee"],"delay_from_requested_min":p["delay_from_requested_min"]})
        return xs
    summary={"event_title":ev.get("title"),"event_volume":float(ev.get("volume") or 0),"markets":len(markets),"mapped":len(results),"explicit_under_eliminations":len(eligible),"current_fee_rate_stress":CURRENT_SPORTS_FEE_RATE,"opportunities_after_10m_le_98c":opp("after_10m",.98),"opportunities_after_30m_le_98c":opp("after_30m",.98),"opportunities_after_2h_le_98c":opp("after_120m",.98),"opportunities_after_10m_le_95c":opp("after_10m",.95)}
    out={"summary":summary,"results":results,"errors":errors,"method_limitations":["ESPN scheduled tip + 5h is used as a deliberately late proxy for result-public time; it is not the exact final-buzzer timestamp.","Data API timestamps can differ from CLOB match time by seconds. Claims focus on >=10 minute delays so this cannot explain economically slow stale prices.","Historical market fees may differ. Profitability is stressed using current Aug-2026 Sports taker rate 5%.","Trade prints demonstrate at least one historical executable fill, not book depth available to us prospectively."]}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary,"errors":errors[:10]},indent=2))
if __name__=="__main__":main()
