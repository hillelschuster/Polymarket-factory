#!/usr/bin/env python3
"""Hardened current liquidity-reward screen.

Wraps v1 primitives but fixes two interpretation issues discovered in the first
live pass:
- fetch the *full* reward list (v1 stopped at 15k / 30 pages);
- separate protected farming from naked band-edge farming using queue depth and
  time to resolution.

Still a screen, not a PnL backtest. `reward_per_day_proxy` uses aggregated visible
book competition and can over/understate exact maker-level reward share.
"""
from __future__ import annotations
import datetime as dt,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import liquidity_reward_live_screen as v1

OUT=Path('liquidity_reward_live_screen_v2.json')
v1.MAX_REWARD_PAGES=60
TOP_POOL=300;TOP_DENSITY=450;MIN_POOL=2.0
MIN_HOURS_TO_END=36
MAX_DAY_MOVE=.05
MIN_PROTECTION_X=1.0

def parse_end(s,now):
    if not s:return None
    try:
        x=dt.datetime.fromisoformat(str(s).replace('Z','+00:00'))
        if x.tzinfo is None:x=x.replace(tzinfo=dt.timezone.utc)
        return (x-now).total_seconds()/3600
    except Exception:return None

def enrich(r,now):
    h=parse_end(r.get('end_date'),now);r['hours_to_end']=h
    qa=float(r.get('queue_ahead_shares') or 0);qat=float(r.get('queue_at_quote_shares') or 0);ms=float(r.get('min_size') or 0)
    r['queue_protection_shares']=qa+qat
    r['queue_protection_min_orders']=(qa+qat)/ms if ms>0 else 0
    flags=list(r.get('risk_flags') or [])
    if h is None:flags.append('unknown_time_to_end')
    elif h<MIN_HOURS_TO_END:flags.append('resolves_within_36h')
    if r['queue_protection_min_orders']<MIN_PROTECTION_X:flags.append('less_than_one_min_order_protection')
    r['risk_flags_v2']=sorted(set(flags))
    return r

def main():
    now=dt.datetime.now(dt.timezone.utc)
    rewards,reward_errors,pages=v1.fetch_rewards()
    usable=[r for r in rewards if v1.fnum(r.get('total_daily_rate'))>=MIN_POOL and v1.fnum(r.get('rewards_min_size'))>0]
    a=sorted(usable,key=lambda r:v1.fnum(r.get('total_daily_rate')),reverse=True)[:TOP_POOL]
    b=sorted(usable,key=lambda r:v1.fnum(r.get('total_daily_rate'))/max(v1.fnum(r.get('rewards_min_size')),1),reverse=True)[:TOP_DENSITY]
    selected={str(r.get('condition_id')):r for r in a+b if r.get('condition_id')}
    gamma,gamma_errors=v1.fetch_gamma(list(selected))
    toks=[]
    for g in gamma.values():
        toks.extend(str(x) for x in v1.jlist(g.get('clobTokenIds')))
    books,book_errors=v1.fetch_books(list(dict.fromkeys(toks)))
    rows=[];parse_errors=[]
    for cid,reward in selected.items():
        g=gamma.get(cid)
        if not g:continue
        try:
            r=v1.parse_market(cid,reward,g,books)
            if r:rows.append(enrich(r,now))
        except Exception as ex:
            if len(parse_errors)<50:parse_errors.append({'condition_id':cid,'error':repr(ex)})
    rows.sort(key=lambda r:r['screen_score'],reverse=True)
    def stable(r):
        return (r['category_screen']!='geopolitics' and (r['hours_to_end'] or -1)>=MIN_HOURS_TO_END
                and float(r.get('abs_one_day_price_change') or 0)<MAX_DAY_MOVE)
    protected=[r for r in rows if stable(r) and r['queue_protection_min_orders']>=MIN_PROTECTION_X]
    naked=[r for r in rows if stable(r) and r['queue_protection_min_orders']<MIN_PROTECTION_X]
    # A stricter candidate needs at least a modeled $1/day reward (payout floor)
    # and avoids very high 24h flow as a crude adverse-selection proxy.
    strict=[r for r in protected if r['reward_per_day_proxy']>=1 and r['volume_24h']<100000]
    pools=[v1.fnum(r.get('total_daily_rate')) for r in rewards]
    out={'generated_at':now.isoformat(),'method':{
        'full_reward_pagination':True,'max_pages':v1.MAX_REWARD_PAGES,
        'protected_definition':f'>={MIN_HOURS_TO_END}h to end, non-geopolitics, <{MAX_DAY_MOVE:.0%} 1d move, >=1 min-order queue ahead+at quote',
        'naked_definition':'same stability gates but <1 min-order queue protection',
        'strict_extra':'reward proxy >=$1/day and 24h volume < $100k',
        'warning':'single-snapshot reward share is a proxy; profitability requires multi-snapshot fill/adverse-selection validation'},
        'landscape':{'reward_pages':pages,'reward_markets':len(rewards),'configured_daily_capacity':sum(pools),
            'median_pool':sorted(pools)[len(pools)//2] if pools else None,'markets_pool_ge_50':sum(x>=50 for x in pools),
            'markets_pool_ge_200':sum(x>=200 for x in pools),'selected_for_books':len(selected),'gamma_resolved':len(gamma),
            'books_resolved':len(books),'fully_scored':len(rows),'protected_stable':len(protected),'naked_stable':len(naked),
            'strict_candidates':len(strict)},
        'top_strict':strict[:75],'top_protected':protected[:100],'top_naked':naked[:100],
        'errors':{'rewards':reward_errors,'gamma':gamma_errors,'books':book_errors,'parse':parse_errors}}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'landscape':out['landscape'],'top_strict':[{
        'q':r['question'],'cat':r['category_screen'],'pool':round(r['pool_per_day'],2),'capital':round(r['required_capital'] or 0,2),
        'reward_proxy':round(r['reward_per_day_proxy'],3),'protection_x':round(r['queue_protection_min_orders'],1),
        'hours':round(r['hours_to_end'] or 0,1),'move1d':round(r['abs_one_day_price_change'],4)} for r in strict[:20]],
        'top_naked':[{'q':r['question'],'pool':round(r['pool_per_day'],2),'capital':round(r['required_capital'] or 0,2),
        'reward_proxy':round(r['reward_per_day_proxy'],2),'hours':round(r['hours_to_end'] or 0,1)} for r in naked[:10]],
        'errors':{k:v[:3] for k,v in out['errors'].items()}},indent=2))
if __name__=='__main__':main()
