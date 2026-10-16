"""Filtres horaires : sessions de trading (heure de Paris) et fenêtres de news."""
from __future__ import annotations

import pandas as pd

from .config import RiskParams


def _parse_window(w: str) -> tuple[int, int]:
    a, b = w.split("-")
    h1, m1 = a.split(":")
    h2, m2 = b.split(":")
    return int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)


class Schedule:
    def __init__(self, risk: RiskParams):
        self.risk = risk
        self.windows = [_parse_window(w) for w in risk.sessions]
        self.news = [pd.Timestamp(t).tz_convert("UTC") if pd.Timestamp(t).tzinfo else pd.Timestamp(t, tz="UTC")
                     for t in risk.news_times]
        self.margin = pd.Timedelta(minutes=risk.news_blackout_minutes)

    def local(self, ts: pd.DatetimeIndex) -> pd.DatetimeIndex:
        return ts.tz_convert(self.risk.session_tz)

    def in_session(self, ts: pd.Timestamp) -> bool:
        """`ts` = ouverture de la bougie (tz-aware). Fenêtres [début, fin)."""
        if not self.risk.use_session_filter:
            return True
        loc = ts.tz_convert(self.risk.session_tz)
        m = loc.hour * 60 + loc.minute
        return any(a <= m < b for a, b in self.windows)

    def in_news_blackout(self, ts: pd.Timestamp) -> bool:
        return any(abs(ts - n) <= self.margin for n in self.news)

    def entry_allowed(self, ts: pd.Timestamp) -> bool:
        return self.in_session(ts) and not self.in_news_blackout(ts)

    def day_key(self, ts: pd.Timestamp):
        return ts.tz_convert(self.risk.session_tz).date()

    def week_key(self, ts: pd.Timestamp):
        iso = ts.tz_convert(self.risk.session_tz).isocalendar()
        return (iso[0], iso[1])
