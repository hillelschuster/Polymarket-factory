#!/usr/bin/env python3
"""Execution-slippage stress for the proven 2024 same-wallet NegRisk cycles.

FOK protects each individual leg from partial fills, but a POST /orders batch is not
basket-atomic. This script asks how much edge remains if every leg executes worse
than the observed trade prices, plus a harsher one-leg completion shock.

Scenarios are deliberately simple and interpretable:
- uniform adverse slippage of +0.1c / +0.25c / +0.5c / +1.0c on every leg;
- one missing/late leg forced +1c / +2c / +5c while other legs stay at observed price.
Current Politics taker fee coefficient 4% is recomputed at stressed prices.
No rebates are credited.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_2024_wallet_basket_audit as src

OUT=Path('negrisk_execution_slippage_stress.json')
RATE=.04
WINDOW=20
UNIFORM=(.001,.0025,.005,.01)
ONE_LEG=(.01,.02,.05)

def fee(p):return RATE*p*(1-p)
def calc(prices,q):
    allin=sum(p+fee(p) for p in prices);edge=1-allin
    return {'all_in_per_share':allin,'net_edge_per_share':edge,'net_roi':edge/allin if allin>0 else None,
            'net_profit_at_observed_common_size':edge*q,'positive':edge>0}
def main():
    by={};coverage={};errs={}
    for n,c in src.tape.LEGS:
        rows,e,cov=src.tape.fetch_leg(n,c);by[n]=rows;errs[n]=e;coverage[n]=cov
    cycles=src.greedy_nonoverlap(src.wallet_sequences(by,WINDOW))
    stressed=[]
    for i,x in enumerate(cycles):
        base_prices=[r['price'] for r in x['legs'].values()];q=x['common_observed_size']
        rec={'cycle':i,'wallet':x.get('wallet'),'span_seconds':x['observed_span_seconds'],'common_size':q,
             'observed_prices':base_prices,'base':calc(base_prices,q),'uniform':{},'one_leg_worst':{}}
        for s in UNIFORM:
            ps=[min(.999,p+s) for p in base_prices];rec['uniform'][str(s)]=calc(ps,q)
        for s in ONE_LEG:
            variants=[]
            for j in range(len(base_prices)):
                ps=list(base_prices);ps[j]=min(.999,ps[j]+s);variants.append(calc(ps,q))
            rec['one_leg_worst'][str(s)]=min(variants,key=lambda z:z['net_edge_per_share'])
        stressed.append(rec)
    summary={'cycles':len(stressed),'base_positive':sum(x['base']['positive'] for x in stressed),'base_net_profit':sum(x['base']['net_profit_at_observed_common_size'] for x in stressed),
             'uniform':{},'one_leg_worst':{}}
    for s in UNIFORM:
        k=str(s);summary['uniform'][k]={'positive_cycles':sum(x['uniform'][k]['positive'] for x in stressed),
            'net_profit_all_cycles':sum(x['uniform'][k]['net_profit_at_observed_common_size'] for x in stressed),
            'median_edge':sorted(x['uniform'][k]['net_edge_per_share'] for x in stressed)[len(stressed)//2] if stressed else None}
    for s in ONE_LEG:
        k=str(s);summary['one_leg_worst'][k]={'positive_cycles':sum(x['one_leg_worst'][k]['positive'] for x in stressed),
            'net_profit_all_cycles':sum(x['one_leg_worst'][k]['net_profit_at_observed_common_size'] for x in stressed),
            'median_edge':sorted(x['one_leg_worst'][k]['net_edge_per_share'] for x in stressed)[len(stressed)//2] if stressed else None}
    out={'method':{'event':'2024 Presidency + Popular Vote','window_seconds':WINDOW,'current_politics_fee':RATE,
        'uniform_slippage_per_leg':list(UNIFORM),'single_late_leg_shocks':list(ONE_LEG),
        'warning':'deterministic price stress, not a probabilistic leg-failure model'},'summary':summary,'cycles':stressed,'coverage':coverage,'errors':errs}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
