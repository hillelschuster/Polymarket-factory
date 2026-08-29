#!/usr/bin/env python3
"""Probe TheSportsDB public 2025-26 NBA season page as a reproducible results source."""
import re, urllib.request
from html.parser import HTMLParser
URL='https://www.thesportsdb.com/season/4387-nba/2025-2026?all=1'
UA={'User-Agent':'Mozilla/5.0','Accept':'text/html,*/*'}
class P(HTMLParser):
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
with urllib.request.urlopen(urllib.request.Request(URL,headers=UA),timeout=40) as r:html=r.read().decode('utf-8','replace')
p=P();p.feed(html)
score=re.compile(r'^\d{1,3}\s*-\s*\d{1,3}$')
hits=[row for row in p.rows if any(score.match(c) for c in row)]
print('html_bytes',len(html),'table_rows',len(p.rows),'score_rows',len(hits))
for r in hits[:20]:print(repr(r))
print('LAST')
for r in hits[-20:]:print(repr(r))
