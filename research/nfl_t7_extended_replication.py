#!/usr/bin/env python3
"""Extended clean NFL T-7 replication across seasons.

Pre-declared primary cell: moneyline first outcome, T-7d price 0.55-0.60,
market lifespan <=14d. Uses explicit game clock, last historical price at/before
anchor (<=24h stale), never a centered/future VWAP. Later anchors are only
mark-to-market diagnostics, not executable historical quote proof.
"""
from __future__ import annotations
import datetime as dt,json,statistics,sys
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import sports_flb_independent_check as base

OUT=Path("nfl_t7_extended_replication.json")
base.CUTOFF_TS=int(dt.datetime(2023,1,1,tzinfo=dt.timezone.utc).timestamp())
base.MAX_EVENTS_PER_SPORT=1400;base.MIN_VOL=500.0
ANCHORS=(7,3,1,0.25,1/24)
BUCKETS=((.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,.80),(.80,.90))

def season(ts):
    d=dt.datetime.fromtimestamp(ts,tz=dt.timezone.utc);return d.year-1 if d.month<=2 else d.year

def table(rows):
    z=[]
    for lo,hi in BUCKETS:
        xs=[r for r in rows if lo<=r['price']<hi]
        if not xs:z.append({'bucket':[lo,hi],'n':0});continue
        n=len(xs);k=sum(r['resolved_first'] for r in xs);mp=statistics.mean(r['price'] for r in xs);wr=k/n
        z.append({'bucket':[lo,hi],'n':n,'wins':k,'mean_price':mp,'realized_first_rate':wr,
                  'calibration_pp':100*(wr-mp),'wilson95':list(base.wilson(k,n))})
    return z

def main():
    errors=[];meta=base.get('https://gamma-api.polymarket.com/sports')
    nfl=next((x for x in meta if str(x.get('sport') or '').lower()=='nfl'),None)
    if not nfl:raise SystemExit('NFL metadata missing')
    events,errs,key,val=base.fetch_league('nfl',nfl);errors.extend(errs)
    # fetch_league is newest-first; apply explicit 2023 cutoff client-side.
    events=[e for e in events if (base.ts(e.get('endDate')) or base.ts(e.get('closedTime')) or 0)>=base.CUTOFF_TS]
    events=list({str(e.get('id') or e.get('slug')):e for e in events}.values())
    cand=[]
    for e in events:
        for m in e.get('markets') or []:
            if str(m.get('sportsMarketType') or '').lower()!='moneyline' or base.fnum(m.get('volume'))<base.MIN_VOL:continue
            y=base.result_yes(m);tok=base.token_yes(m);gs,gf=base.clock(e,m);cr,cf=base.created(e,m)
            if y is None or not tok or not gs or not cr or cr>gs:continue
            outs=base.jl(m.get('outcomes'))
            cand.append({'event_id':e.get('id'),'event_slug':e.get('slug'),'event_title':e.get('title'),
                'market_id':m.get('id'),'condition_id':m.get('conditionId'),'question':m.get('question'),
                'first_outcome':outs[0] if outs else None,'second_outcome':outs[1] if len(outs)>1 else None,
                'market_volume':base.fnum(m.get('volume')),'token':tok,'resolved_first':y,'game_start':gs,
                'clock_field':gf,'creation':cr,'creation_field':cf,'lifespan_days':(gs-cr)/86400,'season':season(gs)})
    by={a:[] for a in ANCHORS};pe=[]
    for r in cand:
        for a in ANCHORS:
            target=int(r['game_start']-a*86400)
            if r['creation']>target:continue
            p,err=base.price_before(r['token'],target)
            if err:
                if len(pe)<150:pe.append({'event_id':r['event_id'],'anchor_days':a,**err})
                continue
            by[a].append({**r,'anchor_days':a,'target_ts':target,**p})
    tabs={}
    for a,rows in by.items():
        strict=[r for r in rows if r['lifespan_days']<=14]
        tabs[str(a)]={'n':len(rows),'n_strict':len(strict),'strict':table(strict),
            'by_season':{str(s):table([r for r in strict if r['season']==s]) for s in sorted({r['season'] for r in strict})}}
    primary=[r for r in by[7] if r['lifespan_days']<=14 and .55<=r['price']<.60]
    n=len(primary);k=sum(r['resolved_first'] for r in primary);mp=statistics.mean([r['price'] for r in primary]) if primary else None
    psummary={'n':n,'wins':k,'mean_price':mp,'realized_first_rate':k/n if n else None,
        'calibration_pp':100*(k/n-mp) if n else None,'wilson95':list(base.wilson(k,n)) if n else [None,None],
        'unique_events':len({r['event_id'] for r in primary}),'by_season':{}}
    for s in sorted({r['season'] for r in primary}):
        xs=[r for r in primary if r['season']==s];kk=sum(r['resolved_first'] for r in xs);mm=statistics.mean(r['price'] for r in xs)
        psummary['by_season'][str(s)]={'n':len(xs),'wins':kk,'mean_price':mm,'realized_first_rate':kk/len(xs),
            'calibration_pp':100*(kk/len(xs)-mm)}
    lookup={(r['event_id'],a):r for a,rows in by.items() for r in rows};paths=[]
    for r in primary:
        p={'event_id':r['event_id'],'event_slug':r['event_slug'],'question':r['question'],'season':r['season'],
           'first_outcome':r['first_outcome'],'second_outcome':r['second_outcome'],'resolved_first':r['resolved_first'],
           't7':r['price'],'lifespan_days':r['lifespan_days'],'clock_field':r['clock_field']}
        for a,label in ((3,'t3'),(1,'t1'),(.25,'t6h'),(1/24,'t1h')):
            q=lookup.get((r['event_id'],a));p[label]=q['price'] if q else None;p[label+'_change_from_t7']=(q['price']-r['price']) if q else None
        paths.append(p)
    pathsum={}
    for label in ('t3','t1','t6h','t1h'):
        xs=[p[label+'_change_from_t7'] for p in paths if p.get(label) is not None]
        if xs:pathsum[label]={'n':len(xs),'mean_price_change':statistics.mean(xs),'median_price_change':statistics.median(xs),
            'share_positive':sum(x>0 for x in xs)/len(xs)}
    out={'method':{'cutoff':'2023-01-01','selector':key,'selector_value':val,'market_type':'moneyline',
         'clock':'gameStartTime/eventStartTime preferred','price':'last print at/before anchor <=24h stale','future_vwap':False,
         'primary':'T-7d 0.55-0.60 lifespan<=14d','execution_warning':'historical prices are not executable ask/depth proof'},
         'inventory':{'events':len(events),'candidates':len(cand),'clock_fields':dict(Counter(r['clock_field'] for r in cand)),
                      'seasons':dict(Counter(r['season'] for r in cand))},
         'primary':psummary,'anchor_tables':tabs,'primary_paths':paths,'path_summary':pathsum,
         'price_error_sample':pe,'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'inventory':out['inventory'],'primary':psummary,'path_summary':pathsum,
      'anchor_n':{str(a):tabs[str(a)]['n_strict'] for a in ANCHORS},'errors':errors[:5]},indent=2))
if __name__=='__main__':main()
