#!/usr/bin/env python3
"""Chronological YouTube horizon-transition falsification test.

Uses only information that was demonstrably available before the target horizon:
resolved earlier-horizon brackets on the exact same YouTube video. Video groups are
split by both exact video ID and the explicit title in Polymarket rules to protect
against bad copied URLs. Conflicting same-horizon resolutions invalidate that group.

A deliberately simple model is tested: historical transition-ratio envelopes. For a
target horizon, earlier video groups with the exact same horizon transition and whose
targets had already closed form the training set. A target bracket outside the
historical forecast envelope generates a NO candidate. Historical taker BUY prints
establish executable fills; current Culture fee rate is applied as forward-cost stress.

This is research/falsification, not an execution bot.
"""
from __future__ import annotations
import datetime as dt
import json,math,re,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

SRC=Path('youtube_horizon_inventory.json'); OUT=Path('youtube_transition_backtest.json')
UA={"User-Agent":"polymarket-factory-research/1.0","Accept":"application/json,*/*"}
FEE_RATE=0.05
MIN_TRAIN_SUPPORT=3
MIN_TRAIN_Q=5
ENTRY_DELAYS=(0,10,30)
CAPS=(0.80,0.85,0.90,0.95)


def parse_dt(x):
    if not x:return None
    try:return dt.datetime.fromisoformat(str(x).replace('Z','+00:00'))
    except:return None

def video_title(desc):
    s=desc or ''
    for p in (r'video titled\s+["“]([^"”]+)',r'refers only to\s+["“]([^"”]+)'):
        m=re.search(p,s,re.I)
        if m:return m.group(1).strip()
    return 'UNKNOWN'

def bracket(label):
    s=(label or '').replace('–','-').replace('—','-').replace(',','').strip().lower()
    nums=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',s)]
    if not nums:return None
    if s.startswith('<') or 'less than' in s:return (0.0,nums[0])
    if '+' in s or 'or more' in s or 'at least' in s:return (nums[0],math.inf)
    if len(nums)>=2:return (nums[0],nums[1])
    return None

def winner(m):
    ps=m.get('outcomePrices') or []
    try:return len(ps)>=2 and float(ps[0])>.99 and float(ps[1])<.01
    except:return False

def winner_interval(ev):
    rs=[bracket(m.get('groupItemTitle') or m.get('question')) for m in ev.get('markets',[]) if winner(m)]
    rs=[x for x in rs if x]
    if not rs:return None
    lo=max(x[0] for x in rs); hi=min(x[1] for x in rs)
    return (lo,hi) if lo<hi else None

def close_time(ev):
    xs=[parse_dt(m.get('closedTime')) for m in ev.get('markets',[]) if winner(m) and m.get('closedTime')]
    return max(xs) if xs else None

def event_close(ev):
    xs=[parse_dt(m.get('closedTime')) for m in ev.get('markets',[]) if m.get('closedTime')]
    return max(xs) if xs else None

def no_token(m):
    outs=[str(x).lower() for x in (m.get('outcomes') or [])]; ids=[str(x) for x in (m.get('clobTokenIds') or [])]
    if 'no' in outs and len(ids)==len(outs):return ids[outs.index('no')]
    return ids[1] if len(ids)>=2 else None

def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r:return json.load(r)

def trade_rows(cid,start,end):
    try:
        r=get('https://data-api.polymarket.com/trades',{'market':cid,'start':int(start.timestamp()),'end':int(end.timestamp()),'limit':10000,'offset':0,'takerOnly':'true'})
        return r if isinstance(r,list) else []
    except Exception:return []
def first_buy(rows,token,ts):
    z=[]
    for x in rows:
        if str(x.get('asset'))!=str(token) or str(x.get('side') or '').upper()!='BUY':continue
        try:t=int(x['timestamp']);p=float(x['price']);size=float(x.get('size') or 0)
        except:continue
        if t>=int(ts.timestamp()):z.append((t,p,size))
    if not z:return None
    t,p,size=min(z,key=lambda q:q[0]); fee=FEE_RATE*p*(1-p); cost=p+fee
    return {'timestamp':t,'price':p,'size':size,'delay_min':(t-int(ts.timestamp()))/60,'fee_stress':fee,'all_in':cost}
