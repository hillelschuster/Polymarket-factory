#!/usr/bin/env python3
"""Dense forward observer for capital-recycling NegRisk converter arbitrage.

Targets the full-set conversion only because it is the cleanest executable route:
    buy equal q of NO on every outcome -> convert -> receive (n-1)*q collateral.
No residual outcome token must be sold after conversion.

Metadata and fee coefficients are cached once. The hot loop repeatedly batch-fetches
all NO books, integrates depth, and records converter-positive episodes.

Paper-actionable gate (deliberately stricter than mathematical break-even):
- <=15 outcomes so buys fit one CLOB batch request;
- after current taker fees, pre-gas profit >= $1;
- pre-gas ROI >= 0.25%;
- edge persists for >=2 consecutive snapshots;
- conversion remains profitable after a fixed $0.10 execution/gas reserve.

The $0.10 reserve is a research stress parameter, not an estimate of actual gas.
No credentials, orders, approvals, conversions, or wallet actions are used.
"""
from __future__ import annotations
import json,statistics,sys,time
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_converter_live_scanner as conv
import negrisk_hotloop_benchmark as hot
import negrisk_fast_depth_observer as base

OUT=Path('negrisk_converter_forward_observer.json')
LOOPS=160
SLEEP=.10
MIN_PROFIT=1.0
MIN_ROI=.0025
RESERVE_USD=.10
CONSEC=2


def build():
    events,errs=base.fetch_active_events();recs=[];fee_cache={};fee_err=[];tokens=[]
    for ev in events:
        if not conv.eligible(ev):continue
        ms=[]
        for m in ev.get('markets') or []:
            y,n=conv.token_pair(m);cid=m.get('conditionId')
            if cid not in fee_cache:
                try:fee_cache[cid]=base.fee_rate({'condition_id':cid,'feesEnabled':bool(m.get('feesEnabled')),'feeSchedule':m.get('feeSchedule')})
                except Exception as ex:fee_cache[cid]=.05;fee_err.append({'condition_id':cid,'error':repr(ex),'fallback':.05})
            ms.append({'condition_id':cid,'question':m.get('question'),'yes_token':y,'no_token':n,'fee_rate':fee_cache[cid]})
            tokens.append(n)
        recs.append({'event_id':ev.get('id'),'title':ev.get('title'),'slug':ev.get('slug'),'n_legs':len(ms),'endDate':ev.get('endDate'),'markets':ms})
    return events,recs,list(dict.fromkeys(tokens)),errs,fee_err

def score(e,books):
    legs=[]
    for m in e['markets']:
        na=conv.levels(books.get(m['no_token']),'asks')
        if not na:return None
        legs.append({**m,'no_asks':na})
    opt=conv.optimize_full(legs)
    if not opt:return None
    return {**{k:e[k] for k in ('event_id','title','slug','n_legs','endDate')},'full_set':opt,
        'positive':opt['net_profit_before_gas']>0,
        'profit_after_reserve':opt['net_profit_before_gas']-RESERVE_USD,
        'positive_after_reserve':opt['net_profit_before_gas']>RESERVE_USD}

def main():
    wall=time.time();t0=time.monotonic();events,recs,tokens,derr,ferr=build();setup=time.monotonic()-t0
    histories=defaultdict(list);episodes=[];open_ep={};loops=[]
    all_pos=[];all_action=[]
    for i in range(LOOPS):
        books,berr,sec,nreq=hot.concurrent_books(tokens);stamp=time.time();pos=[]
        for e in recs:
            r=score(e,books)
            if not r:continue
            opt=r['full_set'];positive=r['positive_after_reserve']
            histories[e['event_id']].append(positive)
            consecutive=0
            for z in reversed(histories[e['event_id']]):
                if not z:break
                consecutive+=1
            r['consecutive_positive_after_reserve']=consecutive
            r['actionable_paper']=bool(positive and consecutive>=CONSEC and opt['net_profit_before_gas']>=MIN_PROFIT and opt['net_roi_before_gas']>=MIN_ROI)
            if r['positive']:
                pos.append(r);all_pos.append(r)
            if r['actionable_paper']:all_action.append(r)
            eid=e['event_id']
            if positive:
                if eid not in open_ep:open_ep[eid]={'event_id':eid,'title':e['title'],'start_i':i,'start_t':stamp,'snapshots':0,'actionable':0,'max_profit_after_reserve':-999,'max_roi':-999}
                ep=open_ep[eid];ep['snapshots']+=1;ep['actionable']+=int(r['actionable_paper']);ep['max_profit_after_reserve']=max(ep['max_profit_after_reserve'],r['profit_after_reserve']);ep['max_roi']=max(ep['max_roi'],opt['net_roi_before_gas'])
            elif eid in open_ep:
                ep=open_ep.pop(eid);ep['end_i']=i-1;ep['end_t']=stamp;ep['duration_s']=ep['end_t']-ep['start_t'];episodes.append(ep)
        loops.append({'i':i,'t':stamp,'book_s':sec,'requests':nreq,'books':len(books),'positive_count':len(pos),'errors':berr})
        time.sleep(SLEEP)
    stamp=time.time()
    for ep in open_ep.values():ep['end_i']=LOOPS-1;ep['end_t']=stamp;ep['duration_s']=stamp-ep['start_t'];ep['open_at_end']=True;episodes.append(ep)
    secs=[x['book_s'] for x in loops]
    out={'generated_at':time.time(),'method':{'route':'full-set NO converter','loops':LOOPS,'sleep_seconds':SLEEP,'reserve_usd':RESERVE_USD,'min_profit_usd':MIN_PROFIT,'min_roi':MIN_ROI,'consecutive':CONSEC,'no_orders':True},
      'inventory':{'events_fetched':len(events),'eligible_events':len(recs),'no_tokens':len(tokens)},
      'timing':{'setup_s':setup,'median_book_s':statistics.median(secs) if secs else None,'min_book_s':min(secs) if secs else None,'max_book_s':max(secs) if secs else None,'wall_s':time.time()-wall},
      'summary':{'mathematical_positive_snapshots':len(all_pos),'actionable_paper_snapshots':len(all_action),'mathematical_positive_events':len({x['event_id'] for x in all_pos}),'actionable_events':len({x['event_id'] for x in all_action}),'reserve_positive_episodes':len(episodes)},
      'episodes':sorted(episodes,key=lambda x:x['max_profit_after_reserve'],reverse=True),
      'best_positive':sorted(all_pos,key=lambda x:x['full_set']['net_profit_before_gas'],reverse=True)[:60],
      'best_actionable':sorted(all_action,key=lambda x:x['full_set']['net_profit_before_gas'],reverse=True)[:60],
      'loop_errors':[x for x in loops if x['errors']], 'errors':{'discovery':derr,'fees':ferr}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'inventory':out['inventory'],'timing':out['timing'],'summary':out['summary'],'episodes':out['episodes'][:12],
      'best_actionable':[{'event':x['title'],'profit':x['full_set']['net_profit_before_gas'],'roi':x['full_set']['net_roi_before_gas'],'capital':x['full_set']['all_in_cost'],'consecutive':x['consecutive_positive_after_reserve']} for x in out['best_actionable'][:12]]},indent=2))
if __name__=='__main__':main()
