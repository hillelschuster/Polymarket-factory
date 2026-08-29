#!/usr/bin/env python3
"""Probe TheSportsDB NBA season page around regular-season boundaries/cup final."""
import re, urllib.request, datetime as dt
from html.parser import HTMLParser
URL='https://www.thesportsdb.com/season/4387-nba/2025-2026?all=1';UA={'User-Agent':'Mozilla/5.0','Accept':'text/html,*/*'}
class P(HTMLParser):
    def __init__(self):super().__init__();self.in_tr=False;self.in_cell=False;self.cell=[];self.row=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.in_tr=True;self.row=[]
        elif self.in_tr and tag in ('td','th'):self.in_cell=True;self.cell=[]
    def handle_data(self,data):
        if self.in_cell:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.in_cell:self.row.append(' '.join(''.join(self.cell).split()));self.in_cell=False
        elif tag=='tr' and self.in_tr:
            if self.row:self.rows.append(self.row)
            self.in_tr=False;self.row=[]
with urllib.request.urlopen(urllib.request.Request(URL,headers=UA),timeout=40) as r:html=r.read().decode('utf-8','replace')
p=P();p.feed(html);score=re.compile(r'^\d{1,3}\s*-\s*\d{1,3}$');hits=[row for row in p.rows if len(row)>=5 and any(score.match(c) for c in row)]
print('score_rows',len(hits))
watch={dt.date(2025,10,20),dt.date(2025,10,21),dt.date(2025,10,22),dt.date(2025,12,16),dt.date(2025,12,17),dt.date(2026,4,11),dt.date(2026,4,12),dt.date(2026,4,13),dt.date(2026,4,14)}
for row in hits:
    try:d=dt.datetime.strptime(row[0],'%d %b %y').date()
    except:continue
    if d in watch:print(repr(row))
