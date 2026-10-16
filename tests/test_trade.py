import pytest

from bot.config import Instrument, StrategyParams
from bot.trade import Trade, position_size

P = StrategyParams()
GOLD = Instrument("XAUUSD", value_per_point_per_lot=100.0)


def _long(lots=0.40):
    # entrée 2000, stop 1995 => risque 5 ; TP1 2005, TP2 2010
    return Trade.open(1, 2000.0, 1995.0, lots, P, GOLD)


def test_position_size_risks_target_percent():
    lots = position_size(10_000, 0.5, 5.0, GOLD)  # 50 $ / (5 * 100) = 0.10 lot
    assert lots == pytest.approx(0.10)
    assert position_size(100, 0.5, 5.0, GOLD) == 0.0  # sous le lot minimum => refusé, jamais arrondi vers le haut
    assert position_size(10_000, 0.5, 0.0, GOLD) == 0.0


def test_levels_and_partial_sizes():
    t = _long()
    assert (t.tp1, t.tp2) == (2005.0, 2010.0)
    assert (t.lots_tp1, t.lots_tp2) == (pytest.approx(0.20), pytest.approx(0.10))
    s = Trade.open(-1, 2000.0, 2005.0, 0.40, P, GOLD)
    assert (s.tp1, s.tp2) == (1995.0, 1990.0)


def test_full_winner_path_and_pnl():
    t = _long()
    f1 = t.step(2001, 2000.5, 2006, P)         # TP1
    assert [f.reason for f in f1] == ["TP1"] and t.stop == 2000.0  # breakeven
    f2 = t.step(2006, 2001, 2011, P)           # TP2
    assert [f.reason for f in f2] == ["TP2"] and t.remaining == pytest.approx(0.10)
    assert t.on_bar_close(2011, 2.0, P)        # trailing: 2011 - 1.5*2 = 2008
    assert t.stop == pytest.approx(2008.0)
    t.on_bar_close(2009, 2.0, P)               # le trailing ne recule jamais
    assert t.stop == pytest.approx(2008.0)
    f3 = t.step(2010, 2007, 2012, P)
    assert [f.reason for f in f3] == ["TRAIL"] and t.closed
    # 0.2*5 + 0.1*10 + 0.1*8 = 2.8 pts * 100 = 280 $
    assert t.pnl(GOLD) == pytest.approx(280.0)


def test_stop_checked_before_targets_when_both_in_same_bar():
    t = _long()
    fills = t.step(2000, 1994, 2006, P)
    assert [f.reason for f in fills] == ["SL"] and t.closed
    assert t.pnl(GOLD) == pytest.approx(-0.40 * 5 * 100)


def test_tp1_then_breakeven_in_same_bar_is_pessimistic():
    t = _long()
    fills = t.step(2002, 1999.5, 2006, P)  # touche TP1 puis retombe sous l'entrée
    assert [f.reason for f in fills] == ["TP1", "BE"] and t.closed
    assert t.pnl(GOLD) == pytest.approx(0.20 * 5 * 100)


def test_gap_through_stop_fills_at_open():
    t = _long()
    fills = t.step(1990, 1989, 1991, P)
    assert fills[0].price == 1990.0  # pas 1995 : le gap est subi


def test_short_mirror():
    t = Trade.open(-1, 2000.0, 2005.0, 0.40, P, GOLD)
    fills = t.step(1999, 1994, 1999.5, P)
    assert [f.reason for f in fills] == ["TP1"] and t.stop == 2000.0
    t.step(1996, 1989, 1997, P)
    assert t.tp2_hit
    t.on_bar_close(1989, 2.0, P)
    assert t.stop == pytest.approx(1992.0)


def test_roundtrip_serialization():
    t = _long()
    t.step(2001, 2000.5, 2006, P)
    t2 = Trade.from_dict(t.to_dict())
    assert t2 == t
