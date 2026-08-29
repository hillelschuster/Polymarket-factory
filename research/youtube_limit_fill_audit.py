#!/usr/bin/env python3
"""Audit whether chronological YouTube tail-NO signals actually traded cheaply.

For each signaled NO from youtube_transition_backtest.json, inspect all taker BUY
prints during the first 120 minutes after the declared decision. Report the first
print and observed traded shares/notional at forward all-in cost caps. A qualifying
print must also be at least six hours before target market close.

This establishes historical traded availability, not guaranteed queue position or
full prospective depth. No signal is selected using the realized outcome.
"""
from __future__ import annotations
import datetime as dt,json,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

BACK=Path('youtube_transition_backtest.json'); INV=Path('youtube_horizon_inventory.json'); OUT=Path('youtube_limit_fill_audit.json')
UA={"User-Agent":"polymarket-factory-research/1.0","Accept":"application/json,*/*"}
FEE_RATE=.05; WINDOW_MIN=120; MIN_REMAIN_HOURS=6; CAPS=(.80,.85,.90,.95)

def parse(x):return dt.datetime.fromisoformat(str(x).replace('Z','+00:00'))
def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r:return json.load(r)
def no_token(m):
    outs=[str(x).lower() for x in (m.get('outcomes') or [])];ids=[str(x) for x in (m.get('clobTokenIds') or [])]
    if 'no' in outs and len(ids)==len(outs):return ids[outs.index('no')]
    return ids[1] if len(ids)>=2 else None
def fee(p):return FEE_RATE*p*(1-p)

def main():
    b=json.loads(BACK.read_text()); inv=json.loads(INV.read_text())
    market={str(m.get('id')):m for e in inv.get('events',[]) for m in e.get('markets',[])}
    # Deduplicate candidates emitted by two model variants while preserving which variants signaled them.
    dedup={}
    for r in b.get('candidates',[]):
        k=(str(r['target_market_id']),r['decision_time'])
        if k not in dedup:dedup[k]={**r,'variants':[]}
        dedup[k]['variants'].append(r['variant'])
    cache={}; rows=[];errors=[]
    for r in dedup.values():
        m=market.get(str(r['target_market_id']));tok=no_token(m or {})
        if not m or not tok:errors.append({'market_id':r['target_market_id'],'error':'missing market/token'});continue
        start=parse(r['decision_time']);close=parse(r['target_close']);end=min(start+dt.timedelta(minutes=WINDOW_MIN),close-dt.timedelta(hours=MIN_REMAIN_HOURS))
        if end<=start:continue
        cid=str(r['target_condition_id']);ck=(cid,int(start.timestamp()),int(end.timestamp()))
        if ck not in cache:
            try:x=get('https://data-api.polymarket.com/trades',{'market':cid,'start':ck[1],'end':ck[2],'limit':10000,'offset':0,'takerOnly':'true'});cache[ck]=x if isinstance(x,list) else []
            except Exception as ex:errors.append({'conditionId':cid,'error':repr(ex)});cache[ck]=[]
        prints=[]
        for x in cache[ck]:
            if str(x.get('asset'))!=tok or str(x.get('side') or '').upper()!='BUY':continue
            try:t=int(x['timestamp']);p=float(x['price']);sz=float(x.get('size') or 0)
            except:continue
            if not ck[1]<=t<=ck[2]:continue
            prints.append({'timestamp':t,'minutes_after_decision':(t-ck[1])/60,'price':p,'size':sz,'all_in':p+fee(p)})
        prints.sort(key=lambda z:z['timestamp'])
        capstats={}
        for cap in CAPS:
            xs=[x for x in prints if x['all_in']<=cap]
            capstats[f'{cap:.2f}']={'prints':len(xs),'shares':sum(x['size'] for x in xs),'notional_approx':sum(x['size']*x['price'] for x in xs),'first':xs[0] if xs else None,'best_all_in':min((x['all_in'] for x in xs),default=None)}
        rows.append({'variants':sorted(set(r['variants'])),'youtube_id':r['youtube_id'],'video_title':r['video_title'],'transition':r['transition'],'training_n':r['training_n'],'decision_time':r['decision_time'],'target_event_id':r['target_event_id'],'target_market_id':r['target_market_id'],'target_bracket':r['target_bracket'],'target_is_winner':r['target_is_winner'],'window_end':end.isoformat(),'total_no_buy_prints':len(prints),'first_no_buy':prints[0] if prints else None,'caps':capstats})
    summary={}
    for variant in ('support','q10q90'):
        vr=[r for r in rows if variant in r['variants']]
        summary[variant]={'signals':len(vr),'events':len(set(r['target_event_id'] for r in vr)),'videos':len(set(r['youtube_id'] for r in vr)),'signal_losses':sum(r['target_is_winner'] for r in vr),'caps':{}}
        for cap in CAPS:
            k=f'{cap:.2f}';eligible=[r for r in vr if r['caps'][k]['prints']]
            summary[variant]['caps'][k]={'signal_markets_with_traded_availability':len(eligible),'events_with_availability':len(set(r['target_event_id'] for r in eligible)),'videos_with_availability':len(set(r['youtube_id'] for r in eligible)),'observed_shares':sum(r['caps'][k]['shares'] for r in eligible),'observed_notional_approx':sum(r['caps'][k]['notional_approx'] for r in eligible),'all_qualifying_signals_were_correct':all(not r['target_is_winner'] for r in eligible) if eligible else None}
    out={'method':{'fee_rate_stress':FEE_RATE,'window_minutes':WINDOW_MIN,'minimum_hours_before_target_close':MIN_REMAIN_HOURS,'interpretation':'historical taker BUY prints prove traded availability but not our queue priority or full fillable depth'},'summary':summary,'rows':rows,'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps({'summary':summary,'errors':errors[:10]},indent=2))
if __name__=='__main__':main()
