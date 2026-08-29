#!/usr/bin/env python3
"""Inventory repeated YouTube-view Polymarket horizons without guessing video identity.

Goal: determine whether resolved earlier-horizon markets can serve as historical
state checkpoints for later-horizon markets on the same underlying video.

This stage does NOT trade or fit a model. It records resolver/source identifiers,
horizons, bracket shapes and exact event timing so later tests can group only when
identity is defensible.
"""
from __future__ import annotations
import json,re,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path

UA={"User-Agent":"polymarket-factory-research/1.0","Accept":"application/json,*/*"}
OUT=Path("youtube_horizon_inventory.json")
QUERIES=("views on day 1","views on day 2","views in week 1","YouTube views MrBeast","# of views YouTube","MrBeast video views")
URL_RE=re.compile(r"https?://[^\s\]\[)<>'\"]+",re.I)
YT_RE=re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,})",re.I)


def get(url,params=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,doseq=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r:return json.load(r)

def arr(v):
    if isinstance(v,list):return v
    try:return json.loads(v or '[]')
    except:return []

def txt_fields(obj):
    keys=("title","slug","question","groupItemTitle","description","rules","resolutionSource","source","url")
    return "\n".join(str(obj.get(k) or "") for k in keys)

def youtube_ids(obj):
    text=txt_fields(obj)
    return sorted(set(m.group(1) for m in YT_RE.finditer(text)))

def all_urls(obj):
    return sorted(set(x.rstrip('.,;') for x in URL_RE.findall(txt_fields(obj))))

def horizon(text):
    t=(text or '').lower()
    pats=[
      (r'\bday\s*1\b|\b1\s*day\b|\b24\s*(?:h|hr|hrs|hours?)\b',24),
      (r'\bday\s*2\b|\b2\s*days?\b|\b48\s*(?:h|hr|hrs|hours?)\b',48),
      (r'\bday\s*3\b|\b3\s*days?\b|\b72\s*(?:h|hr|hrs|hours?)\b',72),
      (r'\bday\s*4\b|\b4\s*days?\b|\b96\s*(?:h|hr|hrs|hours?)\b',96),
      (r'\bday\s*5\b|\b5\s*days?\b|\b120\s*(?:h|hr|hrs|hours?)\b',120),
      (r'\bday\s*6\b|\b6\s*days?\b|\b144\s*(?:h|hr|hrs|hours?)\b',144),
      (r'\bday\s*7\b|\b7\s*days?\b|\bweek\s*1\b|\b1\s*week\b|\b168\s*(?:h|hr|hrs|hours?)\b',168),
    ]
    for p,h in pats:
        if re.search(p,t):return h
    return None

def compact_market(m):
    text=" ".join([str(m.get('question') or ''),str(m.get('groupItemTitle') or '')])
    return {
      'id':m.get('id'),'conditionId':m.get('conditionId'),'question':m.get('question'),
      'groupItemTitle':m.get('groupItemTitle'),'endDate':m.get('endDate'),'closed':m.get('closed'),
      'outcomes':arr(m.get('outcomes')),'outcomePrices':arr(m.get('outcomePrices')),
      'clobTokenIds':arr(m.get('clobTokenIds')),'volume':float(m.get('volume') or 0),
      'resolutionSource':m.get('resolutionSource'),'youtube_ids':youtube_ids(m),'urls':all_urls(m),
      'text_numbers':re.findall(r'(?<![A-Za-z])\$?\d+(?:\.\d+)?\s*[kmb]?(?![A-Za-z])',text,re.I),
    }

def main():
    found={}; errors=[]
    for q in QUERIES:
      for status in ('resolved','active'):
       for page in range(8):
        try:r=get('https://gamma-api.polymarket.com/public-search',{'q':q,'events_status':status,'limit_per_type':50,'page':page,'keep_closed_markets':1,'search_tags':'false','search_profiles':'false'})
        except Exception as ex:errors.append({'stage':'search','q':q,'status':status,'page':page,'error':repr(ex)});break
        rows=(r.get('events') or []) if isinstance(r,dict) else []
        if not rows:break
        for ev in rows:
            text=txt_fields(ev).lower()+" "+" ".join(txt_fields(m).lower() for m in (ev.get('markets') or []))
            if 'view' not in text:continue
            key=str(ev.get('id') or ev.get('slug'));found[key]={'id':ev.get('id'),'slug':ev.get('slug')}
        pag=r.get('pagination') or {}
        if not (r.get('hasMore') or pag.get('hasMore')):break
        time.sleep(.01)
    events=[]
    for seed in found.values():
        try:ev=get('https://gamma-api.polymarket.com/events/slug/'+str(seed['slug']))
        except Exception as ex:errors.append({'stage':'event','seed':seed,'error':repr(ex)});continue
        title=ev.get('title') or ''
        rec={
          'id':ev.get('id'),'slug':ev.get('slug'),'title':title,'horizon_hours':horizon(title+' '+str(ev.get('description') or '')),
          'startDate':ev.get('startDate'),'endDate':ev.get('endDate'),'createdAt':ev.get('createdAt'),'closed':bool(ev.get('closed')),'active':bool(ev.get('active')),
          'volume':float(ev.get('volume') or 0),'description':ev.get('description'),'resolutionSource':ev.get('resolutionSource'),
          'youtube_ids':youtube_ids(ev),'urls':all_urls(ev),'markets':[compact_market(m) for m in (ev.get('markets') or [])]
        }
        # Include source ids/URLs appearing only at market level.
        rec['youtube_ids']=sorted(set(rec['youtube_ids']+sum((m['youtube_ids'] for m in rec['markets']),[])))
        rec['urls']=sorted(set(rec['urls']+sum((m['urls'] for m in rec['markets']),[])))
        events.append(rec);time.sleep(.01)
    # Exact grouping only: common YouTube video id. Everything else remains ungrouped.
    by_video=defaultdict(list)
    for ev in events:
        for yid in ev['youtube_ids']:by_video[yid].append(ev)
    groups=[]
    for yid,rows in by_video.items():
        uniq={str(x['id']):x for x in rows};rows=sorted(uniq.values(),key=lambda x:(x.get('horizon_hours') or 9999,x.get('endDate') or ''))
        groups.append({'youtube_id':yid,'events':len(rows),'horizons':sorted(set(x['horizon_hours'] for x in rows if x['horizon_hours'])),'total_volume':sum(x['volume'] for x in rows),'rows':[{'id':x['id'],'slug':x['slug'],'title':x['title'],'horizon_hours':x['horizon_hours'],'startDate':x['startDate'],'endDate':x['endDate'],'volume':x['volume'],'market_count':len(x['markets'])} for x in rows]})
    groups.sort(key=lambda g:(len(g['horizons']),g['total_volume']),reverse=True)
    multi=[g for g in groups if len(g['horizons'])>=2]
    out={'summary':{'events':len(events),'closed':sum(x['closed'] for x in events),'active':sum(x['active'] and not x['closed'] for x in events),'total_volume':sum(x['volume'] for x in events),'events_with_youtube_id':sum(bool(x['youtube_ids']) for x in events),'exact_video_groups':len(groups),'multi_horizon_exact_groups':len(multi),'multi_horizon_events':sum(g['events'] for g in multi)},'multi_horizon_groups':multi,'all_exact_groups':groups,'events':sorted(events,key=lambda x:x['volume'],reverse=True),'errors':errors}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'summary':out['summary'],'top_multi':multi[:20],'errors':errors[:10]},indent=2))
if __name__=='__main__':main()
