"""12-month trend rule on a small set of commodity ETFs.

Everything here is a pure function of its inputs except ``load_prices``,
which downloads from Yahoo Finance and caches to ``data/prices.csv``.

Conventions
-----------
* All series are monthly and indexed by month-end date.
* ``returns.loc[t]`` is the asset return over the month ending at ``t``.
* ``weights.loc[t]`` is the portfolio held *during* the month ending at ``t``.
  It is decided at the end of month ``t-1``, so it can only use data up to
  ``t-1`` (no look-ahead).
* Whatever is not in an ETF sits in cash, which earns ``cash_return``
  (0% by default).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TICKERS = ["GLD", "SLV", "USO", "UNG", "DBA"]
CACHE = Path(__file__).resolve().parents[1] / "data" / "prices.csv"


# --------------------------------------------------------------------------- data
def load_prices(tickers=TICKERS, start="2007-01-01", end=None, cache=CACHE, refresh=False):
    """Daily dividend/split-adjusted close prices, one column per ticker.

    Downloads with yfinance on first use and caches to ``cache``. Pass
    ``refresh=True`` to force a new download.
    """
    tickers = list(tickers)
    cache = Path(cache)
    if cache.exists() and not refresh:
        px = pd.read_csv(cache, index_col=0, parse_dates=True)
        if set(tickers) <= set(px.columns):
            px = px.loc[px.index >= pd.Timestamp(start), tickers]
            return px if end is None else px.loc[px.index < pd.Timestamp(end)]

    import yfinance as yf

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    px = raw["Close"][tickers].dropna(how="all")
    px.index = pd.to_datetime(px.index).tz_localize(None)
    cache.parent.mkdir(parents=True, exist_ok=True)
    px.to_csv(cache)
    return px


def month_end_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Last available price in each calendar month."""
    return prices.resample("ME").last()


# ------------------------------------------------------------------------ signals
def month_end_signals(prices: pd.DataFrame, lookback: int = 12) -> pd.DataFrame:
    """1 if the trailing ``lookback``-month return at month-end is positive, else 0.

    Months without enough history (e.g. before an ETF existed) get 0, i.e. cash.
    """
    m = month_end_prices(prices)
    past = m.pct_change(lookback, fill_method=None)
    return (past > 0).astype(int)


def strategy_weights(signals: pd.DataFrame, slot: float | None = None) -> pd.DataFrame:
    """Each asset gets an equal slot (1/N) when its signal is on, else 0.

    Shifted by one month: the signal at month-end ``t`` sets the weight held
    during month ``t+1``.
    """
    if slot is None:
        slot = 1.0 / signals.shape[1]
    return (slot * signals).shift(1).fillna(0.0)


def equal_weights(prices: pd.DataFrame) -> pd.DataFrame:
    """Constant 1/N weights on the month-end grid (the buy-and-hold baseline)."""
    m = month_end_prices(prices)
    n = m.shape[1]
    return pd.DataFrame(1.0 / n, index=m.index, columns=m.columns)


# ----------------------------------------------------------------------- backtest
def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return month_end_prices(prices).pct_change(fill_method=None)


def _turnover(weights: pd.DataFrame, rets: pd.DataFrame, cash_return: float) -> pd.Series:
    """One-way-summed turnover needed at the start of each month.

    Compares the target weights for month ``t`` with the weights the portfolio
    drifted to by the end of month ``t-1``. Cash is the residual and is not
    counted separately.
    """
    w = weights.to_numpy()
    r = rets.to_numpy()
    out = np.zeros(len(w))
    prev = np.zeros(w.shape[1])  # start fully in cash
    for i in range(len(w)):
        out[i] = np.abs(w[i] - prev).sum()
        cash = 1.0 - w[i].sum()
        grown = w[i] * (1.0 + r[i])
        total = grown.sum() + cash * (1.0 + cash_return)
        prev = grown / total if total != 0 else np.zeros_like(grown)
    return pd.Series(out, index=weights.index)


def backtest(prices: pd.DataFrame, weights: pd.DataFrame, cost_bps: float = 5.0,
             cash_return: float = 0.0) -> pd.DataFrame:
    """Monthly backtest.

    Returns a DataFrame with columns ``gross``, ``cost``, ``net``, ``turnover``.
    Cost = ``cost_bps`` x turnover, charged in the month the trade happens.
    ``cash_return`` is a monthly rate.
    """
    rets = monthly_returns(prices).reindex(weights.index)
    held = weights.fillna(0.0)
    # An asset with a weight but no return that month (should not happen after
    # the shift) is treated as flat rather than poisoning the whole row.
    rets = rets.fillna(0.0)
    cash_w = 1.0 - held.sum(axis=1)
    gross = (held * rets).sum(axis=1) + cash_w * cash_return
    turnover = _turnover(held, rets, cash_return)
    cost = turnover * cost_bps / 1e4
    return pd.DataFrame({"gross": gross, "cost": cost, "net": gross - cost, "turnover": turnover})


def buy_and_hold_ew(prices: pd.DataFrame, cost_bps: float = 5.0, cash_return: float = 0.0) -> pd.DataFrame:
    """Equal-weight baseline, rebalanced to 1/N each month, same cost model."""
    return backtest(prices, equal_weights(prices), cost_bps, cash_return)


def contributions(prices: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Per-asset gross contribution (weight x return) each month."""
    rets = monthly_returns(prices).reindex(weights.index).fillna(0.0)
    return weights * rets


# ------------------------------------------------------------------------ metrics
def drawdown(returns: pd.Series) -> pd.Series:
    wealth = (1 + returns).cumprod()
    return wealth / wealth.cummax().clip(lower=1.0) - 1


def metrics(bt: pd.DataFrame | pd.Series, col: str = "net") -> pd.Series:
    """Annualized return, vol, Sharpe (rf=0), max drawdown, annual turnover."""
    r = bt[col] if isinstance(bt, pd.DataFrame) else bt
    n = len(r)
    ann_ret = (1 + r).prod() ** (12 / n) - 1 if n else np.nan
    vol = r.std(ddof=1) * np.sqrt(12)
    sharpe = r.mean() * 12 / vol if vol > 0 else np.nan
    out = {
        "Ann. return": ann_ret,
        "Ann. vol": vol,
        "Sharpe": sharpe,
        "Max DD": drawdown(r).min(),
    }
    if isinstance(bt, pd.DataFrame) and "turnover" in bt:
        out["Turnover / yr"] = bt["turnover"].mean() * 12
    return pd.Series(out)
