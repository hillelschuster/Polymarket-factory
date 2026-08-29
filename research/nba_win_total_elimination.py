#!/usr/bin/env python3
"""Deterministic-state audit: 2025-26 NBA Polymarket team win totals.

For each team market, reconstruct the 82-game regular season from TheSportsDB's
public full-season page. For UNDER winners, find the first game after which:

    wins_so_far + games_remaining <= line

At that state OVER is mathematically impossible. Polymarket's rules explicitly say
such markets may resolve NO early. We inspect certain-side taker BUY prints only from
12:00 UTC on the FOLLOWING day, deliberately far after the game result was public.
This tests economically meaningful stale pricing, not seconds-scale latency.

Research only. No orders.
"""
from __future__ import annotations
import datetime as dt
import json,re,time,urllib.parse,urllib.request
from html.parser import HTMLParser
from pathlib import Path

UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0 Safari/537.36","Accept":"text/html,application/json,*/*"}
OUT=Path("nba_win_total_elimination.json")
EVENT_SLUG="nba-win-totals-over-or-under"
SEASON_PAGE="https://www.thesportsdb.com/season/4387-nba/2025-2026?all=1"
REG_START=dt.date(2025,10,21)
REG_END=dt.date(2026,4,12)
REG_GAMES=82
DELAYS_MIN=(0,10,30,120,360,720)
CURRENT_SPORTS_FEE_RATE=0.05
NBA_TEAMS=[
"Atlanta Hawks","Boston Celtics","Brooklyn Nets","Charlotte Hornets","Chicago Bulls","Cleveland Cavaliers",
"Dallas Mavericks","Denver Nuggets","Detroit Pistons","Golden State Warriors","Houston Rockets","Indiana Pacers",
"Los Angeles Clippers","Los Angeles Lakers","Memphis Grizzlies","Miami Heat","Milwaukee Bucks","Minnesota Timberwolves",
"New Orleans Pelicans","New York Knicks","Oklahoma City Thunder","Orlando Magic","Philadelphia 76ers","Phoenix Suns",
"Portland Trail Blazers","Sacramento Kings","San Antonio Spurs","Toronto Raptors","Utah Jazz","Washington Wizards"]

class Rows(HTMLParser):
    def __init__(self):super().__init__();self.in_tr=False;self.in_cell=False;self.cell=[];self.row=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.in_tr=True;self.row=[]
        elif self.in_tr and tag in ('td','th'):self.in_cell=True;self.cell=[]
    def handle_data(self,data):
        if self.in_cell:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.in_cell:
            self.row.append(' '.join(''.join(self.cell).split()));self.in_cell=False
        elif tag=='tr' and self.in_tr:
            if self.row:self.rows.append(self.row)
            self.in_tr=False;self.row=[]

def request(url,params=None,timeout=40,json_mode=True):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:
        raw=r.read()
    return json.loads(raw) if json_mode else raw.decode('utf-8','replace')

def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or "[]")
    except:return []

def norm(s):return re.sub(r"[^a-z0-9]+"," ",(s or "").lower()).strip()
def fee(p):return CURRENT_SPORTS_FEE_RATE*p*(1-p)

def clean_team(cell):
    low=norm(cell)
    hits=[t for t in NBA_TEAMS if norm(t) in low]
    return max(hits,key=len) if hits else None

def season_games():
    html=request(SEASON_PAGE,json_mode=False);p=Rows();p.feed(html);games=[]
    score_re=re.compile(r'^(\d{1,3})\s*-\s*(\d{1,3})$')
    for row in p.rows:
        if len(row)<5:continue
        sm=score_re.match(row[3])
        if not sm:continue
        try:d=dt.datetime.strptime(row[0],'%d %b %y').date()
        except:continue
        if not (REG_START<=d<=REG_END):continue
        home=clean_team(row[2]);away=clean_team(row[4])
        if not home or not away:continue
        hs,as_=int(sm.group(1)),int(sm.group(2))
        # NBA Cup championship does NOT count in regular-season standings.
        if d==dt.date(2025,12,16) and {home,away}=={'New York Knicks','San Antonio Spurs'}:continue
        games.append({'date':d,'home':home,'away':away,'home_score':hs,'away_score':as_,'round':row[1]})
    games.sort(key=lambda g:(g['date'],g['home'],g['away']))
    return games

def records_by_team(games):
    by={t:[] for t in NBA_TEAMS}
    wins={t:0 for t in NBA_TEAMS};played={t:0 for t in NBA_TEAMS}
    # Same-date ordering does not matter for an elimination state used only next-day noon;
    # if a team somehow plays twice same day, process both before using the daily state.
    for g in games:
        hw=g['home_score']>g['away_score'];aw=not hw
        for t,w in ((g['home'],hw),(g['away'],aw)):
            played[t]+=1;wins[t]+=int(w)
            by[t].append({'date':g['date'],'win':w,'wins_after':wins[t],'games_after':played[t],'opponent':g['away'] if t==g['home'] else g['home']})
    return by

def find_team(market):
    txt=norm(" ".join([str(market.get("question") or ""),str(market.get("groupItemTitle") or "")]))
    hits=[t for t in NBA_TEAMS if norm(t) in txt]
    return max(hits,key=len) if hits else None

def parse_line(market):
    txt=" ".join([str(market.get("question") or ""),str(market.get("groupItemTitle") or "")])
    for pat in (r"more than\s+([0-9]+(?:\.[0-9]+)?)",r"over\s+([0-9]+(?:\.[0-9]+)?)",r"([0-9]+\.5)"):
        m=re.search(pat,txt,re.I)
        if m:return float(m.group(1))
    return None

def certain_token(market,side):
    outs=[str(x).lower() for x in arr(market.get('outcomes'))];ids=[str(x) for x in arr(market.get('clobTokenIds'))]
    wanted='yes' if side=='OVER' else 'no'
    if wanted in outs and len(ids)==len(outs):return ids[outs.index(wanted)],wanted
    if len(ids)>=2:return (ids[0],'index0') if side=='OVER' else (ids[1],'index1')
    return None,None

def deterministic_state(team_games,line):
    """First daily close where either side is mathematically certain."""
    # Collapse to final state after each date; safe action time is next-day 12:00 UTC.
    daily={}
    for g in team_games:daily[g['date']]=g
    for d in sorted(daily):
        g=daily[d];rem=REG_GAMES-g['games_after'];w=g['wins_after'];mx=w+rem
        if w>line:return {'side':'OVER','date':d,'wins':w,'games_played':g['games_after'],'remaining':rem,'max_wins':mx,'line':line,'safe_utc':dt.datetime.combine(d+dt.timedelta(days=1),dt.time(12),tzinfo=dt.timezone.utc)}
        if mx<=line:return {'side':'UNDER','date':d,'wins':w,'games_played':g['games_after'],'remaining':rem,'max_wins':mx,'line':line,'safe_utc':dt.datetime.combine(d+dt.timedelta(days=1),dt.time(12),tzinfo=dt.timezone.utc)}
    return None

def trades(cid,start,end):
    try:
        x=request('https://data-api.polymarket.com/trades',{'market':cid,'start':int(start.timestamp()),'end':int(end.timestamp()),'limit':10000,'offset':0,'takerOnly':'true'})
        return x if isinstance(x,list) else []
    except:return []

def buy_prints(rows,token,start):
    out=[]
    for x in rows:
        if str(x.get('asset'))!=str(token) or str(x.get('side') or '').upper()!='BUY':continue
        try:t=int(x['timestamp']);p=float(x['price']);sz=float(x.get('size') or 0)
        except:continue
        if t>=int(start.timestamp()):out.append({'t':t,'p':p,'size':sz})
    return sorted(out,key=lambda z:z['t'])

def first_after(prints,ts):
    xs=[x for x in prints if x['t']>=int(ts.timestamp())]
    if not xs:return None
    x=xs[0];p=x['p'];cost=p+fee(p)
    return {**x,'delay_min':(x['t']-int(ts.timestamp()))/60,'fee_current':fee(p),'all_in_current_fee':cost,'locked_profit':1-cost,'roi_on_cost':(1-cost)/cost if cost else None}

def main():
    games=season_games();by=records_by_team(games)
    game_counts={t:len(by[t]) for t in NBA_TEAMS}
    bad_counts={t:n for t,n in game_counts.items() if n!=82}
    if bad_counts:raise RuntimeError(f'NBA regular-season reconstruction failed 82-game invariant: {bad_counts}')
    ev=request('https://gamma-api.polymarket.com/events/slug/'+EVENT_SLUG)
    results=[];errors=[]
    for m in ev.get('markets') or []:
        team=find_team(m);line=parse_line(m)
        if not team or line is None:
            errors.append({'question':m.get('question'),'team':team,'line':line});continue
        state=deterministic_state(by[team],line)
        # Determine certain token from the state, not hindsight resolution.
        rec={'team':team,'line':line,'question':m.get('question'),'market_id':m.get('id'),'conditionId':m.get('conditionId'),'volume':float(m.get('volume') or 0),'outcomePrices':arr(m.get('outcomePrices')),'state':None,'post_state':{},'stale_buy_summary':None}
        if state:
            token,label=certain_token(m,state['side']);safe=state['safe_utc'];state_out=dict(state);state_out['date']=state['date'].isoformat();state_out['safe_utc']=safe.isoformat();rec['state']=state_out;rec['certain_token_label']=label
            tr=trades(str(m.get('conditionId')),safe,safe+dt.timedelta(days=7));bp=buy_prints(tr,token,safe) if token else []
            for dm in DELAYS_MIN:rec['post_state'][f'after_{dm}m']=first_after(bp,safe+dt.timedelta(minutes=dm))
            after10=[x for x in bp if x['t']>=int((safe+dt.timedelta(minutes=10)).timestamp())]
            rec['stale_buy_summary']={'n_after_10m':len(after10),'lt99':sum(x['p']<.99 for x in after10),'lt98':sum(x['p']<.98 for x in after10),'lt95':sum(x['p']<.95 for x in after10),'min_price':min((x['p'] for x in after10),default=None),'shares_lt98':sum(x['size'] for x in after10 if x['p']<.98),'dollars_lt98_approx':sum(x['size']*x['p'] for x in after10 if x['p']<.98)}
        results.append(rec);time.sleep(.01)
    states=[r for r in results if r['state']]
    def opportunities(delay,cap):
        xs=[]
        for r in states:
            p=r['post_state'].get(delay)
            if p and p['p']<=cap and p['all_in_current_fee']<1:
                xs.append({'team':r['team'],'side':r['state']['side'],'line':r['line'],'safe_utc':r['state']['safe_utc'],'price':p['p'],'size':p['size'],'delay_min':p['delay_min'],'all_in':p['all_in_current_fee'],'locked_profit_per_share':p['locked_profit'],'roi_on_cost':p['roi_on_cost'],'market_volume':r['volume']})
        return xs
    summary={'event_title':ev.get('title'),'event_volume':float(ev.get('volume') or 0),'markets':len(ev.get('markets') or []),'regular_games_parsed':len(games),'all_teams_82_games':not bad_counts,'deterministic_states':len(states),'over_states':sum(r['state']['side']=='OVER' for r in states),'under_states':sum(r['state']['side']=='UNDER' for r in states),'current_fee_rate_stress':CURRENT_SPORTS_FEE_RATE,'opp_after_safe_10m_le98':opportunities('after_10m',.98),'opp_after_safe_30m_le98':opportunities('after_30m',.98),'opp_after_safe_2h_le98':opportunities('after_120m',.98),'opp_after_safe_6h_le98':opportunities('after_360m',.98),'opp_after_safe_10m_le95':opportunities('after_10m',.95),'total_stale_shares_lt98_after10':sum((r.get('stale_buy_summary') or {}).get('shares_lt98',0) for r in states),'total_stale_dollars_lt98_after10_approx':sum((r.get('stale_buy_summary') or {}).get('dollars_lt98_approx',0) for r in states)}
    out={'summary':summary,'game_counts':game_counts,'results':results,'errors':errors,'method_limits':['TheSportsDB public schedule is independently reconstructed and checked against the 82-game invariant for every team.','Safe action time is noon UTC the day after the eliminating game, intentionally much later than final score publication.','Historical taker trade timestamps are used as evidence of actual fills; they do not prove prospective book depth.','Current Aug-2026 Sports fee rate is applied as a conservative economics stress even if historical fees differed.']}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'summary':summary,'errors':errors[:10]},indent=2))
if __name__=='__main__':main()
