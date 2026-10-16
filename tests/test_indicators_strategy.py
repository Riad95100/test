import numpy as np
import pandas as pd

from bot.config import StrategyParams
from bot.data import synthetic_m5
from bot.indicators import adx, atr, ema, rsi
from bot.strategy import compute_signals


def _trend(n=200, step=1.0):
    c = pd.Series(100 + np.arange(n) * step, index=pd.date_range("2025-01-06", periods=n, freq="5min", tz="UTC"))
    return pd.DataFrame({"open": c - step / 2, "high": c + 0.2, "low": c - step / 2 - 0.2, "close": c})


def test_rsi_extremes():
    df = _trend()
    assert rsi(df["close"], 14).iloc[-1] == 100.0
    assert rsi(df["close"][::-1].reset_index(drop=True) * -1 + 1000, 14).iloc[-1] == 100.0


def test_ema_matches_manual():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    k = 2 / (3 + 1)
    manual = [1.0]
    for v in s[1:]:
        manual.append(manual[-1] + k * (v - manual[-1]))
    assert np.allclose(ema(s, 3).dropna().to_numpy(), manual[2:])


def test_atr_constant_range():
    idx = pd.date_range("2025-01-06", periods=50, freq="5min", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=idx)
    assert abs(atr(df, 14).iloc[-1] - 2.0) < 1e-9


def test_adx_high_in_trend_low_in_chop():
    trend = adx(_trend(300, 1.0), 14).iloc[-1]
    rng = np.random.default_rng(1)
    c = pd.Series(100 + np.sin(np.arange(300) / 3.0) * 2 + rng.normal(0, 0.05, 300), index=_trend(300).index)
    chop = pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.1, "low": c - 0.1, "close": c})
    assert trend > 40 and adx(chop, 14).iloc[-1] < 25


def test_no_lookahead_signals_identical_on_truncated_history():
    full = synthetic_m5(days=40, seed=3)
    p = StrategyParams(adx_threshold=0.0)  # davantage de signaux => test plus sévère
    sig_full = compute_signals(full, p)
    cut = len(full) // 2 + 7  # coupe en plein milieu d'une bougie H1/M15
    sig_cut = compute_signals(full.iloc[:cut], p)
    cols = ["atr", "ema_pb", "adx", "bias", "long_signal", "short_signal", "long_sl", "short_sl"]
    a, b = sig_full.iloc[:cut][cols], sig_cut[cols]
    pd.testing.assert_frame_equal(a, b, check_dtype=False)
    assert sig_full["long_signal"].sum() + sig_full["short_signal"].sum() > 0


def test_htf_bias_only_sees_closed_candles():
    full = synthetic_m5(days=30, seed=5)
    p = StrategyParams()
    sig = compute_signals(full, p)
    ts = full.index[(full.index.hour == 10) & (full.index.minute == 55)][12]  # dernière M5 de la H1 10:00
    mod = full.copy()
    mod.loc[ts, ["open", "high", "low", "close"]] *= 1.3                      # perturbation violente de cette seule bougie
    sig2 = compute_signals(mod, p)
    before = sig.index < ts
    pd.testing.assert_frame_equal(sig.loc[before, ["bias", "adx"]], sig2.loc[before, ["bias", "adx"]])
