"""Configuration du bot : paramètres de stratégie, de risque et profils d'instruments."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Instrument:
    """Caractéristiques d'un instrument chez *votre* broker (à vérifier !)."""

    symbol: str                      # nom du symbole chez le broker (ex. "XAUUSD", "US30", "DJ30"...)
    value_per_point_per_lot: float   # gain en devise du compte pour 1.0 de mouvement de prix et 1 lot
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 50.0
    spread: float = 0.30             # spread typique (en prix) utilisé par le backtest
    slippage: float = 0.05           # glissement par exécution market (en prix), backtest
    max_spread: float = 0.80         # en live : pas d'entrée si le spread dépasse cette valeur
    commission_per_lot: float = 0.0  # commission aller-retour par lot (devise du compte)
    min_risk_spread_ratio: float = 4.0  # distance SL minimale = ratio × spread (sinon le spread mange le trade)


# Valeurs par défaut indicatives. XAUUSD : 1 lot = 100 oz => 100 $ par 1.00 de prix.
# US30 : très variable selon le broker (1 $ ou 10 $ par point et par lot). VÉRIFIEZ les spécifications du contrat.
INSTRUMENTS: dict[str, Instrument] = {
    "XAUUSD": Instrument("XAUUSD", value_per_point_per_lot=100.0, spread=0.30, slippage=0.05, max_spread=0.80),
    "US30": Instrument("US30", value_per_point_per_lot=1.0, spread=2.0, slippage=0.5, max_spread=5.0,
                       min_lot=0.1, lot_step=0.1),
}


@dataclass
class StrategyParams:
    htf_ema_fast: int = 50
    htf_ema_slow: int = 200
    ema_pullback: int = 21
    swing_lookback: int = 10
    adx_len: int = 14
    adx_threshold: float = 22.0
    rsi_len: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_len: int = 14
    atr_mult: float = 1.0          # buffer SL au-delà du swing
    rr_tp1: float = 1.0
    rr_tp2: float = 2.0
    tp1_fraction: float = 0.50
    tp2_fraction: float = 0.25     # le reste (25 %) = runner avec trailing ATR
    trail_atr_mult: float = 1.5
    breakeven_after_tp1: bool = True


@dataclass
class RiskParams:
    risk_pct: float = 0.5               # % du capital risqué par trade
    max_trades_per_day: int = 3         # par instrument
    max_daily_loss_pct: float = 2.0     # stop journalier (tous instruments confondus en live)
    max_weekly_loss_pct: float = 6.0
    sessions: list[str] = field(default_factory=lambda: ["09:00-11:30", "14:30-17:00"])
    session_tz: str = "Europe/Paris"
    use_session_filter: bool = True
    close_at_session_end: bool = True
    # Fenêtres autour des news à fort impact, ISO 8601 avec fuseau (ex. "2026-11-06T14:30:00+01:00")
    news_times: list[str] = field(default_factory=list)
    news_blackout_minutes: int = 30


@dataclass
class BotConfig:
    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    instruments: dict[str, Instrument] = field(default_factory=lambda: dict(INSTRUMENTS))
    initial_capital: float = 10_000.0   # backtest uniquement
    data_tz: str = "UTC"                # fuseau des timestamps de vos CSV

    @classmethod
    def from_json(cls, path: str | Path) -> "BotConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = cls()
        for name, klass in (("strategy", StrategyParams), ("risk", RiskParams)):
            if name in raw:
                _check_keys(klass, raw[name], name)
                setattr(cfg, name, klass(**{**asdict(getattr(cfg, name)), **raw[name]}))
        if "instruments" in raw:
            for key, vals in raw["instruments"].items():
                base = asdict(cfg.instruments[key]) if key in cfg.instruments else {"symbol": key, "value_per_point_per_lot": 1.0}
                _check_keys(Instrument, vals, f"instruments.{key}")
                cfg.instruments[key] = Instrument(**{**base, **vals})
        for key in ("initial_capital", "data_tz"):
            if key in raw:
                setattr(cfg, key, raw[key])
        return cfg

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


def _check_keys(klass, values: dict, where: str) -> None:
    allowed = {f.name for f in fields(klass)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Clés inconnues dans '{where}': {sorted(unknown)} (autorisées: {sorted(allowed)})")