def qtile(xs,q):
    xs=sorted(xs)
    if not xs:return None
    if len(xs)==1:return xs[0]
    pos=(len(xs)-1)*q; i=int(math.floor(pos)); f=pos-i
    return xs[i]*(1-f)+xs[min(i+1,len(xs)-1)]*f

def build_groups(events):
    raw=defaultdict(list)
    for ev in events:
        yids=ev.get('youtube_ids') or []
        if len(yids)!=1:continue
        raw[(yids[0],video_title(ev.get('description')))].append(ev)
    groups=[]; rejected=[]
    for (yid,title),es in raw.items():
        by_h=defaultdict(list)
        for ev in es:
            h=ev.get('horizon_hours'); wi=winner_interval(ev)
            if h and wi:by_h[int(h)].append((ev,wi))
        if len(by_h)<2:continue
        states={}; conflict=False; reasons=[]
        for h,rows in by_h.items():
            lo=max(w[0] for _,w in rows); hi=min(w[1] for _,w in rows)
            if not lo<hi:
                conflict=True;reasons.append(f'conflicting winning intervals at {h}h');continue
            known=[close_time(ev) for ev,_ in rows]
            if any(x is None for x in known):
                reasons.append(f'missing winner closedTime at {h}h');continue
            states[h]={'interval':(lo,hi),'known_time':max(known),'events':[ev for ev,_ in rows]}
        if conflict or len(states)<2:
            rejected.append({'youtube_id':yid,'video_title':title,'reasons':reasons,'event_ids':[e.get('id') for e in es]});continue
        groups.append({'youtube_id':yid,'video_title':title,'states':states,'events':es,'volume':sum(float(e.get('volume') or 0) for e in es)})
    return groups,rejected

def transitions(groups):
    rows=[]
    for g in groups:
        hs=sorted(g['states'])
        for j in range(1,len(hs)):
            h1,h2=hs[j-1],hs[j]; a=g['states'][h1]['interval'];b=g['states'][h2]['interval']
            if a[0]<=0 or math.isinf(a[1]) or math.isinf(b[1]):continue
            rows.append({'group':g,'h1':h1,'h2':h2,'prev':a,'target':b,'target_known':g['states'][h2]['known_time'],'ratio_lo':b[0]/a[1],'ratio_hi':b[1]/a[0]})
    return rows

def model_envelope(train,prev,variant):
    los=[x['ratio_lo'] for x in train];his=[x['ratio_hi'] for x in train]
    if variant=='support':lo=min(los);hi=max(his)
    else:lo=qtile(los,.10);hi=qtile(his,.90)
    return (prev[0]*lo,prev[1]*hi),{'ratio_lo':lo,'ratio_hi':hi,'n':len(train)}
def disjoint(a,b):return a[1]<=b[0] or a[0]>=b[1]

def summarize(rows):
    out={}
    for variant in ('support','q10q90'):
      vr=[r for r in rows if r['variant']==variant]
      out[variant]={'candidates':len(vr),'videos':len(set(r['youtube_id'] for r in vr)),'with_any_fill':sum(any(v for v in r['fills'].values()) for r in vr),'caps':{}}
      for dm in ENTRY_DELAYS:
       dk=f'{dm}m'
       for cap in CAPS:
        chosen=[];by=defaultdict(list)
        for r in vr:
            f=r['fills'].get(dk)
            if f and f['all_in']<=cap:by[(r['youtube_id'],r['target_event_id'])].append((f['all_in'],r))
        for vals in by.values():chosen.append(min(vals,key=lambda x:x[0])[1])
        pnl=[]
        for r in chosen:
            f=r['fills'][dk]; cost=f['all_in']; win=not r['target_is_winner']; pnl.append((100/cost)*(1-cost) if win else -100)
        key=f'{dk}_cap_{cap:.2f}'
        out[variant]['caps'][key]={'trades':len(chosen),'videos':len(set(r['youtube_id'] for r in chosen)),'wins':sum(not r['target_is_winner'] for r in chosen),'losses':sum(r['target_is_winner'] for r in chosen),'equal_100_pnl':sum(pnl),'roi_on_deployed':sum(pnl)/(100*len(chosen)) if chosen else None}
    return out

