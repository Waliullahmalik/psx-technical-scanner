"""PSX technical scanner: local, CSV-only, no API or trading execution."""
from __future__ import annotations
import csv, io, math, re
from datetime import date
from pathlib import Path
import pandas as pd
import numpy as np

COLUMNS=['Date','Open','High','Low','Close','Volume']


def parse_prices(source):
    """Read bytes, filename or filelike; accepts standard and Investing.com exports."""
    if isinstance(source,(str,Path)):
        raw=Path(source).read_bytes()
    elif isinstance(source,bytes):
        raw=source
    else:
        raw=source.read()
    if isinstance(raw,str): raw=raw.encode()
    raw=raw.decode('utf-8-sig',errors='replace')
    df=pd.read_csv(io.StringIO(raw),sep=None,engine='python',on_bad_lines='error')
    df.columns=[str(x).strip().lower().replace('\ufeff','') for x in df.columns]
    aliases={'date':['date','datetime','time','timestamp'], 'open':['open','opening'],
             'high':['high'], 'low':['low'], 'close':['close','price','last'],
             'volume':['volume','vol.','vol','traded volume']}
    ren={}
    for dst,opts in aliases.items():
        found=next((x for x in opts if x in df.columns),None)
        if found:ren[found]=dst
    df=df.rename(columns=ren)
    missing=[x for x in ['date','open','high','low','close','volume'] if x not in df.columns]
    if missing:raise ValueError('Missing required OHLCV columns: '+', '.join(missing))
    df=df[['date','open','high','low','close','volume']].copy()
    df['date']=pd.to_datetime(df['date'].astype(str),errors='coerce',dayfirst=False)
    for key in ['open','high','low','close','volume']:
        v=df[key].astype(str).str.replace(',','',regex=False).str.replace('Rs.','',regex=False).str.strip()
        if key=='volume':
            def vol(x):
                x=x.upper().replace(' ','')
                m=re.fullmatch(r'([+-]?[0-9]*\.?[0-9]+)([KMB]?)',x)
                return float(m.group(1))*{'':1,'K':1e3,'M':1e6,'B':1e9}[m.group(2)] if m else np.nan
            df[key]=v.map(vol)
        else:df[key]=pd.to_numeric(v,errors='coerce')
    n_before=len(df)
    df=df.dropna().sort_values('date')
    df=df.drop_duplicates('date',keep=False) # remove conflicting AND same-date duplicates conservatively
    mask=(df[['open','high','low','close']]>0).all(axis=1)&(df.volume>=0)&(df.high>=df[['open','close','low']].max(axis=1))&(df.low<=df[['open','close','high']].min(axis=1))
    df=df.loc[mask].copy()
    df['date']=df['date'].dt.normalize()
    df=df.reset_index(drop=True)
    if len(df)==0:raise ValueError('No valid price rows after validation')
    return df,{'input_rows':n_before,'valid_rows':len(df),'removed_rows':n_before-len(df)}


