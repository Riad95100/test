import pandas as pd
import pytest

from bot.config import BotConfig
from bot.data import load_csv


def test_load_mt5_export_tab_separated_with_timezone(tmp_path):
    f = tmp_path / "xau.csv"
    f.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n"
                 "2025.01.06\t10:00:00\t2000.0\t2001.0\t1999.0\t2000.5\t10\n"
                 "2025.01.06\t10:05:00\t2000.5\t2002.0\t2000.0\t2001.5\t12\n")
    df = load_csv(f, tz="Europe/Athens")  # UTC+2 en janvier
    assert df.index[0] == pd.Timestamp("2025-01-06 08:00", tz="UTC")
    assert list(df.columns) == ["open", "high", "low", "close"]


def test_load_csv_comma_and_rejects_inconsistent_bars(tmp_path):
    ok = tmp_path / "ok.csv"
    ok.write_text("time,open,high,low,close\n2025-01-06 10:00,1,2,0.5,1.5\n")
    assert len(load_csv(ok)) == 1
    bad = tmp_path / "bad.csv"
    bad.write_text("time,open,high,low,close\n2025-01-06 10:00,1,0.9,0.5,1.5\n")
    with pytest.raises(ValueError):
        load_csv(bad)


def test_config_roundtrip_and_unknown_keys(tmp_path):
    p = tmp_path / "c.json"
    BotConfig().to_json(p)
    assert BotConfig.from_json(p).strategy == BotConfig().strategy
    p.write_text('{"risk": {"risk_percent": 1}}')
    with pytest.raises(ValueError, match="inconnues"):
        BotConfig.from_json(p)
