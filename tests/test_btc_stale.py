# -*- coding: utf-8 -*-
"""2026-10-24 scanner/btc.py：ETH 數據攞唔到時，100 日線燈號沿用上一份要標 stale（之前寫新時間、app 當正常）。
假數據，唔上網。用法：python tests/test_btc_stale.py"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import btc  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


idx = pd.date_range("2019-01-01", "2026-10-23", freq="D")
px = pd.Series(np.exp(np.cumsum(np.random.default_rng(3).normal(0.0005, 0.02, len(idx)))) * 30000, index=idx)
FAKE_BTC = pd.DataFrame({"px": px, "mvrv": 2.0}, index=idx)


def fake_cm(asset="btc", since=None):
    if asset == "eth":
        raise RuntimeError("coinmetrics eth 503")
    return FAKE_BTC.copy()


def boom(*a, **k):
    raise RuntimeError("唔上網")


btc.coinmetrics, btc.live, btc.funding14, btc.fred, btc.get = fake_cm, boom, boom, boom, boom
out = Path(os.environ.get("TEST_OUT") or T / "_out") / "btc" / time.strftime("%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)
old = {"btc": {"date": "2026-09-01", "px": 100000.0, "ma": {"100": 95000.0}}, "eth": {"date": "2026-09-01", "px": 4000.0, "ma": {"100": 3800.0}},
       "hold": True, "dist": 0.05, "since": "2026-08-19", "flips": []}
(out / "btc.json").write_text(json.dumps({"ma100": old, "rates": {"at": "2000-01-01T00:00:00+00:00"}}), encoding="utf-8")
btc.main(str(out))
o = json.loads((out / "btc.json").read_text(encoding="utf-8"))
check(o["ma100"].get("stale") is True and o["ma100"]["btc"]["date"] == "2026-09-01", "ETH 攞唔到：沿用上一份燈號，而且標咗 stale（app 會顯示舊數據、健康 ⚠）")
check(o["close"]["date"] == "2026-10-23", "BTC 自己嘅 365 日線照樣用新數據")
print(f"\n全部 {ok} 項通過")
