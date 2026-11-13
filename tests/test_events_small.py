# -*- coding: utf-8 -*-
"""2026-11-13 scanner/events.py 行為測試（流程審計 S6：test_events.py 將 earnings 換走、冇測美股未收市剔走今日、pack 貼日子、
ai_fill 幾時問／幾時停）。假數據、唔上網、唔叫 AI、唔改規則。
1. earnings：開市前公佈睇當日、收市後睇翌日；週末公佈貼下一個交易日；冇實際 EPS、圖外、第一日開市前、最後一日收市後都唔要；
   說明有預測、勝／輸預期先寫
2. 紐約 16:15 前今日未收市：_ohlc／tech／add_ohlc／long_of／main 都唔用今日；16:15 起照用
3. pack：唔係交易日貼去下一個交易日；圖之後嘅唔要
4. ai_fill：收錢 AI 非繁忙照問、免費 AI 繁忙都照問；出錯（唔係額度）記失敗、照問下一批；額度用晒即刻停、唔記失敗；
   冇來源唔用；之前搵到嘅原因重問失敗照留
用法：python tests/test_events_small.py"""
import json
import os
import sys
import time
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "events_small" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(EVENTS_OUT=str(OUT))
import events as E  # noqa: E402
import llm  # noqa: E402
import bars  # noqa: E402
import structure  # noqa: E402

NYT = ZoneInfo("America/New_York")
SLEPT = []
E.time.sleep = lambda s: SLEPT.append(s)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


