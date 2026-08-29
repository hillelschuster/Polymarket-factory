#!/usr/bin/env python3
"""Reconstruct Friday/Saturday/Sunday domestic grosses for Polymarket opening-weekend events.

Source: The Numbers daily domestic charts. Research only. No trading.
We use literal 3-calendar-day Fri-Sun events only. Friday and Saturday grosses are the
public state available before a conservative Sunday-afternoon decision; Sunday gross
is retained only as the later realized outcome for backtesting.
"""
from __future__ import annotations
import datetime as dt, html, json, re, time, urllib.request, unicodedata
from html.parser import HTMLParser
from pathlib import Path

INV=Path("boxoffice_weekend_inventory.json")
OUT=Path("boxoffice_state_data.json")
UA={"User-Agent":"Mozilla/5.0 polymarket-factory-research/1.0"}
MONTH={m.lower():i for i,m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"],1)}

class TableRows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=[]; self.in_cell=False
    def handle_starttag(self,tag,attrs):
        if tag=="tr": self.row=[]
        if tag in ("td","th"): self.in_cell=True; self.cell=[]
    def handle_data(self,data):
        if self.in_cell:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()));self.in_cell=False
        if tag=="tr" and self.row:
            self.rows.append(self.row);self.row=[]

def fetch(url,timeout=25):
    req=urllib.request.Request(url,headers=UA)
    last=None
    for i in range(3):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode("utf-8","replace")
        except Exception as ex:
            last=ex
            if i<2:time.sleep(.5*(i+1))
    raise last

def money(s):
    m=re.search(r"\$\s*([0-9][0-9,]*)",s or "")
    return int(m.group(1).replace(",","")) if m else None

def norm(s):
    s=unicodedata.normalize("NFKD",s or "").encode("ascii","ignore").decode()
    s=s.lower().replace("&"," and ")
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return " ".join(s.split())

def movie_title(event_title):
    s=event_title or ""
    s=re.sub(r"\s*\((?:even )?(?:higher|lower) (?:strikes|brackets)\)\s*"," ",s,flags=re.I)
    s=re.sub(r"\s+cont\.?\s*$","",s,flags=re.I)
    s=re.sub(r"\b(?:3|4|5)-day\b"," ",s,flags=re.I)
    s=re.sub(r"\bopening weekend box office\b"," ",s,flags=re.I)
    s=s.strip().strip("'\"“”‘’ ")
    return s

def parse_dates(raw,end_date):
    if not raw:return None
    m=re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})",raw,re.I)
    if not m:return None
    m1=MONTH[m.group(1).lower()];d1=int(m.group(2));m2=MONTH[(m.group(3) or m.group(1)).lower()];d2=int(m.group(4))
    ey=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).year
    em=dt.datetime.fromisoformat(str(end_date).replace("Z","+00:00")).month
    y1=y2=ey
    if em==1 and m2==12:y1=y2=ey-1
    if m2<m1:y2=y1+1
    try:return dt.date(y1,m1,d1),dt.date(y2,m2,d2)
    except:return None

def daily_chart(day):
    url=f"https://www.the-numbers.com/box-office-chart/daily/{day:%Y/%m/%d}"
    p=TableRows();p.feed(fetch(url))
    rows=[]
    for r in p.rows:
        # Main table: Rank | Prev | Title | Gross | ...; secondary table: Rank|Title|Daily|...
        if len(r)>=4 and money(r[3]) is not None:
            title=r[2];gross=money(r[3])
        elif len(r)>=3 and money(r[2]) is not None:
            title=r[1];gross=money(r[2])
        else:continue
        if title and gross is not None:rows.append({"title":title,"gross":gross,"norm":norm(title)})
    # de-duplicate secondary table copies
    d={}
    for r in rows:d[(r["norm"],r["gross"])]=r
    return url,list(d.values())

def similarity(a,b):
    aa=set(norm(a).split());bb=set(norm(b).split())
    if not aa or not bb:return 0.0
    inter=len(aa&bb); union=len(aa|bb)
    j=inter/union
    # Exact normalized containment is common for punctuation/subtitle differences.
    na,nb=norm(a),norm(b)
    if na==nb:return 1.0
    if na in nb or nb in na:return max(j,.90)
    return j

