#!/usr/bin/env python3
"""Repeated near-simultaneous verification of the live 2026 volcano NegRisk basket.

The broad fast observer saw a fee-adjusted positive basket once. This script
removes two major doubts:
- all six YES books are requested in ONE POST /books call every cycle;
- the opportunity must survive repeated samples, not one snapshot.

It records each book's server timestamp, best-ask sum, current fee coefficients,
and a depth-aware optimum. No orders are placed.
"""
from __future__ import annotations
import json,statistics,time,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_fast_depth_observer as base

OUT=Path('negrisk_volcano_repeated_verify.json')
EVENT_ID='135338'
SAMPLES=50
SLEEP_S=.5


def get_event():
    rows=base.req(base.GAMMA+'/events',{'id':EVENT_ID,'limit':3})
    if not isinstance(rows,list) or not rows:
        rows=base.req(base.GAMMA+'/events',{'slug':'how-many-large-volcano-eruption-vei-4-in-2026-657','limit':3})
    if not isinstance(rows,list) or len(rows)!=1:raise ValueError(f'event rows={len(rows) if isinstance(rows,list) else type(rows)}')
    return rows[0]

def server_ts(book):
    try:return int(book.get('timestamp') or 0)
    except:return None

def one_snapshot(legs,fees):
    t0=time.monotonic()
    books,errs=base.fetch_books([x['yes_token'] for x in legs])
    elapsed=time.monotonic()-t0
    xs=[];timestamps=[]
    for m in legs:
        b=books.get(m['yes_token']);lv=base.asks(b)
        if not lv:return {'ok':False,'reason':'missing_book','errors':errs,'fetch_seconds':elapsed}
        st=server_ts(b)
        if st:timestamps.append(st)
        xs.append({**m,'asks':lv,'best_ask':lv[0][0],'best_size':lv[0][1],'fee_rate':fees[m['condition_id']],'server_ts':st})
    raw=sum(x['best_ask'] for x in xs)
    opt=base.optimize_depth(xs) if raw<1 else None
    return {'ok':True,'fetch_seconds':elapsed,'sum_best_yes_asks':raw,'raw_underround':raw<1,
        'positive_after_fees':bool(opt and opt['net_profit']>0),'depth_optimum':opt,
        'server_timestamp_span_ms':max(timestamps)-min(timestamps) if timestamps else None,
        'legs':[{'label':x['groupItemTitle'],'best_ask':x['best_ask'],'best_size':x['best_size'],'fee_rate':x['fee_rate'],'server_ts':x['server_ts']} for x in xs],
        'errors':errs}

def main():
    ev=get_event()
    if not base.eligible(ev):raise ValueError('event failed complete non-augmented NegRisk eligibility')
    rec=base.event_rec(ev);labels=[m.get('groupItemTitle') for m in rec['markets']]
    if set(labels)!={'0','1','2','3','4','5+'}:raise ValueError(f'unexpected exhaustive labels: {labels}')
    fees={m['condition_id']:base.fee_rate(m) for m in rec['markets']}
    samples=[]
    for i in range(SAMPLES):
        s=one_snapshot(rec['markets'],fees);s['i']=i;s['wall_time']=time.time();samples.append(s)
        if i<SAMPLES-1:time.sleep(SLEEP_S)
    good=[x for x in samples if x.get('ok')];raw=[x for x in good if x.get('raw_underround')];pos=[x for x in good if x.get('positive_after_fees')]
    sums=[x['sum_best_yes_asks'] for x in good]
    profits=[x['depth_optimum']['net_profit'] for x in pos]
    edges=[x['depth_optimum']['net_edge_per_share'] for x in pos]
    # contiguous positive streaks in samples
    streaks=[];cur=[]
    for x in samples:
        if x.get('positive_after_fees'):cur.append(x)
        elif cur:streaks.append(cur);cur=[]
    if cur:streaks.append(cur)
    streak_summary=[]
    for s in streaks:
        streak_summary.append({'samples':len(s),'wall_seconds':s[-1]['wall_time']-s[0]['wall_time'],
            'min_net_profit':min(x['depth_optimum']['net_profit'] for x in s),
            'max_net_profit':max(x['depth_optimum']['net_profit'] for x in s),
            'min_edge_per_share':min(x['depth_optimum']['net_edge_per_share'] for x in s)})
    out={'generated_at':time.time(),'method':{'event_id':EVENT_ID,'samples':SAMPLES,'sleep_seconds':SLEEP_S,
            'single_batched_books_request_per_sample':True,'all_six_outcome_labels':['0','1','2','3','4','5+'],
            'no_orders':True},
        'event':{'title':rec['title'],'slug':rec['slug'],'negRiskAugmented':rec['negRiskAugmented'],'volume':rec['volume'],'liquidity':rec['liquidity']},
        'fees_by_condition':fees,
        'summary':{'good_samples':len(good),'raw_underround_samples':len(raw),'positive_after_fees_samples':len(pos),
            'positive_share':len(pos)/len(good) if good else None,'min_best_ask_sum':min(sums) if sums else None,
            'median_best_ask_sum':statistics.median(sums) if sums else None,'max_best_ask_sum':max(sums) if sums else None,
            'best_net_profit':max(profits) if profits else None,'median_positive_net_profit':statistics.median(profits) if profits else None,
            'best_net_edge_per_share':max(edges) if edges else None,
            'median_fetch_seconds':statistics.median([x['fetch_seconds'] for x in good]) if good else None,
            'max_server_timestamp_span_ms':max((x['server_timestamp_span_ms'] for x in good if x['server_timestamp_span_ms'] is not None),default=None),
            'positive_streaks':streak_summary},
        'samples':samples}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out['summary'],indent=2))
if __name__=='__main__':main()
