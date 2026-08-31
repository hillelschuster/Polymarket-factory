#!/usr/bin/env python3
"""Blind near-resolution replication of complete NegRisk YES underrounds.

Unlike the candidate-driven historical study, this test does NOT use price history
to nominate a favorable timestamp. It preselects high-volume closed non-augmented
NegRisk events, then searches the final 48h of the actual public taker trade tape.

To avoid category/fee-classification optimism, every reconstructed YES basket is
stressed with the *highest current general taker coefficient used on Polymarket*,
7%, regardless of category. Maker rebates are never credited.

Evidence gates:
- every leg's public tape must reach the start of the 48h audit window;
- observed taker BUY of YES in every leg within 10/30/60 seconds;
- same-wallet version separately requires one proxyWallet to execute every leg;
- summed stressed cost must remain < $1.

This is still executed-trade evidence, not proof simultaneous L2 depth was visible
to an external trader at every sequence.
"""
from __future__ import annotations
import datetime as dt,json,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

OUT=Path('negrisk_blind_close_window_replication.json')
UA={'User-Agent':'polymarket-factory-research/1.0'};GAMMA='https://gamma-api.polymarket.com';DATA='https://data-api.polymarket.com/trades'
MAX_FETCH=1800;MAX_EVENTS=40;MIN_VOLUME=25_000.;MAX_OUTCOMES=8;LOOKBACK_H=48;RATE=.07;WINDOWS=(10,30,60);LIMIT=500;MAX_OFFSET=9500

