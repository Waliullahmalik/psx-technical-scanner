from pathlib import Path
import os
import re
import pandas as pd
import streamlit as st
from scanner import parse_prices, scan_folder, enrich
from daily_update import infer_symbol, split_market_csv, update_many
from live_psx import pilot as fetch_live_quotes

PUBLIC_VIEW = os.getenv('PSX_PUBLIC_VIEW', '0') == '1'
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
st.set_page_config(page_title='PSX Technical Scanner', layout='wide')
st.title('PSX Technical Scanner')
st.caption('KSE-100 technical screening and conditional entry/exit levels · research only')
if PUBLIC_VIEW:
    st.info('Shared read-only dashboard. Signals use the last uploaded completed daily candles; live snapshots are only as fresh as the owner-approved published refresh.')
universe = pd.read_csv(ROOT / 'kse100_symbols.csv')
symbols = universe.Symbol.astype(str).str.upper().tolist()


def ticker_from_filename(filename):
    """Accept ABL.csv or ABL_history_2025.csv, not arbitrary silently-mapped names."""
    stem = Path(filename).stem.upper().strip()
    match = re.fullmatch(r'([A-Z0-9-]{1,25})(?:[_ -](?:HISTORY|HIST|PRICES|OHLCV|CLEAN|DAILY)(?:[_ -].*)?)?', stem)
    return match.group(1) if match else None


def import_file(upload, ticker):
    df, info = parse_prices(upload.getvalue())
    normalized = df.rename(columns={col: col.title() for col in df.columns})
    normalized.to_csv(DATA / f'{ticker}.csv', index=False, date_format='%Y-%m-%d')
    return info


