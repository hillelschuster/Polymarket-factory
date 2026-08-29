#!/usr/bin/env python3
"""Falsify a simple central-bin YouTube forecasting model before price testing.

For exact same-video day sequences with three consecutive 24h horizons, predict the
next cumulative view count from:
  next_increment = previous_increment * median(prior-video decay factors)
Training is chronological and excludes the target video. Minimum training support=3.

If this cannot locate the narrow winning bracket reliably, there is no reason to add
pricing complexity or tune a richer model. Research only.
"""
from __future__ import annotations
import datetime as dt,json,math,re,statistics
from collections import defaultdict
from pathlib import Path

SRC=Path('youtube_horizon_inventory.json');OUT=Path('youtube_velocity_decay_test.json');MIN_TRAIN=3

def parse(x):return dt.datetime.fromisoformat(str(x).replace('Z','+00:00')) if x else None
def title(desc):
    for p in (r'video titled\s+["“]([^"”]+)',r'refers only to\s+["“]([^"”]+)'):
        m=re.search(p,desc or '',re.I)
        if m:return m.group(1).strip()
    return 'UNKNOWN'
def bracket(label):
    s=(label or '').replace('–','-').replace('—','-').replace(',','').lower();nums=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',s)]
    if not nums:return None
    if s.startswith('<') or 'less than' in s:return (0.0,nums[0])
    if '+' in s or 'or more' in s or 'at least' in s:return (nums[0],math.inf)
    if len(nums)>=2:return (nums[0],nums[1])
def winner(m):
    p=m.get('outcomePrices') or []
    try:return len(p)>=2 and float(p[0])>.99 and float(p[1])<.01
    except:return False
def win_interval(ev):
    xs=[bracket(m.get('groupItemTitle') or m.get('question')) for m in ev.get('markets',[]) if winner(m)];xs=[x for x in xs if x]
    if not xs:return None
    z=(max(x[0] for x in xs),min(x[1] for x in xs));return z if z[0]<z[1] else None
def close(ev):
    xs=[parse(m.get('closedTime')) for m in ev.get('markets',[]) if winner(m) and m.get('closedTime')]
    return max(xs) if xs else None

def groups(events):
    raw=defaultdict(list)
    for e in events:
        y=e.get('youtube_ids') or []
        if len(y)==1:raw[(y[0],title(e.get('description')))].append(e)
    out=[]
    for key,es in raw.items():
        by=defaultdict(list)
        for e in es:
            if e.get('horizon_hours') and win_interval(e):by[int(e['horizon_hours'])].append(e)
        st={};bad=False
        for h,rows in by.items():
            ints=[win_interval(e) for e in rows];lo=max(x[0] for x in ints);hi=min(x[1] for x in ints)
            if lo>=hi:bad=True;break
            cs=[close(e) for e in rows]
            if any(c is None for c in cs) or math.isinf(hi):continue
            st[h]={'interval':(lo,hi),'mid':(lo+hi)/2,'known':max(cs)}
        if not bad and len(st)>=3:out.append({'key':key,'states':st})
    return out

def main():
    d=json.loads(SRC.read_text());gs=groups(d.get('events',[]));obs=[]
    for g in gs:
        hs=sorted(g['states'])
        for i in range(2,len(hs)):
            h0,h1,h2=hs[i-2:i+1]
            if h1-h0!=24 or h2-h1!=24:continue
            a,b,c=(g['states'][h]['mid'] for h in (h0,h1,h2))
            if b<=a:continue
            obs.append({'g':g,'triple':(h0,h1,h2),'decay':(c-b)/(b-a),'target_known':g['states'][h2]['known']})
    rows=[]
    for o in obs:
        g=o['g'];h0,h1,h2=o['triple'];decision=g['states'][h1]['known']+dt.timedelta(minutes=5)
        train=[x for x in obs if x['triple']==o['triple'] and x['g']['key']!=g['key'] and x['target_known']<decision]
        if len(train)<MIN_TRAIN:continue
        decay=statistics.median(x['decay'] for x in train);a=g['states'][h0]['mid'];b=g['states'][h1]['mid'];pred=b+decay*(b-a);actual=g['states'][h2]['interval']
        hit=actual[0]<=pred<actual[1];dist=0 if hit else min(abs(pred-actual[0]),abs(pred-actual[1]))
        rows.append({'youtube_id':g['key'][0],'video_title':g['key'][1],'triple':o['triple'],'training_n':len(train),'decision_time':decision.isoformat(),'median_decay':decay,'prediction_m':pred,'actual_interval_m':actual,'exact_bracket_hit':hit,'distance_to_winning_interval_m':dist})
    n=len(rows);dist=[r['distance_to_winning_interval_m'] for r in rows]
    out={'method':{'minimum_training_videos':MIN_TRAIN,'forecast':'prior increment * chronological median decay factor','purpose':'gate central-bin price work; no tuning'},'summary':{'predictions':n,'independent_target_videos':len(set(r['youtube_id'] for r in rows)),'exact_bracket_hits':sum(r['exact_bracket_hit'] for r in rows),'exact_bracket_hit_rate':sum(r['exact_bracket_hit'] for r in rows)/n if n else None,'mean_distance_to_winning_interval_m':sum(dist)/n if n else None,'median_distance_to_winning_interval_m':statistics.median(dist) if dist else None,'within_0_5m':sum(x<=.5 for x in dist),'within_1m':sum(x<=1 for x in dist)},'rows':rows}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out['summary'],indent=2))
if __name__=='__main__':main()
