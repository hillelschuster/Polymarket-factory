#!/usr/bin/env python3
"""Exact-source + recent fill-pressure audit for current reward candidates.

Candidates come from the 2026-08-30 hardened discovery screen. This script does
NOT carry over discovery-page economics blindly:
- re-fetch exact Gamma identity/state;
- fetch exact condition-specific reward source and active config;
- record `market_competitiveness`;
- fetch current books;
- fetch recent public market trade tape;
- normalize all trades into the proposed cheap-outcome coordinate and measure
  how often taker SELL flow traded at/below the proposed reward-farming bid.

A SELL-through is a direct historical example of the kind of flow that could
have filled our resting bid. It is still not a queue-position backtest.
"""
from __future__ import annotations
import datetime as dt,json,time,urllib.parse,urllib.request
from pathlib import Path

OUT=Path('liquidity_reward_candidate_audit.json')
UA={'User-Agent':'polymarket-factory-research/1.0'}
CLOB='https://clob.polymarket.com';GAMMA='https://gamma-api.polymarket.com';DATA='https://data-api.polymarket.com/trades'
CANDS=[
 {'condition_id':'0x7373afd8dfb6f478a7b7c21058031de5f9386340dd69768493bf59b0a51bc874','question':'Will Anthropic have the greatest valuation growth in August 2026?','discovery_pool':64.0,'quote_outcome':'No','quote_price':.093,'discovery_min_size':20},
 {'condition_id':'0x545564631d6c12085fcbbe12155a1039ec2d0bdac6785eff74b3c0366b7fd83d','question':'Will the PQ win fewer than 50 seats in the National Assembly of Quebec in this election?','discovery_pool':64.0,'quote_outcome':'Yes','quote_price':.165,'discovery_min_size':20},
 {'condition_id':'0xa6fa847c42fa0f6469115db523e49a49f9c7af1697797a552547bdb63a1e1349','question':'Will the lowest temperature in Tokyo be 25°C on September 1?','discovery_pool':34.0,'quote_outcome':'Yes','quote_price':.32,'discovery_min_size':20},
 {'condition_id':'0x2eb372b763fa45bc7693f89bf13edfe59b4d5c2e8dd6488581e461333148cf3b','question':'Will the lowest temperature in New York City be between 72-73°F on September 1?','discovery_pool':43.0,'quote_outcome':'Yes','quote_price':.43,'discovery_min_size':20},
 {'condition_id':'0x25a5928295839d8b2bfbaac7f154b3cad02b8fb107213d2680b8e34e41f37414','question':'Will Grand Theft Auto VI Extended Look get between 20 and 22 million views on week 1?','discovery_pool':483.0,'quote_outcome':'Yes','quote_price':.16,'discovery_min_size':200},
]

def req(url,params=None,method='GET',body=None,retries=3):
    if params:url+=('&' if '?' in url else '?')+urllib.parse.urlencode(params,doseq=True)
    data=json.dumps(body).encode() if body is not None else None;h=dict(UA)
    if data:h['Content-Type']='application/json'
    last=None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=30) as r:return json.load(r)
        except Exception as ex:last=ex;time.sleep(.2*(i+1))
    raise last

def jl(x):
    if isinstance(x,list):return x
    try:
        y=json.loads(x) if x else [];return y if isinstance(y,list) else []
    except:return []
def num(x):
    try:return float(x or 0)
    except:return 0.0

def exact_reward(cid,now):
    d=req(f'{CLOB}/rewards/markets/{cid}',{'sponsored':'true'})
    rows=d.get('data') or []
    if len(rows)!=1:raise ValueError(f'exact reward rows={len(rows)}')
    r=rows[0];active=[]
    today=now.date()
    for c in r.get('rewards_config') or []:
        try:
            s=dt.date.fromisoformat(str(c.get('start_date'))[:10]);e=dt.date.fromisoformat(str(c.get('end_date'))[:10])
            if s<=today<=e:active.append(c)
        except:pass
    rate=sum(num(c.get('rate_per_day')) for c in active)
    return r,active,rate

def gamma(cid):
    xs=req(f'{GAMMA}/markets',{'condition_ids':cid,'limit':3})
    ys=[x for x in xs if str(x.get('conditionId') or '').lower()==cid.lower()]
    if len(ys)!=1:raise ValueError(f'gamma rows={len(ys)}')
    return ys[0]

def books(tokens):
    xs=req(f'{CLOB}/books',method='POST',body=[{'token_id':t} for t in tokens])
    return {str(x.get('asset_id')):x for x in xs if x.get('asset_id')}
def best(book,side):
    vals=[]
    for z in (book or {}).get(side) or []:
        try:vals.append((float(z['price']),float(z['size'])))
        except:pass
    if not vals:return None
    return max(vals,key=lambda x:x[0]) if side=='bids' else min(vals,key=lambda x:x[0])

def tape(cid,max_pages=20):
    out=[];old=None;coverage={'pages':0,'rows':0,'oldest':None,'newest':None,'hit_offset_cap':False}
    for page in range(max_pages):
        off=page*500
        if off>9500:coverage['hit_offset_cap']=True;break
        xs=req(DATA,{'market':cid,'takerOnly':'true','limit':500,'offset':off})
        if not isinstance(xs,list) or not xs:break
        out.extend(xs);coverage['pages']+=1
        ts=[]
        for x in xs:
            try:ts.append(int(x.get('timestamp') or 0))
            except:pass
        if ts:
            mn,mx=min(ts),max(ts);old=mn if old is None else min(old,mn)
            coverage['oldest']=old;coverage['newest']=mx if coverage['newest'] is None else max(coverage['newest'],mx)
        if len(xs)<500:break
        time.sleep(.03)
    coverage['rows']=len(out)
    return out,coverage

