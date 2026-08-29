#!/usr/bin/env python3
"""Chronological backtest of a repeated finite-state Polymarket alpha family.

Family: standard 3-day opening-weekend box-office bracket markets.
Signal uses ONLY Friday+Saturday gross and prior movies' Sunday/Saturday ratios.
Sunday gross is outcome only. One independent decision per movie/weekend.

Execution proxy is deliberately harsh:
- fixed Sunday 21:00 UTC decision clock (Saturday daily gross should already be public)
- last YES taker BUY print at/before clock, max 120m stale; fallback any YES print
- +2c execution buffer (sensitivity 1/2/3/5c)
- current Culture taker fee 0.05*p*(1-p) applied to ALL historical entries

This is still a research backtest: historical Friday/Saturday pages are final archived values,
not point-in-time snapshots. State-revision stress (0-3%) is therefore reported explicitly.
No orders are placed.
"""
from __future__ import annotations
import datetime as dt
import json, math, re, time, urllib.parse, urllib.request
from pathlib import Path

STATE=Path('boxoffice_state_data.json')
OUT=Path('boxoffice_crossval_backtest.json')
UA={'User-Agent':'polymarket-factory-research/1.0'}
DECISION_HOUR_UTC=21
MIN_PRIOR=10
FEE_RATE=0.05
BUFFERS=(0.01,0.02,0.03,0.05)
CAPS=(0.80,0.85,0.90,0.95)
STATE_STRESS=(0.00,0.01,0.02,0.03)
VARIANTS=('range','q05_q95','q10_q90')


def get(url,params=None,timeout=30):
    if params:url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:return json.load(r)

def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or '[]')
    except:return []

def q(xs,p):
    xs=sorted(xs)
    if not xs:return None
    z=p*(len(xs)-1); lo=int(z); hi=min(lo+1,len(xs)-1); w=z-lo
    return xs[lo]*(1-w)+xs[hi]*w

def ratio_interval(prior,variant):
    if variant=='range':return min(prior),max(prior)
    if variant=='q05_q95':return q(prior,.05),q(prior,.95)
    if variant=='q10_q90':return q(prior,.10),q(prior,.90)
    raise ValueError(variant)

def unit_num(text):
    s=(text or '').lower().replace(',','').replace('$','').strip()
    m=re.search(r'([0-9]+(?:\.[0-9]+)?)\s*([mkb])?',s)
    if not m:return None
    x=float(m.group(1));u=m.group(2)
    return x*({'k':1e3,'m':1e6,'b':1e9}.get(u,1.0))

def parse_bracket(label,question=''):
    """Return [low, high) dollar bounds; infinities allowed."""
    s=(label or '').strip()
    if not s:s=question or ''
    low=s.lower().replace('–','-').replace('—','-')
    # Keep only the compact outcome-looking portion when question repeats prose.
    # Common labels: <90m, <$48m, 137-150m, $105-115m, >115m, 350m+.
    nums=re.findall(r'\$?\s*([0-9]+(?:\.[0-9]+)?)\s*([mkb])?',low)
    def cv(pair):
        x=float(pair[0]);u=pair[1]
        return x*({'k':1e3,'m':1e6,'b':1e9}.get(u,1.0))
    if not nums:return None
    if ('<' in low or 'under' in low) and len(nums)>=1:return (-math.inf,cv(nums[-1]))
    if ('>' in low or 'over' in low) and len(nums)>=1:return (cv(nums[-1]),math.inf)
    if '+' in low and len(nums)>=1:return (cv(nums[-1]),math.inf)
    if len(nums)>=2:return (cv(nums[-2]),cv(nums[-1]))
    return None

def winning_market(markets):
    wins=[]
    for m in markets or []:
        try:yes=float(arr(m.get('outcomePrices'))[0])
        except:continue
        if yes>.999:wins.append(m)
    return wins[0] if len(wins)==1 else None

def market_defs(markets):
    out=[]
    for m in markets or []:
        ids=arr(m.get('clobTokenIds'))
        cid=m.get('conditionId')
        b=parse_bracket(m.get('groupItemTitle'),m.get('question'))
        if b and ids and cid:
            out.append({'market':m,'bounds':b,'yes_token':str(ids[0]),'conditionId':str(cid)})
    return out

