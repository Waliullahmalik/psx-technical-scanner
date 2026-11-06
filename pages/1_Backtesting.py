"""PSX scanner backtesting page (v1.1).
Upload to GitHub: pages/1_Backtesting.py
Requires existing scanner.py, data/*.csv, pandas, numpy and Streamlit.

Research simulation: end-of-day signals, next-session open execution, fixed protective
stops, conservative treatment when stop and target are both touched, and transaction costs.
END_OF_DATA exits are marked censored and excluded from completed-trade statistics.
No orders are placed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scanner import enrich, parse_prices  # noqa: E402

DATA = ROOT / "data"
st.set_page_config(page_title="PSX | Backtesting", layout="wide")
st.title("PSX Technical Scanner | Backtesting")
st.caption("Replays historical daily candles. Baseline matches scanner.py signal rules; V2 is an experimental filter, not a validated trading strategy.")


def valid_number(x):
    try:
        return bool(np.isfinite(float(x)))
    except (TypeError, ValueError):
        return False


def signal_at(x: pd.DataFrame, i: int, strategy: str, score_limit: int, volume_limit: float, risk_limit: float):
    """Replicate scanner.evaluate technical conditions using precomputed indicators.

    Signals use bars 0..i only; no future bars are read. Unlike the live scanner,
    historical bars are not rejected for staleness.
    """
    if i < 64:
        return None
    r = x.iloc[i]
    fields = ("ma20", "ma50", "rsi14", "atr14", "prior20_high", "vol_ratio", "turnover20", "momentum20")
    if not all(valid_number(r[k]) for k in fields):
        return None
    close, resistance = float(r.close), float(r.prior20_high)
    if resistance <= 0:
        return None
    criteria = (
        (close > r.ma20, 15),
        (close > r.ma50, 15),
        (r.ma20 > r.ma50, 10),
        (r.momentum20 > 0.03, 10),
        (close >= 0.96 * resistance, 15),
        (48 <= r.rsi14 <= 72, 15),
        (r.vol_ratio >= 1.2, 10),
        (r.turnover20 >= 5_000_000, 10),
    )
    score = sum(points for passed, points in criteria if passed)
    breakout = close > resistance and r.vol_ratio >= 1.3 and close > r.ma20
    if not breakout:
        return None

    planned_entry = close  # exact original confirmed-breakout reference
    swing_low = float(x.low.iloc[i - 9:i + 1].min())
    stop = max(0.01, min(planned_entry - float(r.atr14) * 1.5, swing_low))
    risk = planned_entry - stop
    if not (0 < risk < planned_entry):
        return None
    risk_pct = 100 * risk / planned_entry
    if strategy == "V2":
        if not (
            score >= score_limit
            and float(r.vol_ratio) >= volume_limit
            and r.ma20 > r.ma50
            and 50 <= r.rsi14 <= 70
            and risk_pct <= risk_limit
        ):
            return None
    return {
        "Signal Date": r.date.date().isoformat(),
        "Signal Close": round(close, 4),
        "Score": int(score),
        "Volume Ratio": round(float(r.vol_ratio), 3),
        "RSI14": round(float(r.rsi14), 2),
        "Resistance": round(resistance, 4),
        "Planned Stop": stop,
        "Signal Risk %": round(risk_pct, 2),
    }


def execute_trade(x: pd.DataFrame, signal_i: int, signal: dict, horizon: int, rr: float, fee_bps: float):
    """Enter at next session OPEN, exit by stop/target or the horizon close.

    The stop established on signal day remains fixed. Target is 2R (configurable)
    measured from executed entry to that stop, rather than an impossible assumed
    fill at the prior day's closing price.
    """
    entry_i = signal_i + 1
    if entry_i >= len(x):
        return None, signal_i + 1
    entry_bar = x.iloc[entry_i]
    entry = float(entry_bar.open)
    stop = float(signal["Planned Stop"])
    if entry <= stop:
        return None, entry_i  # gap through the stop before entering: skip
    risk = entry - stop
    target = entry + rr * risk
    if entry <= 0:
        return None, entry_i
    last_i = min(len(x) - 1, entry_i + horizon - 1)
    exit_i = last_i
    exit_price = float(x.iloc[last_i].close)
    reason = "TIME_EXIT" if last_i == entry_i + horizon - 1 else "END_OF_DATA"
    for j in range(entry_i, last_i + 1):
        bar = x.iloc[j]
        o, h, l = float(bar.open), float(bar.high), float(bar.low)
        if j > entry_i and o <= stop:
            exit_i, exit_price, reason = j, o, "STOP_GAP"
            break
        if j > entry_i and o >= target:
            exit_i, exit_price, reason = j, o, "TARGET_GAP"
            break
        # Both touched in the same daily bar: assume the stop was filled first.
        if l <= stop:
            exit_i, exit_price, reason = j, stop, "STOP"
            break
        if h >= target:
            exit_i, exit_price, reason = j, target, "TARGET"
            break
    gross_pct = (exit_price / entry - 1.0) * 100
    # Symmetric turnover-based friction, charged on entry and exit notional.
    cost_rate = fee_bps / 10_000
    net_return = (exit_price * (1 - cost_rate)) / (entry * (1 + cost_rate)) - 1
    net_pct = 100 * net_return
    net_r = ((exit_price * (1 - cost_rate)) - entry * (1 + cost_rate)) / risk
    result = {
        **{k: v for k, v in signal.items() if k != "Planned Stop"},
        "Entry Date": entry_bar.date.date().isoformat(),
        "Entry": round(entry, 4),
        "Stop": round(stop, 4),
        "Target": round(target, 4),
        "Exit Date": x.iloc[exit_i].date.date().isoformat(),
        "Exit": round(exit_price, 4),
        "Exit Reason": reason,
        "Trade Status": "CENSORED" if reason == "END_OF_DATA" else "COMPLETED",
        "Holding Bars": int(exit_i - entry_i + 1),
        "Gross Return %": round(gross_pct, 4),
        "Net Return %": round(net_pct, 4),
        "Net R": round(net_r, 4),
    }
    return result, exit_i + 1


def run_symbol(symbol: str, frame: pd.DataFrame, strategy: str, score_limit: int, volume_limit: float,
               risk_limit: float, horizon: int, rr: float, fee_bps: float):
    x = enrich(frame)
    trades = []
    i = 64
    while i < len(x) - 1:
        signal = signal_at(x, i, strategy, score_limit, volume_limit, risk_limit)
        if signal is None:
            i += 1
            continue
        trade, resume_i = execute_trade(x, i, signal, horizon, rr, fee_bps)
        if trade is not None:
            trade["Symbol"] = symbol
            trade["Strategy"] = strategy
            trades.append(trade)
        i = max(i + 1, resume_i)  # no overlapping positions in same stock
    return trades


def performance(trades: pd.DataFrame, label: str):
    """Only genuinely completed trades enter performance statistics.

    END_OF_DATA is not an executed exit: its mark-to-market price and return remain
    visible in the trade ledger, but must not be treated as realized P&L.
    """
    closed = trades.loc[trades["Trade Status"].eq("COMPLETED")] if not trades.empty else trades
    base = {
        "Strategy": label,
        "Signals Entered": len(trades),
        "Completed": len(closed),
        "Censored": len(trades) - len(closed),
        "Win Rate %": None,
        "Avg Net %": None,
        "Avg Net R": None,
        "Profit Factor": None,
        "Target Hit %": None,
    }
    if closed.empty:
        return base
    net = closed["Net Return %"]
    positives = net[net > 0].sum()
    negatives = -net[net < 0].sum()
    pf = positives / negatives if negatives > 0 else (float("inf") if positives > 0 else np.nan)
    base.update({
        "Win Rate %": round(100 * (net > 0).mean(), 2),
        "Avg Net %": round(float(net.mean()), 3),
        "Avg Net R": round(float(closed["Net R"].mean()), 3),
        "Profit Factor": round(float(pf), 3) if np.isfinite(pf) else None,
        "Target Hit %": round(100 * closed["Exit Reason"].isin(["TARGET", "TARGET_GAP"]).mean(), 2),
    })
    return base


def stock_summary(trades: pd.DataFrame) -> pd.DataFrame:
    """Ticker and strategy results; censored trades never inflate closed P&L."""
    columns = ["Symbol", "Strategy", "Signals Entered", "Completed", "Censored",
               "Win Rate %", "Avg Net %", "Avg Net R", "Profit Factor", "Target Hit %"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (symbol, strategy), group in trades.groupby(["Symbol", "Strategy"], sort=True):
        m = performance(group, strategy)
        rows.append({"Symbol": symbol, **m})
    out = pd.DataFrame(rows, columns=columns)
    return out.sort_values(["Strategy", "Completed", "Symbol"],
                           ascending=[True, False, True]).reset_index(drop=True)


files = sorted(DATA.glob("*.csv")) if DATA.exists() else []
if not files:
    st.warning("No historical files found in data/. Add the CSVs to your deployed repository first.")
    st.stop()

names = [file.stem.upper() for file in files]
with st.sidebar:
    st.header("Backtest settings")
    chosen = st.multiselect("Stocks", names, default=names)
    horizon = st.select_slider("Maximum holding period (trading bars)", options=[5, 10, 20, 30, 60], value=20)
    rr = st.number_input("Reward / risk target", min_value=1.0, max_value=5.0, value=2.0, step=0.5)
    fee_bps = st.number_input("Cost per side (basis points)", min_value=0.0, max_value=200.0, value=15.0, step=5.0,
                              help="Applies equally to entry and exit; include commission, taxes and slippage allowance.")
    st.subheader("Experimental V2 filters")
    score_limit = st.slider("Minimum score", 50, 95, 70, 5)
    volume_limit = st.slider("Minimum volume ratio", 1.0, 4.0, 1.5, 0.1)
    risk_limit = st.slider("Maximum signal stop risk (%)", 2.0, 20.0, 8.0, 0.5)
    go = st.button("Run V1 vs V2 backtest", type="primary", use_container_width=True)

st.info("V1 uses the original BREAKOUT_CONFIRMED criteria. V2 adds configurable quality filters. Entries occur at the next daily open; historical OHLC is never treated as intraday execution data.")
if not go:
    st.write("Choose stocks and press **Run V1 vs V2 backtest** to calculate actual historical performance.")
    st.stop()
if not chosen:
    st.error("Select at least one ticker.")
    st.stop()

all_trades = []
failures = []
progress = st.progress(0, text="Analyzing history...")
for n, symbol in enumerate(chosen, start=1):
    try:
        frame, _ = parse_prices(DATA / f"{symbol}.csv")
        if len(frame) < 66:
            failures.append(f"{symbol}: insufficient data ({len(frame)} candles)")
        else:
            for strategy in ("V1", "V2"):
                all_trades.extend(run_symbol(symbol, frame, strategy, score_limit, volume_limit,
                                             risk_limit, horizon, rr, fee_bps))
    except Exception as exc:
        failures.append(f"{symbol}: {str(exc)[:160]}")
    progress.progress(n / len(chosen), text=f"Processed {n}/{len(chosen)} stocks")

if failures:
    with st.expander(f"Data warnings ({len(failures)})"):
        for msg in failures:
            st.write(msg)
trades = pd.DataFrame(all_trades)
if trades.empty:
    st.warning("No simulated entries. Try more stocks, longer histories or different settings.")
    st.stop()

v1 = trades.loc[trades.Strategy == "V1"].copy()
v2 = trades.loc[trades.Strategy == "V2"].copy()
st.subheader("Strategy comparison — completed trades only")
summary = pd.DataFrame([performance(v1, "V1: Original scanner"), performance(v2, "V2: Quality-filtered")])
st.dataframe(summary, hide_index=True, use_container_width=True)
st.caption(
    "Completed = TARGET, TARGET_GAP, STOP, STOP_GAP or TIME_EXIT. "
    "Censored = END_OF_DATA (insufficient future candles to finish the holding period); "
    "these are excluded from win rate, average returns, profit factor and target hit rate. "
    "Trade-level returns are net of the configured trading costs. No portfolio equity curve "
    "or capital allocation is simulated."
)

closed = trades.loc[trades["Trade Status"] == "COMPLETED"].copy()
censored = trades.loc[trades["Trade Status"] == "CENSORED"].copy()
if not censored.empty:
    st.warning(
        f"{len(censored)} trades are END_OF_DATA / censored. The exit prices recorded "
        "for these rows are last-known closing prices (mark-to-market only), not real exits. "
        "Their returns are excluded from completed-trade metrics."
    )
if closed.empty:
    st.info("No fully resolved trades in the chosen period. More historical future candles "
            "are needed for an unbiased performance assessment.")

st.subheader("Stock-wise profitability — completed trades")
stockwise = stock_summary(trades)
stock_filter = st.radio("Stock breakdown", ["Both", "V1", "V2"], horizontal=True, key="stock_filter")
stock_view = stockwise if stock_filter == "Both" else stockwise.loc[stockwise.Strategy == stock_filter]
st.dataframe(stock_view, hide_index=True, use_container_width=True)
st.caption("Each stock is evaluated separately for V1 and V2. Stocks with only censored "
           "trades show no calculated win rate or profit factor; small samples are unreliable.")
st.download_button("Download stock-wise performance (CSV)",
                   stock_view.to_csv(index=False).encode("utf-8"),
                   file_name="psx_backtest_by_stock.csv", mime="text/csv")

st.subheader("Individual trades")
strategy_filter = st.radio("Show strategy", ["Both", "V1", "V2"], horizontal=True)
completion_filter = st.radio("Trade status", ["All", "Completed", "Censored"], horizontal=True)
view = trades if strategy_filter == "Both" else trades.loc[trades.Strategy == strategy_filter]
if completion_filter != "All":
    view = view.loc[view["Trade Status"] == completion_filter.upper()]
view = view.sort_values(["Entry Date", "Symbol", "Strategy"], ascending=[False, True, True])
st.dataframe(view, use_container_width=True, hide_index=True)
st.download_button("Download trade results (CSV)", view.to_csv(index=False).encode("utf-8"),
                   file_name="psx_backtest_trades.csv", mime="text/csv")
st.download_button("Download strategy comparison (CSV)", summary.to_csv(index=False).encode("utf-8"),
                   file_name="psx_backtest_summary.csv", mime="text/csv")