class NowDT(datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW


E.datetime = NowDT

# ============================================================ 1. earnings
IDX = pd.bdate_range("2026-01-02", "2026-03-31")
C = pd.Series(100.0, index=IDX)
C[C.index >= "2026-02-10"] *= 0.8                          # 02-09 收市後公佈 → 翌日 -20%
C[C.index >= "2026-02-16"] *= 1.05                         # 02-14（星期六）公佈 → 下一個交易日 02-16 +5%
C[C.index >= "2026-03-02"] *= 1.1                          # 03-02 開市前公佈 → 當日 +10%
nan = float("nan")
ROWS = [(datetime(2026, 2, 9, 16, 5), 1.00, 1.50, -33.3),       # 收市後
        (datetime(2026, 2, 14, 18, 0), 1.20, 1.14, 5.0),        # 星期六晚：貼 02-16（唔再加一日）
        (datetime(2026, 3, 2, 8, 0), 1.10, nan, nan),           # 開市前；冇預測、冇勝負
        (datetime(2026, 2, 23, 16, 0), nan, 1.0, nan),          # 未公佈（冇實際 EPS）
        (datetime(2025, 11, 3, 8, 0), 0.9, 0.8, 12.5),          # 圖之前
        (datetime(2026, 4, 15, 16, 0), 1.3, 1.2, 8.3),          # 圖之後
        (datetime(2026, 3, 31, 16, 5), 1.4, 1.3, 7.7),          # 最後一日收市後：冇翌日
        (datetime(2026, 1, 2, 8, 0), 0.8, 0.8, 0.0)]            # 第一日開市前：冇前一日
ED = pd.DataFrame({"Reported EPS": [r[1] for r in ROWS], "EPS Estimate": [r[2] for r in ROWS], "Surprise(%)": [r[3] for r in ROWS]},
                  index=pd.DatetimeIndex([r[0] for r in ROWS], tz=NYT))
YF = {"ed": ED}


class Tk:
    def __init__(self, sym):
        pass

    def get_earnings_dates(self, limit=16):
        if isinstance(YF["ed"], Exception):
            raise YF["ed"]
        return YF["ed"]


sys.modules["yfinance"] = types.SimpleNamespace(Ticker=Tk)
got = [(e["d"], e["label"], e["detail"], e["chg"]) for e in E.earnings("AAA", C)]
check(got == [("2026-02-10", "業績 -20%", "2026-02-09 收市後公佈：每股盈利 1.00，預測 1.50（輸預期 33.3%）；翌日股價 -20.0%。", -0.2),
              ("2026-02-16", "業績 +5%", "2026-02-14 收市後公佈：每股盈利 1.20，預測 1.14（勝預期 5.0%）；翌日股價 +5.0%。", 0.05),
              ("2026-03-02", "業績 +10%", "2026-03-02 開市前公佈：每股盈利 1.10；當日股價 +10.0%。", 0.1)],
      "earnings：收市後睇翌日、開市前睇當日、週末貼下一個交易日；冇實際 EPS／圖外／冇前一日或翌日嘅唔要；有預測、勝負先寫")
YF["ed"] = None
check(E.earnings("AAA", C) == [], "earnings：Yahoo 冇業績日 → 冇")
YF["ed"] = RuntimeError("Yahoo 404")
check(E.earnings("AAA", C) == [], "earnings：Yahoo 出錯 → 冇（唔 crash）")

# ============================================================ 2. 紐約 16:15 前今日未收市
DAYS = pd.bdate_range("2026-10-01", "2026-11-13")             # 最後一日 11-13 星期五
CL = np.linspace(100, 120, len(DAYS))
ONE = pd.DataFrame({"Open": CL - 1, "High": CL + 2, "Low": CL - 2, "Close": CL}, index=DAYS)
E.RAW = pd.concat({"AAA": ONE}, axis=1)
E.RAW_LONG = E.RAW
bars.long_bars = lambda d, o, h, lo, c: list(d)
structure.analyze = lambda d, o, h, lo, c: list(d)


def at(hh, mm):
    NowDT.NOW = datetime(2026, 11, 13, hh, mm, tzinfo=NYT)


at(15, 0)
CH = dict(d=[str(x.date()) for x in DAYS], c=[round(float(x), 2) for x in CL])
ch = E.add_ohlc(CH, "AAA")
check(str(E._ohlc("AAA").index[-1].date()) == "2026-11-12" and E.tech("AAA")[-1] == "2026-11-12" and E.long_of("AAA")[-1] == "2026-11-12",
      "紐約 15:00：今日未收市 → 開高低收、技術結構、長歷史 K 線都唔用今日")
check(ch["o"][-1] == ch["c"][-1] == ch["h"][-1] == ch["l"][-1] and ch["o"][-2] == round(float(CL[-2] - 1), 2),
      "add_ohlc：今日未收市嗰支用收市價補（冇影）；之前照用開高低")
at(16, 14)
check(E.long_of("AAA")[-1] == "2026-11-12" and str(E._ohlc("AAA").index[-1].date()) == "2026-11-12", "16:14 照當未收市")
at(16, 15)
check(str(E._ohlc("AAA").index[-1].date()) == "2026-11-13" and E.long_of("AAA")[-1] == "2026-11-13" and E.tech("AAA")[-1] == "2026-11-13",
      "16:15 起當收市，用埋今日")
check(E.add_ohlc(CH, "AAA")["h"][-1] == round(float(CL[-1] + 2), 2), "add_ohlc：收市後今日用真開高低")
check(E.long_of("ZZZ") is None and E.tech("ZZZ") is None and E.add_ohlc(CH, "ZZZ") == CH, "冇呢隻嘅數據 → 冇長歷史、冇技術結構、圖唔變")

# ============================================================ 3. pack
c3 = pd.Series([1.0, 2.0, 3.0], index=pd.DatetimeIndex(["2026-11-11", "2026-11-12", "2026-11-13"]))
P = E.pack("AAA", "AAA", c3, [dict(d="2026-11-12", kind="big"), dict(d="2026-11-01", kind="light"), dict(d="2026-11-12T", kind="x"),
                              dict(d="2026-11-14", kind="big")])
check([(e["d"], e["i"]) for e in P["events"]] == [("2026-11-12", 1), ("2026-11-01", 0), ("2026-11-12T", 2)] and P["chart"]["c"] == [1.0, 2.0, 3.0],
      "pack：交易日對到第幾日；唔係交易日貼去之後第一個交易日；圖最後一日之後嘅唔要")

# ============================================================ 4. ai_fill
E.PAUSE, E.BATCH, E.MAX_CALLS, E.AI_SECS = 0, 1, 5, 900
llm.available = lambda: True
ASK = []
REPLY = []


def search(prompt, timeout=None):
    ASK.append(prompt)
    if len(ASK) > 5:
        raise AssertionError("問得太多")
    x = REPLY.pop(0)
    if isinstance(x, Exception):
        raise x
    return x


llm.search = search


def jobs(*ds):
    return [((0, -int(d.replace("-", ""))), "MARKET", "納指 100", dict(d=d, kind="big", chg=0.05)) for d in ds]


def fill(prov, peak, reply, ds, cache=None):
    ASK.clear()
    REPLY[:] = reply
    llm.PROVIDER, llm.peak_now = prov, (lambda: peak)
    cache = {} if cache is None else cache
    n = E.ai_fill(jobs(*ds), cache)
    return n, cache


OKR = lambda d, lab: ({"items": [{"date": d, "label": lab, "detail": "原因", "src": [1]}]}, "Gemini（Google 搜尋）", True,  # noqa: E731
                      [{"title": "Reuters", "url": "https://r.test/a"}])
n, cache = fill("deepseek", False, [OKR("2026-11-12", "減息")], ["2026-11-12"])
check(n == 1 and len(ASK) == 1 and cache["MARKET|2026-11-12"]["label"] == "減息" and cache["MARKET|2026-11-12"]["model"] == "Gemini",
      "ai_fill：收錢 AI（DeepSeek）非繁忙時段照問")
n, cache = fill("gemini", True, [OKR("2026-11-12", "減息")], ["2026-11-12"])
check(n == 1 and len(ASK) == 1, "ai_fill：免費 AI 喺繁忙時段都照問（繁忙時段只限收錢 AI）")
n, cache = fill("deepseek", True, [], ["2026-11-12"])
check(n == 0 and ASK == [], "ai_fill：收錢 AI 繁忙時段唔問")
n, cache = fill("gemini", False, [(None, "AI 搜尋出錯：timeout", False, []), OKR("2026-11-11", "非農")], ["2026-11-12", "2026-11-11"])
check(n == 2 and len(ASK) == 2 and cache["MARKET|2026-11-12"]["fail"] == 1 and cache["MARKET|2026-11-12"]["why"] == "AI 搜尋出錯：timeout"
      and cache["MARKET|2026-11-11"]["label"] == "非農", "ai_fill：一批出錯（唔係額度）→ 記失敗原因，照問下一批")
n, cache = fill("gemini", False, [RuntimeError("connection reset"), OKR("2026-11-11", "非農")], ["2026-11-12", "2026-11-11"])
check(n == 2 and cache["MARKET|2026-11-12"]["why"] == "connection reset" and "label" in cache["MARKET|2026-11-11"], "ai_fill：搜尋 crash 都當一批失敗，照做落去")
n, cache = fill("gemini", False, [(None, "HTTP Error 429: Too Many Requests", False, []), OKR("2026-11-11", "非農")], ["2026-11-12", "2026-11-11"])
check(n == 0 and len(ASK) == 1 and cache == {}, "ai_fill：額度／速度上限 → 即刻停、唔記失敗（聽日再問）")
n, cache = fill("gemini", False, [({"items": [{"date": "2026-11-12", "label": "減息"}]}, "Gemini", False, [])], ["2026-11-12"],
                {"MARKET|2026-11-12": {"fail": 1}})
check(cache["MARKET|2026-11-12"]["fail"] == 2 and cache["MARKET|2026-11-12"]["why"] == "冇搜尋來源", "ai_fill：有答案但冇搜尋來源 → 唔用，失敗 +1")
old = {"MARKET|2026-11-12": {"label": "舊原因", "src": []}}
n, cache = fill("gemini", False, [({"items": [{"date": "2026-11-12", "label": "unknown"}]}, "Gemini", True, [])], ["2026-11-12"], old)
check(cache["MARKET|2026-11-12"] == {"label": "舊原因", "src": [], "sv": 2}, "ai_fill：之前搵到原因、重問搵唔到 → 保留舊原因，唔再問")

# ============================================================ 5. main：未收市唔用今日
E.RAW = E.RAW_LONG = None
ND = pd.bdate_range("2022-06-01", "2026-11-13")
E.download = lambda syms, start: pd.DataFrame({"^NDX": 10000 * np.exp(0.0003 * np.arange(len(ND)))}, index=ND)
E.targets = lambda: ([], set(), set(), {}, {})
llm.available = lambda: False
llm.start = llm.finish = lambda *a, **k: None                # 唔好寫真 docs/ai_usage_scan.json


def last_day():
    E.main()
    m = json.loads((OUT / "MARKET.json").read_text(encoding="utf-8"))
    return m["chart"]["d"][-1], json.loads((OUT / "index.json").read_text(encoding="utf-8"))["items"]["MARKET"]["last"]


at(15, 0)
check(last_day() == ("2026-11-12", "2026-11-12"), "main：紐約 15:00 今日未收市 → 事件線去到昨日")
at(16, 15)
check(last_day() == ("2026-11-13", "2026-11-13"), "main：16:15 起用埋今日")
print(f"\n全部 {ok} 項通過")
