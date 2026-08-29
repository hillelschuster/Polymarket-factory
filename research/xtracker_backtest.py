#!/usr/bin/env python3
"""Chronological XTracker count-market backtest using only public point-in-time data.

Research only. Historical CLOB price-history is used as a price proxy; fixed execution
buffers are applied because historical L2 books are not available from this endpoint.
"""
import bisect, datetime as dt, json, math, re, statistics, urllib.parse, urllib.request

UA={'User-Agent':'polymarket-factory-research/1.0'}

def get(url, params=None):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params, doseq=True)
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)

def post(url, payload):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,headers={**UA,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=60) as r: return json.load(r)

def iso(s):
    if not s: return None
    return dt.datetime.fromisoformat(s.replace('Z','+00:00'))

def ts(x): return int(x.timestamp())

def unwrap_data(x):
    if isinstance(x,dict) and 'data' in x: return x['data']
    return x

def extract_post_time(p):
    for k in ('postedAt','publishedAt','createdAt','timestamp','created_at','date','created_at_iso'):
        if k not in p or p[k] in (None,''): continue
        v=p[k]
        try:
            if isinstance(v,(int,float)):
                if v>1e12: v/=1000
                return dt.datetime.fromtimestamp(v,dt.timezone.utc)
            return iso(str(v))
        except Exception: pass
    return None

def parse_arr(v):
    if isinstance(v,list): return v
    if not v: return []
    try: return json.loads(v)
    except Exception: return []

def bracket(label):
    s=(label or '').replace('–','-').replace('—','-').replace(',','').strip().lower()
    nums=[int(x) for x in re.findall(r'\d+',s)]
    if not nums: return None
    if '<' in s or 'below' in s or 'under' in s:
        hi=nums[0]-1 if '<' in s else nums[0]-1
        return (-10**9,hi)
    if '+' in s or 'above' in s or 'over' in s or '≥' in s:
        lo=nums[0] if ('+' in s or '≥' in s) else nums[0]+1
        return (lo,10**9)
    if len(nums)>=2: return (nums[0],nums[1])
    return (nums[0],nums[0])

def in_bracket(n,b): return b and b[0] <= n <= b[1]

def point_at(history, when):
    if not history: return None
    arr=sorted((int(x['t']),float(x['p'])) for x in history if x.get('t') is not None and x.get('p') is not None)
    times=[x[0] for x in arr]; i=bisect.bisect_right(times,ts(when))-1
    return arr[i][1] if i>=0 else None

def count_between(times,a,b):
    return bisect.bisect_left(times,ts(b))-bisect.bisect_left(times,ts(a))

def empirical_remaining(times, checkpoint, hours, lookback_days=42):
    # Same UTC clock window as the future remaining interval; each sample comes from a prior day.
    h=dt.timedelta(hours=hours); vals=[]
    for days in range(1,lookback_days+1):
        a=checkpoint-dt.timedelta(days=days)
        b=a+h
        if b>checkpoint: continue
        vals.append(count_between(times,a,b))
    return vals

def fee_per_share(p,rate=.04): return rate*p*(1-p)

