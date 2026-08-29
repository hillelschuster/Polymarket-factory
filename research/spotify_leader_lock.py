#!/usr/bin/env python3
"""Polymarket history for annual Top Spotify Artist leader-lock research.
Research only. Reads public Gamma/CLOB data and current books; never trades.
"""
import json, urllib.parse, urllib.request, datetime as dt
UA={'User-Agent':'polymarket-factory-research/1.0'}
def get(url,params=None):
    if params:url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or '[]')
    except:return []
def find_bad_bunny(slug):
    ev=get('https://gamma-api.polymarket.com/events/slug/'+slug)
    for m in ev.get('markets') or []:
        s=((m.get('groupItemTitle') or '')+' '+(m.get('question') or '')).lower()
        if 'bad bunny' in s:
            ids=arr(m.get('clobTokenIds'))
            return ev,m,str(ids[0]) if ids else None
    raise RuntimeError('Bad Bunny market not found')
def book(token):
    try:return get('https://clob.polymarket.com/book',{'token_id':token})
    except Exception as ex:return {'error':repr(ex)}
def best(side):
    xs=[]
    for x in side or []:
        try:xs.append((float(x['price']),float(x['size'])))
        except:pass
    return min(xs) if xs else None
def main():
    ev25,m25,t25=find_bad_bunny('top-spotify-artist-2025-146')
    start=int(dt.datetime(2025,8,4,tzinfo=dt.timezone.utc).timestamp());end=int(dt.datetime(2025,12,5,tzinfo=dt.timezone.utc).timestamp())
    histories={}
    for interval,fid in [('all',60),('1d',60),('1w',60)]:
        try:histories[interval]=get('https://clob.polymarket.com/prices-history',{'market':t25,'startTs':start,'endTs':end,'interval':interval,'fidelity':fid})
        except Exception as ex:histories[interval]={'error':repr(ex)}
    ev26,m26,t26=find_bad_bunny('top-spotify-artist-2026')
    b26=book(t26)
    asks=b26.get('asks') or []; bids=b26.get('bids') or []
    out={'2025':{'event_volume':ev25.get('volume'),'market_volume':m25.get('volume'),'question':m25.get('question'),'token':t25,'history':histories},'2026':{'event_volume':ev26.get('volume'),'market_volume':m26.get('volume'),'question':m26.get('question'),'outcomePrices':m26.get('outcomePrices'),'token':t26,'best_ask':best(asks),'best_bid':max([(float(x['price']),float(x['size'])) for x in bids],default=None),'book':b26}}
    json.dump(out,open('spotify_leader_lock.json','w'),indent=2)
    # compact history: first/last and roughly weekly samples
    h=(histories.get('all') or {}).get('history') or []
    print(json.dumps({'2025_event_volume':ev25.get('volume'),'2025_points':len(h),'first':h[:5],'last':h[-5:],'2026_event_volume':ev26.get('volume'),'2026_best_ask':out['2026']['best_ask'],'2026_best_bid':out['2026']['best_bid']},indent=2))
if __name__=='__main__':main()
