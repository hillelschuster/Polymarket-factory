#!/usr/bin/env python3
"""Profitability audit for reward farming without grossly overpaying for fills.

A qualifying-size midpoint can be badly distorted in thin books. Reward farming is
not attractive if earning Q requires bidding far above the market's recent value.

For a small set of strongest exact-source candidates this script:
- reconciles exact reward config and current CLOB books;
- chooses the cheaper outcome;
- defines a conservative fair/reference price from exact reward token price and
  CLOB last trade;
- forbids quotes more than 1c (or two ticks) above BOTH reference and current best bid;
- enumerates only reward-eligible quotes under that ceiling;
- applies 5x visible-competition stress and recent SELL-through pressure.

No orders are placed.
"""
from __future__ import annotations
import datetime as dt,json,statistics,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import liquidity_reward_candidate_audit as aud
import liquidity_reward_live_screen as lr

OUT=Path('liquidity_reward_safe_quote_audit.json')
CIDS=[
'0x90a9e20caf2e08566ff238476fd3e45aed40430614fb81c9ccead60e5f31a838',
'0xda8f6fe7ee0adf9be543e0bb2c6c2fb9bb9d33db9e16beda2e81755a2c4a4f66',
'0xa0df1628ba4af5f958809cb3c80360b75b87b5a88533e1ec36750c3de80e07d3',
'0xc6111ea9194ceda56e30ffa589935f920974f8716dfb242a649526ace097e7c5',
'0x7373afd8dfb6f478a7b7c21058031de5f9386340dd69768493bf59b0a51bc874',
]
STRESS=5.0

def n(x):return aud.num(x)
def exact(cid,now):
    d=aud.req(f'{aud.CLOB}/rewards/markets/{cid}',{'sponsored':'true'});rows=d.get('data') or []
    if len(rows)!=1:raise ValueError(f'exact rows={len(rows)}')
    r=rows[0];rate=0.0;today=now.date()
    for c in r.get('rewards_config') or []:
        try:
            s=dt.date.fromisoformat(str(c.get('start_date'))[:10]);e=dt.date.fromisoformat(str(c.get('end_date'))[:10])
            if s<=today<=e:rate+=n(c.get('rate_per_day'))
        except:pass
    return r,rate

def focal_reference(row,outcomes,idx,book):
    refs=[]
    for t in row.get('tokens') or []:
        if str(t.get('outcome','')).casefold()==outcomes[idx].casefold():
            p=n(t.get('price'))
            if 0<p<1:refs.append(('exact_token_price',p))
    p=n(book.get('last_trade_price'))
    if 0<p<1:refs.append(('clob_last_trade',p))
    vals=[x[1] for x in refs]
    return (statistics.median(vals) if vals else None),refs

def scoreq(p,mid,v,size):
    dist=abs(mid-p)
    if dist>v+1e-12:return 0.0
    return (((v-dist)/v)**2*size)/3 if .10<=mid<=.90 else 0.0