def main():
    tr=unwrap_data(get('https://xtracker.polymarket.com/api/users/realDonaldTrump/trackings',{'platform':'TRUTH_SOCIAL','activeOnly':'false'})) or []
    closed=[x for x in tr if not x.get('isActive') and x.get('startDate') and x.get('endDate')]
    closed.sort(key=lambda x:x['endDate'])
    if not closed: raise RuntimeError('no closed trackings')
    global_start=min(iso(x['startDate']) for x in closed)-dt.timedelta(days=50)
    global_end=max(iso(x['endDate']) for x in closed)
    raw=unwrap_data(get('https://xtracker.polymarket.com/api/users/realDonaldTrump/posts',{
        'platform':'TRUTH_SOCIAL','startDate':global_start.isoformat(),'endDate':global_end.isoformat()
    })) or []
    if isinstance(raw,dict): raw=raw.get('posts') or raw.get('results') or []
    post_times=sorted(ts(t) for p in raw if (t:=extract_post_time(p)) is not None)
    if len(post_times)<100:
        raise RuntimeError(f'only {len(post_times)} parsed posts; sample keys={list(raw[0]) if raw else []}')

    rows=[]; errors=[]
    horizons=[48,24,12,6]
    for tracking in closed:
        link=tracking.get('marketLink')
        if not link or '/event/' not in link: continue
        slug=link.split('/event/',1)[1].split('?',1)[0].strip('/')
        try: event=get('https://gamma-api.polymarket.com/events/slug/'+slug)
        except Exception as ex:
            errors.append({'slug':slug,'stage':'event','error':repr(ex)}); continue
        markets=event.get('markets') or []
        parsed=[]; tokens=[]
        for m in markets:
            lab=m.get('groupItemTitle') or m.get('question') or ''
            b=bracket(lab); ids=parse_arr(m.get('clobTokenIds')); outs=parse_arr(m.get('outcomePrices'))
            if not b or len(ids)<2: continue
            parsed.append((m,lab,b,ids,outs)); tokens += ids[:2]
        if not parsed: continue
        start,end=iso(tracking['startDate']),iso(tracking['endDate'])
        final_count=count_between(post_times,start,end+dt.timedelta(seconds=2))
        # Pull only the final 3 days at 1m fidelity, where the tested checkpoints live.
        try:
            bh=post('https://clob.polymarket.com/batch-prices-history',{
                'markets':tokens[:20], 'start_ts':ts(end-dt.timedelta(hours=55)),
                'end_ts':ts(end+dt.timedelta(hours=1)), 'interval':'all','fidelity':1
            }).get('history',{})
            if len(tokens)>20:
                bh.update(post('https://clob.polymarket.com/batch-prices-history',{
                    'markets':tokens[20:40], 'start_ts':ts(end-dt.timedelta(hours=55)),
                    'end_ts':ts(end+dt.timedelta(hours=1)), 'interval':'all','fidelity':1
                }).get('history',{}))
        except Exception as ex:
            errors.append({'slug':slug,'stage':'history','error':repr(ex)}); continue

        for h in horizons:
            cp=end-dt.timedelta(hours=h)
            if cp<=start: continue
            observed=count_between(post_times,start,cp)
            rem=empirical_remaining(post_times,cp,h,42)
            if len(rem)<20: continue
            # Laplace-like smoothing: one pseudo-observation spread across all valid brackets.
            n=len(rem)
            candidates=[]
            for m,lab,b,ids,outs in parsed:
                hits=sum(in_bracket(observed+x,b) for x in rem)
                p=(hits+0.5)/(n+1.0)
                py=point_at(bh.get(str(ids[0])) or bh.get(ids[0]) or [],cp)
                pn=point_at(bh.get(str(ids[1])) or bh.get(ids[1]) or [],cp)
                if py is not None:
                    candidates.append({'side':'YES','label':lab,'model_p':p,'raw_price':py,'win':in_bracket(final_count,b)})
                if pn is not None:
                    candidates.append({'side':'NO','label':lab,'model_p':1-p,'raw_price':pn,'win':not in_bracket(final_count,b)})
            for c in candidates:
                # Two sensitivity cases: +2c and +5c above historical price proxy, plus taker fee.
                for buf in (.02,.05):
                    ep=min(.999,c['raw_price']+buf)
                    allin=ep+fee_per_share(ep)
                    edge=c['model_p']-allin
                    c[f'allin_{int(buf*100)}c']=allin
                    c[f'edge_{int(buf*100)}c']=edge
                    c[f'roi_{int(buf*100)}c']=(1.0/allin-1.0) if c['win'] else -1.0
            best=max(candidates,key=lambda z:z.get('edge_2c',-99),default=None)
            if best:
                rows.append({
                    'slug':slug,'title':event.get('title'),'volume':float(event.get('volume') or 0),
                    'end':tracking['endDate'],'hours_before_end':h,'observed':observed,'final_count':final_count,
                    'prior_blocks':len(rem),'prior_mean_remaining':statistics.mean(rem),'prior_sd_remaining':statistics.pstdev(rem),
                    **best
                })

    def summarize(h,buf,thr):
        xs=[r for r in rows if r['hours_before_end']==h and r.get(f'edge_{buf}c',-99)>=thr]
        if not xs: return {'n':0}
        wins=sum(r['win'] for r in xs)
        rois=[r[f'roi_{buf}c'] for r in xs]
        # equal $100 stake per event/checkpoint; ROI equals arithmetic trade ROI.
        return {'n':len(xs),'wins':wins,'win_rate':wins/len(xs),'avg_roi':statistics.mean(rois),
                'median_edge':statistics.median(r[f'edge_{buf}c'] for r in xs),
                'avg_volume':statistics.mean(r['volume'] for r in xs),
                'events':[{'slug':r['slug'],'side':r['side'],'label':r['label'],'edge':r[f'edge_{buf}c'],'raw_price':r['raw_price'],'model_p':r['model_p'],'win':r['win'],'final_count':r['final_count']} for r in xs]}
    summary={}
    for h in horizons:
        for buf in (2,5):
            for thr in (.05,.10,.15): summary[f'h{h}_buf{buf}_edge{int(thr*100)}']=summarize(h,buf,thr)
    out={'method':{
        'model':'exact observed count + empirical distribution of same-horizon remaining post counts from prior 42 same-clock daily windows',
        'chronological':'all empirical windows end at/before each checkpoint; no future posts used',
        'price_proxy':'CLOB prices-history point at/before checkpoint; not historical L2 executable ask',
        'execution_sensitivity':'raw proxy +2c or +5c, then 4% politics taker fee curve',
        'warning':'overlapping 7-day markets create correlated observations; fixed-horizon variants are reported separately'
        },'posts_parsed':len(post_times),'closed_trackings':len(closed),'rows':rows,'summary':summary,'errors':errors}
    with open('xtracker_backtest.json','w') as f: json.dump(out,f,indent=2)
    print(json.dumps({'posts':len(post_times),'closed_trackings':len(closed),'rows':len(rows),'summary':summary,'errors':errors[:5]},indent=2))

if __name__=='__main__': main()