def req(url,params=None,retries=3):
    if params:url+=('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.15*(i+1))
    raise last

def num(x):
    try:return float(x or 0)
    except:return 0.
def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []
def its(x):
    if not x:return None
    try:return int(dt.datetime.fromisoformat(str(x).replace('Z','+00:00')).timestamp())
    except:return None
def yes_info(m):
    outs=[str(x).casefold() for x in jl(m.get('outcomes'))];t=[str(x) for x in jl(m.get('clobTokenIds'))]
    try:i=outs.index('yes')
    except ValueError:return None
    return (i,t[i]) if i<len(t) else None
def close_ts(ev):
    # Prefer the market/event end clock, fall back to closedTime. Using min of
    # available plausible clocks avoids anchoring days after the actual event.
    xs=[its(ev.get('endDate'))]
    xs += [its(m.get('endDate')) for m in ev.get('markets') or []]
    xs=[x for x in xs if x]
    if xs:return min(xs)
    ys=[its(ev.get('closedTime'))]+[its(m.get('closedTime')) for m in ev.get('markets') or []]
    return min((x for x in ys if x),default=None)
def fetch_events():
    rows=[];off=0;errs=[]
    while len(rows)<MAX_FETCH:
        lim=min(100,MAX_FETCH-len(rows))
        try:b=req(GAMMA+'/events',{'limit':lim,'offset':off,'closed':'true','order':'volume','ascending':'false'})
        except Exception as ex:errs.append({'offset':off,'error':repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if len(b)<lim:break
    return rows,errs
def eligible(ev):
    ms=ev.get('markets') or []
    return bool(ev.get('negRisk') or ev.get('enableNegRisk')) and not bool(ev.get('negRiskAugmented')) and num(ev.get('volume'))>=MIN_VOLUME and 2<=len(ms)<=MAX_OUTCOMES and all(yes_info(m) for m in ms) and close_ts(ev) is not None

def tape(cid,yes_idx,start,end):
    raw=[];off=0;oldest=None;errs=[]
    while off<=MAX_OFFSET:
        try:b=req(DATA,{'market':cid,'takerOnly':'true','limit':LIMIT,'offset':off})
        except Exception as ex:errs.append({'offset':off,'error':repr(ex)});break
        if not isinstance(b,list) or not b:break
        raw.extend(b);ts=[]
        for x in b:
            try:ts.append(int(x.get('timestamp') or 0))
            except:pass
        if ts:
            oldest=min(ts) if oldest is None else min(oldest,min(ts))
            if oldest<=start:break
        if len(b)<LIMIT:break
        off+=LIMIT;time.sleep(.015)
    rows=[]
    for x in raw:
        try:
            if str(x.get('side') or '').upper()!='BUY' or int(x.get('outcomeIndex'))!=yes_idx:continue
            t=int(x['timestamp']);p=float(x['price']);s=float(x.get('size') or 0)
            if start<=t<=end and 0<p<1 and s>0:rows.append({'t':t,'price':p,'size':s,'wallet':x.get('proxyWallet'),'tx':x.get('transactionHash')})
        except:pass
    uniq={(x['tx'],x['t'],x['price'],x['size'],x['wallet']):x for x in rows}
    return sorted(uniq.values(),key=lambda x:x['t']),{'raw_rows':len(raw),'oldest':oldest,'reached_start':bool(oldest is not None and oldest<=start),'offset':min(off,MAX_OFFSET),'errors':errs}
def fcost(p):return p+RATE*p*(1-p)
def sequences(by,w,wallet=None):
    if wallet is not None:by={k:[x for x in v if x.get('wallet')==wallet] for k,v in by.items()}
    times=sorted({x['t'] for v in by.values() for x in v});out={}
    for st in times:
        en=st+w;chosen={}
        for k,v in by.items():
            xs=[x for x in v if st<=x['t']<=en]
            if not xs:break
            chosen[k]=min(xs,key=lambda x:(fcost(x['price']),x['t']))
        if len(chosen)!=len(by):continue
        allin=sum(fcost(x['price']) for x in chosen.values())
        if allin>=1:continue
        lo=min(x['t'] for x in chosen.values());hi=max(x['t'] for x in chosen.values());q=min(x['size'] for x in chosen.values())
        key=tuple((k,chosen[k]['tx'],chosen[k]['t']) for k in sorted(chosen))
        r={'all_in_sum_7pct_fee_stress':allin,'net_edge_per_share':1-allin,'span_seconds':hi-lo,'common_observed_size':q,'net_profit_at_common_size':(1-allin)*q,'legs':chosen}
        if key not in out or allin<out[key]['all_in_sum_7pct_fee_stress']:out[key]=r
    return sorted(out.values(),key=lambda x:(x['all_in_sum_7pct_fee_stress'],x['span_seconds']))
def main():
    events,derr=fetch_events();elig=sorted([e for e in events if eligible(e)],key=lambda e:num(e.get('volume')),reverse=True)[:MAX_EVENTS];aud=[]
    for ev in elig:
        end=close_ts(ev);start=end-LOOKBACK_H*3600;by={};cov={};errs=[]
        for i,m in enumerate(ev.get('markets') or []):
            yi,_=yes_info(m);name=str(m.get('groupItemTitle') or m.get('question') or i)
            rs,c=tape(m.get('conditionId'),yi,start,end);by[name]=rs;cov[name]=c
        fully=all(c['reached_start'] for c in cov.values())
        pooled={};same={}
        if fully:
            wallets=set.intersection(*[{x.get('wallet') for x in v if x.get('wallet')} for v in by.values()]) if by else set()
            for w in WINDOWS:
                pooled[str(w)]=sequences(by,w)
                xs=[]
                for wallet in wallets:
                    for r in sequences(by,w,wallet):xs.append({**r,'wallet':wallet})
                same[str(w)]=sorted(xs,key=lambda x:(x['all_in_sum_7pct_fee_stress'],x['span_seconds']))
        aud.append({'event_id':ev.get('id'),'title':ev.get('title'),'slug':ev.get('slug'),'volume':num(ev.get('volume')),'n_legs':len(by),'end_ts':end,'fully_covered_48h':fully,
            'leg_counts':{k:len(v) for k,v in by.items()},'coverage':cov,
            'pooled_counts':{str(w):len(pooled.get(str(w),[])) for w in WINDOWS},'same_wallet_counts':{str(w):len(same.get(str(w),[])) for w in WINDOWS},
            'best_pooled':{str(w):(pooled[str(w)][0] if pooled.get(str(w)) else None) for w in WINDOWS},
            'best_same_wallet':{str(w):(same[str(w)][0] if same.get(str(w)) else None) for w in WINDOWS}})
        print(ev.get('title'),fully,{w:len(same.get(str(w),[])) for w in WINDOWS},flush=True)
    full=[x for x in aud if x['fully_covered_48h']]
    out={'method':{'selection':'top-volume closed non-augmented NegRisk, <=8 outcomes; no price-history timing nomination','lookback_hours':LOOKBACK_H,'fee_stress_rate_all_events':RATE,'windows_seconds':list(WINDOWS),'coverage_required':True},
      'inventory':{'closed_fetched':len(events),'preselected':len(elig),'fully_covered_48h':len(full),
        'pooled_events_10s':sum(x['pooled_counts']['10']>0 for x in full),'same_wallet_events_10s':sum(x['same_wallet_counts']['10']>0 for x in full),
        'pooled_events_30s':sum(x['pooled_counts']['30']>0 for x in full),'same_wallet_events_30s':sum(x['same_wallet_counts']['30']>0 for x in full),
        'pooled_events_60s':sum(x['pooled_counts']['60']>0 for x in full),'same_wallet_events_60s':sum(x['same_wallet_counts']['60']>0 for x in full)},
      'events':aud,'errors':{'discovery':derr}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps({'inventory':out['inventory'],'positive':[{'event':x['title'],'same':x['same_wallet_counts'],'pooled':x['pooled_counts']} for x in full if any(x['same_wallet_counts'].values())]},indent=2))
if __name__=='__main__':main()
