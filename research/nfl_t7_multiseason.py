#!/usr/bin/env python3
"""Force a broad NFL tag pull so T-7 replication is genuinely multi-season.

The prior extended script used Gamma's current NFL series_id and therefore only
returned the 2025 season. This wrapper replaces discovery with the league's
primaryTagId, pages deeply, then reuses the already-audited anchor/calibration
logic unchanged.
"""
from __future__ import annotations
import datetime as dt,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import nfl_t7_extended_replication as study

study.OUT=Path('nfl_t7_multiseason.json')
study.base.CUTOFF_TS=int(dt.datetime(2022,1,1,tzinfo=dt.timezone.utc).timestamp())
study.base.MAX_EVENTS_PER_SPORT=3500

def fetch_by_tag(code,meta):
    errors=[];rows=[]
    tag=meta.get('primaryTagId')
    if not tag:
        xs=[x.strip() for x in str(meta.get('tags') or '').split(',') if x.strip()];tag=xs[-1] if xs else None
    if not tag:return [],[{'sport':code,'error':'no_primary_tag'}],None,None
    off=0
    while len(rows)<study.base.MAX_EVENTS_PER_SPORT:
        lim=min(100,study.base.MAX_EVENTS_PER_SPORT-len(rows))
        try:b=study.base.fetch_page({'limit':lim,'offset':off,'closed':'true','tag_id':tag})
        except Exception as ex:errors.append({'sport':code,'tag_id':tag,'offset':off,'error':repr(ex)});break
        if not isinstance(b,list) or not b:break
        rows.extend(b);off+=len(b)
        if len(b)<lim:break
        time.sleep(.02)
    return rows,errors,'tag_id',tag

study.base.fetch_league=fetch_by_tag

if __name__=='__main__':study.main()
