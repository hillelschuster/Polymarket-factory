#!/usr/bin/env python3
"""Discover repeated Polymarket market classes suitable for finite-state alpha.

Research only. Public Gamma API. No trading.
This is a universe inventory, not an alpha test: it estimates repeated/liquid market
families worth reconstructing. Classification intentionally uses titles/questions,
not long descriptions, to reduce semantic false positives.
"""
from __future__ import annotations
import csv,json,re,time,urllib.parse,urllib.request
from collections import Counter,defaultdict

BASE='https://gamma-api.polymarket.com/events'
UA={'User-Agent':'polymarket-factory-research/1.0'}
LIMIT=100
# Gamma rejects deep offsets around ~2,100. Two thousand highest-volume closed events
# are enough for broad discovery; repeated families get dedicated public-search scans.
MAX_EVENTS=2000
MIN_VOLUME=1000.0

FAMILIES={
 'streaming_views_charts':[r'\bspotify\b',r'\bstreams?\b',r'\bstreamed\b',r'\byoutube\b',r'\bviews?\b',r'\bbillboard\b',r'\bdownloads?\b',r'\bchart\b'],
 'box_office_sales':[r'box office',r'\bgross(?:ing)?\b',r'highest[- ]grossing',r'ticket sales',r'units sold',r'copies sold'],
 'sports_cumulative_stats':[r'season wins?',r'win total',r'goals? scored',r'home runs?',r'touchdowns?',r'strikeouts?',r'assists?',r'scoring title',r'most goals',r'most points',r'most wins',r'statistical leader'],
 'election_accumulation':[r'\bdelegates?\b',r'electoral votes?',r'house seats?',r'senate seats?',r'seats? won',r'seat count',r'popular vote total'],
 'running_counts_rankings':[r'number of .* by',r'how many .* by',r'total .* by',r'most .* in 20\d\d',r'highest .* in 20\d\d'],
}
EXCLUDE=[r'price of',r'above \$',r'below \$',r'between \$',r'market cap',r'\bmentions?\b',r'\btweets?\b',r'truth social posts?',r'temperature',r'rainfall',r'snowfall',r'earthquake',r'match winner',r'moneyline',r'\bspread\b']

def get(params):
    url=BASE+'?'+urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r:return json.load(r)

def num(v):
    try:return float(v or 0)
    except:return 0.0

def event_text(e):
    parts=[e.get('title') or '',e.get('subtitle') or '']
    for m in e.get('markets') or []:parts.extend([m.get('question') or '',m.get('groupItemTitle') or ''])
    return ' '.join(parts).lower()

def classify(text):
    exclusions=[p for p in EXCLUDE if re.search(p,text,re.I)]
    fam=[];reasons=[]
    for family,pats in FAMILIES.items():
        hits=[p for p in pats if re.search(p,text,re.I)]
        if hits:fam.append(family);reasons.extend(hits[:3])
    return fam,reasons,exclusions

def main():
    raw=[];offset=0;seen=set();pages=0
    while len(raw)<MAX_EVENTS:
        batch=get({'closed':'true','limit':LIMIT,'offset':offset,'order':'volume','ascending':'false'})
        pages+=1
        if not batch:break
        added=0
        for e in batch:
            key=str(e.get('id') or e.get('slug'))
            if key in seen:continue
            seen.add(key);raw.append(e);added+=1
            if len(raw)>=MAX_EVENTS:break
        offset+=len(batch)
        print(f'page={pages} fetched={len(raw)} batch={len(batch)} added={added}',flush=True)
        if added==0:break
        time.sleep(.03)

    rows=[]
    for e in raw:
        text=event_text(e);families,reasons,exclusions=classify(text);volume=num(e.get('volume'))
        if not families or volume<MIN_VOLUME:continue
        if exclusions and not any(f in families for f in ('box_office_sales','streaming_views_charts')):continue
        rows.append({'id':e.get('id'),'slug':e.get('slug'),'title':e.get('title'),'category':e.get('category'),'subcategory':e.get('subcategory'),'startDate':e.get('startDate'),'endDate':e.get('endDate'),'volume':volume,'market_count':len(e.get('markets') or []),'families':families,'match_reasons':reasons,'exclusion_warnings':exclusions})
    rows.sort(key=lambda x:x['volume'],reverse=True)
    by=defaultdict(list)
    for r in rows:
        for f in r['families']:by[f].append(r)
    summary={'closed_events_scanned':len(raw),'pages':pages,'min_event_volume':MIN_VOLUME,'candidate_events':len(rows),'family_counts':{f:len(v) for f,v in by.items()},'family_volume':{f:round(sum(r['volume'] for r in v),2) for f,v in by.items()},'category_counts':dict(Counter((r.get('category') or 'unknown') for r in rows)),'top_by_family':{f:[{k:r[k] for k in ('id','slug','title','volume','startDate','endDate','exclusion_warnings')} for r in v[:30]] for f,v in by.items()}}
    with open('cumulative_universe.json','w',encoding='utf-8') as f:json.dump({'summary':summary,'events':rows},f,indent=2)
    with open('cumulative_universe.csv','w',newline='',encoding='utf-8') as f:
        fields=['id','slug','title','category','subcategory','startDate','endDate','volume','market_count','families','match_reasons','exclusion_warnings'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:
            rr=dict(r)
            for k in ('families','match_reasons','exclusion_warnings'):rr[k]=' | '.join(rr[k])
            w.writerow(rr)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
