# -*- coding: utf-8 -*-
"""2026-11-13 scanner/model_cont.py 行為測試（流程審計 S6：之前冇測試）。假 Yahoo 數據、假掃描、唔上網、唔改規則。
model_cont 將研究帳戶（Tiingo 價）轉做 Yahoo 價繼續行：
1. 領導股：入場價、止蝕、R 按「Yahoo 收市 ÷ 研究收市」換算，股數反向換算；掃描冇呢隻就唔換
2. ETF 腳買入價：按 ETF「Yahoo ÷ 研究」比例換算；冇揸（None）唔郁；研究冇嗰隻 ETF 價就唔郁
3. 帳戶其他欄（現金、高位、剎車、閒錢放邊、最近 100 筆交易）照抄；之後逐日重播掃描 + model.run；最後掃描寫返 scan.json（唔覆蓋更新嘅）
用法：python tests/test_model_cont.py"""
import json
import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "model_cont" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
OUT.mkdir(parents=True, exist_ok=True)
import lead  # noqa: E402
import model as M  # noqa: E402
import scan as SC  # noqa: E402
import v24  # noqa: E402
import v25  # noqa: E402
import model_cont as MC  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def make_F(n=230, end="2026-03-31", seed=4):
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    rq = 0.001 + rng.normal(0, 0.01, n)
    qqq = 300 * np.exp(np.cumsum(rq))
    F = pd.DataFrame({"ndx": qqq * 40, "qqq": qqq, "tlt": 90 * np.exp(np.cumsum(rng.normal(0, 0.004, n))),
                      "gld": 180 * np.exp(np.cumsum(rng.normal(0.0003, 0.004, n))), "irx": 4.5, "TQQQ": 50 * np.cumprod(1 + 3 * rq),
                      "IEF": 95 * np.exp(np.cumsum(rng.normal(0, 0.002, n))), "TMF": 30.0, "UGL": 40.0}, index=idx)
    F["tq_open"] = F["TQQQ"] * 0.995
    return F


F = make_F()
R = v24.rows(F, M.next_day(F.index[-1]))
D = [r["d"] for r in R]
d0 = D[-3]
r0 = R[-3]
SCANS, RUNS = [], []
M.yahoo_frame = lambda: F
SC.nasdaq_universe = lambda: (["AAA", "BBB"], {})
SC.download = lambda syms, end=None: {s: pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-03-31"])) for s in syms}


def fake_scan(d):
    SCANS.append(d)
    SC.OUT.write_text(json.dumps({"date": d, "next_day": "x", "stocks": {"AAA": {"close": 55.0}}}), encoding="utf-8")


SC.scan = fake_scan
lead.plan = lambda st, sc, actions: st.update(pending={"buys": [], "sells": []})
M.snap = lambda st, r, fills: None
M.view = lambda st, r, sc, nxt, actions: {"next_day": nxt}
M.total = lambda st: 123456.0
M.run = lambda path, sc=None, F=None: RUNS.append((sc["date"], str(F.index[-1].date())))
M.CONT, M.SCAN = OUT / "model_cont.json", OUT / "scan.json"
(OUT / "tmpscan").mkdir()
MC.tempfile = types.SimpleNamespace(mkdtemp=lambda: str(OUT / "tmpscan"))     # 唔好寫去系統 Temp

px = r0["px"]
SEED = dict(date=d0, nav=100000.0,
            px_end={"TQQQ": px["TQQQ"] / 2, "IEF": px["IEF"] * 2, "UGL": px["UGL"]},      # Yahoo ÷ 研究：TQQQ ×2、IEF ×0.5；冇 TMF
            lead=dict(cash=1000.0, peak=200000.0, braking=True, green=False,
                      positions=[dict(sym="AAA", date="2026-01-05", entry=50.0, shares=100.0, stop=45.0, R=5.0, be=False, close=50.0),
                                 dict(sym="BBB", date="2026-02-02", entry=20.0, shares=10.0, stop=18.0, R=2.0, be=True, close=20.0)]),
            legs=dict(trend=dict(val=50000.0, held="TQQQ", epx=30.0, epx_ief=90.0), dip=dict(val=20000.0, pos=False, epx=None),
                      xr=dict(val=30000.0, hold="TMF", epx=40.0), trades=[dict(n=k) for k in range(105)]))
sp = OUT / "seed.json"
sp.write_text(json.dumps(SEED), encoding="utf-8")
MC.main(sp)
st = json.loads(M.CONT.read_text(encoding="utf-8"))
a, b = st["positions"]
check(a["entry"] == 55.0 and abs(a["stop"] - 49.5) < 1e-9 and a["R"] == 5.5 and abs(a["shares"] - 100 / 1.1) < 1e-9 and a["last_close"] == 55.0
      and abs(a["shares"] * a["entry"] - 5000) < 1e-6, "領導股：Yahoo 收市 55 ÷ 研究 50 = 1.1 → 入場價、止蝕、R × 1.1，股數 ÷ 1.1（金額唔變）")
check((b["entry"], b["stop"], b["R"], b["shares"], b["last_close"], b["be"]) == (20.0, 18.0, 2.0, 10.0, 20.0, True) and a["frac"] == lead.RULE["frac"],
      "領導股：掃描冇呢隻嘅 Yahoo 價 → 唔換算；保本狀態、每注比例照抄")
check(st["trend"]["epx"] == 60.0 and st["trend"]["epx_ief"] == 45.0, "ETF 腳：趨勢腳 TQQQ 買入價 × 2、IEF × 0.5（Yahoo ÷ 研究價）")
check(st["dip"]["epx"] is None and st["xr"]["epx"] == 40.0, "ETF 腳：冇揸（None）唔郁；研究冇嗰隻 ETF（TMF）價就唔郁")
check((st["cash"], st["peak"], st["braking"], st["sleeve"], st["last_green"], st["start"], st["last"], st["ver"]) ==
      (1000.0, 200000.0, True, "ief", False, d0, d0, v25.VER) and [t["n"] for t in st["trades"]] == list(range(5, 105)) and st["pending"] == {"buys": [], "sells": []},
      "帳戶：現金、高位、剎車照抄；紅燈閒錢放 IEF；交易只留最近 100 筆")
check(SCANS == [d0, D[-2], D[-1]] and RUNS == [(D[-2], D[-2]), (D[-1], D[-1])], "之後逐日重播：每日掃描一次，model.run 只用到嗰日嘅數據")
check(json.loads(M.SCAN.read_text(encoding="utf-8"))["date"] == D[-1], "最後一日嘅掃描寫返 scan.json")
M.SCAN.write_text(json.dumps({"date": "2099-01-01"}), encoding="utf-8")
SEED["lead"]["green"] = True
sp.write_text(json.dumps(SEED), encoding="utf-8")
MC.main(sp)
check(json.loads(M.SCAN.read_text(encoding="utf-8"))["date"] == "2099-01-01" and json.loads(M.CONT.read_text(encoding="utf-8"))["sleeve"] == "bill",
      "scan.json 已經新過重播 → 唔覆蓋；綠燈閒錢放短債（bill）")
(OUT / "seed_bad.json").write_text(json.dumps(dict(SEED, date="1999-01-04")), encoding="utf-8")
try:
    MC.main(OUT / "seed_bad.json")
    err = ""
except AssertionError as e:
    err = str(e)
check("Yahoo 數據冇 1999-01-04" in err, "研究帳戶日子唔喺 Yahoo 數據 → 停低（唔會亂接）")
print(f"\n全部 {ok} 項通過")
