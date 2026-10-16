import json
import logging
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bot.brokers.mt5 import MT5Broker, MT5Error
from bot.brokers.replay import ReplayBroker
from bot.config import BotConfig
from bot.data import synthetic_m5
from bot.live import LiveEngine
from bot.trade import Trade


def _cfg():
    cfg = BotConfig()
    cfg.strategy.adx_threshold = 0.0
    cfg.risk.max_trades_per_day = 3
    return cfg


START = 3000  # ~10 jours d'historique : l'EMA200 H1 est chauffée


class Env:
    """Rejoue des bougies à travers le moteur live. On saute les heures hors session (07h-17h UTC suffisent) pour la vitesse."""

    def __init__(self, tmp, observe_only=False):
        self.data = synthetic_m5(days=35, seed=21)
        self.cfg = _cfg()
        self.broker = ReplayBroker({"XAUUSD": self.data}, self.cfg)
        self.sp, self.jp = tmp / "s.json", tmp / "j.csv"
        self.eng = LiveEngine(self.cfg, self.broker, ["XAUUSD"], state_path=self.sp, journal_path=self.jp,
                              observe_only=observe_only)
        self.cursor = START

    @property
    def st(self):
        return self.eng.state["XAUUSD"]

    def drive(self, stop_when=None, max_bars=2500):
        end = min(len(self.data), self.cursor + max_bars)
        while self.cursor < end:
            ts, row = self.data.index[self.cursor], self.data.iloc[self.cursor]
            self.cursor += 1
            if not 7 <= ts.hour < 17:
                continue
            o, h, l, c = row[["open", "high", "low", "close"]]
            for j, px in enumerate([o, l, h, c] if c >= o else [o, h, l, c]):
                self.broker.set_price(ts + pd.Timedelta(seconds=75 * j), "XAUUSD", px)
                self.eng.tick_all()
                assert len(self.broker.pos) <= 1
                if stop_when and stop_when(self):
                    return True
        return False

    def until_trade(self):
        assert self.drive(stop_when=lambda e: e.st.trade is not None), "aucun trade sur la période de test"
        return self.st.trade


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return Env(tmp_path_factory.mktemp("live"))


def test_engine_runs_end_to_end_and_respects_rules(env):
    env.drive(max_bars=1800)
    j = pd.read_csv(env.jp)
    assert len(j) >= 2
    ent = pd.to_datetime(j.entry_time).dt.tz_convert("Europe/Paris")
    assert ent.dt.date.value_counts().max() <= 3
    m = ent.dt.hour * 60 + ent.dt.minute
    assert (((m >= 540) & (m < 695)) | ((m >= 870) & (m < 1025))).all()  # entrée loguée quelques secondes après l'ouverture
    # P&L du journal (prix nominaux) vs P&L réellement encaissé par le broker simulé : même ordre de grandeur
    realized = env.broker.balance - env.cfg.initial_capital
    assert abs(realized - j.pnl_est.sum()) < 0.35 * j.pnl_est.abs().sum() + 100


def test_state_is_resumed_after_restart(env):
    t = env.until_trade()
    env.eng._save_state()
    eng2 = LiveEngine(env.cfg, env.broker, ["XAUUSD"], state_path=env.sp, journal_path=env.jp)
    assert eng2.state["XAUUSD"].trade == t
    assert eng2.state["XAUUSD"].trades_today == env.st.trades_today
    json.loads(env.sp.read_text())


def test_loss_limit_flattens_and_blocks_entries(env):
    env.until_trade()
    env.st.day_start_equity = env.broker.equity() * 1.5       # simule une journée déjà très perdante
    env.eng.tick_all()
    assert env.st.halted_day and env.st.trade is None and not env.broker.pos
    assert pd.read_csv(env.jp).iloc[-1].path.endswith("DAILY_STOP")


def test_server_side_stop_is_detected_and_journaled(env):
    env.st.halted_day = False
    env.st.day_start_equity = env.broker.equity()
    t = env.until_trade()
    px = t.stop - 5 if t.side == 1 else t.stop + 5 - env.cfg.instruments["XAUUSD"].spread
    recs = env.broker.set_price(env.broker.now() + pd.Timedelta(seconds=1), "XAUUSD", px)
    assert recs and recs[0][2] == "server-SL"                  # le broker simulé a fermé côté serveur
    env.eng.tick_all()
    assert env.st.trade is None
    assert pd.read_csv(env.jp).iloc[-1].path.split(">")[-1] in ("SL", "BE", "TRAIL")