if not PUBLIC_VIEW:
    with st.sidebar:
        st.header('Historical data')
        mode = st.radio('Import mode', ['Multiple CSVs (ticker from filename)', 'Single CSV (select ticker)'])
        if mode.startswith('Multiple'):
            uploaded_files = st.file_uploader('Upload daily OHLCV CSV files', type=['csv'], accept_multiple_files=True, key='multi')
            st.caption('Files must be named like ABL.csv, FFC.csv or CHCC_history_2026.csv. Unrecognized names are rejected.')
            if st.button('Import selected CSVs', type='primary'):
                if not uploaded_files:
                    st.warning('Choose at least one CSV file.')
                else:
                    successes, failures = [], []
                    seen = set()
                    for upload in uploaded_files:
                        ticker = ticker_from_filename(upload.name)
                        if not ticker:
                            failures.append(f'{upload.name}: cannot identify a ticker from its filename')
                            continue
                        if ticker in seen:
                            failures.append(f'{upload.name}: duplicate ticker {ticker} in upload set')
                            continue
                        seen.add(ticker)
                        try:
                            info = import_file(upload, ticker)
                            successes.append(f'{ticker}: {info["valid_rows"]} rows; {info["removed_rows"]} removed')
                        except Exception as exc:
                            failures.append(f'{upload.name}: {exc}')
                    if successes:
                        st.success(f'Imported {len(successes)} ticker(s): ' + '; '.join(successes[:8]))
                        if len(successes) > 8:
                            st.caption('Remaining imports: ' + '; '.join(successes[8:]))
                    for failure in failures:
                        st.error(failure)
                    if successes:
                        st.session_state.pop('results', None)
        else:
            ticker = st.text_input('PSX ticker for upload', 'FFC').strip().upper()
            upload = st.file_uploader('Upload one daily OHLCV CSV', type=['csv'], key='single')
            if st.button('Import CSV', type='primary'):
                if upload is None:
                    st.error('Select a CSV first.')
                elif not re.fullmatch(r'[A-Z0-9-]{1,25}', ticker):
                    st.error('Invalid ticker.')
                else:
                    inferred = ticker_from_filename(upload.name)
                    if inferred and inferred != ticker:
                        st.error(f'Ticker mismatch: selected {ticker}, but file is {upload.name} ({inferred}). Change the ticker to {inferred} before importing.')
                    elif not inferred:
                        st.error('Cannot determine ticker from filename. Rename the file like ABL.csv to prevent an incorrect mapping.')
                    else:
                        try:
                            info = import_file(upload, ticker)
                            st.success(f'Imported {ticker}: {info["valid_rows"]} valid rows ({info["removed_rows"]} removed).')
                            st.session_state.pop('results', None)
                        except Exception as exc:
                            st.error(f'Import failed: {exc}')
        st.divider()
        st.subheader('Daily Update — incremental')
        st.caption('Upload new daily candles without replacing your history. Accepts one CSV per ticker (e.g. FFC.csv) or a combined file with Symbol,Date,Open,High,Low,Close,Volume.')
        update_mode = st.radio('Update file format', ['Multiple stock CSVs', 'One combined market CSV'], horizontal=True)
        update_files = st.file_uploader('Daily files', type=['csv'], accept_multiple_files=True, key='update_multi') if update_mode.startswith('Multiple') else None
        market_file = st.file_uploader('Daily market file (Symbol + OHLCV)', type=['csv'], key='update_market') if update_mode.startswith('One') else None
        allow_new = st.checkbox('Include stocks without existing history', value=False, help='Otherwise only update tickers already imported.')
        correct_existing = st.checkbox('Allow verified corrections to existing dates', value=False, help='Off by default. Conflicting dates are rejected without changes. When on, prior file is backed up.')
        if st.button('Apply daily updates', type='primary'):
            try:
                payloads = {}
                if update_mode.startswith('Multiple'):
                    if not update_files:
                        raise ValueError('Select daily CSV files first')
                    for uploaded in update_files:
                        sym = infer_symbol(uploaded.name)
                        if sym in payloads:
                            raise ValueError(f'Duplicate file for {sym}')
                        payloads[sym] = uploaded.getvalue()
                else:
                    if market_file is None:
                        raise ValueError('Select a combined market CSV first')
                    payloads = split_market_csv(market_file.getvalue())
                log = update_many(DATA, payloads, correct_existing=correct_existing, allow_new=allow_new)
                log_dir = ROOT / 'output'
                log_dir.mkdir(exist_ok=True)
                log_path = log_dir / 'daily_update_report.csv'
                log.to_csv(log_path, index=False)
                st.session_state['daily_update_log'] = log
                st.session_state.pop('results', None)
                st.session_state['refresh_screening'] = True
                success = int((log.status == 'UPDATED').sum())
                failed = int((log.status == 'FAILED').sum())
                st.success(f'Updated {success} ticker(s); {failed} failed. Report: {log_path.name}')
                if failed:
                    st.warning('Some files failed. See report below. Existing histories were preserved for failed files.')
            except Exception as exc:
                st.error(f'Daily update stopped: {exc}')
        if 'daily_update_log' in st.session_state:
            st.dataframe(st.session_state['daily_update_log'], hide_index=True, use_container_width=True)
            st.download_button('Download daily update report', st.session_state['daily_update_log'].to_csv(index=False).encode(), 'daily_update_report.csv', 'text/csv')
        st.divider()
        st.subheader('Live PSX quotes — on demand')
        st.caption('PSX company-page REG quotes. One snapshot per click; no auto-polling, no changes to historical CSVs. Fetches may fail or be delayed.')
        quote_scope = st.selectbox('Fetch universe', ['Selected tickers', 'All imported stocks', 'KSE-100 list'])
        quote_symbols = st.text_input('Selected symbols (comma separated)', 'FFC, CHCC, SYS', key='live_symbols') if quote_scope == 'Selected tickers' else ''
        delay_seconds = st.number_input('Delay between company requests (seconds)', min_value=1.0, max_value=30.0, value=2.0, step=0.5)
        if st.button('Fetch Live PSX Rates', type='primary'):
            if quote_scope == 'Selected tickers':
                syms = list(dict.fromkeys(x.strip().upper() for x in quote_symbols.split(',') if x.strip()))
            elif quote_scope == 'All imported stocks':
                syms = sorted(x.stem.upper() for x in DATA.glob('*.csv'))
            else:
                syms = symbols
            if not syms or len(syms) > 110 or any(not re.fullmatch(r'[A-Z0-9-]{1,25}', x) for x in syms):
                st.error('Enter valid stock symbols (maximum 110 per run).')
            else:
                progress = st.progress(0, text='Connecting to PSX...')
                def update_progress(done, total, record):
                    progress.progress(done / total, text=f'{done}/{total}: {record["Symbol"]} — {record["Status"]}')
                with st.spinner('Fetching on demand — keep this browser tab open until the run completes'):
                    live_results = fetch_live_quotes(syms, ROOT / 'output' / 'live', delay=float(delay_seconds), progress=update_progress)
                good = sum(x['Status'] == 'OK' for x in live_results)
                if good:
                    st.success(f'{good}/{len(syms)} primary REG quotes retrieved. Saved output/live/live_quotes.csv')
                else:
                    st.error('No valid quotes retrieved; historical records remain unchanged.')
                if good < len(syms):
                    st.warning(f'{len(syms) - good} quote(s) failed; see the failure table below.')
                st.session_state['live_quotes'] = pd.DataFrame(live_results)
        st.divider()
        existing = sorted(p.stem for p in DATA.glob('*.csv'))
        st.subheader('Manage imported CSVs')
        if existing:
            selected_delete = st.selectbox('Choose ticker to remove', existing)
            if st.button('Delete selected dataset'):
                (DATA / f'{selected_delete}.csv').unlink(missing_ok=True)
                st.session_state.pop('results', None)
                st.success(f'Removed {selected_delete}.csv. Run screening to refresh.')
                st.rerun()
        else:
            st.caption('No imported CSVs.')
        max_age = st.number_input('Maximum CSV age (calendar days)', min_value=1, max_value=60, value=7, step=1)
        extras = st.text_input('Additional ticker symbols (comma separated)', '')
        st.caption('Historical signals remain daily-close based. The live quote button never writes daily OHLCV history or places trades.')