def match(rows,title):
    scored=sorted(((similarity(title,r["title"]),r) for r in rows),key=lambda x:x[0],reverse=True)
    if not scored:return None,[]
    best=scored[0]
    return ({**best[1],"score":best[0]} if best[0]>=.62 else None),[{"score":s,"title":r["title"],"gross":r["gross"]} for s,r in scored[:5]]

def normalize_group(title):
    return norm(movie_title(title))

def main():
    inv=json.loads(INV.read_text())
    # choose one representative event set per movie/weekend, preferring highest volume
    reps={}
    for ev in inv.get("events") or []:
        if not ev.get("closed") or ev.get("weekend_type")!="3-day":continue
        dates=parse_dates(ev.get("weekend_dates_raw"),ev.get("endDate"))
        if not dates or (dates[1]-dates[0]).days!=2:continue
        key=(normalize_group(ev.get("title")),dates[0].isoformat(),dates[1].isoformat())
        if key not in reps or float(ev.get("volume") or 0)>float(reps[key].get("volume") or 0):reps[key]=ev
    cache={};out=[];errors=[]
    for _,ev in sorted(reps.items(),key=lambda kv:parse_dates(kv[1].get("weekend_dates_raw"),kv[1].get("endDate"))[0]):
        first,last=parse_dates(ev.get("weekend_dates_raw"),ev.get("endDate")); title=movie_title(ev.get("title"))
        rec={"event_title":ev.get("title"),"movie_title":title,"event_slug":ev.get("slug"),"event_volume":ev.get("volume"),"friday":first.isoformat(),"sunday":last.isoformat(),"weekend_dates_raw":ev.get("weekend_dates_raw"),"markets":ev.get("markets")}
        vals={}
        for label,day in (("friday",first),("saturday",first+dt.timedelta(days=1)),("sunday",last)):
            try:
                if day not in cache:cache[day]=daily_chart(day)
                url,rows=cache[day];m,cands=match(rows,title)
                vals[label]={"date":day.isoformat(),"url":url,"match":m,"candidates":cands}
            except Exception as ex:
                vals[label]={"date":day.isoformat(),"error":repr(ex)}
        rec["days"]=vals
        gs=[];ok=True
        for label in ("friday","saturday","sunday"):
            m=vals[label].get("match")
            if not m or m.get("score",0)<.62:ok=False;break
            gs.append(m["gross"])
        if ok:
            rec["friday_gross"]=gs[0];rec["saturday_gross"]=gs[1];rec["sunday_gross"]=gs[2];rec["weekend_total"]=sum(gs);rec["sunday_to_saturday"]=gs[2]/gs[1] if gs[1] else None;rec["matched"]=True
        else:
            rec["matched"]=False;errors.append({"event":ev.get("title"),"title":title,"days":vals})
        out.append(rec);time.sleep(.03)
    matched=[r for r in out if r.get("matched")]
    ratios=[r["sunday_to_saturday"] for r in matched if r.get("sunday_to_saturday") is not None]
    ratios_sorted=sorted(ratios)
    def q(p):
        if not ratios_sorted:return None
        x=p*(len(ratios_sorted)-1);lo=int(x);hi=min(lo+1,len(ratios_sorted)-1);w=x-lo
        return ratios_sorted[lo]*(1-w)+ratios_sorted[hi]*w
    summary={"representative_events":len(out),"matched":len(matched),"unmatched":len(out)-len(matched),"ratio_summary":{"n":len(ratios),"min":min(ratios) if ratios else None,"q05":q(.05),"q10":q(.10),"median":q(.50),"q90":q(.90),"q95":q(.95),"max":max(ratios) if ratios else None}}
    payload={"note":"Friday/Saturday are model inputs. Sunday is realized outcome only. The Numbers states prior-day daily grosses are generally available by noon Pacific; later backtest uses a conservative Sunday fixed clock.","summary":summary,"events":out,"errors":errors}
    OUT.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary,"matched":[{"movie":r["movie_title"],"friday":r["friday_gross"],"saturday":r["saturday_gross"],"sunday":r["sunday_gross"],"ratio":r["sunday_to_saturday"],"total":r["weekend_total"]} for r in matched],"unmatched":[e["event"] for e in errors]},indent=2))
if __name__=="__main__":main()
