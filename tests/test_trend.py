import numpy as np
import pandas as pd
import pytest

from src import trend

DAYS = pd.bdate_range("2010-01-01", "2014-12-31")


def make_prices(path_fn, cols=("A", "B")):
    t = np.arange(len(DAYS))
    return pd.DataFrame({c: path_fn(t) for c in cols}, index=DAYS)


def test_rising_series_always_invested_after_warmup():
    px = make_prices(lambda t: 100 * 1.001 ** t)
    w = trend.strategy_weights(trend.month_end_signals(px))
    # first 12 months have no signal, month 13 still uses that empty signal
    assert (w.iloc[:13] == 0).all().all()
    assert (w.iloc[13:] == 0.5).all().all()


def test_falling_series_always_cash():
    px = make_prices(lambda t: 100 * 0.999 ** t)
    w = trend.strategy_weights(trend.month_end_signals(px))
    assert (w == 0).all().all()
    bt = trend.backtest(px, w, cost_bps=5)
    assert (bt["net"] == 0).all()
    assert (bt["turnover"] == 0).all()


def test_no_lookahead():
    """Changing the price path from month t onward must not change weight at t."""
    px = make_prices(lambda t: 100 * 1.001 ** t)
    me = trend.month_end_prices(px).index
    t = me[30]
    shocked = px.copy()
    shocked.loc[shocked.index > me[29]] *= 0.01  # crash during month t
    w0 = trend.strategy_weights(trend.month_end_signals(px))
    w1 = trend.strategy_weights(trend.month_end_signals(shocked))
    assert w0.loc[t].equals(w1.loc[t])  # weight for month t decided at t-1
    assert not w0.loc[me[31]].equals(w1.loc[me[31]])  # signal reacts next month


def test_zero_cost_equals_gross():
    rng = np.random.default_rng(0)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(DAYS), 3)), axis=0)),
                      index=DAYS, columns=list("XYZ"))
    w = trend.strategy_weights(trend.month_end_signals(px))
    bt = trend.backtest(px, w, cost_bps=0)
    pd.testing.assert_series_equal(bt["net"], bt["gross"], check_names=False)
    bt5 = trend.backtest(px, w, cost_bps=5)
    assert (bt5["net"] <= bt5["gross"]).all()
    assert bt5["net"].sum() < bt["net"].sum()


def test_turnover_on_known_switch():
    """Flat prices, one asset switches on then off: 0.5 in, 0.5 out."""
    px = make_prices(lambda t: np.full_like(t, 100.0, dtype=float))
    idx = trend.month_end_prices(px).index
    w = pd.DataFrame(0.0, index=idx, columns=px.columns)
    w.iloc[5:10, 0] = 0.5
    bt = trend.backtest(px, w, cost_bps=10)
    expected = np.zeros(len(idx))
    expected[5] = 0.5
    expected[10] = 0.5
    np.testing.assert_allclose(bt["turnover"].to_numpy(), expected)
    assert bt["cost"].iloc[5] == pytest.approx(0.5 * 10 / 1e4)


def test_equal_weight_baseline_rebalance_turnover():
    """After a move, rebalancing back to 1/N costs exactly the drift."""
    idx = pd.date_range("2010-01-31", periods=3, freq="ME")
    px = pd.DataFrame({"A": [100, 110, 110], "B": [100, 100, 100]}, index=idx, dtype=float)
    bt = trend.buy_and_hold_ew(px, cost_bps=0)
    # month 2: A +10%, B flat -> port +5%; drifted A = 0.55/1.05
    drift_a = 0.55 / 1.05
    assert bt["gross"].iloc[1] == pytest.approx(0.05)
    assert bt["turnover"].iloc[2] == pytest.approx(2 * (drift_a - 0.5))


def test_metrics_drawdown():
    r = pd.Series([0.1, -0.5, 0.2])
    m = trend.metrics(r)
    assert m["Max DD"] == pytest.approx(-0.5)
