"""Adaptateur MetaTrader 5 (paquet `MetaTrader5`, Windows uniquement — le terminal MT5 doit tourner).

⚠️ Non testé contre un vrai terminal depuis l'environnement de développement (Linux) : testez-le d'abord sur un
compte DÉMO, avec la plus petite taille de lot, avant toute autre utilisation.
"""
from __future__ import annotations

import time
from datetime import timezone

import pandas as pd

from .base import Broker, BrokerPosition, Quote

TIMEFRAMES = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}
SECONDS = {"M5": 300, "M15": 900, "H1": 3600}


class MT5Error(RuntimeError):
    pass


class MT5Broker(Broker):
    def __init__(self, symbols: dict[str, str], magic: int = 20260101, deviation: int = 20,
                 login: int | None = None, password: str | None = None, server: str | None = None,
                 terminal_path: str | None = None, server_utc_offset_hours: float | None = None,
                 mt5_module=None):
        """`symbols` : clé interne ("XAUUSD") -> nom du symbole chez le broker ("XAUUSD.r", "GOLD", "DJ30", "US30Cash"...).
        `server_utc_offset_hours` : décalage de l'heure serveur MT5 par rapport à l'UTC (ex. 2 ou 3). Si None, il est déduit
        de l'heure du dernier tick (fiable seulement marché ouvert)."""
        if mt5_module is None:
            import MetaTrader5 as mt5_module  # noqa: N813  (import tardif : n'existe pas sous Linux/macOS)
        self.mt5 = mt5_module
        self.symbols, self.magic, self.deviation = symbols, magic, deviation
        kw = {k: v for k, v in dict(path=terminal_path, login=login, password=password, server=server).items() if v}
        if not self.mt5.initialize(**kw):
            raise MT5Error(f"initialize() a échoué: {self.mt5.last_error()}")
        for broker_sym in symbols.values():
            if not self.mt5.symbol_select(broker_sym, True):
                raise MT5Error(f"Symbole introuvable chez le broker: {broker_sym} ({self.mt5.last_error()})")
        self.offset_s = self._detect_offset(server_utc_offset_hours)

    # ---- temps ----
    def _detect_offset(self, hours: float | None) -> int:
        if hours is not None:
            return int(hours * 3600)
        tick = self.mt5.symbol_info_tick(next(iter(self.symbols.values())))
        if tick is None:
            raise MT5Error("Impossible de déduire le décalage horaire serveur (pas de tick). Fournissez server_utc_offset_hours.")
        return int(round((tick.time - time.time()) / 1800.0) * 1800)

    def _to_utc(self, server_epoch: float) -> pd.Timestamp:
        return pd.Timestamp(server_epoch - self.offset_s, unit="s", tz="UTC")

    def now(self) -> pd.Timestamp:
        return pd.Timestamp.now(tz=timezone.utc)

    # ---- données ----
    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        tf = getattr(self.mt5, TIMEFRAMES[timeframe])
        rates = self.mt5.copy_rates_from_pos(self.symbols[symbol], tf, 0, count + 1)
        if rates is None or len(rates) == 0:
            raise MT5Error(f"Pas de bougies pour {symbol} {timeframe}: {self.mt5.last_error()}")
        df = pd.DataFrame(rates)
        df.index = pd.DatetimeIndex([self._to_utc(t) for t in df["time"]], name="time")
        df = df[["open", "high", "low", "close"]].astype(float)
        # Écarte la bougie en formation : une bougie est close si son ouverture + durée <= maintenant
        closed = df.index + pd.Timedelta(seconds=SECONDS[timeframe]) <= self.now()
        return df[closed].iloc[-count:]

    def quote(self, symbol: str) -> Quote:
        t = self.mt5.symbol_info_tick(self.symbols[symbol])
        if t is None or t.bid <= 0 or t.ask <= 0:
            raise MT5Error(f"Pas de cotation pour {symbol}")
        return Quote(float(t.bid), float(t.ask))

    def equity(self) -> float:
        info = self.mt5.account_info()
        if info is None:
            raise MT5Error("account_info() indisponible")
        return float(info.equity)

    def is_demo(self) -> bool:
        info = self.mt5.account_info()
        return bool(info) and info.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO

    # ---- positions / ordres ----
    def _raw_position(self, symbol: str):
        pos = self.mt5.positions_get(symbol=self.symbols[symbol]) or []
        mine = [p for p in pos if p.magic == self.magic]
        return mine[0] if mine else None

    def position(self, symbol: str) -> BrokerPosition | None:
        p = self._raw_position(symbol)
        if p is None:
            return None
        side = 1 if p.type == self.mt5.POSITION_TYPE_BUY else -1
        return BrokerPosition(side, float(p.volume), float(p.price_open), float(p.sl))

    def _filling(self, broker_symbol: str):
        mode = self.mt5.symbol_info(broker_symbol).filling_mode
        if mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        if mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: dict) -> float:
        res = self.mt5.order_send(req)
        if res is None or res.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"order_send refusé: retcode={getattr(res, 'retcode', None)} "
                           f"comment={getattr(res, 'comment', None)} req={req}")
        return float(res.price)

    def open_market(self, symbol: str, side: int, lots: float, sl: float) -> float:
        bs = self.symbols[symbol]
        t = self.mt5.symbol_info_tick(bs)
        digits = self.mt5.symbol_info(bs).digits
        return self._send({
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": bs, "volume": float(lots),
            "type": self.mt5.ORDER_TYPE_BUY if side == 1 else self.mt5.ORDER_TYPE_SELL,
            "price": t.ask if side == 1 else t.bid, "sl": round(float(sl), digits),
            "deviation": self.deviation, "magic": self.magic, "comment": "scalp-bot",
            "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(bs),
        })

    def close_partial(self, symbol: str, lots: float) -> float:
        p = self._raw_position(symbol)
        if p is None:
            raise MT5Error(f"Aucune position à fermer sur {symbol}")
        bs = self.symbols[symbol]
        t = self.mt5.symbol_info_tick(bs)
        is_buy = p.type == self.mt5.POSITION_TYPE_BUY
        return self._send({
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": bs, "position": p.ticket,
            "volume": float(min(lots, p.volume)),
            "type": self.mt5.ORDER_TYPE_SELL if is_buy else self.mt5.ORDER_TYPE_BUY,
            "price": t.bid if is_buy else t.ask, "deviation": self.deviation, "magic": self.magic,
            "comment": "scalp-bot", "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(bs),
        })

    def close_all(self, symbol: str) -> float:
        p = self._raw_position(symbol)
        if p is None:
            raise MT5Error(f"Aucune position à fermer sur {symbol}")
        return self.close_partial(symbol, float(p.volume))

    def modify_sl(self, symbol: str, sl: float) -> None:
        p = self._raw_position(symbol)
        if p is None:
            return
        digits = self.mt5.symbol_info(self.symbols[symbol]).digits
        self._send_sltp({
            "action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbols[symbol], "position": p.ticket,
            "sl": round(float(sl), digits), "tp": float(p.tp), "magic": self.magic,
        })

    def _send_sltp(self, req: dict) -> None:
        res = self.mt5.order_send(req)
        if res is None or res.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"modification SL refusée: retcode={getattr(res, 'retcode', None)} comment={getattr(res, 'comment', None)}")
