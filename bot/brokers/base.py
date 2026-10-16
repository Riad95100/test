"""Interface broker : le moteur live ne dépend que de ceci (MT5 en prod, ReplayBroker en test/paper)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Quote:
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class BrokerPosition:
    side: int        # +1 long, -1 short
    lots: float
    price: float     # prix moyen d'ouverture
    sl: float        # 0.0 si pas de stop


class Broker(ABC):
    @abstractmethod
    def now(self) -> pd.Timestamp:
        """Heure courante UTC (tz-aware)."""

    @abstractmethod
    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """`count` dernières bougies CLÔTURÉES ('M5' | 'M15' | 'H1'), index = ouverture UTC, colonnes open/high/low/close (BID)."""

    @abstractmethod
    def quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def position(self, symbol: str) -> BrokerPosition | None:
        """Position ouverte par CE bot sur ce symbole (filtrée par magic number), ou None."""

    @abstractmethod
    def open_market(self, symbol: str, side: int, lots: float, sl: float) -> float:
        """Ouvre au marché avec stop loss serveur. Retourne le prix d'exécution. Lève une exception si refusé."""

    @abstractmethod
    def close_partial(self, symbol: str, lots: float) -> float:
        """Ferme `lots` de la position. Retourne le prix d'exécution."""

    @abstractmethod
    def close_all(self, symbol: str) -> float: ...

    @abstractmethod
    def modify_sl(self, symbol: str, sl: float) -> None: ...

    @abstractmethod
    def is_demo(self) -> bool: ...
