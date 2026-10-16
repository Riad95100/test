"""Machine à états d'un trade : TP1 (50 %) -> breakeven, TP2 (25 %), runner (25 %) avec trailing ATR.

Utilisée À L'IDENTIQUE par le backtester et par le moteur live, pour que les deux se comportent pareil.
Les prix passés à `step` sont ceux du côté de sortie : bid pour un long, ask pour un short.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .config import Instrument, StrategyParams


def round_down(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def position_size(equity: float, risk_pct: float, risk_distance: float, inst: Instrument) -> float:
    """Lots tels que perte au SL ≈ risk_pct % du capital. 0.0 si sous le lot minimum (trade refusé)."""
    if risk_distance <= 0 or equity <= 0:
        return 0.0
    lots = (equity * risk_pct / 100.0) / (risk_distance * inst.value_per_point_per_lot)
    lots = min(round_down(lots, inst.lot_step), inst.max_lot)
    return round(lots, 8) if lots >= inst.min_lot else 0.0


@dataclass
class Fill:
    reason: str     # "SL", "BE", "TP1", "TP2", "TRAIL", "SESSION", "DAILY_STOP", ...
    price: float
    lots: float


@dataclass
class Trade:
    side: int               # +1 long, -1 short
    entry: float
    stop: float             # stop courant
    initial_stop: float
    tp1: float
    tp2: float
    lots: float
    lots_tp1: float
    lots_tp2: float
    remaining: float = 0.0
    tp1_hit: bool = False
    tp2_hit: bool = False
    fills: list[Fill] = field(default_factory=list)
    entry_time: str = ""

    # ------------------------------------------------------------------ construction
    @classmethod
    def open(cls, side: int, entry: float, stop: float, lots: float, p: StrategyParams, inst: Instrument,
             entry_time: str = "") -> "Trade":
        risk = (entry - stop) * side
        if risk <= 0:
            raise ValueError("Stop du mauvais côté du prix d'entrée")
        l1 = round_down(lots * p.tp1_fraction, inst.lot_step)
        l2 = round_down(lots * p.tp2_fraction, inst.lot_step)
        return cls(side=side, entry=entry, stop=stop, initial_stop=stop,
                   tp1=entry + side * risk * p.rr_tp1, tp2=entry + side * risk * p.rr_tp2,
                   lots=lots, lots_tp1=l1, lots_tp2=l2, remaining=lots, entry_time=entry_time)

    # ------------------------------------------------------------------ évolution
    @property
    def closed(self) -> bool:
        return self.remaining <= 1e-9

    def _fill(self, reason: str, price: float, lots: float) -> None:
        lots = min(lots, self.remaining)
        self.remaining = max(0.0, self.remaining - lots)
        self.fills.append(Fill(reason, price, lots))

    def step(self, open_: float, low: float, high: float, p: StrategyParams) -> list[Fill]:
        """Fait avancer le trade sur une plage de prix (côté de sortie). Hypothèse pessimiste intrabarre :
        le stop est testé avant les objectifs, et un stop déplacé à breakeven peut être touché dans la
        même bougie que TP1."""
        n0 = len(self.fills)
        s = self.side
        # le "pire" extrême pour la position = low pour un long, high pour un short
        worst = low if s == 1 else high
        best = high if s == 1 else low

        def stop_hit() -> bool:
            return (worst - self.stop) * s <= 0

        if stop_hit():
            gap_price = open_ if (open_ - self.stop) * s < 0 else self.stop  # gap défavorable -> prix d'ouverture
            self._fill(self._stop_reason(), gap_price, self.remaining)
            return self.fills[n0:]

        if not self.tp1_hit and (best - self.tp1) * s >= 0:
            self.tp1_hit = True
            if self.lots_tp1 > 0:
                self._fill("TP1", self.tp1, self.lots_tp1)
            if p.breakeven_after_tp1:
                self.stop = self.entry
            if stop_hit() and not self.closed:
                self._fill("BE", self.stop, self.remaining)
                return self.fills[n0:]
        if self.tp1_hit and not self.tp2_hit and (best - self.tp2) * s >= 0:
            self.tp2_hit = True
            if self.lots_tp2 > 0:
                self._fill("TP2", self.tp2, self.lots_tp2)
        return self.fills[n0:]

    def _stop_reason(self) -> str:
        if self.tp2_hit:
            return "TRAIL"
        if self.tp1_hit and abs(self.stop - self.entry) < 1e-12:
            return "BE"
        return "SL"

    def on_bar_close(self, close: float, atr: float, p: StrategyParams) -> bool:
        """Trailing du runner (après TP2). Retourne True si le stop a été resserré."""
        if self.closed or not self.tp2_hit or not atr or atr != atr:
            return False
        cand = close - self.side * atr * p.trail_atr_mult
        if (cand - self.stop) * self.side > 0:
            self.stop = cand
            return True
        return False

    def close_all(self, reason: str, price: float) -> list[Fill]:
        n0 = len(self.fills)
        if not self.closed:
            self._fill(reason, price, self.remaining)
        return self.fills[n0:]

    # ------------------------------------------------------------------ résultat
    def pnl(self, inst: Instrument) -> float:
        gross = sum((f.price - self.entry) * self.side * f.lots for f in self.fills) * inst.value_per_point_per_lot
        return gross - inst.commission_per_lot * self.lots

    def risk_amount(self, inst: Instrument) -> float:
        return abs(self.entry - self.initial_stop) * self.lots * inst.value_per_point_per_lot

    # ------------------------------------------------------------------ persistance (live)
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        d = dict(d)
        d["fills"] = [Fill(**f) for f in d.get("fills", [])]
        return cls(**d)