else:
    max_age = 7
    extras = ""
    with st.sidebar:
        st.info("Public viewer mode: stock data and snapshots are read-only. Updates are managed by the owner.")
        st.caption("No uploads, deletions, market fetches, or account access are available in public mode.")

custom = [s.strip().upper() for s in extras.split(',') if re.fullmatch(r'[A-Za-z0-9-]{1,25}', s.strip())]
scan_symbols = list(dict.fromkeys(symbols + custom + sorted(p.stem.upper() for p in DATA.glob('*.csv'))))
if st.button('Run screening', type='primary') or 'results' not in st.session_state or st.session_state.pop('refresh_screening', False):
    st.session_state.results, st.session_state.loaded = scan_folder(DATA, scan_symbols, max_age_days=int(max_age))
results = st.session_state.results
usable = results[results.Status.isin(['EARLY_WATCH','BREAKOUT_CONFIRMED','DEVELOPING','WEAK'])]
a,b,c,d = st.columns(4)
a.metric('Universe', len(scan_symbols))
b.metric('Usable data', len(usable))
c.metric('Early watch', int((results.Status == 'EARLY_WATCH').sum()))
d.metric('Breakouts', int((results.Status == 'BREAKOUT_CONFIRMED').sum()))
status_filter = st.multiselect('Filter status', sorted(results.Status.unique()), default=list(sorted(results.Status.unique())))
filtered = results[results.Status.isin(status_filter)].copy()
cols = [col for col in ['Symbol','Status','Score','Last Date','Close','RSI14','Vol Ratio','20D High','Entry Trigger','Stop Loss','Target 2R','Upside %','Risk %','R:R','Notes'] if col in filtered]
st.dataframe(filtered[cols], use_container_width=True, hide_index=True)
st.download_button('Download screening results CSV', results.dropna(axis=1,how='all').to_csv(index=False).encode(), 'psx_screening.csv', 'text/csv')
st.divider()
st.subheader('Live market snapshot — provisional only')
quote_path=ROOT / 'output' / 'live' / 'live_quotes.csv'
if quote_path.exists():
    try:
        live=pd.read_csv(quote_path)
        ok=live[live.Status.eq('OK')].copy()
        if len(ok):
            ok['Quote Time PKT']=pd.to_datetime(ok['Quote Time PKT'],errors='coerce',utc=True).dt.tz_convert('Asia/Karachi')
            now_p=pd.Timestamp.now(tz='Asia/Karachi')
            ok['Quote age (min)']=((now_p-ok['Quote Time PKT']).dt.total_seconds()/60).round(0)
            lookups=[]
            for _,q in ok.iterrows():
                sym=q['Symbol']
                path=DATA / f'{sym}.csv'
                entry={'Symbol':sym,'Live Price':q['Last'],'Quoted At (PKT)':q['Quote Time PKT'],'Age (min)':q['Quote age (min)'],'Live Watch':'NO_HISTORY','Historical 20D High':None,'Historical Signal':None}
                if path.is_file():
                    try:
                        daily, _ = parse_prices(path)
                        if len(daily)>=21:
                            from scanner import enrich
                            historic=enrich(daily)
                            # Use 20 prior completed daily bars; exclude incomplete session from the historical side.
                            hist_date=daily.date.iloc[-1].date()
                            quote_date=q['Quote Time PKT'].date()
                            if hist_date>=quote_date: hist=historic[historic.date.dt.date<quote_date]
                            else:hist=historic
                            if len(hist)>=20:
                                resistance=float(hist.high.tail(20).max())
                                price=float(q['Last'])
                                entry['Historical 20D High']=round(resistance,2)
                                if (quote_date - hist.date.iloc[-1].date()).days > int(max_age):
                                    entry['Live Watch']='STALE_HISTORY — cannot confirm current resistance'
                                else:
                                    entry['Live Watch']='ABOVE_RESISTANCE_PROVISIONAL' if price>resistance else 'NEAR_RESISTANCE_PROVISIONAL' if price>=0.98*resistance else 'BELOW_RESISTANCE'
                                match=results[results.Symbol.eq(sym)]
                                if len(match):entry['Historical Signal']=match.iloc[0]['Status']
                    except Exception as exc: entry['Live Watch']='HISTORY_ERROR: '+str(exc)[:70]
                if pd.isna(q['Quote age (min)']) or q['Quote age (min)']>30 or q['Quote age (min)']<0:
                    entry['Live Watch']='STALE_QUOTE — '+entry['Live Watch']
                lookups.append(entry)
            st.dataframe(pd.DataFrame(lookups),hide_index=True,use_container_width=True)
            st.caption('Live watch compares the last price to resistance from completed historical bars. It does NOT recalculate daily RSI, ATR or confirmed breakout signals from an incomplete session.')
        failures=live[live.Status.ne('OK')]
        if len(failures): st.warning('Quote fetch failures: '+ '; '.join(f'{r.Symbol}: {r.Error}' for _,r in failures.iterrows()))
        st.download_button('Download live quote CSV',quote_path.read_bytes(),'live_quotes.csv','text/csv')
    except Exception as exc: st.error(f'Live snapshot load failed: {exc}')
