#!/usr/bin/env python3
"""Live depth-aware scanner for converter-enabled NegRisk arbitrage.

Targets Polymarket's protocol-executable NO->YES/collateral equivalence and includes
BOTH costs that matter:
- current CLOB taker fees on the trades used to acquire/sell positions;
- the event's `negRiskFeeBips` charged by the NegRisk Adapter itself.

For conversion fee fraction f, converting q of a subset S yields only
`q*(1-f)` of each nominal output. For a full set of n NO positions this is
`(n-1)*q*(1-f)` collateral.

Two screens:
1. Full-set NO conversion: depth-aware NO asks, adapter fee, current taker fees.
2. Partial subset: top-level screen that buys NO on S, converts, and sells returned
   complementary YES positions. It is not atomic and is screening only.

No orders or wallet actions are performed.
"""
from __future__ import annotations
import json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import negrisk_hotloop_benchmark as hot
import negrisk_fast_depth_observer as base

OUT=Path('negrisk_converter_live_scanner.json')
MAX_LEGS=15
MIN_VOLUME=5_000.0

def token_pair(m):
    outs=[str(x).casefold() for x in base.jl(m.get('outcomes'))];toks=[str(x) for x in base.jl(m.get('clobTokenIds'))]
    try:yi=outs.index('yes');ni=outs.index('no')
    except ValueError:return None
    return (toks[yi],toks[ni]) if yi<len(toks) and ni<len(toks) else None

def eligible(ev):
    ms=ev.get('markets') or []
    if not(ev.get('negRisk') or ev.get('enableNegRisk')) or ev.get('negRiskAugmented'):return False
    if base.num(ev.get('volume'))<MIN_VOLUME or not(2<=len(ms)<=MAX_LEGS):return False
    return all(m.get('active') and not m.get('closed') and token_pair(m) for m in ms)

def levels(book,side):
    xs=[]
    for z in (book or {}).get(side) or []:
        try:
            p=float(z['price']);s=float(z['size'])
            if 0<p<1 and s>0:xs.append((p,s))
        except:pass
    return sorted(xs,reverse=(side=='bids'))

def fee(p,r):return r*p*(1-p)
def integrate_asks(xs,q,r):
    left=q;cost=fees=0.0
    for p,s in xs:
        z=min(left,s);cost+=z*p;fees+=z*fee(p,r);left-=z
        if left<=1e-12:break
    return None if left>1e-9 else (cost,fees)

def optimize_full(legs,conversion_fee_fraction=0.0):
    maxq=min(sum(s for _,s in x['no_asks']) for x in legs)
    if maxq<=0:return None
    qs={maxq}
    for x in legs:
        c=0
        for _,s in x['no_asks']:
            c+=s
            if c<=maxq+1e-9:qs.add(c)
    best=None;n=len(legs);out_frac=1-conversion_fee_fraction
    for q in sorted(qs):
        cost=fees=0.0;ok=True
        for x in legs:
            z=integrate_asks(x['no_asks'],q,x['fee_rate'])
            if z is None:ok=False;break
            cost+=z[0];fees+=z[1]
        if not ok:continue
        nominal=(n-1)*q;payout=nominal*out_frac;conv_fee=nominal-payout;allin=cost+fees;profit=payout-allin
        r={'basket_shares':q,'nominal_conversion_output':nominal,'adapter_conversion_fee':conv_fee,'payout_collateral':payout,
           'gross_cost':cost,'clob_taker_fee_cost':fees,'all_in_trade_cost':allin,'net_profit_before_gas':profit,
           'net_roi_before_gas':profit/allin if allin>0 else None,'break_even_conversion_gas_usd':max(0,profit)}
        if best is None or r['net_profit_before_gas']>best['net_profit_before_gas']:best=r
    return best

def partial_top(legs,conversion_fee_fraction=0.0):
    if any(not x['no_asks'] or not x['yes_bids'] for x in legs):return None
    out_frac=1-conversion_fee_fraction;rows=[]
    for x in legs:
        ya,ys=x['yes_bids'][0];na,ns=x['no_asks'][0];r=x['fee_rate']
        sell_net=ya-fee(ya,r);buy_allin=na+fee(na,r)
        rows.append({**x,'yes_bid':ya,'yes_bid_size':ys,'no_ask':na,'no_ask_size':ns,'sell_yes_net':sell_net,'buy_no_allin':buy_allin,
                     'subset_increment':out_frac*(1-sell_net)-buy_allin})
    base_edge=out_frac*(sum(x['sell_yes_net'] for x in rows)-1)
    chosen=[x for x in rows if x['subset_increment']>0]
    if not chosen:chosen=[max(rows,key=lambda x:x['subset_increment'])]
    chosen_ids={x['condition_id'] for x in chosen};complement=[x for x in rows if x['condition_id'] not in chosen_ids]
    edge=base_edge+sum(x['subset_increment'] for x in chosen)
    direct=out_frac*((len(chosen)-1)+sum(x['sell_yes_net'] for x in complement))-sum(x['buy_no_allin'] for x in chosen)
    # Returned YES amount is q*out_frac, so input q can be constrained by YES bid size/out_frac.
    sizes=[x['no_ask_size'] for x in chosen]+[(x['yes_bid_size']/out_frac if out_frac>0 else 0) for x in complement]
    q=min(sizes) if sizes else 0.0
    return {'subset_size':len(chosen),'complement_size':len(complement),'conversion_fee_fraction':conversion_fee_fraction,
            'unit_edge_before_gas':edge,'direct_unit_edge_check':direct,'top_level_input_size':q,
            'top_level_profit_before_gas':edge*q,'break_even_conversion_gas_usd':max(0,edge*q),
            'subset':[{'condition_id':x['condition_id'],'question':x['question'],'no_ask':x['no_ask'],'no_size':x['no_ask_size'],'increment':x['subset_increment']} for x in chosen],
            'complement_sales':[{'condition_id':x['condition_id'],'question':x['question'],'yes_bid':x['yes_bid'],'yes_size':x['yes_bid_size']} for x in complement]}

