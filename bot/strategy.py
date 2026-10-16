"""Calcul des signaux : Trend Pullback + Momentum Confirmation.

Logique identique à strategies/scalping_strategy.pine, avec la structure multi-timeframe du document :
  - H1  : biais de tendance (EMA50/EMA200)
  - M15 : filtre ADX
  - M5  : pullback sur EMA21 + confirmation (engulfing / sortie RSI / cassure de micro-structure)

Les signaux sont évalués sur la clôture d'une bougie M5. Les valeurs des timeframes supérieurs ne sont
utilisées qu'une fois leur bougie CLÔTURÉE (aucun lookahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyParams
from .indicators import adx, atr, ema, rsi

M5 = pd.Timedelta(minutes=5)
M15 = pd.Timedelta(minutes=15)
H1 = pd.Timedelta(hours=1)


def resample_ohlc(m5: pd.DataFrame, rule: str) -> pd.DataFrame:
    """M5 -> M15/H1. Les bougies partielles (fin de données ou trous) sont conservées telles quelles,
    mais la dernière bougie encore ouverte est écartée par `_known_at`."""
    out = m5.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    return out.dropna(subset=["close"])


def _known_at(series: pd.Series, duration: pd.Timedelta, target_index: pd.DatetimeIndex, lag: pd.Timedelta) -> pd.Series:
    """Aligne une série HTF (indexée sur l'ouverture de la bougie) sur `target_index`.
    La valeur d'une bougie HTF n'est disponible qu'à sa clôture (ouverture + durée).
    `lag` = durée d'une bougie cible : on évalue au moment de la CLÔTURE de la bougie M5."""
    avail = series.copy()
    avail.index = avail.index + duration
    out = avail.reindex(target_index + lag, method="ffill")
    out.index = target_index
    return out


def compute_signals(
    m5: pd.DataFrame,
    p: StrategyParams,
    m15: pd.DataFrame | None = None,
    h1: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Retourne le DataFrame M5 enrichi des colonnes :
    atr, ema_pb, adx, bias, long_signal, short_signal, long_sl, short_sl.

    `m15` et `h1` : si None, dérivés du M5 (backtest). En live on peut les fournir directement depuis le broker.
    Sur la dernière bougie M5 fournie (supposée clôturée), `long_signal`/`short_signal` indiquent s'il faut
    entrer à l'ouverture de la bougie suivante.
    """
    if not m5.index.is_monotonic_increasing:
        raise ValueError("Les bougies M5 doivent être triées par date croissante.")
    df = m5[["open", "high", "low", "close"]].astype(float).copy()
    m15 = resample_ohlc(df, "15min") if m15 is None else m15
    h1 = resample_ohlc(df, "1h") if h1 is None else h1

    # --- Biais H1 ---
    h1_fast = ema(h1["close"], p.htf_ema_fast)
    h1_slow = ema(h1["close"], p.htf_ema_slow)
    bull = ((h1_fast > h1_slow) & (h1["close"] > h1_fast) & (h1["close"] > h1_slow)).astype(float)
    bear = ((h1_fast < h1_slow) & (h1["close"] < h1_fast) & (h1["close"] < h1_slow)).astype(float)
    valid = (h1_fast.notna() & h1_slow.notna()).astype(float)
    bias_h1 = (bull - bear).where(valid == 1.0)
    df["bias"] = _known_at(bias_h1, H1, df.index, M5)

    # --- ADX M15 ---
    df["adx"] = _known_at(adx(m15, p.adx_len), M15, df.index, M5)

    # --- M5 ---
    df["atr"] = atr(df, p.atr_len)
    df["ema_pb"] = ema(df["close"], p.ema_pullback)
    df["rsi"] = rsi(df["close"], p.rsi_len)

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    near_long = (l <= df["ema_pb"]) & (c >= df["ema_pb"])
    near_short = (h >= df["ema_pb"]) & (c <= df["ema_pb"])

    prev_rsi = df["rsi"].shift(1)
    rsi_exit_os = (df["rsi"] > p.rsi_oversold) & (prev_rsi <= p.rsi_oversold)
    rsi_exit_ob = (df["rsi"] < p.rsi_overbought) & (prev_rsi >= p.rsi_overbought)

    bull_engulf = (c.shift(1) < o.shift(1)) & (c > o) & (c >= o.shift(1)) & (o <= c.shift(1))
    bear_engulf = (c.shift(1) > o.shift(1)) & (c < o) & (c <= o.shift(1)) & (o >= c.shift(1))

    micro_high = h.shift(1).rolling(p.swing_lookback).max()
    micro_low = l.shift(1).rolling(p.swing_lookback).min()
    break_up = c > micro_high
    break_dn = c < micro_low

    adx_ok = df["adx"] > p.adx_threshold
    df["long_signal"] = (df["bias"] == 1) & near_long & adx_ok & (bull_engulf | rsi_exit_os | break_up)
    df["short_signal"] = (df["bias"] == -1) & near_short & adx_ok & (bear_engulf | rsi_exit_ob | break_dn)

    swing_low = l.rolling(p.swing_lookback).min()
    swing_high = h.rolling(p.swing_lookback).max()
    df["long_sl"] = swing_low - df["atr"] * p.atr_mult
    df["short_sl"] = swing_high + df["atr"] * p.atr_mult

    # Signaux invalides tant que les indicateurs ne sont pas chauffés
    warm = df[["atr", "ema_pb", "adx", "bias", "rsi"]].notna().all(axis=1) & micro_high.notna()
    df["long_signal"] &= warm
    df["short_signal"] &= warm
    return df