def normalize_trade(x,outcomes,cheap_idx):
    try:
        oi=int(x.get('outcomeIndex'));p=float(x.get('price'));side=str(x.get('side') or '').upper();sz=float(x.get('size') or 0);t=int(x.get('timestamp') or 0)
        if oi not in (0,1) or side not in ('BUY','SELL') or not(0<p<1) or sz<=0:return None
        if oi==cheap_idx:return {'t':t,'price':p,'side':side,'size':sz}
        # Opposite token at p is cheap token at 1-p; BUY opposite == SELL cheap.
        return {'t':t,'price':1-p,'side':'SELL' if side=='BUY' else 'BUY','size':sz}
    except:return None

def audit(c,now):
    cid=c['condition_id'];g=gamma(cid);outs=[str(x) for x in jl(g.get('outcomes'))];tokens=[str(x) for x in jl(g.get('clobTokenIds'))]
    if len(outs)!=2 or len(tokens)!=2:raise ValueError('not binary')
    exact,configs,rate=exact_reward(cid,now)
    # Reconcile exact source identity + settings with Gamma.
    if str(exact.get('condition_id') or '').lower()!=cid.lower():raise ValueError('reward condition mismatch')
    exact_tokens=exact.get('tokens') or []
    if [str(x.get('token_id')) for x in exact_tokens]!=tokens:raise ValueError('reward token mismatch')
    minsize=num(exact.get('rewards_min_size'));maxspread=num(exact.get('rewards_max_spread'))
    cheap_idx=next((i for i,o in enumerate(outs) if o.casefold()==c['quote_outcome'].casefold()),None)
    if cheap_idx is None:raise ValueError('quote outcome missing')
    bks=books(tokens);bb=best(bks.get(tokens[cheap_idx]),'bids');ba=best(bks.get(tokens[cheap_idx]),'asks')
    raw,cov=tape(cid);norm=[z for x in raw if (z:=normalize_trade(x,outs,cheap_idx))]
    q=c['quote_price'];sells=[x for x in norm if x['side']=='SELL'];through=[x for x in sells if x['price']<=q+1e-12]
    nowts=int(now.timestamp());windows={}
    for h in (6,24,72,168):
        xs=[x for x in norm if x['t']>=nowts-h*3600];ss=[x for x in xs if x['side']=='SELL'];tt=[x for x in ss if x['price']<=q+1e-12]
        windows[str(h)]={'trades':len(xs),'sell_trades':len(ss),'sell_through_count':len(tt),'sell_through_shares':sum(x['size'] for x in tt),
                         'min_normalized_trade_price':min((x['price'] for x in xs),default=None),'min_sell_price':min((x['price'] for x in ss),default=None)}
    # How far is proposed bid from current touch after exact-settings refresh?
    current_bid=bb[0] if bb else None;current_ask=ba[0] if ba else None
    config_mismatch=(abs(rate-c['discovery_pool'])>1e-9 or abs(minsize-c['discovery_min_size'])>1e-9)
    return {**c,'gamma_question':g.get('question'),'outcomes':outs,'tokens':tokens,'active_reward_rate_exact':rate,
            'exact_active_configs':configs,'exact_min_size':minsize,'exact_max_spread_cents':maxspread,
            'market_competitiveness':exact.get('market_competitiveness'),'sponsored_daily_rate':exact.get('sponsored_daily_rate'),
            'native_daily_rate':exact.get('native_daily_rate'),'total_daily_rate_exact_field':exact.get('total_daily_rate'),
            'discovery_vs_exact_config_mismatch':config_mismatch,'current_cheap_best_bid':current_bid,'current_cheap_best_ask':current_ask,
            'quote_distance_below_best_bid':(current_bid-q) if current_bid is not None else None,'trade_coverage':cov,
            'all_observed_sell_through_count':len(through),'all_observed_sell_through_shares':sum(x['size'] for x in through),
            'recent_windows_hours':windows,'fees_enabled':g.get('feesEnabled'),'fee_schedule':g.get('feeSchedule'),
            'end_date':g.get('endDate')}

def main():
    now=dt.datetime.now(dt.timezone.utc);rows=[];errors=[]
    for c in CANDS:
        try:rows.append(audit(c,now))
        except Exception as ex:errors.append({'condition_id':c['condition_id'],'question':c['question'],'error':repr(ex)})
    out={'generated_at':now.isoformat(),'method':{'exact_reward':'condition-specific /rewards/markets/{condition_id}?sponsored=true',
         'fill_pressure':'public takerOnly /trades normalized into proposed cheap outcome','sell_through':'normalized taker SELL price <= proposed resting bid',
         'warning':'observed sell-through estimates historical fill pressure but not queue position, post-fill markout, or future risk'},
         'candidates':rows,'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'candidates':[{'q':r['question'],'exact_rate':r['active_reward_rate_exact'],'min_size':r['exact_min_size'],
         'spread':r['exact_max_spread_cents'],'competitiveness':r['market_competitiveness'],'config_mismatch':r['discovery_vs_exact_config_mismatch'],
         'bid':r['quote_price'],'touch':r['current_cheap_best_bid'],'24h':r['recent_windows_hours']['24'],'72h':r['recent_windows_hours']['72']} for r in rows],
         'errors':errors},indent=2))
if __name__=='__main__':main()