def test_observe_only_sends_no_orders(tmp_path, caplog):
    e = Env(tmp_path, observe_only=True)
    with caplog.at_level(logging.INFO, logger="scalp-bot"):
        e.drive(max_bars=900)
    assert e.broker.log == [] and not e.jp.exists()
    assert any("OBSERVATION" in r.message for r in caplog.records)


def test_stop_file_blocks_new_entries(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STOP").write_text("")
    e = Env(tmp_path)
    with caplog.at_level(logging.INFO, logger="scalp-bot"):
        e.drive(max_bars=900)
    assert e.broker.log == []
    assert any("STOP" in r.message for r in caplog.records)


# ---------------------------------------------------------------- adaptateur MT5 (faux module)
class FakeMT5:
    TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1 = 5, 15, 60
    ACCOUNT_TRADE_MODE_DEMO = 0
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009

    def __init__(self, server_offset_h=3):
        self.off = server_offset_h * 3600
        self.sent, self.positions = [], []
        self.retcode = 10009

    def initialize(self, **kw): return True
    def last_error(self): return (1, "ok")
    def symbol_select(self, s, e): return s != "NOPE"
    def symbol_info(self, s): return SimpleNamespace(filling_mode=2, digits=2)
    def symbol_info_tick(self, s): return SimpleNamespace(time=int(time.time()) + self.off, bid=2000.0, ask=2000.3)
    def account_info(self): return SimpleNamespace(equity=10_000.0, trade_mode=0)
    def positions_get(self, symbol=None): return self.positions

    def copy_rates_from_pos(self, s, tf, pos, count):
        step = tf * 60
        now_srv = (int(time.time()) + self.off) // step * step  # bougie en formation
        times = [now_srv - step * k for k in range(count - 1, -1, -1)]
        return np.array([(t, 1.0, 2.0, 0.5, 1.5) for t in times],
                        dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")])

    def order_send(self, req):
        self.sent.append(req)
        return SimpleNamespace(retcode=self.retcode, price=req.get("price", 0.0), comment="")


def test_mt5_adapter_wiring():
    fm = FakeMT5(server_offset_h=3)
    b = MT5Broker({"XAUUSD": "GOLD"}, mt5_module=fm)
    assert b.offset_s == 3 * 3600                        # décalage serveur déduit du tick
    c = b.candles("XAUUSD", "M5", 10)
    assert len(c) == 10 and c.index[-1] + pd.Timedelta(minutes=5) <= b.now()   # bougie en formation écartée
    assert str(c.index.tz) == "UTC"

    b.open_market("XAUUSD", 1, 0.1, 1995.123)
    r = fm.sent[-1]
    assert r["action"] == fm.TRADE_ACTION_DEAL and r["type"] == fm.ORDER_TYPE_BUY and r["sl"] == 1995.12
    assert r["symbol"] == "GOLD" and r["magic"] == b.magic and r["type_filling"] == fm.ORDER_FILLING_IOC

    fm.positions = [SimpleNamespace(magic=b.magic, type=0, volume=0.1, price_open=2000.3, sl=1995.12, tp=0.0, ticket=42)]
    assert b.position("XAUUSD").lots == 0.1 and b.position("XAUUSD").side == 1
    b.close_partial("XAUUSD", 0.05)
    r = fm.sent[-1]
    assert r["type"] == fm.ORDER_TYPE_SELL and r["position"] == 42 and r["volume"] == 0.05 and r["price"] == 2000.0
    b.modify_sl("XAUUSD", 2000.3)
    r = fm.sent[-1]
    assert r["action"] == fm.TRADE_ACTION_SLTP and r["sl"] == 2000.3 and r["position"] == 42
    fm.positions[0].magic = 999                          # position d'un autre EA : ignorée
    assert b.position("XAUUSD") is None
    fm.retcode = 10006
    with pytest.raises(MT5Error):
        b.open_market("XAUUSD", -1, 0.1, 2005.0)
    assert b.is_demo()
    with pytest.raises(MT5Error):
        MT5Broker({"X": "NOPE"}, mt5_module=FakeMT5())
