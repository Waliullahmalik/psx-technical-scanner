"""PSX company-page quote pilot; research-only snapshots, NEVER writes daily OHLCV CSVs.

Requires beautifulsoup4. HTML structure is not an official API and may change.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, math, os, re, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

BASE='https://dps.psx.com.pk'
TZ=dt.timezone(dt.timedelta(hours=5))
FIELDS=['Symbol','Company','Quote Time PKT','Fetch Time PKT','Last','Open','High','Low','Volume','LDCP','Change %','Source','Status','Error']
class QuoteError(ValueError): pass
class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target=urljoin(req.full_url,newurl);p=urlparse(target)
        if p.scheme!='https' or p.hostname!='dps.psx.com.pk': raise QuoteError('Unexpected redirect blocked')
        return super().redirect_request(req,fp,code,msg,headers,target)

def fetch_company(symbol, timeout=15):
    import urllib.error
    sym=symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9-]{1,25}',sym):raise QuoteError('Invalid ticker')
    url=f'{BASE}/company/{sym}'
    opener=build_opener(SafeRedirects())
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; PSXResearchPilot/1.0)','Accept':'text/html'})
    with opener.open(req,timeout=timeout) as resp:
        if not resp.headers.get('Content-Type','').lower().startswith('text/html'): raise QuoteError('Unexpected response content-type')
        body=resp.read(4_000_001)
        if len(body)>4_000_000:raise QuoteError('HTML too large')
        return body.decode('utf-8',errors='replace')

def num(s):
    s=str(s).replace(',','').replace('Rs.','').replace('%','').strip()
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',s):raise QuoteError('Invalid numeric value: '+repr(s)[:70])
    x=float(s)
    if not math.isfinite(x):raise QuoteError('Nonfinite number')
    return x

def parse_company(html,symbol):
    soup=BeautifulSoup(html,'html.parser')
    for item in soup(['script','style','noscript']):item.decompose()
    name=soup.select_one('.quote__name')
    price=soup.select_one('.quote__close')
    date=soup.select_one('.quote__date')
    if not (name and price and date): raise QuoteError('Missing PSX primary quote selectors (name, close or date)')
    company=name.get_text(' ',strip=True)
    last=num(price.get_text(' ',strip=True))
    raw_time=date.get_text(' ',strip=True)
    raw_time=re.sub(r'^\s*\^?\s*As of\s*','',raw_time,flags=re.I).strip()
    try:
        parsed=dt.datetime.strptime(raw_time,'%a, %b %d, %Y %I:%M %p').replace(tzinfo=TZ)
    except ValueError as e:raise QuoteError('Invalid quote timestamp: '+raw_time) from e
    now=dt.datetime.now(TZ)
    if parsed>now+dt.timedelta(minutes=10):raise QuoteError('Future quote timestamp')
    # Scope to the REG board between its label and the first subsequent DFC label.
    # This prevents mixing secondary trading boards (DFC/CSF/ODL) with main-equity quote.
    visible=[v.strip() for v in soup.get_text('\n',strip=True).splitlines() if v.strip()]
    ix=next((i for i,s in enumerate(visible) if re.search(r'\bAs of\b',s,re.I) and raw_time in s),None)
    if ix is None:raise QuoteError('Cannot locate primary quote in text')
    tail=visible[ix+1:]
    reg=next((i for i,x in enumerate(tail[:25]) if x.upper()=='REG'),None)
    if reg is None:raise QuoteError('REG board marker missing')
    # Tab navigation may list REG DFC CSF ODL before the actual table. Skip this nav.
    start=reg+1
    while start<len(tail) and tail[start].upper() in {'DFC','CSF','ODL','REG'}:start+=1
    segment=tail[start:]
    cut=next((i for i,x in enumerate(segment) if x.lower().startswith('last update:') or x.upper()=='DFC'),None)
    # The first Last update often signals the beginning of the secondary board.
    if cut is not None:segment=segment[:cut]
    def field(label):
        for i,x in enumerate(segment):
            if x.strip().lower()==label.lower() and i+1<len(segment):return num(segment[i+1])
        raise QuoteError('Missing REG field: '+label)
    opened,high,low,volume,ldcp=[field(x) for x in ('Open','High','Low','Volume','LDCP')]
    if min(last,opened,high,low,ldcp)<=0 or volume<0:raise QuoteError('Nonpositive price or negative volume')
    if low>min(opened,last) or high<max(opened,last) or low>high:raise QuoteError('OHLC inconsistency in primary quote')
    return dict(Symbol=symbol.upper(),Company=company,**{'Quote Time PKT':parsed.isoformat(),'Fetch Time PKT':now.isoformat()},Last=last,Open=opened,High=high,Low=low,Volume=int(volume),LDCP=ldcp,**{'Change %':round(100*(last/ldcp-1),3)},Source=f'{BASE}/company/{symbol.upper()}',Status='OK',Error='')

def pilot(symbols,out_dir,delay=1.5,progress=None):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    records=[]
    for i,sym in enumerate(symbols):
        sym=sym.upper().strip()
        try:
            rec=parse_company(fetch_company(sym),sym)
            print(f'[{sym}] OK last={rec["Last"]} time={rec["Quote Time PKT"]}')
        except Exception as exc:
            rec={c:'' for c in FIELDS};rec.update(Symbol=sym,Status='FAILED',Source=f'{BASE}/company/{sym}',Error=f'{type(exc).__name__}: {exc}')
            print(f'[{sym}] FAILED: {rec["Error"]}')
        records.append(rec)
        if progress is not None: progress(i + 1, len(symbols), rec)
        if i+1<len(symbols):time.sleep(max(0,delay))
    path=out/'live_quotes.csv'
    # Replace snapshots atomically so a previous valid file survives interrupted writes.
    csv_tmp=out/'live_quotes.csv.tmp'
    json_tmp=out/'live_quotes.json.tmp'
    with csv_tmp.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(records)
    json_tmp.write_text(json.dumps(records,indent=2),encoding='utf-8')
    os.replace(csv_tmp,path)
    os.replace(json_tmp,out/'live_quotes.json')
    print('Saved:',path)
    return records

if __name__=='__main__':
    p=argparse.ArgumentParser(description='PSX three-stock quote smoke test; no historical CSV changes')
    p.add_argument('symbols',nargs='*',default=['FFC','CHCC','SYS']);p.add_argument('--output',default='output/live');p.add_argument('--delay',type=float,default=1.5)
    a=p.parse_args()
    pilot(a.symbols,a.output,a.delay)
