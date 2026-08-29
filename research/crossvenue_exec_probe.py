#!/usr/bin/env python3
"""Current executable Polymarket/Kalshi cross-venue probe for 2028 GOP nominee.
Research only. Reads public APIs; never places orders.
"""
import json, urllib.parse, urllib.request, math
UA={'User-Agent':'polymarket-factory-research/1.0'}
def get(url,params=None):
    if params: url += ('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def arr(v):
    if isinstance(v,list): return v
    try:return json.loads(v or '[]')
    except:return []
def f(x):
    try:return float(x)
    except:return None
def norm(s):return ''.join(c.lower() for c in (s or '') if c.isalnum() or c.isspace()).strip()
def pm_book(token):
    return get('https://clob.polymarket.com/book',{'token_id':token})
def best_ask(book):
    asks=book.get('asks') or []
    if not asks:return None
    xs=[]
    for a in asks:
        p=f(a.get('price')); s=f(a.get('size'))
        if p is not None and s is not None: xs.append((p,s))
    return min(xs) if xs else None
def k_market_candidates():
    j=get('https://api.elections.kalshi.com/trade-api/v2/markets',{'series_ticker':'KXPRESNOMR','limit':100})
    return j.get('markets') or []
def k_orderbook(ticker):
    return get(f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook',{'depth':100})
def k_yes_no_asks(m):
    # Current API typically exposes dollar prices directly. Fall back to cent fields.
    ya=f(m.get('yes_ask_dollars')); na=f(m.get('no_ask_dollars'))
    if ya is None:
        v=f(m.get('yes_ask')); ya=(v/100 if v is not None and v>1 else v)
    if na is None:
        v=f(m.get('no_ask')); na=(v/100 if v is not None and v>1 else v)
    return ya,na
def fee_pm(p):return 0.04*p*(1-p)
def fee_k(p):return 0.07*p*(1-p)
def main():
    ev=get('https://gamma-api.polymarket.com/events/slug/republican-presidential-nominee-2028')
    pms=[]
    for m in ev.get('markets') or []:
        name=m.get('groupItemTitle') or m.get('question') or ''
        ids=arr(m.get('clobTokenIds'))
        if len(ids)<2:continue
        yb=pm_book(str(ids[0])); nb=pm_book(str(ids[1]))
        pms.append({'name':name,'id':m.get('id'),'conditionId':m.get('conditionId'),'question':m.get('question'),'description':m.get('description'),'yes_token':str(ids[0]),'no_token':str(ids[1]),'yes_best_ask':best_ask(yb),'no_best_ask':best_ask(nb),'volume':f(m.get('volume'))})
    kms=k_market_candidates(); ks=[]
    for m in kms:
        name=m.get('yes_sub_title') or m.get('subtitle') or m.get('title') or ''
        ya,na=k_yes_no_asks(m)
        try: ob=k_orderbook(m['ticker'])
        except Exception as ex: ob={'error':repr(ex)}
        ks.append({'name':name,'ticker':m.get('ticker'),'title':m.get('title'),'subtitle':m.get('subtitle'),'yes_sub_title':m.get('yes_sub_title'),'rules_primary':m.get('rules_primary'),'rules_secondary':m.get('rules_secondary'),'yes_ask':ya,'no_ask':na,'yes_bid_dollars':m.get('yes_bid_dollars'),'no_bid_dollars':m.get('no_bid_dollars'),'volume_fp':m.get('volume_fp'),'open_interest_fp':m.get('open_interest_fp'),'orderbook':ob})
    targets=['J.D. Vance','Ron DeSantis','Marco Rubio','Tucker Carlson']
    rows=[]
    for t in targets:
        p=next((x for x in pms if t.lower().replace('.','') in x['name'].lower().replace('.','')),None)
        k=next((x for x in ks if t.lower().replace('.','') in (x['name']+' '+str(x['subtitle'])+' '+str(x['yes_sub_title'])).lower().replace('.','')),None)
        if not p or not k:
            rows.append({'target':t,'error':'match missing','pm_matches':[x['name'] for x in pms],'kalshi_matches':[x['name'] for x in ks]}); continue
        pya=p['yes_best_ask'][0] if p['yes_best_ask'] else None; pna=p['no_best_ask'][0] if p['no_best_ask'] else None
        kya=k['yes_ask']; kna=k['no_ask']
        choices=[]
        if pya is not None and kna is not None:
            gross=1-pya-kna; fees=fee_pm(pya)+fee_k(kna); choices.append({'legs':'PM YES + K NO','pm_ask':pya,'k_ask':kna,'gross_per_share':gross,'est_taker_fees_per_share':fees,'net_before_slippage':gross-fees,'pm_top_size':p['yes_best_ask'][1]})
        if pna is not None and kya is not None:
            gross=1-pna-kya; fees=fee_pm(pna)+fee_k(kya); choices.append({'legs':'PM NO + K YES','pm_ask':pna,'k_ask':kya,'gross_per_share':gross,'est_taker_fees_per_share':fees,'net_before_slippage':gross-fees,'pm_top_size':p['no_best_ask'][1]})
        rows.append({'target':t,'pm':p,'kalshi':{x:k[x] for x in ['name','ticker','title','subtitle','yes_sub_title','rules_primary','rules_secondary','yes_ask','no_ask','volume_fp','open_interest_fp']},'choices':choices})
    out={'note':'Fee estimates use Polymarket Politics taker rate .04 and Kalshi general taker rate .07; verify exact per-market schedules before trading. Prices are actual best asks from public APIs where available, not midpoint aggregator prices. No orders placed.','rows':rows}
    json.dump(out,open('crossvenue_exec_probe.json','w'),indent=2)
    compact=[]
    for r in rows:
        if 'choices' in r: compact.append({'target':r['target'],'pm_yes':r['pm']['yes_best_ask'],'pm_no':r['pm']['no_best_ask'],'k_yes':r['kalshi']['yes_ask'],'k_no':r['kalshi']['no_ask'],'choices':r['choices']})
        else: compact.append(r)
    print(json.dumps(compact,indent=2))
if __name__=='__main__':main()
