#!/usr/bin/env python3
import datetime as dt, json, statistics, urllib.parse, urllib.request
UA={'User-Agent':'polymarket-factory-research/1.0'}

def get(url,params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r: return json.load(r)
def iso(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def arr(v):
    if isinstance(v,list): return v
    try:return json.loads(v or '[]')
    except:return []
def fee(p): return .04*p*(1-p)

d=json.load(open('xtracker_backtest.json'))
rows=[r for r in d['rows'] if r['hours_before_end'] in (12,6)]
out=[]; mismatches=[]; errors=[]
for r in rows:
    try:
        ev=get('https://gamma-api.polymarket.com/events/slug/'+r['slug'])
        m=next((m for m in ev.get('markets',[]) if (m.get('groupItemTitle') or m.get('question') or '')==r['label']),None)
        if not m: raise RuntimeError('label market not found')
        prices=[float(x) for x in arr(m.get('outcomePrices'))]
        resolved_yes=(len(prices)>=2 and prices[0]>.99)
        if resolved_yes != bool(r['win'] if r['side']=='YES' else not r['win']):
            mismatches.append({'slug':r['slug'],'label':r['label'],'side':r['side'],'final_count':r['final_count'],'script_win':r['win'],'gamma_yes':resolved_yes})
        ids=arr(m.get('clobTokenIds')); asset=str(ids[0 if r['side']=='YES' else 1])
        cond=m.get('conditionId')
        cp=iso(r['end'])-dt.timedelta(hours=r['hours_before_end'])
        trades=get('https://data-api.polymarket.com/trades',{'market':cond,'limit':10000})
        # The public Data API reports trade timestamp/asset/side/size/price.
        relevant=[]
        for t in trades if isinstance(trades,list) else trades.get('data',[]):
            try:
                tt=int(t.get('timestamp') or 0); a=str(t.get('asset') or t.get('asset_id') or '')
                if a!=asset or str(t.get('side','')).upper()!='BUY': continue
                if int(cp.timestamp())+30 <= tt <= int(cp.timestamp())+300:
                    relevant.append(t)
            except: pass
        relevant.sort(key=lambda t:int(t.get('timestamp') or 0))
        first=relevant[0] if relevant else None
        entry=float(first['price']) if first else None
        allin=(entry+fee(entry)+.01) if entry is not None else None # additional 1c adverse buffer
        actual_edge=r['model_p']-allin if allin is not None else None
        roi=((1/allin-1) if r['win'] else -1) if allin and allin<1 else None
        # Observed executed BUY notional in 30s..5m window at prices that still leave >=10c model edge after fee+1c.
        cap=0.0; shares=0.0
        for t in relevant:
            p=float(t['price']); sz=float(t['size']); ai=p+fee(p)+.01
            if r['model_p']-ai>=.10:
                cap += p*sz; shares += sz
        out.append({**r,'conditionId':cond,'asset':asset,'gamma_resolved_yes':resolved_yes,'buy_trades_30s_5m':len(relevant),'first_buy_price':entry,'trade_allin_plus1c':allin,'trade_edge':actual_edge,'trade_roi':roi,'qualifying_print_notional':cap,'qualifying_print_shares':shares})
    except Exception as ex: errors.append({'slug':r['slug'],'label':r['label'],'error':repr(ex)})

def eligible(rs): return [x for x in rs if x.get('trade_edge') is not None and x['trade_edge']>=.10]
def nonoverlap(rs):
    # Greedy earliest-end selection, at most one 7-day tracking per non-overlapping block.
    a=sorted(rs,key=lambda x:x['end']); keep=[]; last_start=None
    # select backwards so each retained tracking ends before the next begins
    next_start=None
    for x in reversed(a):
        end=iso(x['end']); start=end-dt.timedelta(days=7)
        if next_start is None or end<=next_start:
            keep.append(x); next_start=start
    return list(reversed(keep))
def summ(rs):
    if not rs:return {'n':0}
    return {'n':len(rs),'wins':sum(x['win'] for x in rs),'win_rate':sum(x['win'] for x in rs)/len(rs),
            'avg_roi':statistics.mean(x['trade_roi'] for x in rs),'median_edge':statistics.median(x['trade_edge'] for x in rs),
            'total_observed_qualifying_print_notional':sum(x['qualifying_print_notional'] for x in rs),
            'median_observed_qualifying_print_notional':statistics.median(x['qualifying_print_notional'] for x in rs),
            'recent_n':sum(iso(x['end'])>=dt.datetime(2026,6,1,tzinfo=dt.timezone.utc) for x in rs),
            'recent_wins':sum(x['win'] for x in rs if iso(x['end'])>=dt.datetime(2026,6,1,tzinfo=dt.timezone.utc))}
summary={}
for h in (12,6):
    rs=eligible([x for x in out if x['hours_before_end']==h])
    summary[f'h{h}_actualprints_edge10']=summ(rs)
    summary[f'h{h}_nonoverlap']=summ(nonoverlap(rs))
    summary[f'h{h}_recent_since_june']=summ([x for x in rs if iso(x['end'])>=dt.datetime(2026,6,1,tzinfo=dt.timezone.utc)])
res={'method':{'actual_print_gate':'first public Data API BUY of selected token from +30s to +5m after checkpoint','entry':'first BUY print + current politics fee curve + additional 1c adverse buffer','qualification':'model probability minus all-in >=10c','capacity_proxy':'actual BUY notional printed in same 30s..5m window at prices preserving >=10c model edge; NOT guaranteed available depth'},'resolution_mismatches':mismatches,'rows':out,'summary':summary,'errors':errors}
json.dump(res,open('xtracker_audit.json','w'),indent=2)
print(json.dumps({'mismatches':mismatches[:10],'mismatch_n':len(mismatches),'errors_n':len(errors),'summary':summary},indent=2))