def interval_inside(bounds,lo,hi):
    a,b=bounds
    # small epsilon avoids floating-point boundary artifacts
    return lo>=a-1e-6 and hi<b+1e-6

def choose_lock(markets,final_lo,final_hi):
    hits=[m for m in markets if interval_inside(m['bounds'],final_lo,final_hi)]
    return hits[0] if len(hits)==1 else None

def fetch_trades(cid,start,end):
    try:return get('https://data-api.polymarket.com/trades',{'market':cid,'start':int(start.timestamp()),'end':int(end.timestamp()),'limit':10000,'offset':0,'takerOnly':'true'})
    except Exception as ex:return {'error':repr(ex)}

def entry_print(md,sunday):
    clock=dt.datetime.combine(sunday,dt.time(DECISION_HOUR_UTC),tzinfo=dt.timezone.utc)
    start=clock-dt.timedelta(hours=2); raw=fetch_trades(md['conditionId'],start,clock)
    if not isinstance(raw,list):return {'error':raw.get('error') if isinstance(raw,dict) else 'bad response'}
    xs=[]
    for x in raw:
        if str(x.get('asset'))!=md['yes_token']:continue
        try:
            ts=int(x['timestamp']);p=float(x['price']);side=str(x.get('side') or '').upper();size=float(x.get('size') or 0)
        except:continue
        if ts<=int(clock.timestamp()):xs.append((ts,p,side,size))
    if not xs:return None
    buys=[x for x in xs if x[2]=='BUY']
    x=max(buys,key=lambda z:z[0]) if buys else max(xs,key=lambda z:z[0])
    return {'t':x[0],'p':x[1],'side':x[2],'size':x[3],'age_min':(int(clock.timestamp())-x[0])/60,'used_buy':bool(buys)}

def fee(p):return FEE_RATE*p*(1-p)

def max_drawdown(curve):
    peak=0.0;dd=0.0
    for x in curve:
        peak=max(peak,x);dd=max(dd,peak-x)
    return dd

def summarize(rows,buffer,cap):
    trades=[];cum=0.0;curve=[]
    for r in rows:
        ep=r.get('entry')
        if not ep:continue
        raw=float(ep['p']); execp=min(.999,raw+buffer);cost=execp+fee(execp)
        if cost>cap or cost>=1:continue
        win=bool(r['correct'])
        # Equal $100 capital per independent movie.
        roi=(1.0/cost-1.0) if win else -1.0
        pnl100=100*roi
        cum+=pnl100;curve.append(cum)
        trades.append({'movie':r['movie'],'date':r['sunday'],'raw_price':raw,'cost':cost,'win':win,'pnl_per_100':pnl100,'entry_age_min':ep.get('age_min'),'entry_side':ep.get('side')})
    n=len(trades);wins=sum(t['win'] for t in trades);capital=100*n
    return {'n':n,'wins':wins,'losses':n-wins,'win_rate':wins/n if n else None,'pnl_equal_100':sum(t['pnl_per_100'] for t in trades),'roi_on_total_capital':sum(t['pnl_per_100'] for t in trades)/capital if capital else None,'max_drawdown_equal_100':max_drawdown(curve),'trades':trades}