def main():
    d=json.loads(SRC.read_text());groups,rejected=build_groups(d.get('events',[]));trs=transitions(groups);candidates=[]; diagnostics=[]
    for g in groups:
      hs=sorted(g['states'])
      for j in range(1,len(hs)):
        h1,h2=hs[j-1],hs[j]; prev=g['states'][h1]
        targets=[e for e in g['events'] if e.get('horizon_hours')==h2 and winner_interval(e)]
        for ev in targets:
          decision=max(parse_dt(ev.get('startDate')) or prev['known_time'],prev['known_time']+dt.timedelta(minutes=5))
          close=event_close(ev)
          if close is None or decision>=close:
            diagnostics.append({'youtube_id':g['youtube_id'],'target_event_id':ev.get('id'),'skip':'no pre-close decision window','decision':decision.isoformat(),'close':close.isoformat() if close else None});continue
          train=[x for x in trs if x['h1']==h1 and x['h2']==h2 and x['group']['youtube_id']!=g['youtube_id'] and x['target_known']<decision]
          for variant,min_n in (('support',MIN_TRAIN_SUPPORT),('q10q90',MIN_TRAIN_Q)):
            if len(train)<min_n:continue
            env,params=model_envelope(train,prev['interval'],variant)
            signal_markets=[]
            for m in ev.get('markets',[]):
                br=bracket(m.get('groupItemTitle') or m.get('question')); tok=no_token(m)
                if br and tok and disjoint(br,env):signal_markets.append((m,br,tok))
            for m,br,tok in signal_markets:
                end=min(close,decision+dt.timedelta(days=3));tr=trade_rows(str(m.get('conditionId')),decision,end);fills={}
                for dm in ENTRY_DELAYS:fills[f'{dm}m']=first_buy(tr,tok,decision+dt.timedelta(minutes=dm))
                candidates.append({'variant':variant,'youtube_id':g['youtube_id'],'video_title':g['video_title'],'transition':[h1,h2],'training_n':len(train),'decision_time':decision.isoformat(),'target_close':close.isoformat(),'prev_interval_m':prev['interval'],'forecast_envelope_m':env,'model':params,'target_event_id':ev.get('id'),'target_event_title':ev.get('title'),'target_market_id':m.get('id'),'target_condition_id':m.get('conditionId'),'target_bracket':m.get('groupItemTitle'),'target_interval_m':br,'target_is_winner':winner(m),'market_volume':float(m.get('volume') or 0),'fills':fills})
                time.sleep(.005)
    out={'method':{'fee_rate_stress':FEE_RATE,'min_train_support':MIN_TRAIN_SUPPORT,'min_train_q10q90':MIN_TRAIN_Q,'entry_delays_min':ENTRY_DELAYS,'caps':CAPS,'identity_rule':'exact YouTube ID + explicit video title; conflicting same-horizon winners reject group','chronology_rule':'prior-state winner closedTime + 5m; training targets must have closed before decision','signal_rule':'buy NO only when target bracket is disjoint from historical transition-ratio envelope','selection_rule':'summary keeps cheapest filled candidate per target event to avoid counting many correlated tail NOs'},'groups_clean':len(groups),'groups_rejected':rejected,'transition_observations':len(trs),'summary':summarize(candidates),'candidates':candidates,'diagnostics':diagnostics}
    OUT.write_text(json.dumps(out,indent=2,default=str),encoding='utf-8');print(json.dumps({'groups_clean':len(groups),'rejected':len(rejected),'transition_observations':len(trs),'summary':out['summary'],'diagnostics':diagnostics[:10]},indent=2))
if __name__=='__main__':main()