else:
    st.info('No live quote snapshot published. Historical scanner works without live quotes.') if PUBLIC_VIEW else st.info('Click Fetch Live PSX Rates to take a snapshot. Historical scanner still works without live quotes.')

st.divider()
if st.session_state.loaded:
    sel=st.selectbox('Inspect stock', st.session_state.loaded)
    df,_=parse_prices(DATA / f'{sel}.csv')
    x=enrich(df)
    st.subheader(f'{sel} — daily technical chart')
    try:
        import plotly.graph_objects as go
        fig=go.Figure()
        z=x.tail(180)
        fig.add_trace(go.Candlestick(x=z.date,open=z.open,high=z.high,low=z.low,close=z.close,name='OHLC'))
        fig.add_trace(go.Scatter(x=z.date,y=z.ma20,name='MA20',line={'width':1.5}))
        fig.add_trace(go.Scatter(x=z.date,y=z.ma50,name='MA50',line={'width':1.5}))
        fig.update_layout(height=480,xaxis_rangeslider_visible=False)
        st.plotly_chart(fig,use_container_width=True)
    except ImportError:
        st.line_chart(x.tail(180).set_index('date')[['close','ma20','ma50']])
    match=results[results.Symbol==sel]
    if not match.empty:
        st.write('Technical plan (conditional levels; not a recommendation to place an order)')
        st.table(match[[col for col in ['Symbol','Status','Entry Trigger','Stop Loss','Target 2R','Risk %','Upside %','Notes'] if col in match]].T)
    st.warning('Corporate actions, gaps, transaction costs and intraday stop execution can materially change outcomes. Targets are mechanical 2R levels, not price forecasts.')
else:
    st.info('No historical stock datasets have been published yet. The owner must include data/*.csv in a deployment.') if PUBLIC_VIEW else st.info('Import one or more daily OHLCV CSVs to generate signals. Stocks without data are marked NO_DATA.')
