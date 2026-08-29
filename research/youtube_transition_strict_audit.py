#!/usr/bin/env python3
"""Strict execution audit for youtube_transition_backtest.json.

The transition backtest intentionally stores raw first observed taker fills. This audit
rejects any fill that is not tightly contemporaneous with the declared decision:
  - no more than 120 minutes after the requested entry clock;
  - at least 6 hours before the target market's resolution/close timestamp.

The second condition is a conservative guard against accidentally treating a trade
near/after the factual horizon as predictive. It is not an assertion that closedTime
is the exact YouTube cutoff; it deliberately leaves a wide safety margin.
"""
from __future__ import annotations
import datetime as dt,json
from collections import defaultdict
from pathlib import Path

SRC=Path('youtube_transition_backtest.json'); OUT=Path('youtube_transition_strict_audit.json')
MAX_LATENCY_MIN=120.0; MIN_REMAIN_HOURS=6.0
CAPS=(.80,.85,.90,.95); ENTRY_DELAYS=(0,10,30)

def parse(x):return dt.datetime.fromisoformat(str(x).replace('Z','+00:00'))

def valid(r,key):
    f=r.get('fills',{}).get(key)
    if not f:return None
    if float(f.get('delay_min',1e9))>MAX_LATENCY_MIN:return None
    close=parse(r['target_close']); trade=dt.datetime.fromtimestamp(int(f['timestamp']),tz=dt.timezone.utc)
    if (close-trade).total_seconds()<MIN_REMAIN_HOURS*3600:return None
    return f

def summarize(rows):
    out={}
    for variant in ('support','q10q90'):
      vr=[r for r in rows if r['variant']==variant]
      out[variant]={'candidates':len(vr),'videos':len(set(r['youtube_id'] for r in vr)),'caps':{}}
      for dm in ENTRY_DELAYS:
       key=f'{dm}m'
       for cap in CAPS:
        by=defaultdict(list)
        for r in vr:
            f=valid(r,key)
            if f and f['all_in']<=cap:by[(r['youtube_id'],r['target_event_id'])].append((f['all_in'],r))
        chosen=[min(v,key=lambda x:x[0])[1] for v in by.values()]
        pnl=[]
        for r in chosen:
            f=valid(r,key); cost=f['all_in']; win=not r['target_is_winner']
            pnl.append((100/cost)*(1-cost) if win else -100)
        out[variant]['caps'][f'{key}_cap_{cap:.2f}']={'trades':len(chosen),'videos':len(set(r['youtube_id'] for r in chosen)),'wins':sum(not r['target_is_winner'] for r in chosen),'losses':sum(r['target_is_winner'] for r in chosen),'equal_100_pnl':sum(pnl),'roi_on_deployed':sum(pnl)/(100*len(chosen)) if chosen else None,'selected':[{'youtube_id':r['youtube_id'],'video_title':r['video_title'],'target_event_id':r['target_event_id'],'transition':r['transition'],'target_bracket':r['target_bracket'],'all_in':valid(r,key)['all_in'],'raw_fill_latency_min':valid(r,key)['delay_min'],'target_is_winner':r['target_is_winner']} for r in chosen]}
    return out

def main():
    d=json.loads(SRC.read_text()); rows=d.get('candidates',[])
    fill_audit={'raw_fill_slots':0,'valid_fill_slots':0,'latency_rejected':0,'near_close_rejected':0}
    for r in rows:
      for dm in ENTRY_DELAYS:
        key=f'{dm}m';f=r.get('fills',{}).get(key)
        if not f:continue
        fill_audit['raw_fill_slots']+=1
        if float(f.get('delay_min',1e9))>MAX_LATENCY_MIN:fill_audit['latency_rejected']+=1;continue
        close=parse(r['target_close']);trade=dt.datetime.fromtimestamp(int(f['timestamp']),tz=dt.timezone.utc)
        if (close-trade).total_seconds()<MIN_REMAIN_HOURS*3600:fill_audit['near_close_rejected']+=1;continue
        fill_audit['valid_fill_slots']+=1
    out={'method':{'max_fill_latency_min':MAX_LATENCY_MIN,'minimum_hours_before_target_close':MIN_REMAIN_HOURS,'reason':'prevent hindsight contamination and stale first-fill searches; closedTime used only as a conservative outer bound'},'fill_audit':fill_audit,'summary':summarize(rows)}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
if __name__=='__main__':main()
