"""Chargement de bougies M5 depuis un CSV (export MT5, cTrader, TradingView, Dukascopy...) + données synthétiques."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    """Lit un CSV M5 et retourne un DataFrame OHLC indexé en UTC (index = ouverture de la bougie).

    Formats acceptés : colonnes `time|datetime|date` (+ éventuellement `<TIME>` séparée de `<DATE>` comme l'export MT5),
    `open, high, low, close` (casse et chevrons ignorés), séparateur virgule / point-virgule / tabulation.
    `tz` = fuseau des timestamps du fichier (beaucoup de brokers MT5 sont en GMT+2/+3 : ex. "Europe/Athens").
    """
    raw = pd.read_csv(path, sep=None, engine="python")
    raw.columns = [str(c).strip().strip("<>").lower() for c in raw.columns]
    if "date" in raw.columns and "time" in raw.columns:
        ts = pd.to_datetime(raw["date"].astype(str) + " " + raw["time"].astype(str))
    else:
        tcol = next((c for c in ("time", "datetime", "date", "timestamp", "gmt time", "local time") if c in raw.columns), None)
        if tcol is None:
            raise ValueError(f"Colonne de date introuvable dans {path}: {list(raw.columns)}")
        if pd.api.types.is_numeric_dtype(raw[tcol]):
            ts = pd.to_datetime(raw[tcol], unit="s" if raw[tcol].iloc[0] < 1e11 else "ms")
        else:
            ts = pd.to_datetime(raw[tcol], dayfirst=False)
    missing = {"open", "high", "low", "close"} - set(raw.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path}: {sorted(missing)}")
    df = raw[["open", "high", "low", "close"]].astype(float)
    df.index = pd.DatetimeIndex(ts)
    df.index = df.index.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward") if df.index.tz is None else df.index
    df.index = df.index.tz_convert("UTC")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "time"
    bad = (df["high"] < df[["open", "close", "low"]].max(axis=1) - 1e-9) | (df["low"] > df[["open", "close", "high"]].min(axis=1) + 1e-9)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} bougies incohérentes (high/low) dans {path}")
    return df


def synthetic_m5(days: int = 60, start: str = "2025-01-06", seed: int = 0, start_price: float = 2000.0,
                 vol: float = 0.25) -> pd.DataFrame:
    """Marche aléatoire avec régimes de tendance et clustering de volatilité (jours ouvrés, 24h).
    SERT UNIQUEMENT aux tests / démos : les résultats sur ces données n'ont AUCUNE valeur prédictive."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 288, freq="5min", tz="UTC")
    idx = idx[idx.dayofweek < 5]
    n = len(idx)
    drift = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.integers(100, 800))
        drift[i:i + length] = rng.normal(0, vol * 0.08)
        i += length
    sigma = vol * np.exp(np.cumsum(rng.normal(0, 0.02, n)) * 0.3 - 0.0)
    sigma = vol * sigma / sigma.mean() * 1.0
    steps = drift + rng.normal(0, 1, n) * sigma
    close = start_price + np.cumsum(steps)
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.normal(0, sigma * 0.6))
    high = np.maximum(open_, close) + wick * rng.random(n)
    low = np.minimum(open_, close) - wick * rng.random(n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx).rename_axis("time")
