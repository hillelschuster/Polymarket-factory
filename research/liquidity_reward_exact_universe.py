#!/usr/bin/env python3
"""Exact-source universe search for unusually attractive Polymarket LP rewards.

Goal: find better candidates than a hand-picked five-market audit without trusting
stale discovery-page reward economics.

Pipeline:
1. fetch the entire public current reward list;
2. nominate a manageable union by discovery pool and pool/min-size density;
3. concurrently reconcile each candidate against the exact condition-specific
   reward endpoint and Gamma metadata;
4. use exact active rate/min-size/max-spread + current two-token books;
5. enumerate eligible single-sided bid ticks and rank under 5x visible-competition
   stress, with capital / queue / time / category filters;
6. for only the top static candidates, inspect recent public taker trade tape and
   penalize observed SELL-through at/below the proposed quote.

No orders are placed. Reward share remains a proxy because maker-level denominator
and future participation are not observable from the public book.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import liquidity_reward_live_screen as lr
import liquidity_reward_candidate_audit as aud

OUT=Path('liquidity_reward_exact_universe.json')
DISCOVERY_TOP_POOL=120
DISCOVERY_TOP_DENSITY=160
MAX_NOMINEES=220
EXACT_WORKERS=8
MIN_EXACT_RATE=5.0
MAX_MIN_SIZE=100.0
MIN_HOURS=48
MAX_DAY_MOVE=.05
COMP_STRESS=5.0
TOP_TAPE=18
MAX_GRID=120


def active_rate(row,now):
    rate=0.0;active=[];today=now.date()
    for c in row.get('rewards_config') or []:
        try:
            s=dt.date.fromisoformat(str(c.get('start_date'))[:10]);e=dt.date.fromisoformat(str(c.get('end_date'))[:10])
            if s<=today<=e:
                active.append(c);rate+=aud.num(c.get('rate_per_day'))
        except:pass
    return rate,active

def exact_one(cid,now):
    try:
        d=aud.req(f'{aud.CLOB}/rewards/markets/{cid}',{'sponsored':'true'})
        rows=d.get('data') or []
        if len(rows)!=1:return cid,None,f'rows={len(rows)}'
        r=rows[0];rate,active=active_rate(r,now)
        return cid,{'row':r,'rate':rate,'active':active},None
    except Exception as ex:return cid,None,repr(ex)
def parse_hours(end,now):
    if not end:return None
    try:
        x=dt.datetime.fromisoformat(str(end).replace('Z','+00:00'))
        if x.tzinfo is None:x=x.replace(tzinfo=dt.timezone.utc)
        return (x-now).total_seconds()/3600
    except:return None
def own_books(books,tokens,idx):
    return lr.merge_yes_book(books[tokens[idx]],books[tokens[1-idx]]),books[tokens[idx]]
def score_quote(p,mid,v,size):
    dist=abs(mid-p)
    if dist>v+1e-12:return 0.0
    return (((v-dist)/v)**2*size)/3.0 if .10<=mid<=.90 else 0.0
def grid(lo,hi,tick):
    if tick<=0 or hi<lo:return []
    n=int((hi-lo)/tick)+1;step=max(1,math.ceil(n/MAX_GRID));out=[];i=0
    while lo+i*tick<=hi+1e-12:
        if i%step==0:out.append(round(lo+i*tick,10))
        i+=1
    if not out or abs(out[-1]-hi)>1e-9:out.append(round(hi,10))
    return sorted(set(out))
def static_candidate(cid,disc,ex,g,books,now):
    row=ex['row'];rate=ex['rate'];minsize=aud.num(row.get('rewards_min_size'));v=aud.num(row.get('rewards_max_spread'))/100
    if rate<MIN_EXACT_RATE or minsize<=0 or minsize>MAX_MIN_SIZE or v<=0:return None
    toks=[str(x) for x in lr.jlist(g.get('clobTokenIds'))];outs=[str(x) for x in lr.jlist(g.get('outcomes'))]
    if len(toks)!=2 or len(outs)!=2 or any(t not in books for t in toks):return None
    cat=lr.classify(g);hours=parse_hours(g.get('endDate'),now);move=abs(lr.fnum(g.get('oneDayPriceChange')))
    if cat=='geopolitics' or hours is None or hours<MIN_HOURS or move>=MAX_DAY_MOVE:return None
    # Evaluate each outcome as the possible cheap side. In a binary contract one of them
    # should have midpoint <=.5; use exact focal-coordinate merged books.
    possibilities=[]
    for idx in (0,1):
        (bids,asks),own=own_books(books,toks,idx)
        ab=lr.cutoff_price(bids,minsize);aa=lr.cutoff_price(asks,minsize)
        if ab is None or aa is None or aa<=ab:continue
        mid=(ab+aa)/2
        if not(.10<=mid<=.50):continue
        qbid=lr.score_side(bids,mid,v);qask=lr.score_side(asks,mid,v);comp=lr.qmin_proxy(qbid,qask,mid)
        tick=aud.num(own.get('tick_size')) or .001
        own_bids=sorted(lr.levels(own,'bids'),reverse=True);own_asks=sorted(lr.levels(own,'asks'))
        bestbid=own_bids[0][0] if own_bids else None;bestask=own_asks[0][0] if own_asks else None
        lo=max(tick,mid-v+tick);hi=min(mid-tick,(bestask-tick) if bestask is not None else mid-tick)
        for p in grid(lo,hi,tick):
            q=score_quote(p,mid,v,minsize)
            if q<=0:continue
            reward5=rate*q/(COMP_STRESS*comp+q) if comp>0 else rate
            capital=minsize*p
            ahead=sum(s for px,s in own_bids if px>p+1e-12);at=sum(s for px,s in own_bids if abs(px-p)<=1e-12)
            protect=(ahead+at)/minsize
            # Prioritize stressed reward yield but penalize naked price improvement.
            naked_penalty=.55 if (bestbid is not None and p>bestbid+1e-12) else 1.0
            shelter=min(2.5,1+protect/6)
            score=(reward5/max(capital,1e-9))*shelter*naked_penalty
            possibilities.append({'outcome_index':idx,'outcome':outs[idx],'quote_price':p,'capital':capital,'our_qmin':q,
                'visible_qmin_proxy':comp,'reward5x':reward5,'full_loss_cover_days_5x':capital/reward5 if reward5>0 else None,
                'queue_ahead_shares':ahead,'queue_at_shares':at,'queue_protection_min_orders':protect,
                'best_bid':bestbid,'best_ask':bestask,'mid':mid,'tick':tick,'improves_best_bid':bool(bestbid is not None and p>bestbid+1e-12),
                'static_score':score})
    if not possibilities:return None
    best=max(possibilities,key=lambda x:x['static_score'])
    exact_total=aud.num(row.get('total_daily_rate')) or rate
    return {'condition_id':cid,'question':g.get('question'),'slug':g.get('slug'),'category':cat,'hours_to_end':hours,
        'one_day_move':move,'volume24h':lr.fnum(g.get('volume24hr') or g.get('volume24hrClob')),
        'discovery_rate':lr.fnum(disc.get('total_daily_rate')),'exact_active_rate':rate,'exact_total_field':exact_total,
        'exact_min_size':minsize,'exact_max_spread_cents':v*100,'market_competitiveness':row.get('market_competitiveness'),
        'source_mismatch':abs(rate-lr.fnum(disc.get('total_daily_rate')))>1e-9 or abs(minsize-lr.fnum(disc.get('rewards_min_size')))>1e-9,
        'tokens':toks,'outcomes':outs,'best_static':best,'top_static':sorted(possibilities,key=lambda x:x['static_score'],reverse=True)[:12],
        'end_date':g.get('endDate'),'fees_enabled':g.get('feesEnabled'),'fee_schedule':g.get('feeSchedule')}
def tape_enrich(r,now):
    idx=r['best_static']['outcome_index'];p=r['best_static']['quote_price'];minsize=r['exact_min_size'];cid=r['condition_id']
    raw,cov=aud.tape(cid);norm=[]
    for x in raw:
        z=aud.normalize_trade(x,r['outcomes'],idx)
        if z:norm.append(z)
    nowts=int(now.timestamp());sells=[x for x in norm if x['side']=='SELL']
    windows={}
    for h in (24,72,168):
        xs=[x for x in sells if x['t']>=nowts-h*3600 and x['price']<=p+1e-12];shares=sum(x['size'] for x in xs);days=h/24
        windows[str(h)]={'sell_through_count':len(xs),'sell_through_shares':shares,'min_orders_per_day':shares/minsize/days if minsize else None,
            'min_sell_price':min((x['price'] for x in xs),default=None)}
    fp=windows['72']['min_orders_per_day'] or 0;static=r['best_static']['static_score']
    r['tape_coverage']=cov;r['sell_through']=windows;r['final_score']=static/(1+fp)
    return r
def main():
    now=dt.datetime.now(dt.timezone.utc);t0=time.monotonic()
    rewards,reward_err,pages=lr.fetch_rewards();usable=[r for r in rewards if lr.fnum(r.get('total_daily_rate'))>0 and lr.fnum(r.get('rewards_min_size'))>0]
    bypool=sorted(usable,key=lambda r:lr.fnum(r.get('total_daily_rate')),reverse=True)[:DISCOVERY_TOP_POOL]
    bydense=sorted(usable,key=lambda r:lr.fnum(r.get('total_daily_rate'))/max(lr.fnum(r.get('rewards_min_size')),1),reverse=True)[:DISCOVERY_TOP_DENSITY]
    nominees={str(r.get('condition_id')):r for r in bypool+bydense if r.get('condition_id')}
    if len(nominees)>MAX_NOMINEES:
        ranked=sorted(nominees.values(),key=lambda r:(lr.fnum(r.get('total_daily_rate'))/max(lr.fnum(r.get('rewards_min_size')),1),lr.fnum(r.get('total_daily_rate'))),reverse=True)[:MAX_NOMINEES]
        nominees={str(r['condition_id']):r for r in ranked}
    exact={};exact_errors=[]
    with ThreadPoolExecutor(max_workers=EXACT_WORKERS) as exr:
        futs={exr.submit(exact_one,cid,now):cid for cid in nominees}
        for f in as_completed(futs):
            cid,z,err=f.result()
            if z:exact[cid]=z
            else:exact_errors.append({'condition_id':cid,'error':err})
    gamma,gamma_err=lr.fetch_gamma(list(exact))
    pre=[]
    for cid,z in exact.items():
        g=gamma.get(cid);disc=nominees.get(cid)
        if not g or not disc:continue
        rate=z['rate'];mins=aud.num(z['row'].get('rewards_min_size'));hours=parse_hours(g.get('endDate'),now);cat=lr.classify(g);move=abs(lr.fnum(g.get('oneDayPriceChange')))
        if rate>=MIN_EXACT_RATE and 0<mins<=MAX_MIN_SIZE and hours is not None and hours>=MIN_HOURS and cat!='geopolitics' and move<MAX_DAY_MOVE:pre.append(cid)
    toks=[]
    for cid in pre:
        for t in lr.jlist(gamma[cid].get('clobTokenIds')):toks.append(str(t))
    books,book_err=lr.fetch_books(list(dict.fromkeys(toks)))
    rows=[];parse_err=[]
    for cid in pre:
        try:
            r=static_candidate(cid,nominees[cid],exact[cid],gamma[cid],books,now)
            if r:rows.append(r)
        except Exception as ex:parse_err.append({'condition_id':cid,'error':repr(ex)})
    rows.sort(key=lambda r:r['best_static']['static_score'],reverse=True)
    tape_rows=[];tape_err=[]
    for r in rows[:TOP_TAPE]:
        try:tape_rows.append(tape_enrich(r,now))
        except Exception as ex:tape_err.append({'condition_id':r['condition_id'],'error':repr(ex)})
    tape_rows.sort(key=lambda r:r.get('final_score',0),reverse=True)
    # Require $1/day even at 5x competition stress because below-floor earnings may not pay.
    robust=[r for r in tape_rows if r['best_static']['reward5x']>=1 and (r['sell_through']['72']['min_orders_per_day'] or 0)<1]
    out={'generated_at':now.isoformat(),'method':{'exact_source_required':True,'competition_stress':COMP_STRESS,'min_exact_rate':MIN_EXACT_RATE,
        'max_min_size':MAX_MIN_SIZE,'min_hours':MIN_HOURS,'top_tape':TOP_TAPE,
        'robust_gate':'5x-stress reward >= $1/day and observed 72h sell-through <1 min-order/day',
        'warning':'reward share denominator remains a visible-book proxy; no earnings guarantee or orders'},
        'inventory':{'reward_pages':pages,'reward_markets':len(rewards),'nominees':len(nominees),'exact_resolved':len(exact),'gamma_resolved':len(gamma),
            'prefilter':len(pre),'books':len(books),'static_scored':len(rows),'tape_audited':len(tape_rows),'robust_candidates':len(robust),
            'elapsed_seconds':time.monotonic()-t0},
        'top_robust':robust,'top_tape':tape_rows,'top_static':rows[:50],
        'errors':{'reward':reward_err,'exact':exact_errors,'gamma':gamma_err,'books':book_err,'parse':parse_err,'tape':tape_err}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'inventory':out['inventory'],'robust':[{'q':r['question'],'cat':r['category'],'exact_rate':r['exact_active_rate'],
        'quote':r['best_static']['quote_price'],'outcome':r['best_static']['outcome'],'capital':round(r['best_static']['capital'],2),
        'reward5x':round(r['best_static']['reward5x'],3),'cover_days':round(r['best_static']['full_loss_cover_days_5x'],2),
        'queue_x':round(r['best_static']['queue_protection_min_orders'],2),'fp72_day':round(r['sell_through']['72']['min_orders_per_day'] or 0,3),
        'mismatch':r['source_mismatch']} for r in robust[:20]],'errors':{k:v[:3] for k,v in out['errors'].items()}},indent=2))
if __name__=='__main__':main()
