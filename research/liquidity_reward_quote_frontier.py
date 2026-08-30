#!/usr/bin/env python3
"""Quote frontier for exact-source liquidity-reward candidates.

For each audited candidate, enumerate every eligible single-sided bid tick from
the reward-band edge toward the midpoint. At each quote price compute:
- current visible reward-score proxy;
- exact active reward pool/min-size/max-spread;
- reward-share proxy under 1x/2x/5x/10x visible-competition stress;
- required capital for one minimum-size order;
- current queue/protection at or ahead of the quote;
- recent observed taker SELL-through counts/shares at or below that price;
- days of stressed reward needed to cover one total-loss fill.

This is deliberately a frontier, not a single magic score. Historical trade tape
uses today's candidate price threshold against recent flow and therefore measures
fill-pressure risk, not a full dynamic fill backtest.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import liquidity_reward_candidate_audit as audit
import liquidity_reward_live_screen as lr

OUT=Path('liquidity_reward_quote_frontier.json')
COMP_STRESS=(1,2,5,10)
MAX_TICKS=250


def own_coordinate_books(books_by_token,tokens,own_idx):
    own=books_by_token[tokens[own_idx]]
    other=books_by_token[tokens[1-own_idx]]
    # lr.merge_yes_book treats first argument as the focal outcome and the other
    # token as its binary complement, exactly what we need here.
    return lr.merge_yes_book(own,other),own


def score_quote(price,mid,v,size):
    dist=abs(mid-price)
    if dist>v+1e-12:return 0.0
    raw=((v-dist)/v)**2*size
    return raw/3.0 if .10<=mid<=.90 else 0.0


def quote_levels(lo,hi,tick):
    if tick<=0:return []
    n=int((hi-lo)/tick)+1
    if n>MAX_TICKS:
        step=max(1,n//MAX_TICKS)
    else:step=1
    out=[]
    i=0
    while lo+i*tick<=hi+1e-12:
        if i%step==0:out.append(round(lo+i*tick,10))
        i+=1
    if hi>0 and (not out or abs(out[-1]-hi)>1e-9):out.append(round(hi,10))
    return sorted(set(out))


def normalized_tape(cid,outcomes,own_idx):
    raw,cov=audit.tape(cid)
    rows=[]
    for x in raw:
        z=audit.normalize_trade(x,outcomes,own_idx)
        if z:rows.append(z)
    return rows,cov


def frontier(c,now):
    cid=c['condition_id'];g=audit.gamma(cid)
    outcomes=[str(x) for x in audit.jl(g.get('outcomes'))]
    tokens=[str(x) for x in audit.jl(g.get('clobTokenIds'))]
    if len(outcomes)!=2 or len(tokens)!=2:raise ValueError('not binary')
    exact,configs,rate=audit.exact_reward(cid,now)
    min_size=audit.num(exact.get('rewards_min_size'));v=audit.num(exact.get('rewards_max_spread'))/100
    if rate<=0 or min_size<=0 or v<=0:raise ValueError('inactive reward')
    own_idx=next((i for i,o in enumerate(outcomes) if o.casefold()==c['quote_outcome'].casefold()),None)
    if own_idx is None:raise ValueError('quote outcome missing')
    bks=audit.books(tokens)
    (bids,asks),own_book=own_coordinate_books(bks,tokens,own_idx)
    adj_bid=lr.cutoff_price(bids,min_size);adj_ask=lr.cutoff_price(asks,min_size)
    if adj_bid is None or adj_ask is None or adj_ask<=adj_bid:raise ValueError('no adjusted midpoint')
    mid=(adj_bid+adj_ask)/2
    if not(.10<=mid<=.90):raise ValueError('single-sided not reward eligible at extreme midpoint')
    qbid=lr.score_side(bids,mid,v);qask=lr.score_side(asks,mid,v);comp=lr.qmin_proxy(qbid,qask,mid)
    tick=audit.num(own_book.get('tick_size'),.001) or .001
    own_bids=sorted(lr.levels(own_book,'bids'),reverse=True)
    own_asks=sorted(lr.levels(own_book,'asks'))
    best_bid=own_bids[0][0] if own_bids else None;best_ask=own_asks[0][0] if own_asks else None
    low=max(tick,mid-v+tick)
    high=min(mid-tick,(best_ask-tick) if best_ask is not None else mid-tick)
    if high<low:raise ValueError('no eligible bid grid')
    trades,cov=normalized_tape(cid,outcomes,own_idx);nowts=int(now.timestamp())
    sells=[x for x in trades if x['side']=='SELL']
    rows=[]
    for p in quote_levels(low,high,tick):
        q=score_quote(p,mid,v,min_size)
        if q<=0:continue
        ahead=sum(sz for px,sz in own_bids if px>p+1e-12)
        at=sum(sz for px,sz in own_bids if abs(px-p)<=1e-12)
        capital=min_size*p
        r={'quote_price':p,'our_qmin':q,'capital':capital,'queue_ahead_shares':ahead,'queue_at_shares':at,
           'queue_protection_min_orders':(ahead+at)/min_size,'improves_best_bid':bool(best_bid is not None and p>best_bid+1e-12),
           'reward_proxy':{},'full_loss_cover_days':{},'fill_pressure':{}}
        for mult in COMP_STRESS:
            rew=rate*q/(mult*comp+q) if comp>0 else rate
            r['reward_proxy'][str(mult)+'x_visible_competition']=rew
            r['full_loss_cover_days'][str(mult)+'x_visible_competition']=capital/rew if rew>0 else None
        for h in (24,72,168):
            ss=[x for x in sells if x['t']>=nowts-h*3600 and x['price']<=p+1e-12]
            shares=sum(x['size'] for x in ss)
            days=h/24
            r['fill_pressure'][str(h)+'h']={'sell_through_count':len(ss),'sell_through_shares':shares,
                'sell_through_min_orders':shares/min_size if min_size else None,
                'sell_through_min_orders_per_day':shares/min_size/days if min_size else None,
                'min_sell_price':min((x['price'] for x in ss),default=None)}
        # Profitability-oriented robust heuristic: use 5x competition stress and
        # penalize observed 72h sell-through plus zero queue shelter.
        rew5=r['reward_proxy']['5x_visible_competition'];fp=r['fill_pressure']['72h']['sell_through_min_orders_per_day'] or 0
        shelter=min(3.0,1.0+r['queue_protection_min_orders']/5.0)
        r['robust_score']=(rew5/max(capital,1e-9))*shelter/(1+fp)
        rows.append(r)
    rows.sort(key=lambda x:x['robust_score'],reverse=True)
    return {
        'condition_id':cid,'question':g.get('question'),'quote_outcome':outcomes[own_idx],'exact_reward_rate':rate,
        'exact_min_size':min_size,'exact_max_spread_cents':v*100,'market_competitiveness':exact.get('market_competitiveness'),
        'mid_size_filtered':mid,'adjusted_bid':adj_bid,'adjusted_ask':adj_ask,'visible_q_bid':qbid,'visible_q_ask':qask,
        'visible_qmin_proxy':comp,'tick':tick,'best_bid':best_bid,'best_ask':best_ask,'trade_coverage':cov,
        'current_fee_schedule':g.get('feeSchedule'),'end_date':g.get('endDate'),'top_frontier':rows[:40],
        'best_by_robust_score':rows[0] if rows else None,
        'band_edge_quote':min(rows,key=lambda x:x['quote_price']) if rows else None,
        'join_best_bid_quote':min(rows,key=lambda x:abs(x['quote_price']-best_bid)) if rows and best_bid is not None else None,
    }


def main():
    now=dt.datetime.now(dt.timezone.utc);rows=[];errors=[]
    for c in audit.CANDS:
        try:rows.append(frontier(c,now))
        except Exception as ex:errors.append({'condition_id':c['condition_id'],'question':c['question'],'error':repr(ex)})
    out={'generated_at':now.isoformat(),'method':{'competition_stress':list(COMP_STRESS),
        'reward_formula_proxy':'exact pool * our_Q / (stress * visible_aggregate_Qmin + our_Q)',
        'fill_pressure':'recent normalized taker SELL trades at/below static candidate quote',
        'robust_score':'(5x-stress reward/capital)*queue shelter/(1+72h sell-through min-orders/day)',
        'warning':'visible aggregate Qmin is not exact maker denominator; quote frontier is screening, not guaranteed earnings'},
        'candidates':rows,'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'candidates':[{'q':r['question'],'rate':r['exact_reward_rate'],'comp':r['visible_qmin_proxy'],
        'best':{k:(r['best_by_robust_score'] or {}).get(k) for k in ['quote_price','capital','queue_protection_min_orders','robust_score','reward_proxy','full_loss_cover_days','fill_pressure']}}
        for r in rows],'errors':errors},indent=2))

if __name__=='__main__':main()
