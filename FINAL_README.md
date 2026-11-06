# PSX Technical Scanner — Final v3.4

A local, research-only Streamlit scanner. Includes **KSE-100 watchlist**, individual/bulk historical CSV import, incremental daily data updates, technical scanning and entry/stop/2R levels, and an on-demand PSX company-page quote fetcher.

## Upgrade an existing v3.1 / v3.2 / v3.3 installation (recommended)
1. Stop Streamlit (Ctrl+C).
2. **Back up your entire project**, especially `data/`.
3. Extract this ZIP to a **new folder**.
4. Copy **only** your existing `data/*.csv` into the new folder's `data/`, overwriting the bundled FFC example only if you have your own real FFC history. Never delete the old folder until the replacement is verified.
5. Open a PowerShell terminal in the new project directory.
6. `python -m pip install -r requirements.txt`
7. `python -m streamlit run app.py`
8. Open http://localhost:8501 and select **Run screening**.

## Live prices
1. Sidebar → **Live PSX quotes — on demand**.
2. Select **Selected tickers**, **All imported stocks**, or **KSE-100 list**.
3. Click **Fetch Live PSX Rates**.
4. Results write to `output/live/live_quotes.csv` and `.json`. Any failure is retained as a failed row; other symbols continue.
5. The scanner continues using your completed daily history for RSI, ATR, and confirmed breakouts. Live quotes are a **provisional overlay** and never overwrite `data/*.csv`.

The source is a public, per-company PSX website page, **not** a documented market-data API or exchange-grade feed. If automated requests are disallowed or begin returning errors, stop the batch and use an authorized provider. Quotes can be delayed or unavailable; a fetched quote should never be presumed real-time without checking its timestamp. Do not use unattended auto-polling. Large batches issue sequential requests and respect the configured delay.

## Daily historical update
Sidebar → Daily Update — incremental → choose multiple ticker CSVs or one combined CSV with `Symbol,Date,Open,High,Low,Close,Volume` → Apply daily updates. Existing candles are preserved; conflicts are blocked by default and corrections generate backups.

## Signals and trading levels
- Statuses: `EARLY_WATCH`, `BREAKOUT_CONFIRMED`, `DEVELOPING`, `WEAK`, plus explicit invalid/missing/stale statuses.
- Entry trigger, ATR-based stop, and mechanical 2R target are **conditional research levels**, not automatic orders or forecasts.
- Historical data must be recent, valid and appropriately adjusted for splits, dividends and other corporate actions for dependable analysis.
- A breakout seen within the session remains **provisional** until a completed daily candle confirms it.

## Command line and tests
- Scan: `python run_scan.py`
- Quote smoke test: `python live_psx.py FFC CHCC SYS`
- Automated tests: `python -m unittest discover -s tests` (or `python -m pytest -q tests` if pytest installed)

**Limitations:** This program does not provide brokerage connectivity, buy/sell execution, live streaming, guaranteed early-stock predictions, fundamental valuation, or a licensed PSX bulk data feed.
