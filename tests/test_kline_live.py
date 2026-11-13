# -*- coding: utf-8 -*-
"""2026-11-09 scanner/kline_live.py 測試（盤中 1 小時／4 小時 K；老師：「K線冇4小時或者一小時嗎？」「K線要繼續更新」）。
人手砌嘅 60 分鐘 K，唔上網。用法：python tests/test_kline_live.py"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

T = Path(__file__).resolve().parent
TMP = Path(os.environ.get("TEST_OUT") or T / "_out") / "kline_live" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"   # 2026-11-13：唔用系統 Temp（規矩：只喺專案 folder 寫嘢）
TMP.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import kline_live as K  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def day(d, base):
    """一日 7 支 60 分鐘 K（09:30 … 15:30，紐約時間），收市逐支 +1。"""
    return {f"{d} {h:02d}:30": (base + i, base + i + 0.5, base + i - 0.5, base + i + 0.2) for i, h in enumerate(range(9, 16))}


h1 = {**day("2026-11-05", 100), **day("2026-11-06", 110)}
h4 = K.h4_of(h1)
check(sorted(h4) == ["2026-11-05 09:30", "2026-11-05 13:30", "2026-11-06 09:30", "2026-11-06 13:30"], "4 小時：每日兩支（09:30、13:30）")
a = h4["2026-11-05 09:30"]
check(a == (100, 103.5, 99.5, 103.2), "第一支 4 小時 = 09:30–12:30 四支：開第一支、高最高、低最低、收第四支")
b = h4["2026-11-05 13:30"]
check(b == (104, 106.5, 103.5, 106.2), "第二支 4 小時 = 13:30–15:30 三支")
check(len(K.trim({**h1, **day("2026-11-04", 90)}, 2)) == 14, "trim 留最近 N 個交易日")
newer = {**day("2026-11-06", 110), **day("2026-11-09", 120)}
m = K.merge(h1, newer, 120)
check(m is not None and len(m) == 21 and m["2026-11-09 15:30"][3] == 126.2, "駁埋：舊 + 新（重疊嗰日用新）")
split = {t: (o / 4, h / 4, lo / 4, c / 4) for t, (o, h, lo, c) in day("2026-11-06", 110).items()}
check(K.merge(h1, split, 120) is None, "重疊嗰段差超過 2%（例如拆股）→ 要攞返長歷史")
p = K.pack(m)
check(p["t"] == sorted(m) and K.unpack(p) == m, "pack／unpack 來回一樣")

# rows_of：yfinance 嘅 DataFrame（UTC 時間）→ 紐約時間，淨係正常交易時段
ix = pd.DatetimeIndex(["2026-11-06 14:30", "2026-11-06 15:30", "2026-11-06 21:00", "2026-11-06 13:00"], tz="UTC")
df = pd.DataFrame({"Open": [1.0, 2, 3, 4], "High": [1.5, 2.5, 3.5, 4.5], "Low": [0.5, 1.5, 2.5, 3.5], "Close": [1.2, 2.2, 3.2, 4.2]}, index=ix)
r = K.rows_of(df)
check(sorted(r) == ["2026-11-06 09:30", "2026-11-06 10:30"], "時間轉紐約；開市前（08:00）同收市後（16:00）唔要")

# main：冇上一份 → 攞 730 日；有新鮮上一份 → 攞 5 日駁落去
calls = []
K.keys = lambda: ["MARKET", "AAA"]


def fake_dl(tickers, period):
    calls.append((tuple(tickers), period))
    return {s: ({**day("2026-11-05", 100), **day("2026-11-06", 110)} if period == "730d" else day("2026-11-09", 120)) for s in tickers}


K.download = fake_dl
tmp = TMP
K.main(tmp)
j = json.loads((Path(tmp) / "kline" / "MARKET.json").read_text(encoding="utf-8"))
check(calls[-1] == (("^NDX", "AAA"), "730d") and j["sym"] == "^NDX" and len(j["h1"]["t"]) == 14 and len(j["h4"]["t"]) == 4, "第一次：大市用 ^NDX，攞 730 日")
K.main(Path(tmp) / "b", Path(tmp) / "kline")
j2 = json.loads((Path(tmp) / "b" / "kline" / "AAA.json").read_text(encoding="utf-8"))
check(calls[-1] == (("^NDX", "AAA"), "5d") and len(j2["h1"]["t"]) == 21 and j2["h4"]["t"][-1] == "2026-11-09 13:30", "第二次：淨係攞 5 日駁落上一份")
# 2026-11-13（流程審計 S6）：上一份壞咗（at 讀唔到）唔當新鮮 → 攞返長歷史；攞唔到嘅沿用上一份
bad = Path(tmp) / "bad"
bad.mkdir()
(bad / "MARKET.json").write_text(json.dumps(dict(j, at="壞日子")), encoding="utf-8")
(bad / "AAA.json").write_text(json.dumps(j2), encoding="utf-8")                  # 啱啱寫嘅（新鮮）
K.main(Path(tmp) / "c", bad)
check(calls[-2:] == [(("AAA",), "5d"), (("^NDX",), "730d")], "上一份 at 讀唔到 → 唔當新鮮，攞 730 日；新鮮嘅照攞 5 日")
K.download = lambda tickers, period: calls.append((tuple(tickers), period)) or {}
K.main(Path(tmp) / "d", bad)
check(json.loads((Path(tmp) / "d" / "kline" / "MARKET.json").read_text(encoding="utf-8"))["at"] == "壞日子", "Yahoo 攞唔到 → 沿用上一份")
check(K._r(123.456789) == 123.46 and K._r(0.123456789) == 0.123457 and K._r(1.0) == 1.0 and K._r(None) is None and K._r(float("nan")) is None,
      "_r：1 或以上兩個小數、細過 1 六個小數；冇數／NaN → None")
print(f"\n全部 {ok} 項通過")
