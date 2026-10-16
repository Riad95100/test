"""Moteur live : même stratégie et même machine à états de trade que le backtest, exécutée via un Broker.

Principe : `Trade` (trade.py) est l'ÉTAT SOUHAITÉ ; à chaque tick on le réconcilie avec la position réelle du broker
(volume restant, niveau du stop). Un stop loss serveur est toujours posé à l'ouverture : si le bot plante, le risque
initial reste borné.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .brokers.base import Broker, Quote
from .config import BotConfig
from .schedule import Schedule
from .strategy import M5, compute_signals
from .trade import Trade, position_size, round_down

log = logging.getLogger("scalp-bot")

STOP_FILE = "STOP"  # créer ce fichier (même vide) = plus aucune nouvelle entrée ; les positions restent gérées


@dataclass
class SymbolState:
    trade: Trade | None = None
    trades_today: int = 0
    day_key: str | None = None
    day_start_equity: float = 0.0
    halted_day: bool = False
    last_boundary: str | None = None
    sl_sent: float | None = None   # dernier stop envoyé au broker (le broker arrondit les prix : on ne compare pas à sa valeur)


class LiveEngine:
    def __init__(self, cfg: BotConfig, broker: Broker, symbols: list[str], state_path: str | Path = "bot_state.json",
                 journal_path: str | Path = "journal.csv", m5_bars: int = 400, m15_bars: int = 300, h1_bars: int = 500,
                 observe_only: bool = False):
        self.cfg, self.broker, self.symbols = cfg, broker, symbols
        self.observe_only = observe_only  # True : calcule et logue les signaux, n'envoie AUCUN ordre
        self.sched = Schedule(cfg.risk)
        self.state_path, self.journal_path = Path(state_path), Path(journal_path)
        self.bars = {"M5": m5_bars, "M15": m15_bars, "H1": h1_bars}
        self.state: dict[str, SymbolState] = {s: SymbolState() for s in symbols}
        self.week_key: str | None = None
        self.week_start_equity = 0.0
        self.halted_week = False
        self._load_state()

    # ------------------------------------------------------------------ persistance
    def _save_state(self) -> None:
        data = {
            "week_key": self.week_key, "week_start_equity": self.week_start_equity, "halted_week": self.halted_week,
            "symbols": {s: {**{k: v for k, v in st.__dict__.items() if k != "trade"},
                            "trade": st.trade.to_dict() if st.trade else None} for s, st in self.state.items()},
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.week_key, self.week_start_equity = data.get("week_key"), data.get("week_start_equity", 0.0)
        self.halted_week = data.get("halted_week", False)
        for s, d in data.get("symbols", {}).items():
            if s in self.state:
                t = d.pop("trade", None)
                self.state[s] = SymbolState(trade=Trade.from_dict(t) if t else None, **d)
        log.info("État rechargé depuis %s", self.state_path)

    def _journal(self, symbol: str, t: Trade) -> None:
        inst = self.cfg.instruments[symbol]
        new = not self.journal_path.exists()
        with self.journal_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["entry_time", "exit_time", "symbol", "side", "entry", "stop", "lots", "pnl_est", "R_est", "path"])
            pnl = t.pnl(inst)
            risk = t.risk_amount(inst)
            w.writerow([t.entry_time, str(self.broker.now()), symbol, "long" if t.side == 1 else "short", t.entry,
                        t.initial_stop, t.lots, round(pnl, 2), round(pnl / risk, 3) if risk else "",
                        ">".join(f.reason for f in t.fills)])
        log.info("Trade clos %s %s : P&L estimé %+.2f (%s)", symbol, "long" if t.side == 1 else "short", t.pnl(inst),
                 ">".join(f.reason for f in t.fills))

    # ------------------------------------------------------------------ périodes & limites
    def _roll_periods(self, now: pd.Timestamp, equity: float) -> None:
        dk, wk = str(self.sched.day_key(now)), str(self.sched.week_key(now))
        if wk != self.week_key:
            self.week_key, self.week_start_equity, self.halted_week = wk, equity, False
        for st in self.state.values():
            if st.day_key != dk:
                st.day_key, st.trades_today, st.day_start_equity, st.halted_day = dk, 0, equity, False

    def _check_loss_limits(self, equity: float) -> bool:
        r = self.cfg.risk
        newly = False
        for st in self.state.values():
            if not st.halted_day and equity <= st.day_start_equity * (1 - r.max_daily_loss_pct / 100):
                st.halted_day = newly = True
                log.warning("STOP JOURNALIER atteint (équité %.2f). Plus d'entrées aujourd'hui.", equity)
        if not self.halted_week and equity <= self.week_start_equity * (1 - r.max_weekly_loss_pct / 100):
            self.halted_week = newly = True
            log.warning("STOP HEBDOMADAIRE atteint (équité %.2f). Plus d'entrées cette semaine.", equity)
        return newly

    # ------------------------------------------------------------------ boucle
    def run_forever(self, poll_seconds: float = 2.0) -> None:
        log.info("Moteur démarré pour %s", ", ".join(self.symbols))
        while True:
            try:
                self.tick_all()
            except KeyboardInterrupt:
                raise
            except Exception:  # un incident réseau ne doit pas tuer le bot ; les stops serveur protègent les positions
                log.exception("Erreur pendant le tick — nouvelle tentative au prochain cycle")
            time.sleep(poll_seconds)

    def tick_all(self) -> None:
        now = self.broker.now()
        equity = self.broker.equity()
        self._roll_periods(now, equity)
        flatten = self._check_loss_limits(equity)
        for s in self.symbols:
            self.tick(s, now, flatten_for_loss=flatten or self.state[s].halted_day or self.halted_week)
        self._save_state()

    def tick(self, symbol: str, now: pd.Timestamp, flatten_for_loss: bool = False) -> None:
        st, inst, p = self.state[symbol], self.cfg.instruments[symbol], self.cfg.strategy
        q = self.broker.quote(symbol)

        if st.trade is not None:
            self._manage_open(symbol, st, q)
            if st.trade is not None and flatten_for_loss:
                self._flatten(symbol, st, "DAILY_STOP")

        boundary = now.floor("5min")
        last = pd.Timestamp(st.last_boundary) if st.last_boundary else None
        if last is None:
            st.last_boundary = str(boundary)  # démarrage : on n'agit pas sur une bougie déjà en cours
        elif boundary > last:
            if self._on_new_bar(symbol, st, q, now, boundary) or now - boundary > pd.Timedelta(seconds=90):
                st.last_boundary = str(boundary)

    # ------------------------------------------------------------------ gestion position ouverte
    def _manage_open(self, symbol: str, st: SymbolState, q: Quote) -> None:
        t, p = st.trade, self.cfg.strategy
        pos = self.broker.position(symbol)
        if pos is None:  # fermée côté serveur (stop loss) ou manuellement
            t.close_all("SL" if not t.tp1_hit else ("TRAIL" if t.tp2_hit else "BE"), t.stop)
            self._finish(symbol, st)
            return
        px = q.bid if t.side == 1 else q.ask
        t.step(px, px, px, p)
        self._reconcile(symbol, st, pos.lots)

    def _reconcile(self, symbol: str, st: SymbolState, broker_lots: float) -> None:
        t, inst = st.trade, self.cfg.instruments[symbol]
        excess = round_down(broker_lots - t.remaining, inst.lot_step) if not t.closed else broker_lots
        try:
            if t.closed:
                if broker_lots > 0:
                    price = self.broker.close_all(symbol)
                    log.info("%s fermeture complète @ %.2f", symbol, price)
                self._finish(symbol, st)
                return
            if excess >= inst.lot_step - 1e-9:
                price = self.broker.close_partial(symbol, excess)
                log.info("%s sortie partielle %.2f lot @ %.2f (restant %.2f)", symbol, excess, price, t.remaining)
            if st.sl_sent is None or abs(st.sl_sent - t.stop) > 1e-9:
                self.broker.modify_sl(symbol, t.stop)
                st.sl_sent = t.stop
                log.info("%s stop -> %.2f", symbol, t.stop)
        except Exception:
            log.exception("%s: échec d'exécution, nouvelle tentative au prochain tick", symbol)

    def _flatten(self, symbol: str, st: SymbolState, reason: str) -> None:
        t = st.trade
        q = self.broker.quote(symbol)
        t.close_all(reason, q.bid if t.side == 1 else q.ask)
        pos = self.broker.position(symbol)
        self._reconcile(symbol, st, pos.lots if pos else 0.0)

    def _finish(self, symbol: str, st: SymbolState) -> None:
        self._journal(symbol, st.trade)
        st.trade = None
        self._save_state()

    # ------------------------------------------------------------------ nouvelle bougie M5 clôturée
    def _on_new_bar(self, symbol: str, st: SymbolState, q: Quote, now: pd.Timestamp, boundary: pd.Timestamp) -> bool:
        p, r = self.cfg.strategy, self.cfg.risk
        m5 = self.broker.candles(symbol, "M5", self.bars["M5"])
        if len(m5) == 0 or m5.index[-1] != boundary - M5:
            return False  # la bougie qui vient de se clôturer n'est pas encore disponible
        m15 = self.broker.candles(symbol, "M15", self.bars["M15"])
        h1 = self.broker.candles(symbol, "H1", self.bars["H1"])
        sig = compute_signals(m5, p, m15, h1)
        row = sig.iloc[-1]

        if st.trade is not None:
            t = st.trade
            close_x = row["close"] + (0.0 if t.side == 1 else q.spread)
            t.on_bar_close(close_x, row["atr"], p)
            pos = self.broker.position(symbol)
            if pos is not None:
                self._reconcile(symbol, st, pos.lots)
            if st.trade is not None and r.close_at_session_end and r.use_session_filter and not self.sched.in_session(boundary):
                log.info("%s fin de session : clôture de la position", symbol)
                self._flatten(symbol, st, "SESSION")
            return True

        self._maybe_enter(symbol, st, q, row, boundary)
        return True

    def _maybe_enter(self, symbol: str, st: SymbolState, q: Quote, row: pd.Series, boundary: pd.Timestamp) -> None:
        p, r, inst = self.cfg.strategy, self.cfg.risk, self.cfg.instruments[symbol]
        if not (row["long_signal"] or row["short_signal"]):
            return
        side = 1 if row["long_signal"] else -1
        why = None
        if (self.state_path.parent / STOP_FILE).exists() or Path(STOP_FILE).exists():
            why = "fichier STOP présent"
        elif st.halted_day or self.halted_week:
            why = "stop journalier/hebdo atteint"
        elif st.trades_today >= r.max_trades_per_day:
            why = "max trades/jour atteint"
        elif not self.sched.entry_allowed(boundary):
            why = "hors session ou fenêtre de news"
        elif q.spread > inst.max_spread:
            why = f"spread trop large ({q.spread:.2f} > {inst.max_spread})"
        elif self.broker.position(symbol) is not None:
            why = "une position existe déjà chez le broker"
        if why:
            log.info("%s signal %s ignoré : %s", symbol, "LONG" if side == 1 else "SHORT", why)
            return

        stop = float(row["long_sl"] if side == 1 else row["short_sl"])
        price = q.ask if side == 1 else q.bid
        risk_dist = (price - stop) * side
        if risk_dist <= 0 or risk_dist < inst.min_risk_spread_ratio * q.spread:
            log.info("%s signal ignoré : distance de stop %.2f trop faible vs spread %.2f", symbol, risk_dist, q.spread)
            return
        lots = position_size(self.broker.equity(), r.risk_pct, risk_dist, inst)
        if lots <= 0:
            log.info("%s signal ignoré : taille < lot minimum pour %.2f%% de risque", symbol, r.risk_pct)
            return

        if self.observe_only:
            log.info("%s [OBSERVATION] aurait ouvert %s %.2f lot @ ~%.2f, SL %.2f", symbol, "LONG" if side == 1 else "SHORT",
                     lots, price, stop)
            return
        fill = self.broker.open_market(symbol, side, lots, stop)
        try:
            st.trade = Trade.open(side, fill, stop, lots, p, inst, entry_time=str(self.broker.now()))
        except ValueError:  # exécution au-delà du stop (slippage extrême) : on referme immédiatement
            log.error("%s exécution %.2f au-delà du stop %.2f : fermeture immédiate", symbol, fill, stop)
            self.broker.close_all(symbol)
            return
        st.trades_today += 1
        st.sl_sent = stop
        log.info("%s %s %.2f lot @ %.2f | SL %.2f TP1 %.2f TP2 %.2f", symbol, "LONG" if side == 1 else "SHORT", lots,
                 fill, stop, st.trade.tp1, st.trade.tp2)
        self._save_state()
