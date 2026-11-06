# PSX Technical Scanner v3 — KSE-100

**Scope is deliberately limited:** (1) Chart Scanner for KSE-100 breakouts, RSI and relative volume; (2) conditional technical entry, stop-loss and 2R target. No fundamentals, LLM, brokerage, Monte Carlo or web scraping.

## Windows quick start

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Or double-click `START.bat` after dependencies are installed.

Dashboard: http://localhost:8501

## Data imports

- One file per ticker: `data/FFC.csv`, `data/MARI.csv`, etc.
- Standard CSV: `Date,Open,High,Low,Close,Volume`.
- Investing.com-style: `Date,Price,Open,High,Low,Vol.,Change %` (additional columns ignored). Volume suffixes K/M/B supported.
- Upload from the sidebar and press **Import CSV**, then **Run screening**.
- Existing **cleaned** FFC daily example included, with last complete bar Nov 3, 2026. This is a user-provided research dataset, *not* newly downloaded or automatically corporate-action-adjusted.
- Data must be recent (by default <=7 calendar days) and contain >=65 valid bars to qualify. The preview chart uses 180 latest bars.
- Conflicting duplicate dates and malformed OHLC prices are dropped conservatively. Check import notices. No missing bars are invented.
- Stocks lacking data are marked `NO_DATA`. No fake rankings.
- To add any extra PSX ticker, import its CSV; it automatically joins the scan, or type it under additional tickers.
- `kse100_symbols.csv` contains a snapshot of 100 symbols from the official PSX KSE100 constituents page as observed Nov 4 2026. Update for future recompositions: https://dps.psx.com.pk/indices/KSE100

## Scanner rules (transparent heuristic, not win probability)

Scores (total 100): close above MA20 (15), close above MA50 (15), MA20>MA50 (10), 20D momentum >3% (10), within 4% of prior 20D high (15), RSI14 48-72 (15), volume / prior 20D volume >=1.2 (10), median turnover 20D >=PKR 5m (10).

- `EARLY_WATCH`: below/at prior 20D high, within 4%, ascending MA20/MA50, RSI 45-72, score >=65.
- `BREAKOUT_CONFIRMED`: close above *prior* 20D high, volume ratio >=1.3, close above MA20.
- `DEVELOPING`: score >=55 without the above setup.
- `WEAK`: everything else with adequate data.

Indicators use only bars available through the evaluation date. `prior20_high` excludes current day to avoid lookahead. Volume ratio compares current volume with the *previous* 20-day mean.

## Entry / exit plan

- Confirmed breakout: reference entry = last daily close (not a guaranteed executable fill).
- Otherwise: buy-stop trigger = prior 20-day high x 1.002 (0.2% buffer); conditional level, *not* instruction to execute.
- Stop = lower of (entry - 1.5 x ATR14) and the last 10 daily lows. This can produce a wide stop; risk percent is shown.
- Target = entry + 2 x (entry - stop) (mechanical reward/risk = 2:1). Upside in dashboard is measured from planned entry, **not** current market price. Not a forecast or fundamental price target.
- Inputs are historical daily closes; open gaps, slippage, splits, rights, dividends, liquidity and market constraints can invalidate a suggested level. Validate adjusted/unadjusted basis before interpreting technical triggers.

## CLI

```powershell
python run_scan.py
```

Output: `output/screening.csv`. No automatic fetching, paid subscriptions or keys required.

## Unit tests

```powershell
python -m unittest discover -s tests -v
```

## v3.1 mapping fix

- Multi-file import reads tickers from filenames: ABL.csv -> ABL, FFC.csv -> FFC.
- Single-file upload rejects mismatch between file name and selected ticker.
- Sidebar **Manage imported CSVs** can delete an incorrectly mapped dataset.
- After changing data, click **Run screening** to refresh.
- To correct a previously imported ABL.csv labelled as FFC: delete the wrong `FFC` entry, import `ABL.csv` using multi-file mode, then separately import actual `FFC.csv` if available.


## v3.2 Daily Updates (new)

Use **Daily Update — incremental** in the Streamlit sidebar. This is an **offline importer**, not a live market-data downloader. Obtain new daily OHLCV CSVs from a source you are authorized to use.

- **Multiple stock CSVs:** upload `FFC.csv`, `ABL.csv`, and others simultaneously. Ticker is inferred from the filename.
- **One combined market CSV:** upload a file with the exact logical fields `Symbol,Date,Open,High,Low,Close,Volume` (case-insensitive). The importer separates rows by Symbol.
- **Existing records are retained:** adds previously unseen dates and skips identical date+OHLCV records.
- **Conflicting records are blocked by default:** explicitly enable **Allow verified corrections** to replace same-date rows after checking your source; a timestamped original-file backup is then created in `backups/`.
- **No partial invalid imports:** any invalid/duplicate date inside a ticker's new CSV causes that ticker's import to fail without updating its existing file. Other tickers can still be processed.
- **Avoid importing incomplete intraday candles** as the day's final OHLCV; update only after market close.
- Results are recorded in `output/daily_update_report.csv`; rerun screening to refresh scores (the dashboard also refreshes after an update).
- **Include stocks without existing history** is OFF by default; turn it on only when the CSV contains enough history for scanner indicators.

### Upgrade an existing working v3.1 installation without deleting your 100 imported files

1. Stop Streamlit (`Ctrl+C`). Make a backup copy of your existing `data/` folder.
2. Extract v3.2 **somewhere else**; copy only its `app.py` and `daily_update.py` into the existing v3.1 application folder, replacing `app.py`. The existing `scanner.py`, `data/`, `kse100_symbols.csv`, and Python installation can stay as they are.
3. Start `python -m streamlit run app.py`.
4. In **Daily Update — incremental**, upload one or more small daily CSVs and click **Apply daily updates**. Inspect the per-ticker update report before relying on refreshed signals.

**Note:** This package also contains example FFC history for a fresh installation. Do not overwrite your existing `data/` folder with it.
