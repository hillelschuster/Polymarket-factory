#!/usr/bin/env python3
"""Current executable Polymarket/Kalshi cross-venue probe for 2028 GOP nominee.
Research only. Reads public APIs; never places orders.
"""
import json, urllib.parse, urllib.request
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
def pm_book(token):
    try:return get('https://clob.polymarket.com/book',{'token_id':token})
    except Exception:return {}
def best_ask(book):
    xs=[]
    for a in book.get('asks') or []:
        p=f(a.get('price')); s=f(a.get('size'))
        if p is not None and s is not None: xs.append((p,s))
    return min(xs) if xs else None
def k_market_candidates():return get('https://api.elections.kalshi.com/trade-api/v2/markets',{'series_ticker':'KXPRESNOMR','limit':100}).get('markets') or []
def k_yes_no_asks(m):
    ya=f(m.get('yes_ask_dollars')); na=f(m.get('no_ask_dollars'))
    if ya is None:
        v=f(m.get('yes_ask')); ya=(v/100 if v is not None and v>1 else v)
    if na is None:
        v=f(m.get('no_ask')); na=(v/100 if v is not None and v>1 else v)
    return ya,na
def fee_pm(p):return .04*p*(1-p)
def fee_k(p):return .07*p*(1-p)
def main():
    ev=get('https://gamma-api.polymarket.com/events/slug/republican-presidential-nominee-2028')
    pms=[]
    for m in ev.get('markets') or []:
        ids=arr(m.get('clobTokenIds'))
        if len(ids)<2:continue
        yb=pm_book(str(ids[0])); nb=pm_book(str(ids[1]))
        ya,na=best_ask(yb),best_ask(nb)
        if ya is None and na is None:continue
        pms.append({'name':m.get('groupItemTitle') or m.get('question') or '','id':m.get('id'),'conditionId':m.get('conditionId'),'question':m.get('question'),'description':m.get('description'),'yes_best_ask':ya,'no_best_ask':na,'volume':f(m.get('volume'))})
    ks=[]
    for m in k_market_candidates():
        ya,na=k_yes_no_asks(m)
        ks.append({'name':m.get('yes_sub_title') or m.get('subtitle') or m.get('title') or '','ticker':m.get('ticker'),'title':m.get('title'),'subtitle':m.get('subtitle'),'yes_sub_title':m.get('yes_sub_title'),'rules_primary':m.get('rules_primary'),'rules_secondary':m.get('rules_secondary'),'yes_ask':ya,'no_ask':na,'volume_fp':m.get('volume_fp'),'open_interest_fp':m.get('open_interest_fp')})
    rows=[]
    for t in ['J.D. Vance','Ron DeSantis','Marco Rubio','Tucker Carlson']:
        key=t.lower().replace('.','')
        p=next((x for x in pms if key in x['name'].lower().replace('.','')),None)
        k=next((x for x in ks if key in (x['name']+' '+str(x['subtitle'])+' '+str(x['yes_sub_title'])).lower().replace('.','')),None)
        if not p or not k:
            rows.append({'target':t,'error':'match missing'});continue
        pya=p['yes_best_ask'][0] if p['yes_best_ask'] else None;pna=p['no_best_ask'][0] if p['no_best_ask'] else None;kya=k['yes_ask'];kna=k['no_ask'];choices=[]
        if pya is not None and kna is not None:
            gross=1-pya-kna;fees=fee_pm(pya)+fee_k(kna);choices.append({'legs':'PM YES + K NO','gross':gross,'fees_est':fees,'net_before_slippage':gross-fees,'pm_top_size':p['yes_best_ask'][1]})
        if pna is not None and kya is not None:
            gross=1-pna-kya;fees=fee_pm(pna)+fee_k(kya);choices.append({'legs':'PM NO + K YES','gross':gross,'fees_est':fees,'net_before_slippage':gross-fees,'pm_top_size':p['no_best_ask'][1]})
        rows.append({'target':t,'pm':p,'kalshi':k,'choices':choices})
    json.dump({'rows':rows},open('crossvenue_exec_probe.json','w'),indent=2)
    print(json.dumps([{'target':r.get('target'),'error':r.get('error'),'pm_yes':r.get('pm',{}).get('yes_best_ask'),'pm_no':r.get('pm',{}).get('no_best_ask'),'k_yes':r.get('kalshi',{}).get('yes_ask'),'k_no':r.get('kalshi',{}).get('no_ask'),'choices':r.get('choices')} for r in rows],indent=2))
if __name__=='__main__':main()
