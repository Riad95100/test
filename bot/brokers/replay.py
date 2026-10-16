"""Broker simulé qui rejoue des bougies M5 historiques à travers le moteur live (paper trading / tests)."""
from __future__ import annotations

import pandas as pd

from ..config import BotConfig
from .base import Broker, BrokerPosition, Quote

DURATIONS = {"M5": pd.Timedelta(minutes=5), "M15": pd.Timedelta(minutes=15), "H1": pd.Timedelta(hours=1)}
RULES = {"M15": "15min", "H1": "1h"}


class ReplayBroker(Broker):
    def __init__(self, data: dict[str, pd.DataFrame], cfg: BotConfig, balance: float | None = None):
        self.data, self.cfg = data, cfg
        self.balance = balance if balance is not None else cfg.initial_capital
        self._now = next(iter(data.values())).index[0]
        self._mid: dict[str, float] = {s: float(d["open"].iloc[0]) for s, d in data.items()}
        self.pos: dict[str, dict] = {}
        self.log: list[tuple] = []
        self._tf: dict[tuple[str, str], pd.DataFrame] = {}
        for sym, d in data.items():
            self._tf[(sym, "M5")] = d
            for tf, rule in RULES.items():
                self._tf[(sym, tf)] = d.resample(rule, label="left", closed="left").agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna(subset=["close"])

    # ---- pilotage de la simulation ----
    def set_price(self, now: pd.Timestamp, symbol: str, bid: float) -> list[tuple]:
        """Avance l'horloge, met à jour le prix et exécute les stops serveur franchis. Retourne les clôtures serveur."""
        self._now, self._mid[symbol] = now, bid
        out = []
        p = self.pos.get(symbol)
        if p:
            inst = self.cfg.instruments[symbol]
            exit_px = bid if p["side"] == 1 else bid + inst.spread
            if p["sl"] and (exit_px - p["sl"]) * p["side"] <= 0:
                price = p["sl"] if (exit_px - p["sl"]) * p["side"] == 0 else exit_px
                out.append(self._realize(symbol, p["lots"], price, "server-SL"))
                del self.pos[symbol]
        return out

    def _realize(self, symbol: str, lots: float, price: float, why: str) -> tuple:
        p, inst = self.pos[symbol], self.cfg.instruments[symbol]
        pnl = (price - p["price"]) * p["side"] * lots * inst.value_per_point_per_lot
        self.balance += pnl - inst.commission_per_lot * lots
        rec = (self._now, symbol, why, lots, price, pnl)
        self.log.append(rec)
        return rec

    # ---- interface Broker ----
    def now(self) -> pd.Timestamp:
        return self._now

    def quote(self, symbol: str) -> Quote:
        bid = self._mid[symbol]
        return Quote(bid, bid + self.cfg.instruments[symbol].spread)

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        d = self._tf[(symbol, timeframe)]
        # bougies clôturées : ouverture + durée <= maintenant  <=>  ouverture <= maintenant - durée
        end = d.index.searchsorted(self._now - DURATIONS[timeframe], side="right")
        return d.iloc[max(0, end - count):end]

    def equity(self) -> float:
        eq = self.balance
        for s, p in self.pos.items():
            inst = self.cfg.instruments[s]
            px = self._mid[s] + (0.0 if p["side"] == 1 else inst.spread)
            eq += (px - p["price"]) * p["side"] * p["lots"] * inst.value_per_point_per_lot
        return eq

    def position(self, symbol: str) -> BrokerPosition | None:
        p = self.pos.get(symbol)
        return BrokerPosition(p["side"], p["lots"], p["price"], p["sl"]) if p else None

    def open_market(self, symbol: str, side: int, lots: float, sl: float) -> float:
        q = self.quote(symbol)
        price = q.ask if side == 1 else q.bid
        self.pos[symbol] = {"side": side, "lots": lots, "lots0": lots, "price": price, "sl": sl}
        self.log.append((self._now, symbol, "open", lots, price, 0.0))
        return price

    def close_partial(self, symbol: str, lots: float) -> float:
        p = self.pos[symbol]
        lots = min(lots, p["lots"])
        q = self.quote(symbol)
        price = q.bid if p["side"] == 1 else q.ask
        self._realize(symbol, lots, price, "close")
        p["lots"] = round(p["lots"] - lots, 8)
        if p["lots"] <= 1e-9:
            del self.pos[symbol]
        return price

    def close_all(self, symbol: str) -> float:
        return self.close_partial(symbol, self.pos[symbol]["lots"])

    def modify_sl(self, symbol: str, sl: float) -> None:
        self.pos[symbol]["sl"] = sl

    def is_demo(self) -> bool:
        return True
