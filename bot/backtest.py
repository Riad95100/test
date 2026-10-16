"""Backtester bar-par-bar (M5) avec spread, slippage, commissions, sorties partielles, limites journalières."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import BotConfig, Instrument
from .schedule import Schedule
from .strategy import M5, compute_signals
from .trade import Trade, position_size

STOP_REASONS = {"SL", "BE", "TRAIL"}


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    stats: dict

    def summary(self) -> str:
        s = self.stats
        if s["trades"] == 0:
            return "Aucun trade."
        return (
            f"Trades: {s['trades']} | Winrate: {s['winrate']:.1%} | Profit factor: {s['profit_factor']:.2f} | "
            f"Espérance: {s['expectancy_R']:+.3f} R/trade | Net: {s['net_pnl']:+,.2f} ({s['return_pct']:+.2f} %) | "
            f"Max drawdown: {s['max_drawdown_pct']:.2f} % | Gain moy: {s['avg_win_R']:+.2f} R / Perte moy: {s['avg_loss_R']:+.2f} R"
        )


def run_backtest(m5: pd.DataFrame, cfg: BotConfig, inst: Instrument, start: str | None = None,
                 end: str | None = None) -> BacktestResult:
    p, r = cfg.strategy, cfg.risk
    sig = compute_signals(m5, p)  # calculé sur TOUT l'historique (chauffe des indicateurs), puis filtré
    if start or end:
        sig = sig.loc[start:end]
    sched = Schedule(r)

    idx = sig.index
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr_v = sig["atr"].to_numpy()
    long_sig, short_sig = sig["long_signal"].to_numpy(), sig["short_signal"].to_numpy()
    long_sl, short_sl = sig["long_sl"].to_numpy(), sig["short_sl"].to_numpy()
    sp, slip = inst.spread, inst.slippage

    equity = cfg.initial_capital
    day_key = week_key = None
    day_start_eq = week_start_eq = equity
    trades_today = 0
    halted_day = halted_week = False
    trade: Trade | None = None
    rows: list[dict] = []
    eq_points: list[tuple[pd.Timestamp, float]] = []
    pending = 0  # +1 / -1 : signal de la bougie précédente
    n = len(sig)

    def finish(t: Trade, exit_time: pd.Timestamp) -> None:
        nonlocal equity
        pnl = t.pnl(inst)
        equity += pnl
        rows.append({
            "entry_time": t.entry_time, "exit_time": exit_time, "side": "long" if t.side == 1 else "short",
            "entry": t.entry, "initial_stop": t.initial_stop, "lots": t.lots, "pnl": pnl,
            "R": pnl / t.risk_amount(inst) if t.risk_amount(inst) else np.nan,
            "exit": t.fills[-1].reason, "path": ">".join(f.reason for f in t.fills),
        })
        eq_points.append((exit_time, equity))

    def adj_fill_price(f, side: int) -> float:
        return f.price - side * slip if f.reason in STOP_REASONS else f.price

    def exit_space(side: int, i: int):
        """Plage de prix côté sortie : bid pour un long, ask (= bid + spread) pour un short."""
        d = 0.0 if side == 1 else sp
        return o[i] + d, l[i] + d, h[i] + d

    for i in range(n):
        ts = idx[i]
        dk, wk = sched.day_key(ts), sched.week_key(ts)
        if dk != day_key:
            day_key, day_start_eq, trades_today, halted_day = dk, equity, 0, False
        if wk != week_key:
            week_key, week_start_eq, halted_week = wk, equity, False

        # --- entrée à l'ouverture de cette bougie sur signal de la bougie précédente ---
        if trade is None and pending != 0 and not (halted_day or halted_week) \
                and trades_today < r.max_trades_per_day and sched.entry_allowed(ts):
            side = pending
            stop = long_sl[i - 1] if side == 1 else short_sl[i - 1]
            entry = o[i] + sp + slip if side == 1 else o[i] - slip
            risk_dist = (entry - stop) * side
            if risk_dist >= inst.min_risk_spread_ratio * sp and risk_dist > 0:
                lots = position_size(equity, r.risk_pct, risk_dist, inst)
                if lots > 0:
                    trade = Trade.open(side, entry, stop, lots, p, inst, entry_time=str(ts))
                    trades_today += 1
        pending = 0

        if trade is not None:
            s = trade.side
            eo, el, eh = exit_space(s, i)
            for f in trade.step(eo, el, eh, p):
                f.price = adj_fill_price(f, s)
            if trade.closed:
                finish(trade, ts + M5)
                trade = None

        # --- fin de bougie ---
        if trade is not None:
            s = trade.side
            close_x = c[i] + (0.0 if s == 1 else sp)
            trade.on_bar_close(close_x, atr_v[i], p)
            unreal = (close_x - trade.entry) * s * trade.remaining * inst.value_per_point_per_lot
            realized_open = sum((f.price - trade.entry) * s * f.lots for f in trade.fills) * inst.value_per_point_per_lot
            eq_now = equity + realized_open + unreal
            if eq_now <= day_start_eq * (1 - r.max_daily_loss_pct / 100):
                halted_day = True
            if eq_now <= week_start_eq * (1 - r.max_weekly_loss_pct / 100):
                halted_week = True
            last = i == n - 1
            session_over = r.close_at_session_end and r.use_session_filter and (last or not sched.in_session(idx[i + 1]))
            if halted_day or halted_week or session_over or last:
                reason = "DAILY_STOP" if (halted_day or halted_week) else "SESSION"
                for f in trade.close_all(reason, close_x):
                    f.price = f.price - s * slip
                finish(trade, ts + M5)
                trade = None
        else:
            if equity <= day_start_eq * (1 - r.max_daily_loss_pct / 100):
                halted_day = True
            if equity <= week_start_eq * (1 - r.max_weekly_loss_pct / 100):
                halted_week = True

        # --- signal pour la bougie suivante ---
        if trade is None and i < n - 1:
            pending = 1 if long_sig[i] else (-1 if short_sig[i] else 0)

    trades = pd.DataFrame(rows)
    eq = pd.Series([cfg.initial_capital] + [e for _, e in eq_points],
                   index=[idx[0] if n else pd.Timestamp.now(tz="UTC")] + [t for t, _ in eq_points], name="equity")
    return BacktestResult(trades, eq, compute_stats(trades, eq, cfg.initial_capital))


def compute_stats(trades: pd.DataFrame, eq: pd.Series, capital: float) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    gross_w, gross_l = wins.pnl.sum(), -losses.pnl.sum()
    peak = eq.cummax()
    dd = ((eq - peak) / peak).min()
    return {
        "trades": len(trades),
        "winrate": len(wins) / len(trades),
        "profit_factor": gross_w / gross_l if gross_l > 0 else float("inf"),
        "expectancy_R": float(trades.R.mean()),
        "avg_win_R": float(wins.R.mean()) if len(wins) else 0.0,
        "avg_loss_R": float(losses.R.mean()) if len(losses) else 0.0,
        "net_pnl": float(trades.pnl.sum()),
        "return_pct": float(trades.pnl.sum() / capital * 100),
        "max_drawdown_pct": float(-dd * 100),
    }
