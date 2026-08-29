#!/usr/bin/env python3
"""Independent CLOB-timestamp robustness check for macro release latency.

The Data API timestamp is potentially on-chain settlement time. This test therefore
uses the CLOB price-history clock, sampled at 1-minute fidelity, and also probes the
new orderbook-history endpoint when available. It asks a weaker but cleaner question:
did the ultimately winning token remain materially below $1 at CLOB timestamps at
least 1/2/5 minutes after the scheduled official release?
"""
import datetime as dt, json, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
UA={'User-Agent':'polymarket-factory-research/1.0'}; ET=ZoneInfo('America/New_York')

def get(url,params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list): return v
    try:return json.loads(v or '[]')
    except:return []
def rel(y,m,d):return dt.datetime(y,m,d,8,30,tzinfo=ET).astimezone(dt.timezone.utc)
CPI={5:(2026,6,10),6:(2026,7,14),7:(2026,8,12)}
PPI={5:(2026,6,11),6:(2026,7,15),7:(2026,8,13)}
EMP={1:(2026,2,11),2:(2026,3,6),3:(2026,4,3),4:(2026,5,8),5:(2026,6,5),6:(2026,7,2),7:(2026,8,7)}
# Exact verified 2026 slugs only; excludes fuzzy/wrong-year matches.
SPECS=[
('JOBS',1,'how-many-jobs-added-in-january-321'),('UNEMP',2,'february-unemployment-rate'),('UNEMP',3,'march-unemployment-rate-561'),
('UNEMP',4,'april-unemployment-rate-372'),('JOBS',4,'how-many-jobs-added-in-april'),
('CPI',5,'core-cpi-ex-food-and-energy-mom-may'),('CPI',5,'core-cpi-yoy-may-2026'),('PPI',5,'producer-price-index-ppi-yoy-may-2026'),
('UNEMP',5,'may-unemployment-rate-168'),('JOBS',5,'how-many-jobs-added-in-may-698'),
('CPI',6,'core-cpi-yoy-june-2026-20260610150514590'),('PPI',6,'ppi-yoy-june-2026-20260702034336684'),('UNEMP',6,'june-unemployment-rate-734'),('JOBS',6,'how-many-jobs-added-in-june'),
('CPI',7,'core-cpi-mom-july-2026-20260705181328287'),('CPI',7,'core-cpi-yoy-july-2026-20260714151811920'),('PPI',7,'ppi-yoy-july-2026-20260715201412025'),
('UNEMP',7,'july-unemployment-rate-20260702221240753'),('JOBS',7,'how-many-jobs-added-in-july-453')]

def winner(ev):
    for m in ev.get('markets') or []:
        ps=[float(x) for x in arr(m.get('outcomePrices'))]
        ids=arr(m.get('clobTokenIds'))
        if len(ps)>=2 and len(ids)>=2 and ps[0]>.99:return m,str(ids[0])
    return None,None

def first_after(hist,t):
    xs=sorted((int(x['t']),float(x['p'])) for x in hist if 't'in x and 'p'in x)
    for a,p in xs:
        if a>=t:return {'t':a,'delay_s':a-t,'p':p}
    return None

def main():
    rows=[]; errors=[]
    for fam,mo,slug in SPECS:
        try:
            ev=get('https://gamma-api.polymarket.com/events/slug/'+slug); m,token=winner(ev)
            if not m:raise RuntimeError('winner token not found')
            date=(CPI if fam=='CPI' else PPI if fam=='PPI' else EMP)[mo]; release=rel(*date); rt=int(release.timestamp())
            ph=get('https://clob.polymarket.com/prices-history',{'market':token,'startTs':rt-180,'endTs':rt+660,'interval':'all','fidelity':1}).get('history',[])
            rec={'family':fam,'month':mo,'slug':slug,'title':ev.get('title'),'volume':float(ev.get('volume') or 0),'winner':m.get('groupItemTitle') or m.get('question'),'release':release.isoformat(),'token':token,'history':ph}
            for mins in (1,2,5):rec[f'first_after_{mins}m']=first_after(ph,rt+60*mins)
            # Optional endpoint probe. Do not fail the experiment if unavailable/undocumented.
            try:
                rec['orderbook_history_probe']=get('https://clob.polymarket.com/orderbook-history',{'asset_id':token,'startTs':rt-60,'endTs':rt+300,'fidelity':'1m','limit':20})
            except Exception as ex:rec['orderbook_history_probe_error']=repr(ex)
            rows.append(rec)
        except Exception as ex:errors.append({'slug':slug,'error':repr(ex)})
    summary={}
    for mins in (1,2,5):
        xs=[r for r in rows if r.get(f'first_after_{mins}m')]
        stale=[r for r in xs if r[f'first_after_{mins}m']['p']<=.95]
        severe=[r for r in xs if r[f'first_after_{mins}m']['p']<=.90]
        summary[f'{mins}m']={'events_with_point':len(xs),'winner_price_le_95c':len(stale),'winner_price_le_90c':len(severe),'events':[{'slug':r['slug'],'family':r['family'],'winner':r['winner'],'volume':r['volume'],**r[f'first_after_{mins}m']} for r in stale]}
    out={'method':{'clock':'CLOB prices-history timestamps; 1-minute fidelity','test':'first sampled winning-token price at/after release+1/2/5 minutes','strength':'cleaner clock than Data API on-chain timestamps, but price-history is not historical executable L2 depth'},'rows':rows,'summary':summary,'errors':errors}
    json.dump(out,open('macro_clob_robustness.json','w'),indent=2); print(json.dumps({'summary':summary,'errors':errors},indent=2))
if __name__=='__main__':main()
