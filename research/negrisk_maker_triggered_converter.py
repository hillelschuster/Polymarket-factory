#!/usr/bin/env python3
"""Scan for maker-triggered full-set NegRisk conversions.

Instead of requiring an all-taker full-set arbitrage at this instant:
1. Rest a maker NO bid on exactly one outcome at a conversion-anchored safe price.
2. If it fills, immediately re-read all other NO books.
3. FOK-buy equal quantity on the remaining outcomes in one batch.
4. Convert the full NO set to (n-1) collateral.

The resting maker leg pays zero trading fee under current Polymarket rules; maker
rebates are deliberately NOT credited. Other legs pay current taker fees.

For candidate quantity q and maker leg i:
    max_safe_bid_i = [(n-1)q - other_all_in_cost(q) - reserve - target_profit] / q

A candidate exists when we can join or improve the current NO bid without crossing
the ask while remaining below max_safe_bid. This is a conditional opportunity,
not guaranteed PnL: after the maker fill, other books can move before FOK completion.
The reserve/target are therefore explicit and conservative.

No orders are placed.
"""
from __future__ import annotations
import json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_converter_live_scanner as conv
import negrisk_hotloop_benchmark as hot
import negrisk_fast_depth_observer as base

OUT=Path('negrisk_maker_triggered_converter.json')
Q_GRID=(5.0,10.0,20.0,50.0)
RESERVE_USD=.20
TARGET_PROFIT_USD=.50
MIN_CONDITIONAL_ROI=.005
MAX_LEGS=15


def integrate(levels,q,rate):
    left=q;cost=fees=0.0
    for p,s in levels:
        z=min(left,s);cost+=z*p;fees+=z*rate*p*(1-p);left-=z
        if left<=1e-12:break
    return None if left>1e-9 else cost+fees

def best_bid(book):
    xs=conv.levels(book,'bids');return xs[0] if xs else None

def best_ask(book):
    xs=conv.levels(book,'asks');return xs[0] if xs else None

def main():
    events,derr=base.fetch_active_events();evs=[e for e in events if conv.eligible(e) and len(e.get('markets') or [])<=MAX_LEGS]
    recs=[];tokens=[];fees={};ferr=[]
    for ev in evs:
        ms=[]
        for m in ev.get('markets') or []:
            y,n=conv.token_pair(m);cid=m.get('conditionId');tokens.append(n)
            if cid not in fees:
                try:fees[cid]=base.fee_rate({'condition_id':cid,'feesEnabled':bool(m.get('feesEnabled')),'feeSchedule':m.get('feeSchedule')})
                except Exception as ex:fees[cid]=.05;ferr.append({'condition_id':cid,'error':repr(ex),'fallback':.05})
            ms.append({'condition_id':cid,'question':m.get('question'),'no_token':n,'fee_rate':fees[cid]})
        recs.append({'event_id':ev.get('id'),'title':ev.get('title'),'slug':ev.get('slug'),'endDate':ev.get('endDate'),'markets':ms})
    tokens=list(dict.fromkeys(tokens));books,berr,book_s,nreq=hot.concurrent_books(tokens)
    setups=[]
    for ev in recs:
        nlegs=len(ev['markets']);legs=[]
        for m in ev['markets']:
            b=books.get(m['no_token']);asks=conv.levels(b,'asks');bb=best_bid(b);ba=best_ask(b)
            if not b or not asks or not ba:legs=[];break
            tick=float(b.get('tick_size') or .001);minsize=float(b.get('min_order_size') or 5)
            legs.append({**m,'asks':asks,'best_bid':bb,'best_ask':ba,'tick':tick,'min_order_size':minsize})
        if not legs:continue
        for i,maker in enumerate(legs):
            others=[x for j,x in enumerate(legs) if j!=i]
            for q0 in Q_GRID:
                q=max(q0,maker['min_order_size'])
                other_cost=0.0;ok=True
                for x in others:
                    z=integrate(x['asks'],q,x['fee_rate'])
                    if z is None:ok=False;break
                    other_cost+=z
                if not ok:continue
                payout=(nlegs-1)*q
                max_bid=(payout-other_cost-RESERVE_USD-TARGET_PROFIT_USD)/q
                if max_bid<=0:continue
                ask=maker['best_ask'][0];bid=(maker['best_bid'] or (0,0))[0];tick=maker['tick']
                improve=round(bid+tick,10) if bid>0 else tick
                max_maker_price=min(max_bid,ask-tick)
                if max_maker_price+1e-12<bid:continue
                if improve<=max_maker_price+1e-12:quote=improve;mode='improve_best_bid'
                elif bid>0 and bid<=max_maker_price+1e-12:quote=bid;mode='join_best_bid'
                else:continue
                maker_cost=q*quote
                total=maker_cost+other_cost+RESERVE_USD
                profit=payout-total;roi=profit/total if total>0 else 0
                if profit<TARGET_PROFIT_USD-1e-9 or roi<MIN_CONDITIONAL_ROI:continue
                setups.append({
                    'event_id':ev['event_id'],'event':ev['title'],'slug':ev['slug'],'endDate':ev['endDate'],'n_legs':nlegs,
                    'maker_condition_id':maker['condition_id'],'maker_question':maker['question'],'quantity':q,'mode':mode,
                    'current_no_best_bid':bid,'current_no_best_ask':ask,'safe_quote':quote,'max_safe_bid':max_bid,
                    'distance_to_ask':ask-quote,'other_taker_all_in':other_cost,'maker_cost':maker_cost,'reserve_usd':RESERVE_USD,
                    'payout_after_conversion':payout,'conditional_profit_after_reserve':profit,'conditional_roi':roi,
                    'break_even_extra_adverse_move_other_legs_usd':profit,
                    'maker_rebate_credited':False,
                })
    setups.sort(key=lambda x:(x['conditional_profit_after_reserve'],x['conditional_roi']),reverse=True)
    out={'generated_at':time.time(),'method':{'q_grid':list(Q_GRID),'reserve_usd':RESERVE_USD,'target_profit_usd':TARGET_PROFIT_USD,'min_conditional_roi':MIN_CONDITIONAL_ROI,'maker_fee':0,'maker_rebate_credited':False,
      'execution':'maker NO trigger then re-read + FOK remaining NO legs + full-set conversion','warning':'conditional economics assume other books remain executable after maker fill; no basket atomicity'},
      'timing':{'book_seconds':book_s,'requests':nreq,'tokens':len(tokens)},
      'inventory':{'events':len(recs),'setups':len(setups),'events_with_setups':len({x['event_id'] for x in setups})},
      'top_setups':setups[:150],'errors':{'discovery':derr,'books':berr,'fees':ferr}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'timing':out['timing'],'inventory':out['inventory'],'top':[{
      'event':x['event'],'maker':x['maker_question'],'q':x['quantity'],'mode':x['mode'],'bid':x['current_no_best_bid'],'ask':x['current_no_best_ask'],'quote':x['safe_quote'],'max_safe':x['max_safe_bid'],'profit':x['conditional_profit_after_reserve'],'roi':x['conditional_roi'],'cushion':x['break_even_extra_adverse_move_other_legs_usd']} for x in setups[:25]],'errors':{k:v[:3] for k,v in out['errors'].items()}},indent=2))
if __name__=='__main__':main()
