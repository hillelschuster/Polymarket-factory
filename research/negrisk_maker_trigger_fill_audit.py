#!/usr/bin/env python3
"""Recent-fill audit for maker-triggered converter setups.

Runs after `negrisk_maker_triggered_converter.py`. For each unique proposed maker
NO quote, reconstruct recent public taker trades in NO-price coordinates and count
SELL trades at/below the proposed bid — trades that could have filled a resting
NO bid at that price (ignoring queue priority).

This answers the key question for passive converter catchers: is the conditional
edge merely enormous because the quote is so far from flow that it never fills?
No orders are placed.
"""
from __future__ import annotations
import datetime as dt,json,time,urllib.parse,urllib.request
from pathlib import Path
SRC=Path('negrisk_maker_triggered_converter.json');OUT=Path('negrisk_maker_trigger_fill_audit.json')
UA={'User-Agent':'polymarket-factory-research/1.0'};GAMMA='https://gamma-api.polymarket.com';DATA='https://data-api.polymarket.com/trades'

def req(url,params=None):
    if params:url+=('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.load(r)
def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []
def gamma(cid):
    xs=req(GAMMA+'/markets',{'condition_ids':cid,'limit':3});ys=[x for x in xs if str(x.get('conditionId') or '').lower()==cid.lower()]
    return ys[0] if len(ys)==1 else None
def tape(cid):
    out=[];off=0
    while off<=9500:
        xs=req(DATA,{'market':cid,'takerOnly':'true','limit':500,'offset':off})
        if not isinstance(xs,list) or not xs:break
        out.extend(xs)
        if len(xs)<500:break
        off+=500;time.sleep(.02)
    return out
def norm_no(x,outs):
    try:
        oi=int(x.get('outcomeIndex'));p=float(x['price']);side=str(x.get('side') or '').upper();sz=float(x.get('size') or 0);t=int(x.get('timestamp') or 0)
        ni=next(i for i,o in enumerate(outs) if o.casefold()=='no')
        if side not in ('BUY','SELL') or not(0<p<1) or sz<=0:return None
        if oi==ni:return {'t':t,'p':p,'side':side,'size':sz}
        return {'t':t,'p':1-p,'side':'SELL' if side=='BUY' else 'BUY','size':sz}
    except:return None
def main():
    src=json.loads(SRC.read_text());now=int(time.time());unique={}
    for x in src.get('top_setups') or []:
        # audit the most capital-efficient/smallest quantity representation once per quote
        k=(x['maker_condition_id'],round(float(x['safe_quote']),8))
        if k not in unique or x['quantity']<unique[k]['quantity']:unique[k]=x
    rows=[];errors=[]
    for x in unique.values():
        try:
            g=gamma(x['maker_condition_id']);outs=[str(z) for z in jl((g or {}).get('outcomes'))]
            raw=tape(x['maker_condition_id']);tr=[z for r in raw if (z:=norm_no(r,outs))];sells=[z for z in tr if z['side']=='SELL'];q=float(x['safe_quote'])
            windows={}
            for days in (1,7,30):
                ss=[z for z in sells if z['t']>=now-days*86400];hit=[z for z in ss if z['p']<=q+1e-12]
                windows[str(days)+'d']={'sell_trades':len(ss),'sell_shares':sum(z['size'] for z in ss),'through_trades':len(hit),'through_shares':sum(z['size'] for z in hit),
                    'min_sell_price':min((z['p'] for z in ss),default=None),'max_sell_price':max((z['p'] for z in ss),default=None)}
            rows.append({'event':x['event'],'maker_question':x['maker_question'],'condition_id':x['maker_condition_id'],'safe_quote':q,'current_bid':x['current_no_best_bid'],'current_ask':x['current_no_best_ask'],
                'conditional_profit_smallest_q':x['conditional_profit_after_reserve'],'conditional_roi':x['conditional_roi'],'quantity':x['quantity'],'raw_tape_rows':len(raw),'normalized_trades':len(tr),'windows':windows})
        except Exception as ex:errors.append({'condition_id':x['maker_condition_id'],'error':repr(ex)})
    out={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'method':{'through':'normalized taker SELL(NO) price <= proposed maker NO bid','warning':'historical through-flow does not guarantee future fills and ignores queue priority'},'candidates':rows,'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps({'candidates':rows,'errors':errors},indent=2))
if __name__=='__main__':main()
