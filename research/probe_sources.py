#!/usr/bin/env python3
import json, urllib.parse, urllib.request

UA = {'User-Agent': 'polymarket-factory-research/1.0'}

def get(url, params=None):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def slim_event(e):
    return {
        'id': e.get('id'), 'title': e.get('title'), 'slug': e.get('slug'),
        'startDate': e.get('startDate'), 'endDate': e.get('endDate'),
        'closed': e.get('closed'), 'volume': e.get('volume'),
        'market_count': len(e.get('markets') or []),
        'markets': [
            {k: m.get(k) for k in ['id','question','slug','groupItemTitle','outcomes','outcomePrices','clobTokenIds','volume','closedTime','bestBid','bestAsk','lastTradePrice']}
            for m in (e.get('markets') or [])[:15]
        ]
    }

out = {}
for q in ['Core CPI', 'Consumer Price Index', 'PPI', 'Unemployment Rate', 'Nonfarm Payrolls', 'Price of Dozen Eggs', 'Truth Social posts']:
    try:
        data = get('https://gamma-api.polymarket.com/public-search', {
            'q': q, 'events_status': 'closed', 'keep_closed_markets': 1,
            'limit_per_type': 20, 'search_profiles': 'false', 'search_tags': 'false'
        })
        out['search_'+q] = [slim_event(e) for e in (data.get('events') or [])[:10]]
    except Exception as ex:
        out['search_'+q] = {'error': repr(ex)}

try:
    tr = get('https://xtracker.polymarket.com/api/users/realDonaldTrump/trackings', {
        'platform':'TRUTH_SOCIAL', 'activeOnly':'false'
    })
    out['xtracker_trackings_type'] = type(tr).__name__
    out['xtracker_trackings'] = tr if isinstance(tr, dict) else tr[:20]
except Exception as ex:
    out['xtracker_trackings'] = {'error': repr(ex)}

try:
    u = get('https://xtracker.polymarket.com/api/users/realDonaldTrump', {'platform':'TRUTH_SOCIAL'})
    out['xtracker_user'] = u
except Exception as ex:
    out['xtracker_user'] = {'error': repr(ex)}

with open('probe_output.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: (len(v) if isinstance(v,list) else list(v.keys())[:8] if isinstance(v,dict) else type(v).__name__) for k,v in out.items()}, indent=2))
