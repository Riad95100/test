import numpy as np
import pandas as pd
import pytest

import bot.backtest as bt
from bot.backtest import run_backtest
from bot.config import BotConfig, Instrument
from bot.data import synthetic_m5


def _cfg(**risk):
    cfg = BotConfig()
    cfg.strategy.adx_threshold = 0.0
    for k, v in risk.items():
        setattr(cfg.risk, k, v)
    return cfg


@pytest.mark.parametrize("symbol,price,vol", [("XAUUSD", 2000.0, 0.25), ("US30", 38000.0, 4.0)])
def test_invariants_on_synthetic_data(symbol, price, vol):
    cfg = _cfg(max_trades_per_day=2)
    m5 = synthetic_m5(days=120, seed=11, start_price=price, vol=vol)
    inst = cfg.instruments[symbol]
    res = run_backtest(m5, cfg, inst)
    t = res.trades
    assert len(t) > 20
    # comptabilité : le P&L cumulé explique exactement la variation de capital
    assert res.equity.iloc[-1] - cfg.initial_capital == pytest.approx(t.pnl.sum())
    # pas de chevauchement de trades
    entry, exit_ = pd.to_datetime(t.entry_time), pd.to_datetime(t.exit_time)
    assert (entry.iloc[1:].to_numpy() >= exit_.iloc[:-1].to_numpy()).all()
    # limites journalières
    per_day = entry.dt.tz_convert("Europe/Paris").dt.date.value_counts()
    assert per_day.max() <= 2
    # toutes les entrées en session (09:00-11:30 / 14:30-17:00 Paris)
    loc = entry.dt.tz_convert("Europe/Paris")
    minutes = loc.dt.hour * 60 + loc.dt.minute
    assert (((minutes >= 540) & (minutes < 690)) | ((minutes >= 870) & (minutes < 1020))).all()
    # le risque par trade est borné (SL ≈ -1R, un peu plus avec spread/slippage), jamais -3R
    assert t.R.min() > -2.0
    # aucune position portée hors session
    ex = exit_.dt.tz_convert("Europe/Paris")
    em = ex.dt.hour * 60 + ex.dt.minute
    assert (((em > 540) & (em <= 690)) | ((em > 870) & (em <= 1020))).all()


def test_deterministic():
    cfg = _cfg()
    m5 = synthetic_m5(days=60, seed=2)
    a = run_backtest(m5, cfg, cfg.instruments["XAUUSD"]).trades
    b = run_backtest(m5, cfg, cfg.instruments["XAUUSD"]).trades
    pd.testing.assert_frame_equal(a, b)


def test_costs_reduce_results():
    m5 = synthetic_m5(days=120, seed=11)
    cfg = _cfg()
    free = Instrument("XAUUSD", 100.0, spread=0.0, slippage=0.0)
    costly = Instrument("XAUUSD", 100.0, spread=0.6, slippage=0.2, commission_per_lot=7.0)
    assert run_backtest(m5, cfg, costly).stats["net_pnl"] < run_backtest(m5, cfg, free).stats["net_pnl"]


def test_hand_built_scenario_entry_next_open_with_spread_tp1_then_session_close(monkeypatch):
    # Janvier => Paris = UTC+1 : session 09:00-11:30 Paris = 08:00-10:30 UTC
    idx = pd.date_range("2025-01-06 08:00", "2025-01-06 11:00", freq="5min", tz="UTC")
    n = len(idx)
    close = np.full(n, 2000.0)
    m5 = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close}, index=idx)
    m5.loc[idx[8], ["high", "low"]] = [2006.0, 2001.0]   # 08:40 : touche TP1 (2005.6) sans revenir sur l'entrée
    m5.loc[idx[9:], ["open", "close"]] = 2002.0
    m5.loc[idx[9:], ["high", "low"]] = [[2002.5, 2001.5]] * (n - 9)

    sig = m5.copy()
    sig["atr"] = 1.0
    for c in ("long_signal", "short_signal"):
        sig[c] = False
    sig.loc[idx[5], "long_signal"] = True                # signal à la clôture de 08:25
    sig["long_sl"], sig["short_sl"] = 1995.0, 2005.0
    monkeypatch.setattr(bt, "compute_signals", lambda *a, **k: sig)

    cfg = _cfg()
    inst = Instrument("XAUUSD", 100.0, spread=0.3, slippage=0.0)
    res = run_backtest(m5, cfg, inst)
    assert len(res.trades) == 1
    tr = res.trades.iloc[0]
    assert pd.Timestamp(tr.entry_time) == idx[6]         # entrée à l'ouverture de la bougie SUIVANTE
    assert tr.entry == pytest.approx(2000.3)             # ask = open + spread
    assert tr.lots == pytest.approx(0.09)                # 50 $ / (5.3 pts * 100 $)
    assert tr.path == "TP1>SESSION"
    # session finie à 10:30 UTC : clôture au close de la bougie 10:25 (2002.0)
    expected = 0.04 * (2005.6 - 2000.3) * 100 + 0.05 * (2002.0 - 2000.3) * 100
    assert tr.pnl == pytest.approx(expected)
    assert pd.Timestamp(tr.exit_time) == pd.Timestamp("2025-01-06 10:30", tz="UTC")