def main():
    data=json.loads(STATE.read_text())
    events=[r for r in data.get('events') or [] if r.get('matched')]
    events.sort(key=lambda r:r['sunday'])
    ratios=[];all_results={};parse_fail=[]
    for stress in STATE_STRESS:
        sk=f'{stress:.2f}';all_results[sk]={}
        for variant in VARIANTS:all_results[sk][variant]=[]
    base_records=[]
    for ev in events:
        sunday=dt.date.fromisoformat(ev['sunday'])
        defs=market_defs(ev.get('markets'))
        winm=winning_market(ev.get('markets'))
        if len(defs)<2 or not winm:
            parse_fail.append({'movie':ev.get('movie_title'),'date':ev.get('sunday'),'parsed_markets':len(defs),'has_unique_winner':bool(winm)})
            ratios.append(float(ev['sunday_to_saturday']));continue
        winner_id=str(winm.get('id'))
        prior=list(ratios)
        record={'movie':ev['movie_title'],'sunday':ev['sunday'],'F':ev['friday_gross'],'S':ev['saturday_gross'],'actual_total':ev['weekend_total'],'actual_ratio':ev['sunday_to_saturday'],'prior_n':len(prior),'winner_market_id':winner_id}
        base_records.append(record)
        if len(prior)>=MIN_PRIOR:
            for stress in STATE_STRESS:
                # Revision stress applies symmetrically to observed Fri/Sat state.
                flo=ev['friday_gross']*(1-stress); slo=ev['saturday_gross']*(1-stress)
                fhi=ev['friday_gross']*(1+stress); shi=ev['saturday_gross']*(1+stress)
                for variant in VARIANTS:
                    rlo,rhi=ratio_interval(prior,variant)
                    final_lo=flo+slo+slo*rlo
                    final_hi=fhi+shi+shi*rhi
                    choice=choose_lock(defs,final_lo,final_hi)
                    if not choice:continue
                    correct=str(choice['market'].get('id'))==winner_id
                    rec={'movie':ev['movie_title'],'sunday':ev['sunday'],'prior_n':len(prior),'variant':variant,'state_stress':stress,'ratio_lo':rlo,'ratio_hi':rhi,'final_lo':final_lo,'final_hi':final_hi,'chosen_label':choice['market'].get('groupItemTitle') or choice['market'].get('question'),'chosen_market_id':str(choice['market'].get('id')),'winner_market_id':winner_id,'correct':correct,'actual_total':ev['weekend_total'],'event_volume':ev.get('event_volume')}
                    # Entry only once per unique (movie,stress,variant) signal.
                    rec['entry']=entry_print(choice,sunday)
                    all_results[f'{stress:.2f}'][variant].append(rec)
                    time.sleep(.015)
        ratios.append(float(ev['sunday_to_saturday']))

    summaries={}
    for sk,vmap in all_results.items():
        summaries[sk]={}
        for variant,rows in vmap.items():
            accuracy=sum(r['correct'] for r in rows)/len(rows) if rows else None
            d={'signals':len(rows),'correct':sum(r['correct'] for r in rows),'accuracy':accuracy,'with_entry':sum(bool(r.get('entry')) for r in rows),'execution':{}}
            for b in BUFFERS:
                d['execution'][f'buffer_{b:.2f}']={f'cap_{c:.2f}':summarize(rows,b,c) for c in CAPS}
            summaries[sk][variant]=d

    out={'method':{'decision_hour_utc':DECISION_HOUR_UTC,'min_prior_movies':MIN_PRIOR,'current_fee_rate_applied_to_history':FEE_RATE,'buffers':BUFFERS,'cost_caps':CAPS,'state_revision_stress':STATE_STRESS,'variants':VARIANTS,'important_limit':'Friday/Saturday historical pages are final values, not archived point-in-time snapshots. State-revision stress reduces but does not eliminate this limitation. Entry is a prior taker trade proxy plus explicit buffer, not reconstructed L2 ask.'},'universe':{'matched_events':len(events),'testable_after_warmup':max(0,len(events)-MIN_PRIOR),'date_start':events[0]['sunday'] if events else None,'date_end':events[-1]['sunday'] if events else None},'summaries':summaries,'signals':all_results,'base_records':base_records,'parse_fail':parse_fail}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    # Print compact decision table only.
    compact={'universe':out['universe'],'parse_fail_n':len(parse_fail),'summary':{}}
    for sk in summaries:
        compact['summary'][sk]={}
        for var,d in summaries[sk].items():
            compact['summary'][sk][var]={'signals':d['signals'],'correct':d['correct'],'accuracy':d['accuracy'],'with_entry':d['with_entry'],'base_buffer_2c':{cap:{k:v for k,v in d['execution']['buffer_0.02'][cap].items() if k!='trades'} for cap in d['execution']['buffer_0.02']}}
    print(json.dumps(compact,indent=2))

if __name__=='__main__':main()
