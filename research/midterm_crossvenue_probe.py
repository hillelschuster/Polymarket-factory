#!/usr/bin/env python3
"""Executable Polymarket/Kalshi cross-venue probe for Blue Wave/Tsunami midterm pairs.
Research only; reads public APIs, never places orders.
"""
import json, urllib.parse, urllib.request, datetime as dt
from zoneinfo import ZoneInfo
UA={'User-Agent':'polymarket-factory-research/1.0'}
def get(url,params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or '[]')
    except:return []
def fl(x):
    try:return float(x)
    except:return None
def best_ask(token):
    b=get('https://clob.polymarket.com/book',{'token_id':token}); xs=[]
    for a in b.get('asks') or []:
        p=fl(a.get('price'));s=fl(a.get('size'))
        if p is not None and s is not None:xs.append((p,s))
    return min(xs) if xs else None
def fee_pm(p):return .04*p*(1-p)
def fee_k(p):return .07*p*(1-p)
def kprice(m,key):
    x=fl(m.get(key+'_dollars'))
    if x is not None:return x
    x=fl(m.get(key)); return x/100 if x is not None and x>1 else x
def kalshi_market(series):
    ms=get('https://api.elections.kalshi.com/trade-api/v2/markets',{'series_ticker':series,'limit':100}).get('markets') or []
    return next((m for m in ms if m.get('status') in ('active','open')),ms[0] if ms else None)
def hist_sources(token,condition,start,end):
    out={}
    for name,url,params in [
        ('ohlc','https://clob.polymarket.com/ohlc',{'asset_id':token,'startTs':start,'endTs':end,'fidelity':'1m','limit':1000}),
        ('orderbook','https://clob.polymarket.com/orderbook-history',{'asset_id':token,'startTs':start,'endTs':end,'fidelity':'1m','limit':1000}),
        ('price','https://clob.polymarket.com/prices-history',{'market':token,'startTs':start,'endTs':end,'interval':'all','fidelity':1}),
    ]:
        try:out[name]=get(url,params)
        except Exception as ex:out[name+'_error']=repr(ex)
    return out
def one(label,pslug,kseries):
    ev=get('https://gamma-api.polymarket.com/events/slug/'+pslug)
    # These are one binary market each; choose first market.
    m=(ev.get('markets') or [None])[0]
    if not m:raise RuntimeError('PM market missing')
    ids=arr(m.get('clobTokenIds')); assert len(ids)>=2
    pya=best_ask(str(ids[0])); pna=best_ask(str(ids[1]))
    km=kalshi_market(kseries)
    if not km:raise RuntimeError('Kalshi market missing')
    kya=kprice(km,'yes_ask'); kna=kprice(km,'no_ask')
    choices=[]
    if pya and kna is not None:
        gross=1-pya[0]-kna; fees=fee_pm(pya[0])+fee_k(kna)
        choices.append({'legs':'PM YES + K NO','pm_ask':pya[0],'pm_size':pya[1],'k_ask':kna,'gross':gross,'fees_est':fees,'net_before_slippage':gross-fees})
    if pna and kya is not None:
        gross=1-pna[0]-kya; fees=fee_pm(pna[0])+fee_k(kya)
        choices.append({'legs':'PM NO + K YES','pm_ask':pna[0],'pm_size':pna[1],'k_ask':kya,'gross':gross,'fees_est':fees,'net_before_slippage':gross-fees})
    start=int(dt.datetime(2026,8,28,0,0,tzinfo=dt.timezone.utc).timestamp());end=int(dt.datetime(2026,8,29,12,0,tzinfo=dt.timezone.utc).timestamp())
    kh={}
    try:kh=get(f'https://api.elections.kalshi.com/trade-api/v2/series/{kseries}/markets/{km["ticker"]}/candlesticks',{'start_ts':start,'end_ts':end,'period_interval':1})
    except Exception as ex:kh={'error':repr(ex)}
    return {'label':label,'pm':{'title':ev.get('title'),'question':m.get('question'),'description':m.get('description'),'conditionId':m.get('conditionId'),'yes_ask':pya,'no_ask':pna,'volume':m.get('volume')},'kalshi':{'ticker':km.get('ticker'),'title':km.get('title'),'subtitle':km.get('subtitle'),'yes_sub_title':km.get('yes_sub_title'),'rules_primary':km.get('rules_primary'),'rules_secondary':km.get('rules_secondary'),'yes_ask':kya,'no_ask':kna,'volume_fp':km.get('volume_fp'),'open_interest_fp':km.get('open_interest_fp')},'choices':choices,'pm_history':hist_sources(str(ids[0]),m.get('conditionId'),start,end),'kalshi_candles':kh.get('candlesticks',kh)}
def main():
    rows=[]
    for spec in [('blue_wave','blue-wave-in-2026','KXBLUEWAVECOMBO'),('blue_tsunami','blue-tsunami-in-2026','KXBLUETSUNAMICOMBO')]:
        try:rows.append(one(*spec))
        except Exception as ex:rows.append({'label':spec[0],'error':repr(ex)})
    out={'note':'Current PM prices use actual best asks from CLOB. Kalshi asks use market API. Fees estimated with PM politics .04 and Kalshi general .07; exact per-market fee schedules still require verification. Historical sources are diagnostic and may have retention/sampling caveats.','rows':rows}
    json.dump(out,open('midterm_crossvenue_probe.json','w'),indent=2)
    print(json.dumps([{'label':r.get('label'),'error':r.get('error'),'pm_yes':r.get('pm',{}).get('yes_ask'),'pm_no':r.get('pm',{}).get('no_ask'),'k_yes':r.get('kalshi',{}).get('yes_ask'),'k_no':r.get('kalshi',{}).get('no_ask'),'choices':r.get('choices'),'pm_hist_errors':{k:v for k,v in r.get('pm_history',{}).items() if k.endswith('_error')},'k_candles_n':len(r.get('kalshi_candles') or []) if isinstance(r.get('kalshi_candles'),list) else None} for r in rows],indent=2))
if __name__=='__main__':main()
