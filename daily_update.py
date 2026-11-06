"""Safe, offline incremental daily OHLCV updater for PSX scanner.

Supports one CSV per ticker or one long-form file with a Symbol column.
Never attempts broker access or website scraping.
"""
from __future__ import annotations
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import os
import re
import shutil
import tempfile
import pandas as pd
from scanner import parse_prices

FIELDS = ['date', 'open', 'high', 'low', 'close', 'volume']
PATTERN = re.compile(r'^([A-Z0-9-]{1,25})(?:[_ -](?:HISTORY|HIST|PRICES|OHLCV|CLEAN|DAILY)(?:[_ -].*)?)?$', re.I)


def infer_symbol(filename: str) -> str:
    match = PATTERN.fullmatch(Path(filename).stem.upper().strip())
    if not match:
        raise ValueError(f'Cannot identify symbol from {filename}; rename to FFC.csv or FFC_history.csv')
    return match.group(1).upper()


def _validated(raw: bytes):
    frame, info = parse_prices(raw)
    # Refuse partially invalid updates to avoid silently discarding a bad session.
    if info['removed_rows']:
        raise ValueError(f'{info["removed_rows"]} invalid or duplicate rows: correct source CSV before updating')
    return frame


def _same(a, b):
    return all(abs(float(a[c]) - float(b[c])) <= max(0.00001, abs(float(a[c])) * 1e-8) for c in FIELDS[1:])


def merge_ticker(data_dir: str | Path, ticker: str, raw: bytes, *, correct_existing: bool = False,
                 backups_dir: str | Path | None = None) -> dict:
    """Merge ticker candles by date, refuse conflicts unless correction explicitly allowed.

    All validation happens before writing; creates a backup on any modification.
    """
    ticker = ticker.strip().upper()
    if not re.fullmatch(r'[A-Z0-9-]{1,25}', ticker):
        raise ValueError('Invalid ticker')
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{ticker}.csv'
    incoming = _validated(raw)
    if target.exists():
        existing, info = parse_prices(target)
        if info['removed_rows']:
            raise ValueError(f'Existing {ticker}.csv contains invalid/duplicate rows; repair it before update')
    else:
        existing = pd.DataFrame(columns=FIELDS)
    prior = {r.date.date().isoformat():r for r in existing.itertuples(index=False)}
    # named tuples support attribute lookup
    added, unchanged, corrected, conflicts = [], [], [], []
    for r in incoming.itertuples(index=False):
        day = r.date.date().isoformat()
        before = prior.get(day)
        if before is None:
            added.append(day)
        elif _same(before._asdict(), r._asdict()):
            unchanged.append(day)
        elif correct_existing:
            corrected.append(day)
        else:
            conflicts.append(day)
    if conflicts:
        raise ValueError(f'{ticker}: {len(conflicts)} conflicting dates, e.g. {", ".join(conflicts[:5])}. ' 
                         'No changes saved. Enable correction mode only after verifying the source.')
    if added or corrected:
        combined = pd.concat([existing, incoming], ignore_index=True) if len(existing) else incoming.copy()
        combined = combined.drop_duplicates('date', keep='last').sort_values('date').reset_index(drop=True)
        # Final validation for output quality
        output = combined.rename(columns={c:c.title() for c in FIELDS}).to_csv(index=False, date_format='%Y-%m-%d').encode('utf-8')
        checked = _validated(output)
        if len(checked) != len(combined):
            raise ValueError('Post-merge validation failed; nothing saved')
        if target.exists():
            backup_root = Path(backups_dir) if backups_dir else folder.parent / 'backups'
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            shutil.copy2(target, backup_root / f'{ticker}_{stamp}.csv')
        fd, tmp = tempfile.mkstemp(prefix=f'.{ticker}_', suffix='.tmp', dir=str(folder))
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(output)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return {'symbol': ticker, 'incoming_rows':len(incoming), 'added':len(added),
            'unchanged':len(unchanged), 'corrected':len(corrected),
            'total_rows':len(existing)+len(added), 'last_date': max(incoming.date.max(), existing.date.max()) .strftime('%Y-%m-%d') if len(existing) else incoming.date.max().strftime('%Y-%m-%d'),
            'status':'UPDATED' if added or corrected else 'UNCHANGED'}


def split_market_csv(raw: bytes) -> dict[str, bytes]:
    """Convert a combined multi-ticker daily file into individual CSV payloads."""
    frame = pd.read_csv(BytesIO(raw), sep=None, engine='python')
    cols = {str(c).strip().lower(): c for c in frame.columns}
    symbol_col = next((cols[k] for k in ('symbol','ticker','scrip','security') if k in cols), None)
    if symbol_col is None:
        raise ValueError('Combined file must include Symbol or Ticker column')
    if len(frame) > 2_000_000:
        raise ValueError('Combined file too large; split by date or stock')
    frame = frame.dropna(subset=[symbol_col])
    result = {}
    for ticker, group in frame.groupby(symbol_col):
        ticker = str(ticker).strip().upper()
        if not re.fullmatch(r'[A-Z0-9-]{1,25}', ticker):
            raise ValueError(f'Invalid ticker: {ticker!r}')
        result[ticker] = group.drop(columns=[symbol_col]).to_csv(index=False).encode('utf-8')
    return result


def update_many(data_dir, payloads: dict[str, bytes], *, correct_existing=False, allow_new=False):
    results=[]
    for ticker, raw in sorted(payloads.items()):
        if not allow_new and not (Path(data_dir)/f'{ticker}.csv').exists():
            results.append({'symbol':ticker,'status':'SKIPPED','message':'No existing history; enable Add new stocks to import'})
            continue
        try:
            results.append(merge_ticker(data_dir,ticker,raw,correct_existing=correct_existing))
        except Exception as exc:
            results.append({'symbol':ticker,'status':'FAILED','message':str(exc)})
    return pd.DataFrame(results)
