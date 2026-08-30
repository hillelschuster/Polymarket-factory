#!/usr/bin/env python3
"""Stress the proven 2024 same-wallet NegRisk baskets with today's Politics taker fee.

The historical event predates the current fee schedule. This intentionally asks a
harder forward-looking question: if the exact same observed basket executions
occurred today and every leg were charged the current Politics coefficient 0.04,
would the repeated complete-basket edge survive?

Fee model: shares * 0.04 * p * (1-p), matching current Polymarket taker fees.
No maker/taker rebates are credited; this is conservative for a taker strategy.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_2024_wallet_basket_audit as src

OUT=Path('negrisk_2024_current_fee_stress.json')
RATE=.04
WINDOWS=(10,20,30)

def stress(x):
    prices=[r['price'] for r in x['legs'].values()];q=x['common_observed_size']
    gross_per=1-sum(prices);fee_per=sum(RATE*p*(1-p) for p in prices);net_per=gross_per-fee_per
    all_in_per=sum(prices)+fee_per
    return {**x,'current_fee_rate_stress':RATE,'gross_edge_per_share':gross_per,'fee_per_share':fee_per,
        'net_edge_per_share_after_current_fee_stress':net_per,'all_in_per_share':all_in_per,
        'net_roi_on_all_in':net_per/all_in_per if all_in_per>0 else None,
        'gross_edge_usd':gross_per*q,'fee_usd':fee_per*q,'net_edge_usd_after_current_fee_stress':net_per*q,
        'positive_after_current_fee_stress':net_per>0}
def main():
    by={};coverage={};errs={}
    for n,c in src.tape.LEGS:
        rows,e,cov=src.tape.fetch_leg(n,c);by[n]=rows;errs[n]=e;coverage[n]=cov
    outwins={}
    for w in WINDOWS:
        seq=src.wallet_sequences(by,w);non=src.greedy_nonoverlap(seq);st=[stress(x) for x in non]
        outwins[str(w)]={'same_wallet_sequences':len(seq),'greedy_nonoverlap_cycles':len(non),
            'positive_cycles_after_current_fee_stress':sum(x['positive_after_current_fee_stress'] for x in st),
            'gross_edge_usd':sum(x['gross_edge_usd'] for x in st),'current_fee_stress_usd':sum(x['fee_usd'] for x in st),
            'net_edge_usd_after_current_fee_stress':sum(x['net_edge_usd_after_current_fee_stress'] for x in st),
            'best_net_cycle_usd':max((x['net_edge_usd_after_current_fee_stress'] for x in st),default=None),
            'best_net_roi_on_all_in':max((x['net_roi_on_all_in'] for x in st),default=None),'cycles':st}
    out={'method':{'event':'2024 Presidency + Popular Vote','fee_rate_stress':RATE,
        'fee_formula':'shares * rate * p * (1-p)','rebates_credited':False,
        'interpretation':'counterfactual current-cost stress of observed historical executions'},
        'coverage':coverage,'windows':outwins,'errors':errs}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'windows':{w:{k:v[k] for k in ['same_wallet_sequences','greedy_nonoverlap_cycles','positive_cycles_after_current_fee_stress','gross_edge_usd','current_fee_stress_usd','net_edge_usd_after_current_fee_stress','best_net_cycle_usd','best_net_roi_on_all_in']} for w,v in outwins.items()},'errors':{k:v[:2] for k,v in errs.items()}},indent=2))
if __name__=='__main__':main()
