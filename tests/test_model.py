# -*- coding: utf-8 -*-
"""2026-11-13 scanner/model.py 行為測試（流程審計 S6：之前淨係黃金檔情境，冇測 run 嘅停低／警告分支同 yahoo_frame）。假數據、唔上網、唔改規則。
1. yahoo_frame：美股未收市（紐約 16:20 前）嗰日係盤中價，唔可以當收市（剔走）；收市後、第二日照用；TQQQ 調整開市價；缺嘅 ETF = 空。
2. run：正常補兩日（中間日用 plans）；scan.json 未更新要等；ETF 缺價 / 冇開市價停喺上一日；隔超過 10 日要手動補；冇 plans 要警告；
   帳戶最後處理日唔喺數據入面唔更新；冇新交易日嗰陣先印「冇新交易日」。
3. ai_search：冇 key、出錯、冇答案、冇上網來源（唔當查證）、有來源先用。
用法：python tests/test_model.py"""
import contextlib
import datetime as _dt
import io
import json
import os
import sys
import time
import types
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import v25  # noqa: E402,F401
import v24  # noqa: E402
import model  # noqa: E402
import llm  # noqa: E402

OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "model_run" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. yahoo_frame
class FakeDT(_dt.datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW


FAKE_DT = types.ModuleType("datetime")
FAKE_DT.__dict__.update({k: getattr(_dt, k) for k in dir(_dt) if not k.startswith("__")})
FAKE_DT.datetime = FakeDT
DAYS = pd.bdate_range(end="2026-11-12", periods=5)        # 最後一日 11-12 星期四


def raw(drop=()):
    cols = {}
    for k, s in enumerate(model.SYMS):
        if s in drop:
            continue
        b = 100.0 + k
        cols[s] = pd.DataFrame({"Open": b, "High": b + 1, "Low": b - 1, "Close": b, "Adj Close": b / 2, "Volume": 1e6}, index=DAYS)
    cols["TQQQ"] = pd.DataFrame({"Open": 60.0, "High": 61.0, "Low": 49.0, "Close": 50.0, "Adj Close": 40.0, "Volume": 1e6}, index=DAYS)
    return pd.concat(cols, axis=1)


def frame(ny, drop=("UGL",)):
    FakeDT.NOW = FakeDT(*ny, tzinfo=ZoneInfo("America/New_York"))
    had = sys.modules.get("yfinance")
    sys.modules["yfinance"] = types.SimpleNamespace(download=lambda *a, **k: raw(drop))
    real = sys.modules["datetime"]
    sys.modules["datetime"] = FAKE_DT
    try:
        return model.yahoo_frame()
    finally:
        sys.modules["datetime"] = real
        if had is None:
            del sys.modules["yfinance"]
        else:
            sys.modules["yfinance"] = had


last = lambda F: str(F.index[-1].date())
F = frame((2026, 11, 12, 10, 0))
check(last(F) == "2026-11-11" and len(F) == 4, "紐約 11-12 早上 10 點：今日嗰行係盤中價 → 剔走，用到 11-11")
check(last(frame((2026, 11, 12, 16, 19))) == "2026-11-11", "16:19（未到 16:20）：照剔走")
check(last(frame((2026, 11, 12, 16, 20))) == "2026-11-12", "16:20：收市價，照用")
check(last(frame((2026, 11, 13, 10, 0))) == "2026-11-12", "第二日早上：昨日（11-12）係收市價，照用")
check(F["ndx"].iloc[-1] == 100.0 and F["qqq"].iloc[-1] == 101.0 / 2 and F["irx"].iloc[-1] == 104.0 and F["TQQQ"].iloc[-1] == 40.0
      and F["tq_open"].iloc[-1] == 60.0 * 40.0 / 50.0 and F["UGL"].isna().all(),
      "欄：NDX 用收市；QQQ、ETF 用調整收市；國債息用收市；TQQQ 開市價按調整比例（60 × 40 ÷ 50 = 48）；Yahoo 冇 UGL = 空")


# ============================================================ 2. run
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


F0 = make_F()
R0 = v24.rows(F0, "2026-04-01")
D = [r["d"] for r in R0]


def plan_of(d, nd):
    return dict(date=d, next_day=nd, week_end=False, ranking=[], stocks={}, green=True, rank1=None)


def case(last_d, sc_end, F=None, plans=True, n_scan=10):
    F = F0 if F is None else F
    st = v25.new_legs(100000.0, R0[D.index(last_d)] if last_d in D else R0[0])
    st.update(cash=35000.0, positions=[], peak=None, braking=False, pending={}, slots=0, sleeve=None, last_green=True, last=last_d)
    k = D.index(sc_end)
    days = D[k - n_scan + 1:k + 1]
    sc = dict(days=days, date=sc_end, next_day=D[k + 1] if k + 1 < len(D) else "2026-04-01", week_end=False, green=True, rank1=None,
              stocks={}, ranking=[], cash=dict(green10=[True] * n_scan, ief10=[100.0] * n_scan, irx10=[4.5] * n_scan),
              plans={d: plan_of(d, D[D.index(d) + 1]) for d in days[:-1]} if plans else {})
    path = OUT / f"m_{len(list(OUT.iterdir()))}.json"
    path.write_text(json.dumps(st), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        model.run(path, sc=sc, F=F)
    return json.loads(path.read_text(encoding="utf-8")), buf.getvalue()


m, out = case(D[-3], D[-1])
w = m["view"]["actions"]["warn"]
check(m["last"] == D[-1] and [h["d"] for h in m["hist"]] == [D[-2], D[-1]] and w == [] and "冇新交易日" not in out
      and m["view"]["data_date"] == D[-1] and m["view"]["next_day"] == "2026-04-01" and m["pending"]["for"] == "2026-04-01",
      "正常：帳戶停喺 3 日前 → 補 2 日（中間日用 plans），冇警告；掛單係俾下一個交易日")
m, out = case(D[-3], D[-1], plans=False)
check(any(x.startswith(f"補跑 {D[-2]}：scan.json 冇當日決策資料") for x in m["view"]["actions"]["warn"]) and m["last"] == D[-1],
      "補跑冇 plans：照行，但警告嗰日冇更新止蝕同賣出決定")
m, out = case(D[-3], D[-3])
w = m["view"]["actions"]["warn"]
check(m["last"] == D[-3] and m["hist"][-1]["d"] == D[-3] and len(w) == 1 and w[0].startswith(f"scan.json 仲係 {D[-3]}（ETF 數據去到 {D[-1]}）")
      and "冇新交易日" not in out, "scan.json 未更新（ETF 數據新過佢）：唔行新日子，警告等掃描")
m, out = case(D[-1], D[-1])
check(m["last"] == D[-1] and m["view"]["actions"]["warn"] == [] and len(m["hist"]) == 1, "同一日再跑：冇新日子，冇「等掃描」警告")
G = make_F()
G.loc[pd.Timestamp(D[-2]), "TMF"] = np.nan
m, out = case(D[-3], D[-1], F=G)
w = m["view"]["actions"]["warn"]
check(m["last"] == D[-3] and w == [f"{D[-2]} 缺數據（TMF）：模型停喺 {D[-3]}，下次掃描再補"] and f"冇新交易日（{D[-3]}）" in out
      and m["view"]["next_day"] == D[-2], "第一個新日子 ETF 缺價：一日都唔行，停喺上一日；印「冇新交易日」")
m, out = case(D[-4], D[-1], F=G)
check(m["last"] == D[-3] and [h["d"] for h in m["hist"]] == [D[-3]] and "缺數據（TMF）" in m["view"]["actions"]["warn"][0] and "冇新交易日" not in out,
      "行咗 1 日先遇到缺價：停喺嗰日（唔印「冇新交易日」）")
H = make_F()
H.loc[pd.Timestamp(D[-2]), "tq_open"] = np.nan
m, out = case(D[-3], D[-1], F=H)
check(m["last"] == D[-3] and "缺數據（TQQQ 開市價）" in m["view"]["actions"]["warn"][0], "冇 TQQQ 開市價（低吸腳要用）：停低")
m, out = case(D[-13], D[-1])
w = m["view"]["actions"]["warn"]
check(m["last"] == D[-13] and w and w[0].startswith(f"隔咗超過 10 個交易日先更新：scan.json 冇 {D[-12]}") and "冇新交易日" in out,
      "隔咗 12 日：scan.json 只有最近 10 日 → 唔好靜靜雞跳過，停低要手動補")
try:
    case("2020-01-02", D[-1])
    msg = ""
except SystemExit as e:
    msg = str(e)
check("唔喺 Yahoo 數據入面" in msg, "帳戶最後處理日唔喺 Yahoo 數據入面：唔更新（報錯）")


# ============================================================ 3. ai_search
def ai(available=True, res=None, lab="Claude", grounded=True, err=None):
    seen = []

    def search(prompt, timeout=300):
        seen.append(prompt)
        if err:
            raise err
        return res, lab, grounded, ["https://src"]
    llm.available, llm.search = (lambda: available), search
    return model.ai_search("XYZ 有冇退市？"), seen


check(ai(available=False)[0] == (None, "冇 AI key"), "ai_search：冇 AI key → 唔查")
got, seen = ai(res={"delisted": "no"})
check(got == ({"delisted": "no"}, "Claude") and seen[0].endswith("唔肯定就答 unknown。"), "ai_search：有上網來源 → 用答案；問題尾加「唔肯定就答 unknown」")
check(ai(res={"delisted": "yes"}, grounded=False)[0] == (None, "Claude：冇上網搜尋來源，唔當查證"), "ai_search：冇上網來源 → 唔當查證（退市、拆股唔可以靠估）")
check(ai(res=None, lab="額度用晒" * 60)[0] == (None, ("額度用晒" * 60)[:200]), "ai_search：AI 冇答案 → 返原因（最多 200 字）")
check(ai(err=RuntimeError("timeout"))[0] == (None, "AI 搜尋出錯：timeout"), "ai_search：出錯 → 返錯誤，唔 crash")
print(f"\n全部 {ok} 項通過")
