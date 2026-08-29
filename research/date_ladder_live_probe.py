#!/usr/bin/env python3
"""Discover and live-probe same-event deadline ladders.

Exact payoff relation for the same proposition under two deadlines:
    event occurs by EARLY  => event occurs by LATE
Therefore YES(LATE) + NO(EARLY) pays >= $1 in every state.

To avoid semantic garbage, discovery is deliberately strict:
- same Gamma event only;
- exactly one explicit month/day deadline in each question;
- normalized question must be identical after replacing that deadline;
- direction word must be `by` or `before` immediately preceding the date;
- same resolutionSource when both are populated;
- only adjacent deadlines are probed.

Current CLOB asks/depth are used. Fees are fetched only for raw baskets < $1.
Every apparent survivor still requires a manual rules/description audit before being
considered executable because descriptions can encode edge cases not visible in title.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

OUT = Path("date_ladder_live_probe.json")
UA = {"User-Agent": "polymarket-factory-research/1.0"}
MAX_EVENTS = 5000
MIN_EVENT_VOLUME = 1_000.0
MAX_LIVE_PAIRS = 500
MONTHS = {m.lower(): i for i, m in enumerate([
    "January","February","March","April","May","June","July","August","September","October","November","December"
], 1)}
MONTH_ALT = "|".join(x.title() for x in MONTHS)
DATE_RE = re.compile(
    rf"\b(?P<dir>by|before)\s+(?P<month>{MONTH_ALT})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>20\d{{2}}))?\b",
    re.I,
)


def get(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fnum(x):
    try: return float(x or 0)
    except Exception: return 0.0


def jlist(x):
    if isinstance(x, list): return x
    try:
        y = json.loads(x) if x else []
        return y if isinstance(y, list) else []
    except Exception: return []


def canon(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def parse_question(q, fallback_year):
    ms = list(DATE_RE.finditer(q or ""))
    if len(ms) != 1: return None
    m = ms[0]
    year = int(m.group("year")) if m.group("year") else fallback_year
    if not year: return None
    try:
        d = dt.date(year, MONTHS[m.group("month").lower()], int(m.group("day")))
    except Exception:
        return None
    # Keep the direction word in the template. `by X` and `before X` are not mixed.
    repl = f"{m.group('dir').lower()} <DEADLINE>"
    template = canon((q or "")[:m.start()] + repl + (q or "")[m.end():])
    return {"deadline": d.isoformat(), "template": template, "date_text": m.group(0)}


def year_hint(ev, m):
    for x in (m.get("endDate"), ev.get("endDate"), m.get("startDate"), ev.get("startDate")):
        if x:
            try: return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).year
            except Exception: pass
    return None


def tokens(m):
    outs = [str(x).lower() for x in jlist(m.get("outcomes"))]
    ts = jlist(m.get("clobTokenIds"))
    try: yi = outs.index("yes")
    except ValueError: yi = 0
    try: ni = outs.index("no")
    except ValueError: ni = 1
    return (str(ts[yi]) if yi < len(ts) else None, str(ts[ni]) if ni < len(ts) else None)


def fetch_events():
    rows=[]; off=0; errors=[]
    while len(rows)<MAX_EVENTS:
        lim=min(100, MAX_EVENTS-len(rows))
        try:
            b=get("https://gamma-api.polymarket.com/events", {"limit":lim,"offset":off,"order":"volume","ascending":"false"})
        except Exception as ex:
            errors.append({"offset":off,"error":repr(ex)}); break
        if not isinstance(b,list) or not b: break
        rows.extend(b); off += len(b)
        if max((fnum(e.get("volume")) for e in b),default=0)<MIN_EVENT_VOLUME: break
    return rows,errors


def best_ask(token, cache):
    if not token: return None
    if token not in cache:
        try:
            b=get("https://clob.polymarket.com/book", {"token_id":token}); xs=[]
            for a in b.get("asks") or []:
                try: xs.append((float(a["price"]),float(a["size"])))
                except Exception: pass
            cache[token]=min(xs,key=lambda z:z[0]) if xs else None
        except Exception: cache[token]=None
    return cache[token]


def fee_rate(cid, cache):
    if not cid: return 0.0
    if cid not in cache:
        try: cache[cid]=fnum((get(f"https://clob.polymarket.com/clob-markets/{cid}").get("fd") or {}).get("r"))
        except Exception: cache[cid]=0.0
    return cache[cid]


def main():
    events,errors=fetch_events(); groups=defaultdict(list)
    for ev in events:
        if fnum(ev.get("volume"))<MIN_EVENT_VOLUME: continue
        for m in ev.get("markets") or []:
            p=parse_question(m.get("question") or "", year_hint(ev,m))
            if not p: continue
            yes,no=tokens(m)
            if not yes or not no: continue
            r={
                "event_id":ev.get("id"),"event_slug":ev.get("slug"),"event_title":ev.get("title"),"event_volume":fnum(ev.get("volume")),
                "market_id":m.get("id"),"condition_id":m.get("conditionId"),"question":m.get("question"),"description":m.get("description"),
                "resolution_source":m.get("resolutionSource") or ev.get("resolutionSource"),"active":bool(m.get("active")),"closed":bool(m.get("closed")),
                "yes_token":yes,"no_token":no,**p,
            }
            groups[(str(ev.get("id")),p["template"])].append(r)

    ladders=[];pairs=[]
    for _,rs in groups.items():
        # One market per deadline; duplicates are semantic ambiguity => reject whole group.
        ds=[r["deadline"] for r in rs]
        if len(set(ds))<2 or len(set(ds))!=len(ds): continue
        rs=sorted(rs,key=lambda r:r["deadline"])
        # If populated resolution sources differ, reject.
        srcs={canon(r["resolution_source"]) for r in rs if r.get("resolution_source")}
        if len(srcs)>1: continue
        ladders.append({"event_id":rs[0]["event_id"],"event_slug":rs[0]["event_slug"],"event_title":rs[0]["event_title"],"event_volume":rs[0]["event_volume"],"template":rs[0]["template"],"deadlines":[r["deadline"] for r in rs],"markets":rs})
        for early,late in zip(rs,rs[1:]):
            pairs.append({"event_id":early["event_id"],"event_slug":early["event_slug"],"event_title":early["event_title"],"event_volume":early["event_volume"],"template":early["template"],"early":early,"late":late})
    ladders.sort(key=lambda x:x["event_volume"],reverse=True);pairs.sort(key=lambda x:x["event_volume"],reverse=True)

    live_pairs=[p for p in pairs if p["early"]["active"] and p["late"]["active"] and not p["early"]["closed"] and not p["late"]["closed"]][:MAX_LIVE_PAIRS]
    bc={};fc={};probes=[]
    for p in live_pairs:
        # guaranteed basket: YES(late) + NO(early)
        aa=best_ask(p["late"]["yes_token"],bc);bb=best_ask(p["early"]["no_token"],bc)
        if not aa or not bb: continue
        py,sy=aa;pn,sn=bb;raw=py+pn
        row={**p,"raw_cost":raw,"yes_late_ask":py,"yes_late_size":sy,"no_early_ask":pn,"no_early_size":sn,"common_top_size":min(sy,sn),"minimum_payoff":1.0}
        if raw<1:
            ry=fee_rate(p["late"]["condition_id"],fc);rn=fee_rate(p["early"]["condition_id"],fc)
            fy=ry*py*(1-py);fn=rn*pn*(1-pn);allin=raw+fy+fn
            row.update({"late_fee_rate":ry,"early_fee_rate":rn,"fee_cost":fy+fn,"all_in_cost":allin,"net_edge_per_share":1-allin,"top_level_max_net_profit":max(0,1-allin)*min(sy,sn),"requires_rules_audit":allin<1})
        else:
            row.update({"all_in_cost":raw,"net_edge_per_share":1-raw,"top_level_max_net_profit":0.0,"fee_skipped":"raw>=1","requires_rules_audit":False})
        probes.append(row)
    probes.sort(key=lambda x:x["all_in_cost"]);positive=[x for x in probes if x["all_in_cost"]<1]
    out={
        "method":{"relation":"by EARLY implies by LATE","basket":"YES(late)+NO(early)","semantic_filter":"same event + exact normalized question + same populated resolution source","pricing":"current CLOB best asks","candidate_gate":"all-in <1 then explicit rules audit"},
        "summary":{"events_scanned":len(events),"ladders":len(ladders),"adjacent_pairs":len(pairs),"active_pairs_probed":len(probes),"raw_below_1":sum(x["raw_cost"]<1 for x in probes),"all_in_below_1":len(positive),"best_all_in":probes[0]["all_in_cost"] if probes else None,"best_top_level_profit":max((x["top_level_max_net_profit"] for x in positive),default=0.0)},
        "positive_candidates":positive,"top_ladders":ladders[:100],"best_50_live":probes[:50],"errors":errors,
    }
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"summary":out["summary"],"positive":[{"id":x["event_id"],"title":x["event_title"],"early":x["early"]["question"],"late":x["late"]["question"],"cost":round(x["all_in_cost"],6),"shares":round(x["common_top_size"],3),"profit":round(x["top_level_max_net_profit"],4)} for x in positive[:20]],"top_ladders":[{"id":x["event_id"],"title":x["event_title"],"volume":round(x["event_volume"],0),"deadlines":x["deadlines"]} for x in ladders[:15]],"errors":errors[:5]},indent=2))

if __name__=="__main__": main()
