#!/usr/bin/env python3
"""Test whether official BLS releases left executable stale-price trades on Polymarket.
Uses actual public trade prints, not midpoints. Research-only historical analysis.
"""
import datetime as dt, json, re, statistics, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
UA={'User-Agent':'polymarket-factory-research/1.0'}
ET=ZoneInfo('America/New_York')

def get(url,params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or '[]')
    except:return []
def release_utc(y,m,d): return dt.datetime(y,m,d,8,30,tzinfo=ET).astimezone(dt.timezone.utc)
def fee(p): return .05*p*(1-p) # current Economics fee curve

# Official BLS schedules, current as of research date. Key = reference month number.
CPI={1:(2026,2,13),2:(2026,3,11),3:(2026,4,10),4:(2026,5,12),5:(2026,6,10),6:(2026,7,14),7:(2026,8,12)}
PPI={1:(2026,2,27),2:(2026,3,18),3:(2026,4,14),4:(2026,5,13),5:(2026,6,11),6:(2026,7,15),7:(2026,8,13)}
EMP={1:(2026,2,11),2:(2026,3,6),3:(2026,4,3),4:(2026,5,8),5:(2026,6,5),6:(2026,7,2),7:(2026,8,7)}
MONTHS={1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',7:'July'}

def search_event(q, title_hint):
    r=get('https://gamma-api.polymarket.com/public-search',{'q':q,'events_status':'closed','keep_closed_markets':1,'limit_per_type':25,'search_profiles':'false','search_tags':'false'})
    evs=r.get('events') or []
    exact=[e for e in evs if title_hint.lower()==(e.get('title') or '').lower()]
    if exact:return exact[0]
    # Restrictive token overlap fallback.
    toks=set(re.findall(r'[a-z0-9]+',title_hint.lower()))
    scored=[]
    for e in evs:
        et=set(re.findall(r'[a-z0-9]+',(e.get('title') or '').lower()))
        scored.append((len(toks&et),e))
    scored.sort(key=lambda z:z[0],reverse=True)
    return scored[0][1] if scored and scored[0][0]>=max(2,len(toks)-2) else None

def winner_market(ev):
    for m in ev.get('markets') or []:
        ps=[float(x) for x in arr(m.get('outcomePrices'))]
        if len(ps)>=2 and ps[0]>.99 and ps[1]<.01: return m
    return None

def trade_rows(m, release):
    cond=m.get('conditionId'); ids=arr(m.get('clobTokenIds')); yes=str(ids[0]) if ids else ''
    data=get('https://data-api.polymarket.com/trades',{'market':cond,'limit':10000})
    xs=data if isinstance(data,list) else data.get('data',[])
    out=[]; rts=int(release.timestamp())
    for t in xs:
        try:
            asset=str(t.get('asset') or t.get('asset_id') or '')
            if asset!=yes or str(t.get('side','')).upper()!='BUY':continue
            tt=int(t.get('timestamp') or 0)
            if rts-120<=tt<=rts+600:
                out.append({'delay_s':tt-rts,'price':float(t['price']),'size':float(t['size']),'notional':float(t['price'])*float(t['size'])})
        except:pass
    return sorted(out,key=lambda x:x['delay_s'])

def analyze_event(family,month,event,release):
    m=winner_market(event)
    if not m:return {'family':family,'month':month,'title':event.get('title'),'slug':event.get('slug'),'error':'no resolved YES winner found'}
    tr=trade_rows(m,release)
    res={'family':family,'month':month,'title':event.get('title'),'slug':event.get('slug'),'event_volume':float(event.get('volume') or 0),'winner_label':m.get('groupItemTitle') or m.get('question'),'release_utc':release.isoformat(),'trades_near_release':tr,'conditionId':m.get('conditionId')}
    for gate in (5,15,30,60):
        w=[x for x in tr if gate<=x['delay_s']<=300]
        first=w[0] if w else None
        if first:
            p=first['price']; allin=p+fee(p)+.01
            res[f'gate_{gate}s']={'delay_s':first['delay_s'],'print_price':p,'allin_current_fee_plus1c':allin,'settlement_roi':(1/allin-1) if allin<1 else None,
                'profitable_print_notional_5m':sum(x['notional'] for x in w if x['price']+fee(x['price'])+.01<.99),
                'sub95c_print_notional_5m':sum(x['notional'] for x in w if x['price']<=.95)}
        else:res[f'gate_{gate}s']=None
    return res

def main():
    specs=[]
    for mo,name in MONTHS.items():
        # Core CPI markets existed inconsistently; probe both MoM and YoY, keep what search resolves exactly.
        for suffix in ('MoM','YoY'):
            specs.append(('CPI',mo,f'Core CPI {suffix} - {name} 2026',CPI[mo]))
        specs.append(('PPI',mo,f'PPI YoY - {name} 2026',PPI[mo]))
        specs.append(('UNEMP',mo,f'{name} Unemployment Rate',EMP[mo]))
        specs.append(('JOBS',mo,f'How many jobs added in {name}?',EMP[mo]))
    rows=[]; seen=set(); errors=[]
    for fam,mo,title,date in specs:
        try:
            ev=search_event(title,title)
            if not ev:continue
            # reject obvious wrong country/year matches on fallback
            key=ev.get('slug')
            if key in seen:continue
            et=(ev.get('title') or '').lower()
            if fam in ('CPI','PPI') and MONTHS[mo].lower() not in et:continue
            if fam in ('UNEMP','JOBS') and MONTHS[mo].lower() not in et:continue
            seen.add(key)
            rows.append(analyze_event(fam,mo,ev,release_utc(*date)))
        except Exception as ex: errors.append({'family':fam,'month':mo,'title':title,'error':repr(ex)})
    good=[r for r in rows if not r.get('error')]
    summary={}
    for gate in (5,15,30,60):
        xs=[r for r in good if r.get(f'gate_{gate}s') and r[f'gate_{gate}s']['settlement_roi'] is not None]
        pos=[r for r in xs if r[f'gate_{gate}s']['settlement_roi']>0]
        summary[f'gate_{gate}s']={'events_with_post_release_buy_print':len(xs),'positive_after_current_fee_plus1c':len(pos),
            'median_settlement_roi':statistics.median([r[f'gate_{gate}s']['settlement_roi'] for r in pos]) if pos else None,
            'total_sub95c_print_notional':sum(r[f'gate_{gate}s']['sub95c_print_notional_5m'] for r in pos),
            'events':[{'slug':r['slug'],'family':r['family'],'winner':r['winner_label'],'volume':r['event_volume'],**r[f'gate_{gate}s']} for r in pos]}
    out={'method':{'release_clock':'official BLS release schedules, 08:30 America/New_York','execution_evidence':'actual public Data API BUY prints in the ultimately winning YES token after the scheduled release','economics':'settlement at $1; apply current Economics fee curve 5%*p*(1-p) plus extra 1c adverse-execution buffer','caveat':'a historical trade print proves someone executed there, not that our future order would receive the same fill or size; source publication/parse latency still must be measured live'},'rows':rows,'summary':summary,'errors':errors}
    json.dump(out,open('macro_release_latency.json','w'),indent=2)
    print(json.dumps({'events':len(good),'summary':summary,'errors':errors[:10]},indent=2))
if __name__=='__main__':main()
