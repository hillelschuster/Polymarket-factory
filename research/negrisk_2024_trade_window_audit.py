#!/usr/bin/env python3
"""Trade-level audit of the 2024 Presidency + Popular Vote NegRisk underround.

The hourly history screen saw the five complete YES outcomes sum to 0.942 near
2024-11-06 01:00 UTC. This audit uses public Data API market trades, not marks.
It requires observed taker BUY trades of YES in all five legs inside short
wall-clock windows. This is stronger evidence but still not simultaneous L2 depth.
"""
from __future__ import annotations
import json,time,urllib.parse,urllib.request
from pathlib import Path
OUT=Path('negrisk_2024_trade_window_audit.json')
UA={'User-Agent':'polymarket-factory-research/1.0'};BASE='https://data-api.polymarket.com/trades'
CENTER=1730869203;START=CENTER-6*3600;END=CENTER+4*3600
LIMIT=500;MAX_OFFSET=9500
LEGS=[
 ('D_both','0xafde9e890a2db339b6515cd75c2d09574dcaf731b483a1ef6ea0a3abc5ec8abd'),
 ('R_both','0x2010ff3939e8e664dd57369aa907bbaa6d03ae18be27fe3ab2f4cdcb95a8b2ab'),
 ('D_pres_R_pop','0x136e99098f7d4087b4c5775d9f9a512de67e50bda37e88fa86b05a226c390182'),
 ('R_pres_D_pop','0xc53c00d3ed7df96cb528e049ca2d8a6056b620a82bfffd3ad58d35c5f92c02d6'),
 ('Other','0xab0132a0b89e43d95c2643ac835877c757849e9a64ebac3c9f0c4696db41a288')]

def get(params,retries=3):
    url=BASE+'?'+urllib.parse.urlencode(params,doseq=True);last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.2*(i+1))
    raise last

def fetch_leg(name,cid):
    raw=[];errors=[];offset=0;oldest=None;hit_cap=False
    while offset<=MAX_OFFSET:
        try:b=get({'market':cid,'takerOnly':'true','limit':LIMIT,'offset':offset})
        except Exception as ex:errors.append({'offset':offset,'error':repr(ex)});break
        if not isinstance(b,list) or not b:break
        raw.extend(b)
        ts=[]
        for x in b:
            try:ts.append(int(x.get('timestamp') or 0))
            except:pass
        if ts:
            batch_old=min(ts);oldest=batch_old if oldest is None else min(oldest,batch_old)
            if oldest<=START:break
        if len(b)<LIMIT:break
        offset+=LIMIT;time.sleep(.03)
    if offset>MAX_OFFSET and (oldest is None or oldest>START):hit_cap=True
    rows=[]
    for x in raw:
        try:
            # For these binary contracts outcomeIndex 0 is YES. `side=BUY` is an
            # observed buyer taking/buying that reported outcome at this price.
            if str(x.get('side') or '').upper()!='BUY' or int(x.get('outcomeIndex'))!=0:continue
            t=int(x['timestamp']);p=float(x['price']);sz=float(x.get('size') or 0)
            if START<=t<=END and 0<p<1 and sz>0:
                rows.append({'t':t,'price':p,'size':sz,'usdc':p*sz,'tx':x.get('transactionHash'),'wallet':x.get('proxyWallet')})
        except Exception:pass
    seen={(r['tx'],r['t'],r['price'],r['size']):r for r in rows}
    cov={'raw_rows':len(raw),'oldest_timestamp':oldest,'reached_audit_start':bool(oldest is not None and oldest<=START),
         'hit_offset_cap_before_start':hit_cap,'last_offset':min(offset,MAX_OFFSET)}
    return sorted(seen.values(),key=lambda x:x['t']),errors,cov

def sliding(by_leg,width):
    times=sorted({r['t'] for xs in by_leg.values() for r in xs});out=[]
    for s in times:
        e=s+width;chosen={}
        for name,xs in by_leg.items():
            ys=[r for r in xs if s<=r['t']<=e]
            if not ys:break
            chosen[name]=min(ys,key=lambda r:r['price'])
        if len(chosen)!=len(LEGS):continue
        sm=sum(x['price'] for x in chosen.values())
        if sm>=1:continue
        lo=min(x['t'] for x in chosen.values());hi=max(x['t'] for x in chosen.values());size=min(x['size'] for x in chosen.values())
        out.append({'window_start':s,'window_seconds':width,'observed_span_seconds':hi-lo,'sum_observed_buy_prices':sm,
                    'gross_edge_per_share':1-sm,'common_observed_trade_size':size,'gross_edge_at_common_observed_size':(1-sm)*size,
                    'legs':chosen})
    uniq={}
    for x in out:
        k=tuple((n,x['legs'][n]['tx'],x['legs'][n]['t']) for n,_ in LEGS)
        if k not in uniq or x['sum_observed_buy_prices']<uniq[k]['sum_observed_buy_prices']:uniq[k]=x
    return sorted(uniq.values(),key=lambda x:(x['sum_observed_buy_prices'],x['observed_span_seconds']))

def main():
    by={};errs={};coverage={}
    for n,c in LEGS:by[n],errs[n],coverage[n]=fetch_leg(n,c)
    opp={str(w):sliding(by,w) for w in (30,60,120,300,600,900)}
    summary={w:{'n_underround_sequences':len(xs),'best_sum':xs[0]['sum_observed_buy_prices'] if xs else None,
                'best_edge':xs[0]['gross_edge_per_share'] if xs else None,'best_span_seconds':xs[0]['observed_span_seconds'] if xs else None,
                'best_common_size':xs[0]['common_observed_trade_size'] if xs else None,
                'best_gross_profit_at_common_size':xs[0]['gross_edge_at_common_observed_size'] if xs else None} for w,xs in opp.items()}
    out={'method':{'event_id':10656,'event':'Who wins Presidency + Popular Vote?','history_screen_min_sum':.942,
        'audit_start':START,'audit_end':END,'source':'public data-api /trades, takerOnly=true',
        'requirement':'YES BUY observed in all 5 legs within window',
        'warning':'close executed buys do not prove simultaneous L2 depth/queue or a single trader could acquire full bundle'},
        'coverage':coverage,'leg_counts':{k:len(v) for k,v in by.items()},'summary':summary,
        'best_sequences':{w:x[:25] for w,x in opp.items()},'errors':errs}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'coverage':coverage,'leg_counts':out['leg_counts'],'summary':summary,'errors':{k:v[:3] for k,v in errs.items()}},indent=2))
if __name__=='__main__':main()
