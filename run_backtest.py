#!/usr/bin/env python3
"""Backtest du bot sur un CSV M5.

Exemples :
  python run_backtest.py --csv data/XAUUSD_M5.csv --symbol XAUUSD --data-tz Europe/Athens
  python run_backtest.py --csv data/US30_M5.csv --symbol US30 --config config.json --from 2025-01-01
  python run_backtest.py --demo            # données SYNTHÉTIQUES : pour tester le code uniquement
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bot.backtest import run_backtest
from bot.config import BotConfig
from bot.data import load_csv, synthetic_m5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="Fichier CSV de bougies M5")
    ap.add_argument("--symbol", default="XAUUSD", help="Profil d'instrument (clé de la config) : XAUUSD, US30...")
    ap.add_argument("--config", help="Fichier JSON de configuration (voir config.example.json)")
    ap.add_argument("--m15-csv", help="CSV M15 (optionnel, historique plus long que le M5 pour l'ADX)")
    ap.add_argument("--h1-csv", help="CSV H1 (optionnel, historique plus long que le M5 pour le biais EMA50/200)")
    ap.add_argument("--data-tz", help="Fuseau horaire des timestamps du CSV (défaut: config.data_tz = UTC)")
    ap.add_argument("--from", dest="start", help="Date de début (YYYY-MM-DD)")
    ap.add_argument("--to", dest="end", help="Date de fin (YYYY-MM-DD)")
    ap.add_argument("--capital", type=float, help="Capital initial")
    ap.add_argument("--demo", action="store_true", help="Utilise des données synthétiques (aucune valeur prédictive)")
    ap.add_argument("--save-trades", help="Écrit la liste des trades dans ce fichier CSV")
    a = ap.parse_args()

    cfg = BotConfig.from_json(a.config) if a.config else BotConfig()
    if a.capital:
        cfg.initial_capital = a.capital
    if a.symbol not in cfg.instruments:
        print(f"Instrument inconnu '{a.symbol}'. Disponibles: {', '.join(cfg.instruments)}", file=sys.stderr)
        return 2
    inst = cfg.instruments[a.symbol]

    if a.demo:
        print("⚠️  DONNÉES SYNTHÉTIQUES — ces résultats ne disent rien sur la rentabilité réelle.\n")
        m5 = synthetic_m5(days=120, start_price=2000.0 if a.symbol == "XAUUSD" else 38000.0,
                          vol=0.25 if a.symbol == "XAUUSD" else 4.0)
    elif a.csv:
        m5 = load_csv(a.csv, tz=a.data_tz or cfg.data_tz)
    else:
        ap.error("--csv ou --demo requis")

    print(f"{a.symbol}: {len(m5)} bougies M5 de {m5.index[0]} à {m5.index[-1]}")
    tz = a.data_tz or cfg.data_tz
    m15 = load_csv(a.m15_csv, tz=tz) if a.m15_csv else None
    h1 = load_csv(a.h1_csv, tz=tz) if a.h1_csv else None
    res = run_backtest(m5, cfg, inst, start=a.start or str(m5.index[0].date()), end=a.end, m15=m15, h1=h1)
    print(res.summary())
    if a.save_trades and not res.trades.empty:
        Path(a.save_trades).parent.mkdir(parents=True, exist_ok=True)
        res.trades.to_csv(a.save_trades, index=False)
        print(f"Trades écrits dans {a.save_trades}")
    if res.stats["trades"] < 100:
        print("⚠️  Moins de 100 trades : échantillon trop petit pour conclure quoi que ce soit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