def analyze(cid,now):
    g=aud.gamma(cid);row,rate=exact(cid,now)
    outs=[str(x) for x in aud.jl(g.get('outcomes'))];toks=[str(x) for x in aud.jl(g.get('clobTokenIds'))]
    if len(outs)!=2 or len(toks)!=2 or rate<=0:raise ValueError('bad binary/exact config')
    minsize=n(row.get('rewards_min_size'));v=n(row.get('rewards_max_spread'))/100
    books=aud.books(toks);poss=[]
    for idx in (0,1):
        own=books[toks[idx]];other=books[toks[1-idx]];bids,asks=lr.merge_yes_book(own,other)
        ab=lr.cutoff_price(bids,minsize);aa=lr.cutoff_price(asks,minsize)
        if ab is None or aa is None or aa<=ab:continue
        mid=(ab+aa)/2
        if not(.10<=mid<=.5):continue
        own_bids=sorted(lr.levels(own,'bids'),reverse=True);own_asks=sorted(lr.levels(own,'asks'))
        bestbid=own_bids[0][0] if own_bids else None;bestask=own_asks[0][0] if own_asks else None
        ref,refs=focal_reference(row,outs,idx,own);tick=n(own.get('tick_size')) or .001
        if ref is None or bestbid is None:continue
        fair_pad=max(.01,2*tick)
        ceiling=min(ref+fair_pad,bestbid+fair_pad,mid-tick,(bestask-tick) if bestask is not None else mid-tick)
        floor=max(tick,mid-v+tick)
        comp=lr.qmin_proxy(lr.score_side(bids,mid,v),lr.score_side(asks,mid,v),mid)
        tape,cov=aud.tape(cid);norm=[]
        for x in tape:
            z=aud.normalize_trade(x,outs,idx)
            if z:norm.append(z)
        sells=[x for x in norm if x['side']=='SELL'];nowts=int(now.timestamp())
        grid=[];p=floor
        while p<=ceiling+1e-12:
            q=scoreq(p,mid,v,minsize)
            if q>0:
                reward=rate*q/(STRESS*comp+q) if comp>0 else rate
                capital=minsize*p;ahead=sum(s for px,s in own_bids if px>p+1e-12);at=sum(s for px,s in own_bids if abs(px-p)<=1e-12)
                ss=[x for x in sells if x['t']>=nowts-72*3600 and x['price']<=p+1e-12];shares=sum(x['size'] for x in ss);fp=shares/minsize/3 if minsize else 0
                overpay=max(0,p-ref)*minsize
                score=(reward/max(capital,1e-9))*(1+min(2,(ahead+at)/minsize/6))/(1+fp)/(1+5*overpay)
                grid.append({'quote_price':round(p,10),'reward5x':reward,'capital':capital,'full_loss_cover_days':capital/reward if reward>0 else None,
                    'queue_protection_min_orders':(ahead+at)/minsize,'sell_through_min_orders_per_day_72h':fp,
                    'reference_price':ref,'quote_premium_to_reference':p-ref,'mark_overpay_if_full_fill':overpay,'score':score})
            p=round(p+tick,10)
        if grid:
            poss.append({'outcome_index':idx,'outcome':outs[idx],'rate':rate,'min_size':minsize,'max_spread_cents':v*100,
                'mid':mid,'best_bid':bestbid,'best_ask':bestask,'reference':ref,'reference_inputs':refs,'safe_ceiling':ceiling,
                'visible_qmin_proxy':comp,'market_competitiveness':row.get('market_competitiveness'),'tape_coverage':cov,
                'best':max(grid,key=lambda x:x['score']),'grid':sorted(grid,key=lambda x:x['score'],reverse=True)[:20]})
    if not poss:return {'condition_id':cid,'question':g.get('question'),'viable':False,'reason':'no reward-eligible quote remains near fair/best-bid reference','rate':rate}
    best=max(poss,key=lambda x:x['best']['score'])
    viable=best['best']['reward5x']>=1 and best['best']['sell_through_min_orders_per_day_72h']<1
    return {'condition_id':cid,'question':g.get('question'),'viable':viable,'best_outcome':best,'alternatives':poss,
        'feesEnabled':g.get('feesEnabled'),'feeSchedule':g.get('feeSchedule'),'endDate':g.get('endDate')}
def main():
    now=dt.datetime.now(dt.timezone.utc);rows=[];errs=[]
    for cid in CIDS:
        try:rows.append(analyze(cid,now))
        except Exception as ex:errs.append({'condition_id':cid,'error':repr(ex)})
    rows.sort(key=lambda r:(r.get('viable',False),(r.get('best_outcome') or {}).get('best',{}).get('score',0)),reverse=True)
    out={'generated_at':now.isoformat(),'method':{'competition_stress':STRESS,'fair_pad':'max(1c,2 ticks) above both reference and best bid',
        'reference':'median of exact reward token price and CLOB last_trade_price when available','no_orders':True},'candidates':rows,'errors':errs}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'candidates':[{'q':r['question'],'viable':r['viable'],'best':(r.get('best_outcome') or {}).get('best'),
        'market':{k:(r.get('best_outcome') or {}).get(k) for k in ['outcome','rate','mid','best_bid','best_ask','reference','safe_ceiling','market_competitiveness']}} for r in rows],'errors':errs},indent=2))
if __name__=='__main__':main()
