#!/usr/bin/env python3
"""Symmetric NFL T-7 favorite calibration test.

The earlier clean multi-season test found a large edge only when the *first-listed*
outcome token happened to trade 0.55-0.60 at T-7. This script removes that possible
ordering artifact by fetching BOTH moneyline outcome tokens and selecting whichever
side is the 55-60c favorite.

Strict primary cohort:
- closed NFL moneyline markets discovered via the broad NFL tag;
- explicit gameStartTime/eventStartTime only (never endDate as game clock);
- market created >=7 days before game and lifespan <=14 days;
- both outcome-token prices observed at/before T-7, each <=24h stale;
- the two independently observed token prices must sum within 3c of $1;
- exactly one side priced [0.55, 0.60);
- no centered/future VWAP.

This is still calibration evidence, not historical executable ask/depth proof.
A current Sports fee coefficient of 0.05 is applied only as a forward-cost stress.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sports_flb_independent_check as base

OUT = Path("nfl_t7_symmetric_favorite.json")
TAG_ID = 450
MAX_EVENTS = 3500
MIN_VOLUME = 500.0
CUTOFF = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp())
TARGET_DAYS = 7
MAX_LIFESPAN_DAYS = 14
SUM_TOLERANCE = 0.03
BUCKETS = ((.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,.80),(.80,.90))
FORWARD_FEE_RATE = 0.05


def fetch_events():
    rows=[]; errors=[]; off=0
    while len(rows)<MAX_EVENTS:
        lim=min(100, MAX_EVENTS-len(rows))
        try:
            b=base.fetch_page({"limit":lim,"offset":off,"closed":"true","tag_id":TAG_ID})
        except Exception as ex:
            errors.append({"offset":off,"error":repr(ex)}); break
        if not isinstance(b,list) or not b: break
        rows.extend(b); off+=len(b)
        if len(b)<lim: break
        time.sleep(.02)
    return rows, errors


def explicit_game_clock(ev,m):
    for field,obj in (("gameStartTime",m),("eventStartTime",m),("eventStartTime",ev)):
        v=base.ts(obj.get(field))
        if v: return v,field
    return None,None


def creation(ev,m):
    return base.created(ev,m)


def resolved_pair(m):
    prices=base.jl(m.get("outcomePrices")); outs=base.jl(m.get("outcomes")); toks=base.jl(m.get("clobTokenIds"))
    if len(prices)!=2 or len(outs)!=2 or len(toks)!=2: return None
    try:p=[float(x) for x in prices]
    except Exception:return None
    if max(p)<.99 or min(p)>.01:return None
    winner=0 if p[0]>=.99 else 1
    return {
        "outcomes":[str(x) for x in outs],
        "tokens":[str(x) for x in toks],
        "winner_index":winner,
    }


def poisson_binomial_tail(ps, k):
    """P(X>=k) for independent Bernoulli with heterogeneous probabilities ps."""
    n=len(ps)
    dp=[0.0]*(n+1); dp[0]=1.0
    for p in ps:
        nxt=[0.0]*(n+1)
        for j in range(n):
            nxt[j]+=dp[j]*(1-p)
            nxt[j+1]+=dp[j]*p
        dp=nxt
    return sum(dp[k:])


def fee_cost(p):
    return FORWARD_FEE_RATE*p*(1-p)


def equal_capital_roi(rows, stake=100.0):
    pnl=0.0
    for r in rows:
        all_in=r["favorite_price"]+fee_cost(r["favorite_price"])
        shares=stake/all_in
        pnl += shares*(1-all_in) if r["favorite_won"] else -stake
    capital=stake*len(rows)
    return {
        "stake_per_trade":stake,
        "pnl":pnl,
        "capital_sum":capital,
        "roi":pnl/capital if capital else None,
    }


def summarize(rows):
    if not rows:return {"n":0}
    n=len(rows); k=sum(r["favorite_won"] for r in rows); mp=statistics.mean(r["favorite_price"] for r in rows)
    ci=base.wilson(k,n)
    return {
        "n":n,"wins":k,"win_rate":k/n,"mean_price":mp,"calibration_pp":100*(k/n-mp),
        "wilson95":list(ci),"poisson_binomial_tail_p":poisson_binomial_tail([r["favorite_price"] for r in rows],k),
        "equal_100_forward_fee_stress":equal_capital_roi(rows),
        "first_listed_favorite_n":sum(r["favorite_index"]==0 for r in rows),
        "second_listed_favorite_n":sum(r["favorite_index"]==1 for r in rows),
        "by_season":{},
    }


def main():
    events,errors=fetch_events()
    events=list({str(e.get("id") or e.get("slug")):e for e in events}.values())
    candidates=[]; price_errors=[]; clocks=Counter()
    for ev in events:
        for m in ev.get("markets") or []:
            if str(m.get("sportsMarketType") or "").lower()!="moneyline":continue
            if base.fnum(m.get("volume"))<MIN_VOLUME:continue
            rp=resolved_pair(m)
            if not rp:continue
            gs,gf=explicit_game_clock(ev,m)
            cr,cf=creation(ev,m)
            if not gs or not cr or gs<cr or gs<CUTOFF:continue
            lifespan=(gs-cr)/86400
            if lifespan>MAX_LIFESPAN_DAYS:continue
            target=gs-TARGET_DAYS*86400
            if cr>target:continue
            clocks[gf]+=1
            obs=[]; bad=False
            for i,tok in enumerate(rp["tokens"]):
                ph,err=base.price_before(tok,target)
                if err:
                    bad=True
                    if len(price_errors)<200:price_errors.append({"event_id":ev.get("id"),"market_id":m.get("id"),"token_index":i,**err})
                    break
                obs.append(ph)
            if bad or len(obs)!=2:continue
            p0,p1=obs[0]["price"],obs[1]["price"]
            s=p0+p1
            if abs(s-1)>SUM_TOLERANCE:continue
            favs=[i for i,p in enumerate((p0,p1)) if .55<=p<.60]
            if len(favs)!=1:continue
            fi=favs[0]; fp=(p0,p1)[fi]
            d=dt.datetime.fromtimestamp(gs,tz=dt.timezone.utc);season=d.year-1 if d.month<=2 else d.year
            candidates.append({
                "event_id":ev.get("id"),"event_slug":ev.get("slug"),"event_title":ev.get("title"),
                "market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),
                "season":season,"game_start":gs,"clock_field":gf,"lifespan_days":lifespan,
                "outcomes":rp["outcomes"],"tokens":rp["tokens"],"winner_index":rp["winner_index"],
                "first_price":p0,"second_price":p1,"price_sum":s,
                "first_age_h":obs[0]["age_hours"],"second_age_h":obs[1]["age_hours"],
                "favorite_index":fi,"favorite_outcome":rp["outcomes"][fi],"favorite_price":fp,
                "favorite_won":1 if rp["winner_index"]==fi else 0,
                "favorite_was_first_listed":fi==0,"market_volume":base.fnum(m.get("volume")),
            })

    overall=summarize(candidates)
    seasons=sorted({r["season"] for r in candidates})
    overall["by_season"]={str(s):summarize([r for r in candidates if r["season"]==s]) for s in seasons}
    overall["by_listing_side"]={
        "first":summarize([r for r in candidates if r["favorite_index"]==0]),
        "second":summarize([r for r in candidates if r["favorite_index"]==1]),
    }

    # Broad symmetric calibration table for all coherent two-token observations at T-7.
    # Re-fetching every market for every bucket would be wasteful; primary cohort is the decision gate.
    out={
        "method":{
            "selector":"broad NFL tag_id 450","market_type":"moneyline","explicit_game_clock_only":True,
            "anchor_days":TARGET_DAYS,"lifespan_max_days":MAX_LIFESPAN_DAYS,"both_token_prices_required":True,
            "max_stale_hours":base.MAX_STALE_H,"token_price_sum_tolerance":SUM_TOLERANCE,
            "primary_bucket":[.55,.60],"forward_fee_rate_stress":FORWARD_FEE_RATE,
            "execution_warning":"historical last print at/before anchor is not executable ask/depth proof",
        },
        "inventory":{
            "raw_events":len(events),"primary_symmetric_favorites":len(candidates),"clock_fields":dict(clocks),
            "seasons":dict(Counter(r["season"] for r in candidates)),
        },
        "primary":overall,
        "rows":candidates,
        "price_error_sample":price_errors,
        "errors":errors,
    }
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"inventory":out["inventory"],"primary":overall,"errors":errors[:5],"price_errors":price_errors[:5]},indent=2))


if __name__=="__main__":main()
