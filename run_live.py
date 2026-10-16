#!/usr/bin/env python3
"""Lance le bot en live (MetaTrader 5) ou en rejeu historique via le moteur live (paper).

  # 1) Observation seule sur compte démo : aucun ordre, juste les signaux dans la console
  python run_live.py mt5 --config config.json --symbols XAUUSD=XAUUSD US30=US30Cash --observe

  # 2) Trading automatique sur compte DÉMO
  python run_live.py mt5 --config config.json --symbols XAUUSD=XAUUSD US30=US30Cash

  # Rejeu d'un CSV M5 à travers le moteur live (vérifie la plomberie, sans broker)
  python run_live.py replay --csv data/XAUUSD_M5.csv --symbols XAUUSD

Arrêt propre : Ctrl+C (les stops serveur restent actifs, l'état est repris au redémarrage).
Plus de nouvelles entrées : créez un fichier nommé STOP dans le dossier courant.
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from bot.config import BotConfig
from bot.data import load_csv
from bot.live import LiveEngine


def parse_symbols(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        k, _, v = it.partition("=")
        out[k] = v or k
    return out


def run_replay(args, cfg: BotConfig) -> int:
    from bot.brokers.replay import ReplayBroker
    sym = list(parse_symbols(args.symbols))[0]
    m5 = load_csv(args.csv, tz=args.data_tz or cfg.data_tz)
    broker = ReplayBroker({sym: m5}, cfg)
    engine = LiveEngine(cfg, broker, [sym], state_path=args.state, journal_path=args.journal)
    for ts, row in m5.iterrows():
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        path = [o, l, h, c] if c >= o else [o, h, l, c]  # ordre intrabarre inconnu : heuristique
        for k, px in enumerate(path):
            broker.set_price(ts + pd.Timedelta(seconds=75 * k), sym, px)
            engine.tick_all()
    print(f"Solde final: {broker.balance:,.2f} (départ {cfg.initial_capital:,.2f}) — journal: {args.journal}")
    return 0


def run_mt5(args, cfg: BotConfig) -> int:
    from bot.brokers.mt5 import MT5Broker
    symbols = parse_symbols(args.symbols)
    unknown = [s for s in symbols if s not in cfg.instruments]
    if unknown:
        print(f"Instruments absents de la config: {unknown}", file=sys.stderr)
        return 2
    broker = MT5Broker(symbols, magic=args.magic, login=args.login, password=args.password, server=args.server,
                       terminal_path=args.terminal, server_utc_offset_hours=args.server_utc_offset)
    if not broker.is_demo() and not args.allow_real:
        print("REFUS : ce compte n'est pas un compte DÉMO. Validez d'abord le bot en démo (voir README_BOT.md). "
              "Si vous assumez pleinement le risque, relancez avec --allow-real.", file=sys.stderr)
        return 3
    print(f"Décalage serveur MT5 détecté: UTC{broker.offset_s / 3600:+.1f}h — vérifiez qu'il est correct.")
    engine = LiveEngine(cfg, broker, list(symbols), state_path=args.state, journal_path=args.journal,
                        observe_only=args.observe)
    try:
        engine.run_forever(args.poll)
    except KeyboardInterrupt:
        print("\nArrêt demandé. Les stops serveur des positions ouvertes restent actifs.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config")
    common.add_argument("--symbols", nargs="+", default=["XAUUSD"], help="CLÉ=SYMBOLE_BROKER (ex. US30=US30Cash)")
    common.add_argument("--state", default="bot_state.json")
    common.add_argument("--journal", default="journal.csv")
    common.add_argument("--data-tz")
    m = sub.add_parser("mt5", parents=[common])
    m.add_argument("--observe", action="store_true", help="Aucun ordre : logue seulement les signaux")
    m.add_argument("--allow-real", action="store_true", help="Autorise un compte RÉEL (déconseillé avant validation)")
    m.add_argument("--magic", type=int, default=20260101)
    m.add_argument("--login", type=int)
    m.add_argument("--password")
    m.add_argument("--server")
    m.add_argument("--terminal", help="Chemin de terminal64.exe si plusieurs MT5 installés")
    m.add_argument("--server-utc-offset", type=float, help="Décalage heure serveur MT5 vs UTC (ex. 3)")
    m.add_argument("--poll", type=float, default=2.0)
    r = sub.add_parser("replay", parents=[common])
    r.add_argument("--csv", required=True)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("bot_live.log", encoding="utf-8")])
    cfg = BotConfig.from_json(args.config) if args.config else BotConfig()
    return run_mt5(args, cfg) if args.mode == "mt5" else run_replay(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
