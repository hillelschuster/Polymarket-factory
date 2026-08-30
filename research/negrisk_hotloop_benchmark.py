#!/usr/bin/env python3
"""Benchmark the deployable book-only hot loop for complete NegRisk baskets.

Discovery/semantics are cached outside the hot path. This script discovers once,
then repeatedly fetches current YES books with concurrent POST /books batches and
scores fee-adjusted depth. It reports all-event and short-horizon universes.

No orders are placed.
"""
from __future__ import annotations
import datetime as dt,json,statistics,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_fast_depth_observer as base

OUT=Path('negrisk_hotloop_benchmark.json')
WORKERS=8; LOOPS=10; SHORT_DAYS=45

def ts(s):
    if not s:return None
    try:return dt.datetime.fromisoformat(str(s).replace('Z','+00:00')).timestamp()
    except:return None

def chunks(xs,n):return [xs[i:i+n] for i in range(0,len(xs),n)]
def get_chunk(chunk):
    xs=base.req(base.CLOB+'/books',method='POST',body=[{'token_id':t} for t in chunk]);out={}
    for b in xs if isinstance(xs,list) else []:
        if b.get('asset_id'):out[str(b['asset_id'])]=b
    return out
def concurrent_books(tokens):
    cs=chunks(tokens,base.BOOK_BATCH);out={};errs=[];t0=time.monotonic()
    with ThreadPoolExecutor(max_workers=min(WORKERS,len(cs) or 1)) as ex:
        futs={ex.submit(get_chunk,c):i for i,c in enumerate(cs)}
        for f in as_completed(futs):
            try:out.update(f.result())
            except Exception as e:errs.append({'chunk':futs[f],'error':repr(e)})
    return out,errs,time.monotonic()-t0,len(cs)
def score(recs,books,fee_cache):
    raw=[];pos=[]
    for e in recs:
        legs=[]
        for m in e['markets']:
            lv=base.asks(books.get(m['yes_token']))
            if not lv:legs=[];break
            legs.append({**m,'asks':lv,'best_ask':lv[0][0],'best_size':lv[0][1]})
        if not legs:continue
        s=sum(x['best_ask'] for x in legs)
        if s>=1:continue
        for x in legs:
            cid=x['condition_id']
            if cid not in fee_cache:fee_cache[cid]=base.fee_rate(x)
            x['fee_rate']=fee_cache[cid]
        opt=base.optimize_depth(legs);r={'event_id':e['event_id'],'title':e['title'],'sum':s,'opt':opt,'endDate':e.get('endDate')}
        raw.append(r)
        if opt and opt['net_profit']>0:pos.append(r)
    return raw,pos
def main():
    t0=time.monotonic();events,derr=base.fetch_active_events();discovery=time.monotonic()-t0;now=time.time()
    originals=[e for e in events if base.eligible(e)]
    recs=[]
    for e in originals:
        r=base.event_rec(e);r['endDate']=e.get('endDate');r['end_ts']=ts(e.get('endDate'));recs.append(r)
    short=[r for r in recs if r['end_ts'] is not None and 0<r['end_ts']-now<=SHORT_DAYS*86400]
    universes={'all':recs,'short_45d':short};fee_cache={};results={}
    for name,rs in universes.items():
        tokens=list(dict.fromkeys(m['yes_token'] for e in rs for m in e['markets']))
        loops=[]
        for i in range(LOOPS):
            books,errs,sec,nreq=concurrent_books(tokens);raw,pos=score(rs,books,fee_cache)
            loops.append({'i':i,'seconds':sec,'requests':nreq,'books':len(books),'errors':errs,'raw_underrounds':len(raw),'positive':pos})
            time.sleep(.15)
        secs=[x['seconds'] for x in loops]
        results[name]={'events':len(rs),'tokens':len(tokens),'requests_per_loop':loops[0]['requests'] if loops else 0,
            'median_seconds':statistics.median(secs) if secs else None,'min_seconds':min(secs) if secs else None,'max_seconds':max(secs) if secs else None,
            'positive_loops':sum(bool(x['positive']) for x in loops),'loops':loops}
    # Scheduled end-date APR is only an optimistic upper bound because actual resolution can be later.
    for u in results.values():
        for loop in u['loops']:
            for r in loop['positive']:
                end=ts(r.get('endDate'));opt=r['opt']
                if end and end>now and opt and opt['capital_required']>0:
                    days=(end-now)/86400;r['scheduled_end_days']=days
                    r['simple_annualized_upper_bound']=opt['net_profit']/opt['capital_required']*365/days
    out={'generated_at':time.time(),'method':{'discovery_cached':True,'parallel_workers':WORKERS,'loops':LOOPS,'short_days':SHORT_DAYS,
        'warning':'scheduled-end annualization is an upper bound; resolution/capital release can occur later','no_orders':True},
        'discovery_seconds':discovery,'eligible_events':len(recs),'short_events':len(short),'fee_cache_size':len(fee_cache),'results':results,'discovery_errors':derr}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'discovery_seconds':discovery,'eligible_events':len(recs),'short_events':len(short),
        'universes':{k:{x:v[x] for x in ['events','tokens','requests_per_loop','median_seconds','min_seconds','max_seconds','positive_loops']} for k,v in results.items()},
        'short_positive':[x for l in results['short_45d']['loops'] for x in l['positive'][:3]][:10]},indent=2))
if __name__=='__main__':main()
