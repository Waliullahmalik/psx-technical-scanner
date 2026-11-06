# v3.3 — PSX Company-page Live Quote Pilot

**Scope:** Chart scanner, Entry/Exit Planner, on-demand quote snapshots. No broker orders, no financial valuations.

## Upgrade safely

1. Stop Streamlit (`Ctrl+C`). Back up your existing `data/` folder.
2. Install `beautifulsoup4` with `python -m pip install beautifulsoup4` (or install the updated `requirements.txt`).
3. Copy **`app.py`** and **`live_psx.py`** from this release to your existing v3.2 application folder. Leave its existing `data/` untouched.
4. Start: `python -m streamlit run app.py`.
5. In the sidebar, enter `FFC, CHCC, SYS` and click **Fetch Live PSX Rates**. The results and any errors appear in the Live Snapshot section.

Or extract the full package to a **new** folder and copy your existing `data/*.csv` into its `data/` folder.

## Direct three-stock smoke test

```powershell
python live_psx.py FFC CHCC SYS
```

Outputs:

- `output/live/live_quotes.csv`: latest fetched REG quote per stock and explicit failures
- `output/live/live_quotes.json`: same data as JSON
- Your existing `data/*.csv`: **not changed**

## Parsing and safety details

- `https://dps.psx.com.pk/company/{TICKER}` is an **unofficial HTML integration**, not a guaranteed API; layout and network behavior may change.
- Extracts primary quote by `.quote__name`, `.quote__close`, `.quote__date`, followed by the REG board. Never uses DFC/CSF/ODL fields for REG.
- Saves symbol, company, quote timestamp PKT, fetch timestamp PKT, last, open, high, low, volume, LDCP, change %, status and error.
- Validates numeric values, basic OHLC bounds, HTTPS redirect host and response size. Failures do not overwrite historical data.
- A live-price breakout is **provisional**. Historic RSI/ATR and confirmed close-based breakouts remain based on completed imported candles.
- The dashboard marks quotes more than 30 minutes old as stale. Overnight and weekend quotes will naturally be stale.
- A fixed lookback against the most recent 20 **completed** historical sessions is used for a provisional resistance comparison.
- **Do not press Daily Update with `live_quotes.csv`**: that file is a live snapshot, not completed daily OHLCV.
- The initial button caps fetches at 10 tickers per click; verify site access and data-use rights before expanding to unattended 100-stock polling. Use a licensed data feed for production use.

## Verification status

Local tests pass with representative mock HTML. Independent publicly indexed PSX pages displayed FFC, CHCC and SYS quote fields on 2026-11-06, but direct Python access from this build environment failed due DNS/network restrictions. Live automated extraction must be verified from your Windows environment. SYS's indexed quote was dated 2026-11-05, so timestamp validation is essential.

## Tests

`python -m unittest discover -s tests -v`
