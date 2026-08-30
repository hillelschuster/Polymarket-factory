#!/usr/bin/env python3
"""Fast, dry, depth-aware observer for non-augmented NegRisk YES baskets.

Historical evidence shows genuine complete-basket underrounds can exist for only
seconds. The older research scanner fetched one order book per leg sequentially;
this observer is designed for the actual money path:

1. discover active non-augmented NegRisk events;
2. batch-fetch every YES-token book with POST /books;
3. reject events whose top-of-book YES ask sum is >= $1 (deeper asks cannot help);
4. only for raw underrounds, fetch current fee coefficients;
5. integrate all ask ladders and choose basket quantity maximizing net dollar PnL.

No orders are placed. Output includes wall-clock scan latency so VPS viability can
be judged directly.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT=Path('negrisk_fast_depth_observer.json')
UA={'User-Agent':'polymarket-factory-research/1.0'}
GAMMA='https://gamma-api.polymarket.com'; CLOB='https://clob.polymarket.com'
MAX_EVENTS=1800; MIN_VOLUME=5000.0; MAX_OUTCOMES=30; BOOK_BATCH=100


def req(url,params=None,method='GET',body=None,retries=3):
    if params:url+=('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    data=None if body is None else json.dumps(body).encode(); h=dict(UA)
    if data is not None:h['Content-Type']='application/json'
    last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.1*(i+1))
    raise last

def num(x):
    try:return float(x or 0)
    except:return 0.0

def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []

def yes_token(m):
    outs=[str(x).casefold() for x in jl(m.get('outcomes'))];t=jl(m.get('clobTokenIds'))
    if not t:return None
    try:i=outs.index('yes')
    except ValueError:return None
    return str(t[i]) if i<len(t) else None

def fetch_active_events():
    rows=[];errs=[];off=0
    while len(rows)<MAX_EVENTS:
        lim=min(100,MAX_EVENTS-len(rows))
        try:b=req(GAMMA+'/events',{'limit':lim,'offset':off,'active':'true','closed':'false','order':'volume','ascending':'false'})
        except Exception as ex:errs.append({'offset':off,'error':repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if len(b)<lim:break
    return rows,errs

def eligible(ev):
    ms=ev.get('markets') or []
    if not(ev.get('negRisk') or ev.get('enableNegRisk')) or ev.get('negRiskAugmented'):return False
    if num(ev.get('volume'))<MIN_VOLUME or not(2<=len(ms)<=MAX_OUTCOMES):return False
    for m in ms:
        if not(m.get('active') and not m.get('closed') and m.get('enableOrderBook',True)):return False
        if not yes_token(m):return False
    return True

def event_rec(ev):
    return {'event_id':ev.get('id'),'slug':ev.get('slug'),'title':ev.get('title'),'volume':num(ev.get('volume')),
        'liquidity':num(ev.get('liquidity')),'negRiskAugmented':bool(ev.get('negRiskAugmented')),
        'markets':[{'market_id':m.get('id'),'condition_id':m.get('conditionId'),'question':m.get('question'),
            'groupItemTitle':m.get('groupItemTitle'),'yes_token':yes_token(m),'feesEnabled':bool(m.get('feesEnabled')),
            'feeSchedule':m.get('feeSchedule')} for m in ev.get('markets') or []]}
def fetch_books(tokens):
    out={};errs=[]
    for i in range(0,len(tokens),BOOK_BATCH):
        chunk=tokens[i:i+BOOK_BATCH]
        try:xs=req(CLOB+'/books',method='POST',body=[{'token_id':t} for t in chunk])
        except Exception as ex:errs.append({'chunk':i//BOOK_BATCH,'error':repr(ex)});continue
        for b in xs if isinstance(xs,list) else []:
            if b.get('asset_id'):out[str(b['asset_id'])]=b
    return out,errs

def asks(book):
    xs=[]
    for a in (book or {}).get('asks') or []:
        try:
            p=float(a['price']);s=float(a['size'])
            if 0<p<1 and s>0:xs.append((p,s))
        except:pass
    return sorted(xs)
def fee_rate(m):
    fs=m.get('feeSchedule') or {}
    if not m.get('feesEnabled'):return 0.0
    r=num(fs.get('rate'))
    if r>0:return r
    cid=m.get('condition_id')
    if not cid:return 0.0
    try:return num((req(f'{CLOB}/clob-markets/{cid}').get('fd') or {}).get('r'))
    except:return 0.0

def integrate(levels,q,rate):
    left=q;cost=0.0;fees=0.0
    for p,s in levels:
        take=min(left,s)
        if take<=0:break
        cost+=take*p;fees+=take*rate*p*(1-p);left-=take
        if left<=1e-12:break
    if left>1e-9:return None
    return cost,fees

def optimize_depth(legs):
    # Candidate q values are cumulative-depth breakpoints. Profit is linear
    # between them, so the maximum occurs at a breakpoint.
    maxq=min(sum(s for _,s in x['asks']) for x in legs)
    if maxq<=0:return None
    qs={maxq}
    for x in legs:
        c=0.0
        for _,s in x['asks']:
            c+=s
            if c<=maxq+1e-9:qs.add(c)
    best=None
    for q in sorted(qs):
        total_cost=total_fee=0.0;ok=True
        for x in legs:
            z=integrate(x['asks'],q,x['fee_rate'])
            if z is None:ok=False;break
            total_cost+=z[0];total_fee+=z[1]
        if not ok:continue
        profit=q-total_cost-total_fee
        rec={'basket_shares':q,'gross_cost':total_cost,'fee_cost':total_fee,'all_in_cost':total_cost+total_fee,
            'net_profit':profit,'net_edge_per_share':profit/q if q else None,'capital_required':total_cost+total_fee}
        if best is None or rec['net_profit']>best['net_profit']:best=rec
    return best

def main():
    t0=time.monotonic();events,discover_err=fetch_active_events();disc_s=time.monotonic()-t0
    elig=sorted([e for e in events if eligible(e)],key=lambda e:num(e.get('volume')),reverse=True)
    recs=[event_rec(e) for e in elig]
    tokens=list(dict.fromkeys(m['yes_token'] for e in recs for m in e['markets']))
    tb=time.monotonic();books,book_err=fetch_books(tokens);book_s=time.monotonic()-tb
    rows=[]
    for e in recs:
        legs=[];missing=False
        for m in e['markets']:
            lv=asks(books.get(m['yes_token']))
            if not lv:missing=True;break
            legs.append({**m,'asks':lv,'best_ask':lv[0][0],'best_size':lv[0][1]})
        if missing:
            rows.append({**e,'complete_books':False,'reason':'missing_yes_book'});continue
        raw=sum(x['best_ask'] for x in legs)
        r={**e,'complete_books':True,'n_legs':len(legs),'sum_best_yes_asks':raw,
            'best_level_common_size':min(x['best_size'] for x in legs),'raw_underround':raw<1,'legs':legs}
        if raw<1:
            for x in legs:x['fee_rate']=fee_rate(x)
            opt=optimize_depth(legs);r['depth_optimum']=opt
            r['positive_after_fees']=bool(opt and opt['net_profit']>0)
        else:
            r['positive_after_fees']=False;r['depth_optimum']=None
        rows.append(r)
    total_s=time.monotonic()-t0
    complete=[r for r in rows if r.get('complete_books')]
    raw=[r for r in complete if r.get('raw_underround')]
    pos=[r for r in raw if r.get('positive_after_fees')]
    out={'generated_epoch':int(time.time()),'method':{'batch_books':True,'book_batch':BOOK_BATCH,
        'non_augmented_only':True,'depth_optimizer':'integrate all ask ladders at cumulative-size breakpoints',
        'no_orders':True,'deployment_note':'historical underrounds lasted seconds; VPS loop should reuse event/token metadata and poll books only'},
        'timing':{'discover_seconds':disc_s,'book_fetch_seconds':book_s,'total_seconds':total_s,'books_requested':len(tokens)},
        'inventory':{'active_events_scanned':len(events),'eligible_complete_events':len(elig),'complete_books':len(complete),
            'raw_underrounds':len(raw),'positive_after_fees':len(pos)},
        'positive':sorted(pos,key=lambda r:r['depth_optimum']['net_profit'],reverse=True),
        'top_by_sum':sorted(complete,key=lambda r:r['sum_best_yes_asks'])[:30],
        'errors':{'discovery':discover_err,'books':book_err}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'timing':out['timing'],'inventory':out['inventory'],'positive':[{'event':r['title'],'sum':r['sum_best_yes_asks'],'opt':r['depth_optimum']} for r in out['positive'][:10]],
        'top':[{'event':r['title'],'legs':r['n_legs'],'sum':r['sum_best_yes_asks']} for r in out['top_by_sum'][:10]],'errors':out['errors']},indent=2))

if __name__=='__main__':main()