def main():
    t0=time.monotonic();events,derr=base.fetch_active_events();discovery=time.monotonic()-t0;evs=[e for e in events if eligible(e)]
    recs=[];fee_cache={};fee_errs=[];tokens=[]
    for ev in evs:
        ms=[]
        for m in ev.get('markets') or []:
            y,n=token_pair(m);cid=m.get('conditionId')
            if cid not in fee_cache:
                try:fee_cache[cid]=base.fee_rate({'condition_id':cid,'feesEnabled':bool(m.get('feesEnabled')),'feeSchedule':m.get('feeSchedule')})
                except Exception as ex:fee_cache[cid]=.05;fee_errs.append({'condition_id':cid,'error':repr(ex),'fallback':.05})
            ms.append({'condition_id':cid,'question':m.get('question'),'groupItemTitle':m.get('groupItemTitle'),'yes_token':y,'no_token':n,'fee_rate':fee_cache[cid]});tokens.extend([y,n])
        bips=base.num(ev.get('negRiskFeeBips'))
        recs.append({'event_id':ev.get('id'),'title':ev.get('title'),'slug':ev.get('slug'),'volume':base.num(ev.get('volume')),'endDate':ev.get('endDate'),
                     'negRiskMarketID':ev.get('negRiskMarketID'),'negRiskFeeBips':bips,'conversion_fee_fraction':bips/10000.0,'markets':ms})
    tokens=list(dict.fromkeys(tokens));books,berrs,book_seconds,nreq=hot.concurrent_books(tokens);rows=[]
    for ev in recs:
        legs=[]
        for m in ev['markets']:
            na=levels(books.get(m['no_token']),'asks');yb=levels(books.get(m['yes_token']),'bids')
            if not na:legs=[];break
            legs.append({**m,'no_asks':na,'yes_bids':yb})
        if not legs:continue
        cf=ev['conversion_fee_fraction'];full=optimize_full(legs,cf);partial=partial_top(legs,cf)
        rows.append({**{k:ev[k] for k in ['event_id','title','slug','volume','endDate','negRiskMarketID','negRiskFeeBips','conversion_fee_fraction']},'n_legs':len(legs),
                     'full_set':full,'full_positive':bool(full and full['net_profit_before_gas']>0),'partial_top':partial,'partial_positive':bool(partial and partial['unit_edge_before_gas']>0)})
    fullpos=[x for x in rows if x['full_positive']];partialpos=[x for x in rows if x['partial_positive']]
    out={'generated_at':time.time(),'method':{'max_legs':MAX_LEGS,'adapter_fee':'Gamma negRiskFeeBips applied to collateral and returned YES outputs','full_set':'depth-aware NO asks + CLOB taker fees + adapter fee','partial_subset':'best-level subset + complement YES sales, including adapter output haircut','gas_included':False,'no_orders':True,
         'execution_warning':'batch FOK is per-order, not basket-atomic; conversion and residual sales are separate actions'},
         'timing':{'discovery_seconds':discovery,'book_seconds':book_seconds,'book_requests':nreq,'tokens':len(tokens)},
         'inventory':{'events_fetched':len(events),'eligible_events':len(recs),'scored_events':len(rows),'full_positive':len(fullpos),'partial_positive':len(partialpos)},
         'full_positive':sorted(fullpos,key=lambda x:x['full_set']['net_profit_before_gas'],reverse=True),'partial_positive':sorted(partialpos,key=lambda x:x['partial_top']['top_level_profit_before_gas'],reverse=True),
         'top_full':sorted(rows,key=lambda x:(x['full_set'] or {}).get('net_roi_before_gas',-999),reverse=True)[:30],'errors':{'discovery':derr,'books':berrs,'fees':fee_errs}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'timing':out['timing'],'inventory':out['inventory'],'conversion_fee_bips_distribution':sorted({x['negRiskFeeBips'] for x in rows}),
      'full_positive':[{'event':x['title'],'bips':x['negRiskFeeBips'],'profit':x['full_set']['net_profit_before_gas'],'roi':x['full_set']['net_roi_before_gas'],'capital':x['full_set']['all_in_trade_cost']} for x in out['full_positive'][:15]],
      'partial_positive':[{'event':x['title'],'bips':x['negRiskFeeBips'],'S':x['partial_top']['subset_size'],'edge':x['partial_top']['unit_edge_before_gas'],'profit':x['partial_top']['top_level_profit_before_gas']} for x in out['partial_positive'][:15]],'errors':{k:v[:3] for k,v in out['errors'].items()}},indent=2))
if __name__=='__main__':main()
