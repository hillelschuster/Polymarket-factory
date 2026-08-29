#!/usr/bin/env python3
"""Minute-level Kalshi vs Polymarket FOMC reaction around Warsh 2026-08-28 10:00 ET speech.
Research only. Uses public historical market data; does not trade.
"""
import datetime as dt, json, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
UA={'User-Agent':'polymarket-factory-research/1.0'}
ET=ZoneInfo('America/New_York')
def get(url, params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def post(url,payload):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={**UA,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list): return v
    try:return json.loads(v or '[]')
    except:return []
def fv(x):
    if x is None:return None
    try:return float(x)
    except:return None

def main():
    start=int(dt.datetime(2026,8,28,9,45,tzinfo=ET).timestamp())
    end=int(dt.datetime(2026,8,28,11,30,tzinfo=ET).timestamp())
    speech=int(dt.datetime(2026,8,28,10,0,tzinfo=ET).timestamp())
    out={'window':{'start':start,'speech':speech,'end':end},'kalshi':{},'polymarket':{}}
    # Exact Kalshi 25bp-hike market ticker observed from public market URL/search data.
    candidates=['KXFEDDECISION-26SEP-H2','KXFEDDECISION-26SEP-H25','KXFEDDECISION-26SEP-HIKE25']
    for ticker in candidates:
        try:
            meta=get('https://api.elections.kalshi.com/trade-api/v2/markets/'+ticker)
            out['kalshi']['ticker']=ticker; out['kalshi']['meta']=meta
            try:
                candles=get(f'https://api.elections.kalshi.com/trade-api/v2/series/KXFEDDECISION/markets/{ticker}/candlesticks',{'start_ts':start,'end_ts':end,'period_interval':1})
            except Exception:
                candles=get(f'https://external-api.kalshi.com/trade-api/v2/series/KXFEDDECISION/markets/{ticker}/candlesticks',{'start_ts':start,'end_ts':end,'period_interval':1})
            out['kalshi']['candlesticks']=candles.get('candlesticks',candles)
            break
        except Exception as ex:
            out['kalshi'].setdefault('candidate_errors',[]).append({'ticker':ticker,'error':repr(ex)})
    # Polymarket exact +25bp YES token.
    ev=get('https://gamma-api.polymarket.com/events/slug/fed-decision-in-september-762')
    target=None
    for m in ev.get('markets') or []:
        title=(m.get('groupItemTitle') or m.get('question') or '').lower()
        if '25' in title and ('increase' in title or 'hike' in title) and not ('50' in title or 'decrease' in title):
            ids=arr(m.get('clobTokenIds'))
            if ids: target=(m,str(ids[0])); break
    if not target: raise RuntimeError('Polymarket +25bp token not found')
    m,token=target
    out['polymarket']['token']=token; out['polymarket']['market']={k:m.get(k) for k in ['id','question','groupItemTitle','slug','outcomePrices','volume']}
    try:
        h=post('https://clob.polymarket.com/batch-prices-history',{'markets':[token],'start_ts':start,'end_ts':end,'interval':'all','fidelity':1}).get('history',{})
        out['polymarket']['price_history']=h.get(token) or h.get(str(token)) or []
    except Exception as ex: out['polymarket']['price_history_error']=repr(ex)
    # Public matched trade prints in window for same token.
    try:
        trades=get('https://data-api.polymarket.com/trades',{'asset_id':token,'limit':1000,'offset':0})
        if isinstance(trades,dict): trades=trades.get('data') or trades.get('trades') or []
        out['polymarket']['trades']=[t for t in trades if start <= int(t.get('timestamp',0)) <= end]
    except Exception as ex: out['polymarket']['trades_error']=repr(ex)
    # Compact comparable minute series.
    kc=[]
    for c in out['kalshi'].get('candlesticks') or []:
        ts=int(c.get('end_period_ts') or 0)
        p=c.get('price') or {}; bid=c.get('yes_bid') or {}; ask=c.get('yes_ask') or {}
        kc.append({'t':ts,'price_close':fv(p.get('close_dollars') or p.get('close')),'bid_close':fv(bid.get('close_dollars') or bid.get('close')),'ask_close':fv(ask.get('close_dollars') or ask.get('close')),'volume':fv(c.get('volume_fp') or c.get('volume'))})
    pp=sorted([{'t':int(x['t']),'p':float(x['p'])} for x in out['polymarket'].get('price_history') or [] if 't' in x and 'p' in x],key=lambda x:x['t'])
    out['compact']={'kalshi':kc,'polymarket':pp}
    json.dump(out,open('fomc_crossvenue_warsh.json','w'),indent=2)
    print(json.dumps({'kalshi_ticker':out['kalshi'].get('ticker'),'kalshi_points':len(kc),'poly_points':len(pp),'poly_trades':len(out['polymarket'].get('trades') or []),'errors':out['kalshi'].get('candidate_errors')},indent=2))
if __name__=='__main__':main()
