#!/usr/bin/env python3
"""Trade-level audit of the 2024 Presidency + Popular Vote NegRisk underround.

The broader history screen found five hourly YES prices summing to 0.942 around
2024-11-06 01:00 UTC. prices-history is not executable quote proof. This script
asks a stronger question using the public Data API activity stream:

Were there observed taker BUY trades of the YES outcome in *all five* complete
basket legs inside the same short wall-clock window, with observed trade prices
summing below $1?

If yes, that proves each price was actually traded by a buyer in a temporally
close sequence. It still does NOT prove all five asks/depth coexisted at one
instant or that one trader could fill the whole bundle at arbitrary size.
"""
from __future__ import annotations
import datetime as dt,json,time,urllib.parse,urllib.request
from pathlib import Path

OUT=Path('negrisk_2024_trade_window_audit.json')
UA={'User-Agent':'polymarket-factory-research/1.0'}
BASE='https://data-api.polymarket.com/activity'
CENTER=1730869203
START=CENTER-6*3600;END=CENTER+4*3600
CHUNK=30*60;LIMIT=500
LEGS=[
 ('D_both','0xafde9e890a2db339b6515cd75c2d09574dcaf731b483a1ef6ea0a3abc5ec8abd'),
 ('R_both','0x2010ff3939e8e664dd57369aa907bbaa6d03ae18be27fe3ab2f4cdcb95a8b2ab'),
 ('D_pres_R_pop','0x136e99098f7d4087b4c5775d9f9a512de67e50bda37e88fa86b05a226c390182'),
 ('R_pres_D_pop','0xc53c00d3ed7df96cb528e049ca2d8a6056b620a82bfffd3ad58d35c5f92c02d6'),
 ('Other','0xab0132a0b89e43d95c2643ac835877c757849e9a64ebac3c9f0c4696db41a288'),
]

def get(params,retries=3):
    url=BASE+'?'+urllib.parse.urlencode(params,doseq=True);last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.2*(i+1))
    raise last

def fetch_leg(name,cid):
    rows=[];errors=[];s=START
    while s<END:
        e=min(END,s+CHUNK)
        try:
            batch=get({'market':cid,'type':'TRADE','start':s,'end':e,'sortBy':'TIMESTAMP','sortDirection':'ASC','limit':LIMIT})
        except Exception as ex:
            errors.append({'start':s,'end':e,'error':repr(ex)});s=e;continue
        if not isinstance(batch,list):
            errors.append({'start':s,'end':e,'error':'non_list_response'});s=e;continue
        if len(batch)>=LIMIT:errors.append({'start':s,'end':e,'warning':'chunk_hit_limit','n':len(batch)})
        for x in batch:
            try:
                # Outcome index 0 is YES for these binary contracts. BUY means the
                # wallet bought the reported outcome token at the reported price.
                if str(x.get('side') or '').upper()!='BUY' or int(x.get('outcomeIndex'))!=0:continue
                ts=int(x['timestamp']);p=float(x['price']);sz=float(x.get('size') or 0)
                if s<=ts<=e and 0<p<1 and sz>0:
                    rows.append({'t':ts,'price':p,'size':sz,'usdc':float(x.get('usdcSize') or p*sz),
                                 'tx':x.get('transactionHash'),'wallet':x.get('proxyWallet')})
            except Exception:pass
        s=e;time.sleep(.03)
    # transaction-level dedup because adjacent closed intervals can overlap at boundary
    seen={};
    for r in rows:seen[(r['tx'],r['t'],r['price'],r['size'])]=r
    return sorted(seen.values(),key=lambda x:x['t']),errors

def sliding_opportunities(by_leg,width):
    all_times=sorted({r['t'] for xs in by_leg.values() for r in xs});out=[]
    for start in all_times:
        end=start+width;chosen={}
        for name,xs in by_leg.items():
            ys=[r for r in xs if start<=r['t']<=end]
            if not ys:break
            # optimistic but observed: cheapest actual BUY in each leg in window.
            chosen[name]=min(ys,key=lambda r:r['price'])
        if len(chosen)!=len(LEGS):continue
        total=sum(x['price'] for x in chosen.values());tmin=min(x['t'] for x in chosen.values());tmax=max(x['t'] for x in chosen.values())
        if total<1:
            out.append({'window_start':start,'window_seconds':width,'observed_span_seconds':tmax-tmin,
                        'sum_observed_buy_prices':total,'gross_edge_per_share':1-total,
                        'common_observed_trade_size':min(x['size'] for x in chosen.values()),
                        'gross_edge_at_common_observed_size':(1-total)*min(x['size'] for x in chosen.values()),
                        'legs':chosen})
    # Deduplicate windows that select the exact same trade tuple.
    uniq={}
    for x in out:
        key=tuple((n,x['legs'][n]['tx'],x['legs'][n]['t']) for n,_ in LEGS);old=uniq.get(key)
        if old is None or x['sum_observed_buy_prices']<old['sum_observed_buy_prices']:uniq[key]=x
    return sorted(uniq.values(),key=lambda x:(x['sum_observed_buy_prices'],x['observed_span_seconds']))

def main():
    by={};errs={}
    for name,cid in LEGS:
        by[name],errs[name]=fetch_leg(name,cid)
    opp={str(w):sliding_opportunities(by,w) for w in (30,60,120,300,600,900)}
    summary={}
    for w,xs in opp.items():
        summary[w]={'n_underround_sequences':len(xs),'best_sum':xs[0]['sum_observed_buy_prices'] if xs else None,
                    'best_edge':xs[0]['gross_edge_per_share'] if xs else None,
                    'best_span_seconds':xs[0]['observed_span_seconds'] if xs else None,
                    'best_common_size':xs[0]['common_observed_trade_size'] if xs else None,
                    'best_gross_profit_at_common_size':xs[0]['gross_edge_at_common_observed_size'] if xs else None}
    out={'method':{'event':'Who wins Presidency + Popular Vote?','event_id':10656,
        'history_screen_center_ts':CENTER,'audit_start':START,'audit_end':END,
        'requirement':'observed YES BUY in all 5 complete outcomes within sliding window',
        'warning':'temporally close executed buys still do not prove simultaneous historical ask depth or achievable multi-leg queue position'},
        'leg_counts':{k:len(v) for k,v in by.items()},'summary':summary,
        'best_sequences':{w:xs[:25] for w,xs in opp.items()},'errors':errs}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'leg_counts':out['leg_counts'],'summary':summary,'errors':{k:v[:3] for k,v in errs.items()}},indent=2))
if __name__=='__main__':main()
