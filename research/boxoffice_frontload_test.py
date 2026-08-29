#!/usr/bin/env python3
"""Chronological diagnostic: does Saturday/Friday improve Sunday decay forecasts?

One domain-justified feature only. This is a falsification test, not model tuning.
Uses 10-movie warmup, then predicts each later movie from prior movies only.
No market prices and no trading.
"""
from __future__ import annotations
import json,math,statistics
from pathlib import Path

SRC=Path('boxoffice_state_data.json'); OUT=Path('boxoffice_frontload_test.json'); WARMUP=10

def ols(xs,ys):
    n=len(xs); mx=sum(xs)/n; my=sum(ys)/n
    den=sum((x-mx)**2 for x in xs)
    b=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/den if den else 0.0
    return my-b*mx,b

def mean(xs):return sum(xs)/len(xs)
def median(xs):return statistics.median(xs)
def mae(xs):return mean([abs(x) for x in xs]) if xs else None
def rmse(xs):return math.sqrt(mean([x*x for x in xs])) if xs else None

def main():
    d=json.loads(SRC.read_text()); events=sorted([r for r in d.get('events',[]) if r.get('matched')],key=lambda r:r['sunday'])
    rows=[]
    for i,ev in enumerate(events):
        if i<WARMUP:continue
        prior=events[:i]
        xs=[r['saturday_gross']/r['friday_gross'] for r in prior]
        ys=[r['sunday_to_saturday'] for r in prior]
        a,b=ols(xs,ys); x=ev['saturday_gross']/ev['friday_gross']; actual=ev['sunday_to_saturday']
        preds={'ols_frontload':a+b*x,'prior_mean':mean(ys),'prior_median':median(ys)}
        rec={'movie':ev['movie_title'],'date':ev['sunday'],'prior_n':len(prior),'x_saturday_over_friday':x,'actual_sunday_over_saturday':actual,'ols_slope':b,'predictions':{}}
        for name,pred in preds.items():
            pred_total=ev['friday_gross']+ev['saturday_gross']*(1+pred)
            rec['predictions'][name]={'ratio':pred,'ratio_error':pred-actual,'weekend_error':pred_total-ev['weekend_total'],'abs_weekend_pct_error':abs(pred_total-ev['weekend_total'])/ev['weekend_total']}
        rows.append(rec)
    summary={}
    for name in ('ols_frontload','prior_mean','prior_median'):
        ratio_err=[r['predictions'][name]['ratio_error'] for r in rows]
        pct=[r['predictions'][name]['abs_weekend_pct_error'] for r in rows]
        summary[name]={'n':len(rows),'ratio_mae':mae(ratio_err),'ratio_rmse':rmse(ratio_err),'mean_abs_weekend_pct_error':mean(pct),'median_abs_weekend_pct_error':median(pct)}
    # Full-sample correlation is descriptive only; OOS metrics above determine usefulness.
    xs=[r['saturday_gross']/r['friday_gross'] for r in events]; ys=[r['sunday_to_saturday'] for r in events]
    mx,my=mean(xs),mean(ys); cov=mean([(x-mx)*(y-my) for x,y in zip(xs,ys)]); sx=math.sqrt(mean([(x-mx)**2 for x in xs])); sy=math.sqrt(mean([(y-my)**2 for y in ys])); corr=cov/(sx*sy) if sx and sy else None
    out={'warmup':WARMUP,'events_total':len(events),'oos_events':len(rows),'full_sample_corr_saturday_friday_vs_sunday_saturday':corr,'summary':summary,'rows':rows,'verdict_rule':'Front-loading feature earns further work only if chronological error improvement is large enough to change bracket decisions, not merely statistically nonzero.'}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8'); print(json.dumps({k:v for k,v in out.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