def enrich(df):
    x=df.copy()
    c=x.close; h=x.high; l=x.low; v=x.volume
    x['ma20']=c.rolling(20).mean();x['ma50']=c.rolling(50).mean();x['ma200']=c.rolling(200).mean()
    change=c.diff();g=change.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean();loss=(-change.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    rs=g/loss.replace(0,np.nan)
    x['rsi14']=100-100/(1+rs)
    x.loc[(loss==0)&(g>0),'rsi14']=100
    x.loc[(loss==0)&(g==0),'rsi14']=50
    prev_close=c.shift(1)
    tr=pd.concat([(h-l),(h-prev_close).abs(),(l-prev_close).abs()],axis=1).max(axis=1)
    x['atr14']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['prior20_high']=h.shift(1).rolling(20).max()
    x['prior20_low']=l.shift(1).rolling(20).min()
    x['vol20']=v.shift(1).rolling(20).mean()
    x['vol_ratio']=v/x.vol20.replace(0,np.nan)
    x['momentum20']=c/c.shift(20)-1
    x['turnover20']=(c*v).rolling(20).median()
    return x


def evaluate(symbol,df,asof=None, max_age_days=7, risk_reward=2.0, atr_mult=1.5):
    today=asof or date.today()
    base={'Symbol':symbol,'Last Date':df.date.iloc[-1].date().isoformat(),'Bars':len(df),'Status':'', 'Score':None,
          'Close':float(df.close.iloc[-1]),'RSI14':None,'Vol Ratio':None,'MA20':None,'MA50':None,
          '20D High':None,'Entry Trigger':None,'Stop Loss':None,'Target 2R':None,'Upside %':None,'Risk %':None,'R:R':None,'Notes':''}
    if len(df)<65:base.update(Status='INSUFFICIENT_HISTORY',Notes='Need at least 65 valid daily bars');return base
    age=(today-df.date.iloc[-1].date()).days
    if age<0 or age>max_age_days:
        base.update(Status='FUTURE_DATE' if age<0 else 'STALE_DATA', Notes=f'Last bar age: {age} calendar days; maximum allowed: {max_age_days}');return base
    x=enrich(df);r=x.iloc[-1];p=x.iloc[-2]
    if not all(np.isfinite(r[k]) for k in ['ma20','ma50','rsi14','atr14','prior20_high','vol_ratio','turnover20']):
        base.update(Status='INVALID_INDICATORS',Notes='Insufficient/invalid indicator inputs');return base
    close=float(r.close); resistance=float(r.prior20_high)
    criteria=[(close>r.ma20,15),(close>r.ma50,15),(r.ma20>r.ma50,10),(r.momentum20>0.03,10),
              (close>=0.96*resistance,15),(48<=r.rsi14<=72,15),(r.vol_ratio>=1.2,10),(r.turnover20>=5_000_000,10)]
    score=sum(weight for ok,weight in criteria if ok)
    breakout=(close>resistance and r.vol_ratio>=1.3 and close>r.ma20)
    pre=(close<=resistance and close>=0.96*resistance and close>r.ma20 and r.ma20>r.ma50 and 45<=r.rsi14<=72 and score>=65)
    status='BREAKOUT_CONFIRMED' if breakout else ('EARLY_WATCH' if pre else ('DEVELOPING' if score>=55 else 'WEAK'))
    # Entry trigger is a conditional reference, not a claim a trade filled.
    entry=(close if breakout else resistance*1.002)
    # ATR stop, anchored to recent support and capped to a sensible technical-risk envelope.
    swing_low=float(x.low.iloc[-10:].min())
    stop=max(0.01,min(entry-float(r.atr14)*atr_mult,swing_low))
    risk=entry-stop
    notes=[]
    if r.rsi14>75:notes.append('RSI extended: avoid chasing')
    if r.turnover20<5_000_000:notes.append('Low liquidity')
    if risk/entry>0.12:notes.append('Wide stop (>12%)')
    if abs(close-resistance)/resistance>0.10:notes.append('Extended above 20-day high')
    if not (0<risk<entry):base.update(Status='NO_VALID_PLAN',Notes='Invalid risk/stop calculation');return base
    target=entry+risk*risk_reward
    base.update(Status=status,Score=score,RSI14=round(float(r.rsi14),2),**{'Vol Ratio':round(float(r.vol_ratio),2),'MA20':round(float(r.ma20),2),'MA50':round(float(r.ma50),2),'20D High':round(resistance,2),'Entry Trigger':round(entry,2),'Stop Loss':round(stop,2),'Target 2R':round(target,2),'Upside %':round(100*(target/entry-1),2),'Risk %':round(100*risk/entry,2),'R:R':round(risk_reward,2),'Notes':'; '.join(notes)})
    return base


def scan_folder(folder, universe, asof=None, max_age_days=7):
    folder=Path(folder)
    records=[]; loaded=[]
    for symbol in universe:
        path=folder/f'{symbol}.csv'
        if not path.is_file():
            records.append({'Symbol':symbol,'Status':'NO_DATA','Notes':'No local CSV'});continue
        try:
            df,info=parse_prices(path)
            records.append(evaluate(symbol,df,asof,max_age_days))
            loaded.append(symbol)
        except Exception as e:
            records.append({'Symbol':symbol,'Status':'DATA_ERROR','Notes':str(e)[:180]})
    out=pd.DataFrame(records)
    out['sort_score']=pd.to_numeric(out['Score'] if 'Score' in out else pd.Series([None]*len(out),index=out.index),errors='coerce').fillna(-1)
    out=out.sort_values(['sort_score','Symbol'],ascending=[False,True]).drop(columns=['sort_score']).reset_index(drop=True)
    return out,loaded
