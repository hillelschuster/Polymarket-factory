#!/usr/bin/env python3
"""Extended independent NFL T-7 calibration replication.

This follows the corrected sports test but isolates NFL and expands history.
Critical rules:
- use Gamma sports metadata and sportsMarketType=moneyline;
- use explicit gameStartTime/eventStartTime, never endDate if a game clock exists;
- price must be the last CLOB historical first-outcome token price AT OR BEFORE
  the anchor, max 24h stale;
- no centered future VWAP;
- one event/market observation only;
- primary test is pre-declared from the prior result: T-7d, first-outcome
  price 0.55-0.60, market lifespan <=14d.

Also follows the primary T-7 cohort to T-3d/T-1d/T-6h/T-1h to determine whether
any anomaly is already repriced before game time. These later historical prices
are mark-to-market diagnostics, not executable historical bids.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sports_flb_independent_check as base

OUT = Path("nfl_t7_extended_replication.json")
base.START_DATE_MIN = "2023-01-01T00:00:00Z"
base.MAX_EVENTS_PER_SPORT = 1400
base.MIN_TOTAL_MARKET_VOLUME = 500.0
ANCHORS = (7.0, 3.0, 1.0, 0.25, 1/24)
BUCKETS = ((0.50,0.55),(0.55,0.60),(0.60,0.65),(0.65,0.70),(0.70,0.80),(0.80,0.90))


def season_label(game_start_ts):
    d = dt.datetime.fromtimestamp(game_start_ts, tz=dt.timezone.utc)
    return d.year - 1 if d.month <= 2 else d.year


def summarize(rows):
    out=[]
    for lo,hi in BUCKETS:
        xs=[r for r in rows if lo<=r["price"]<hi]
        if not xs:
            out.append({"bucket":[lo,hi],"n":0});continue
        k=sum(r["resolved_first"] for r in xs)
        mp=statistics.mean(r["price"] for r in xs)
        wr=k/len(xs); ci=base.wilson(k,len(xs))
        out.append({"bucket":[lo,hi],"n":len(xs),"wins":k,"mean_price":mp,
                    "realized_first_rate":wr,"calibration_pp":100*(wr-mp),
                    "wilson95":[ci[0],ci[1]]})
    return out


def main():
    errors=[]
    meta=base.get("https://gamma-api.polymarket.com/sports")
    nfl=None
    for s in meta:
        if str(s.get("sport") or "").lower()=="nfl": nfl=s;break
    if not nfl:
        raise SystemExit("NFL metadata missing")
    tag=nfl.get("primaryTagId")
    if not tag:
        parts=[x for x in str(nfl.get("tags") or "").split(",") if x.strip()]
        tag=parts[-1] if parts else None
    events,errs=base.fetch_sports_events("nfl",tag); errors.extend(errs)
    byid={str(e.get("id") or e.get("slug")):e for e in events}; events=list(byid.values())

    candidates=[]
    for ev in events:
        for m in ev.get("markets") or []:
            if str(m.get("sportsMarketType") or "").lower()!="moneyline": continue
            if base.fnum(m.get("volume"))<base.MIN_TOTAL_MARKET_VOLUME: continue
            y=base.resolved_yes(m); tok=base.yes_token(m)
            if y is None or not tok: continue
            gs,clock=base.game_start(ev,m); cr,cr_field=base.creation_ts(ev,m)
            if not gs or not cr or cr>gs: continue
            outs=base.jlist(m.get("outcomes"))
            candidates.append({
                "event_id":ev.get("id"),"event_slug":ev.get("slug"),"event_title":ev.get("title"),
                "market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),
                "outcomes":outs,"first_outcome":outs[0] if outs else None,"second_outcome":outs[1] if len(outs)>1 else None,
                "market_volume":base.fnum(m.get("volume")),"token":tok,"resolved_first":y,
                "game_start":gs,"clock_field":clock,"creation":cr,"creation_field":cr_field,
                "lifespan_days":(gs-cr)/86400,"season":season_label(gs),
            })

    rows_by_anchor={a:[] for a in ANCHORS}; price_errors=[]
    for r in candidates:
        for days in ANCHORS:
            target=r["game_start"]-int(days*86400)
            if r["creation"]>target: continue
            ph,err=base.price_before(r["token"],target)
            if err:
                if len(price_errors)<150: price_errors.append({"event_id":r["event_id"],"anchor_days":days,**err})
                continue
            rows_by_anchor[days].append({**r,"anchor_days":days,"target_ts":target,**ph})

    tables={}
    for days,rows in rows_by_anchor.items():
        strict=[r for r in rows if r["lifespan_days"]<=14]
        tables[str(days)]={
            "n":len(rows),"n_strict":len(strict),"strict":summarize(strict),
            "by_season":{str(s):summarize([r for r in strict if r["season"]==s]) for s in sorted({r["season"] for r in strict})},
        }

    primary=[r for r in rows_by_anchor[7.0] if r["lifespan_days"]<=14 and 0.55<=r["price"]<0.60]
    k=sum(r["resolved_first"] for r in primary); mp=statistics.mean([r["price"] for r in primary]) if primary else None
    primary_summary={"n":len(primary),"wins":k,"mean_price":mp,
        "realized_first_rate":k/len(primary) if primary else None,
        "calibration_pp":100*(k/len(primary)-mp) if primary else None,
        "wilson95":list(base.wilson(k,len(primary))) if primary else [None,None],
        "unique_events":len({r["event_id"] for r in primary}),"by_season":{}}
    for s in sorted({r["season"] for r in primary}):
        xs=[r for r in primary if r["season"]==s]; kk=sum(r["resolved_first"] for r in xs); mm=statistics.mean(r["price"] for r in xs)
        primary_summary["by_season"][str(s)]={"n":len(xs),"wins":kk,"mean_price":mm,
            "realized_first_rate":kk/len(xs),"calibration_pp":100*(kk/len(xs)-mm)}

    # Follow only the T-7 primary cohort through later anchors.
    later_lookup={(r["event_id"],a):r for a,rows in rows_by_anchor.items() for r in rows}
    paths=[]
    for r in primary:
        p={"event_id":r["event_id"],"event_slug":r["event_slug"],"question":r["question"],"season":r["season"],
           "first_outcome":r["first_outcome"],"second_outcome":r["second_outcome"],"resolved_first":r["resolved_first"],
           "t7":r["price"],"clock_field":r["clock_field"],"lifespan_days":r["lifespan_days"]}
        for a,label in ((3.0,"t3"),(1.0,"t1"),(0.25,"t6h"),(1/24,"t1h")):
            z=later_lookup.get((r["event_id"],a)); p[label]=z["price"] if z else None
            p[label+"_change_from_t7"]=(z["price"]-r["price"]) if z else None
        paths.append(p)
    path_summary={}
    for label in ("t3","t1","t6h","t1h"):
        xs=[p[label+"_change_from_t7"] for p in paths if p.get(label) is not None]
        if xs:
            path_summary[label]={"n":len(xs),"mean_price_change":statistics.mean(xs),"median_price_change":statistics.median(xs),
                "share_positive":sum(x>0 for x in xs)/len(xs)}

    out={"method":{"start":"2023-01-01","market_type":"moneyline","clock":"explicit game clock preferred",
                   "price":"last historical first-outcome token price at/before anchor, max 24h stale",
                   "primary":"T-7d, 0.55-0.60, lifespan<=14d","future_vwap":False,
                   "path_warning":"later prices are historical prints, not executable bid proof"},
         "inventory":{"events":len(events),"candidates":len(candidates),"clock_fields":dict(__import__('collections').Counter(r['clock_field'] for r in candidates)),
                      "seasons":dict(__import__('collections').Counter(r['season'] for r in candidates))},
         "primary":primary_summary,"anchor_tables":tables,"primary_paths":paths,"path_summary":path_summary,
         "price_error_sample":price_errors,"errors":errors}
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"inventory":out["inventory"],"primary":primary_summary,"path_summary":path_summary,
                      "anchor_n":{str(a):tables[str(a)]["n_strict"] for a in ANCHORS},"errors":errors[:5]},indent=2))

if __name__=="__main__":main()
