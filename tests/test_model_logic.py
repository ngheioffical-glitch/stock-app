# -*- coding: utf-8 -*-
"""2026-10-24 計錢邏輯測試（/codex 檢討：141 項測試全部係週邊，scan／lead／v24／v25／model 冇測試）。唔上網、唔使錢、唔改規則。
1. 手計例子：領導股 buy-stop、跳空、止蝕、開市賣、現金唔夠、退市；保本同跟 swing low 上移、賣出原因、剎車、掛單；現金收息；
   三隻 ETF 腳（分 4 份買返、波幅賣晒、低吸、輪動安全版）；月尾再平衡（領導股只用現金）。
2. 冇事後數據：加咗 T 日之後嘅數據，T 日（同之前）嘅訊號同帳戶唔可以變。
3. 黃金檔：假數據由頭行一次 model.run（40 個交易日、兩次月尾、10 日領導股），同 tests/fixtures/model_golden.json 比較；
   改規則或者改程式改到結果就會唔過。真係有意改：UPDATE_GOLDEN=1 python tests/test_model_logic.py 重寫，再講清楚點解。
用法：python tests/test_model_logic.py"""
import copy
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
APP = T.parent
sys.path.insert(0, str(APP / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import lead  # noqa: E402
import v25  # noqa: E402,F401  （設定 V2.7：vol_ins、xr_safe）
import v24  # noqa: E402
import model  # noqa: E402

OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "model_logic" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
GOLD = T / "fixtures" / "model_golden.json"
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


near = lambda a, b, tol=1e-9: a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))
C = lead.RULE["cost"]

# ============================================================ 1a. 領導股：每日（lead.step）
DAYS = ["2026-01-05", "2026-01-06"]


def lst(cash=10000.0, positions=None, pending=None):
    return dict(cash=cash, positions=positions or [], trades=[], peak=None, braking=False, pending=pending or {}, slots=0, sleeve=None, last_green=True)


def lsc(stocks, ranking=(), green=True, week_end=False, rank1=None, cash=None):
    return dict(days=DAYS, stocks=stocks, ranking=list(ranking), green=green, week_end=week_end, rank1=rank1, next_day="2026-01-07",
                date=DAYS[-1], cash=cash or {})


def bar(o, h, lo, c):
    return dict(o10=[o[0], o[1]], h10=[h[0], h[1]], l10=[lo[0], lo[1]], c10=[c[0], c[1]])


def acts():
    return dict(fills=[], stops=[], warn=[])


buy = lambda sym, trig, stop, frac=0.2, rank=1: dict(sym=sym, rank=rank, trigger=trig, stop=stop, frac=frac)
pend = lambda *b, sells=(): {"for": DAYS[1], "buys": list(b), "sells": list(sells)}

st = lst(pending=pend(buy("AAA", 100.0, 90.0)))
lead.step(st, lsc({"AAA": bar((95, 98), (99, 105), (94, 97), (96, 104))}), 1, acts())
p = st["positions"][0]
check(p["entry"] == 100.0 and near(p["shares"], 2000 / (100 * (1 + C))) and near(st["cash"], 8000.0) and p["R"] == 10.0,
      f"buy-stop：最高 105 ≥ 100 → 用 100 買，20% × 10000 = 2000（連 0.1% 成本），現金剩 8000（{st['cash']:.2f}）")

st = lst(pending=pend(buy("AAA", 100.0, 90.0)))
lead.step(st, lsc({"AAA": bar((95, 103), (99, 106), (94, 102), (96, 105))}), 1, acts())
check(st["positions"][0]["entry"] == 103.0, "跳空高開 103：用開市價 103 成交（唔係 100）")

st = lst(pending=pend(buy("AAA", 100.0, 90.0)))
lead.step(st, lsc({"AAA": bar((95, 98), (99, 99.5), (94, 97), (96, 99))}), 1, acts())
check(not st["positions"] and st["cash"] == 10000.0 and st["pending"] == {}, "冇升穿 100：唔買，掛單用完就清走")

st = lst(cash=1000.0, positions=[dict(sym="ZZZ", date="2026-01-02", entry=90.0, shares=100.0, stop=80.0, R=10.0, be=False, last_close=90.0, frac=0.2)],
         pending=pend(buy("AAA", 100.0, 90.0, frac=0.3)))
lead.step(st, lsc({"AAA": bar((95, 98), (99, 105), (94, 97), (96, 104)), "ZZZ": bar((90, 90), (91, 91), (89, 89), (90, 90))}), 1, acts())
a = next(x for x in st["positions"] if x["sym"] == "AAA")
check(near(a["shares"] * 100 * (1 + C), 1000.0) and near(st["cash"], 0.0), "應該用 30% × 10000 = 3000，但現金得 1000：用晒 1000，唔會借錢")

old = lambda **k: dict(dict(sym="AAA", date="2026-01-02", entry=100.0, shares=20.0, stop=90.0, R=10.0, be=False, last_close=100.0, frac=0.2), **k)
for o, lo, want, what in ((95, 89, 90.0, "盤中跌穿止蝕 90：用止蝕價 90 賣"), (85, 84, 85.0, "開市已經跳空低過止蝕：用開市價 85 賣")):
    st = lst(cash=0.0, positions=[old()])
    lead.step(st, lsc({"AAA": bar((100, o), (101, o + 1), (99, lo), (100, o))}), 1, acts())
    tr = st["trades"][-1]
    check(not st["positions"] and tr["sell"] == want and near(st["cash"], 20 * want * (1 - C))
          and near(tr["ret"], round(want * (1 - C) / (100 * (1 + C)) - 1, 4)), f"{what}（回報 {tr['ret']:+.2%}，已扣兩邊成本）")

st = lst(pending=pend(buy("AAA", 100.0, 90.0)))
lead.step(st, lsc({"AAA": bar((95, 98), (99, 101), (94, 88), (96, 89))}), 1, acts())
check(not st["positions"] and st["trades"][-1]["sell"] == 90.0, "即日買完即日跌穿止蝕：照止蝕價 90 賣")

st = lst(cash=0.0, positions=[old()], pending=pend(sells=[dict(sym="AAA", reason="大市紅燈")]))
lead.step(st, lsc({"AAA": bar((100, 97), (101, 99), (99, 96), (100, 98))}), 1, acts())
check(st["trades"][-1]["sell"] == 97 and st["trades"][-1]["reason"] == "大市紅燈", "上一日決定賣：今日開市價 97 賣")

real_ai = lead._ai
lead._ai = lambda prompt: ({"status": "acquired", "cash_per_share": 105.5, "note": "被收購"}, "測試來源")
st = lst(cash=0.0, positions=[old(miss=4)])
lead.step(st, lsc({"AAA": dict(o10=[100, None], h10=[100, None], l10=[100, None], c10=[100, None])}), 1, a_ := acts())
lead._ai = real_ai
check(not st["positions"] and st["trades"][-1]["sell"] == 105.5 and "被收購" in st["trades"][-1]["reason"], "連續 5 日冇價 + AI（有來源）話被收購：按收購價 105.5 賣")

# ============================================================ 1b. 領導股：收市決定（lead.plan）、現金、要做
ST = lambda close, **k: dict(dict(o10=[close] * 2, h10=[close] * 2, l10=[close] * 2, c10=[close] * 2, close=close, sma200=50.0, swing_low=None, atr=None), **k)
st = lst(cash=0.0, positions=[old(last_close=121.0)])
a_ = acts()
lead.plan(st, lsc({"AAA": ST(121.0, swing_low=112.0, atr=5.0)}, ranking=[dict(rank=1, sym="AAA", status="唔合格", pivot=130, stop=110)]), a_)
p = st["positions"][0]
check(p["be"] and p["stop"] == 111.0 and a_["stops"][0]["new"] == 111.0, "收市 121 ≥ 入貨 100 + 2R：保本（止蝕 ≥ 100），再跟 swing low 112 − 0.2 × ATR 5 = 111")

for kw, sc_kw, want in ((dict(close=95.0), {}, "大市紅燈"), (dict(close=95.0, sma200=96.0), dict(green=True), "收市跌穿 200 日線"),
                        (dict(close=100.0), dict(green=True, week_end=True, rank=20), "排名第 20（要頭 15）")):
    rank = sc_kw.pop("rank", 1)
    st = lst(cash=0.0, positions=[old()])
    lead.plan(st, lsc({"AAA": ST(**kw)}, ranking=[dict(rank=rank, sym="AAA", status="唔合格", pivot=130, stop=90)], **dict(dict(green=False), **sc_kw)), acts())
    check(st["pending"]["sells"] and want in st["pending"]["sells"][0]["reason"] and st["pending"]["buys"] == [], f"賣出原因：{want}")

st = lst(cash=0.0, positions=[old()])
st["braking"] = True
lead.plan(st, lsc({"AAA": ST(100.0)}, ranking=[dict(rank=8, sym="AAA", status="唔合格", pivot=130, stop=90)], week_end=True), acts())
check("排名第 8（要頭 6）" in st["pending"]["sells"][0]["reason"], "剎車中：星期五排名要頭 6")

R4 = [dict(rank=i + 1, sym=s, status=stt, pivot=50.0 + i, stop=45.0 + i) for i, (s, stt) in enumerate(
    [("AAA", "候選"), ("BBB", "唔合格"), ("CCC", "候選"), ("DDD", "收市高過前高，唔追"), ("EEE", "候選"), ("FFF", "候選"), ("GGG", "候選")])]
st = lst(cash=10000.0, positions=[old(sym="ZZZ")])
lead.plan(st, lsc({"ZZZ": ST(100.0)}, ranking=R4, rank1="AAA"), acts())
b = st["pending"]["buys"]
check(st["slots"] == 4 and [x["sym"] for x in b] == ["AAA", "CCC", "EEE", "FFF", "GGG"] and near(b[0]["frac"], 0.3) and near(b[1]["frac"], 0.2),
      "揸 1 隻 → 4 個空位、最多掛 8 張：淨係「候選」、排名次序；排第 1 用 30%、其他 20%")
st = lst(cash=10000.0)
lead.plan(st, lsc({}, ranking=R4, green=False), acts())
check(st["slots"] == 0 and st["pending"]["buys"] == [], "大市紅燈：唔掛買單")

pos5 = [old(sym=s, shares=10.0, last_close=70.0) for s in ("AAA", "BBB", "CCC", "DDD")]
st = lst(cash=900.0, positions=pos5)
st["peak"] = 5000.0
lead.plan(st, lsc({s: ST(70.0) for s in ("AAA", "BBB", "CCC", "DDD")}, week_end=True,
                  ranking=[dict(rank=r, sym=s, status="唔合格", pivot=90, stop=60) for r, s in ((3, "AAA"), (1, "BBB"), (4, "CCC"), (2, "DDD"))]), acts())
check(st["braking"] and sorted(x["sym"] for x in st["pending"]["sells"]) == ["AAA", "CCC"] and st["slots"] == 0,
      "星期五呢部分 3700 ≤ 高位 5000 × 75%：剎車，最多揸 2 隻（留排名最高 BBB、DDD，賣 AAA、CCC）")
st = lst(cash=4500.0)
st.update(peak=5000.0, braking=True)
lead.plan(st, lsc({}, week_end=True), acts())
check(not st["braking"], "返到高位 × 87.5% 以上：剎車解除")

st = lst(cash=10000.0)
lead.cash_sleeve(st, dict(cash=dict(green10=[True, True], ief10=[100.0, 101.0], irx10=[5.04, 5.04])), 1)
check(near(st["cash"], 10000 * (1 + 0.0504 / 252)) and st["sleeve"] == "bill", "上一日綠燈：現金收國債息（5.04% ÷ 252）")
st = lst(cash=10000.0)
st["sleeve"] = "bill"
lead.cash_sleeve(st, dict(cash=dict(green10=[False, False], ief10=[100.0, 101.0], irx10=[5.0, 5.0])), 1)
check(near(st["cash"], 10000 * (1 - 0.001) * 1.01) and st["sleeve"] == "ief", "轉紅燈：現金轉 IEF（扣 0.1%），跟 IEF 升 1%")
st = lst(cash=10000.0, pending={"for": "x", "buys": [buy("AAA", 100.0, 90.0)], "sells": []})
check(near(lead.todo(st, 40000.0)[0]["frac"], 0.05), "要做嘅比例按成個帳戶：領導股 10000 × 20% ÷ 總數 40000 = 5%")

# ============================================================ 1c. 三隻 ETF 腳（v24，V2.7 設定）同再平衡（v25）
check(v24.RULE["vol_ins"] == (0.30, 0.275, 0.25, 0.225) and v24.RULE["xr_safe"] and v25.W == dict(lead=0.35, trend=0.45, dip=0.05, xr=0.15),
      "V2.7 設定：35／45／5／15、趨勢腳 4 個再買門檻、輪動腳安全版")


def rr(d="2026-01-06", px=None, op=None, green=True, vol=0.20, rsi2=50.0, me=False, pick="CASH", pick_safe="CASH", bill=0.0):
    return dict(d=d, px=px or {"TQQQ": 100.0, "IEF": 100.0}, op=op, bill=bill, green=green, vol=vol, rsi2=rsi2, me=me, pick=pick, why_pick="測試",
                pick_safe=pick_safe, why_safe="測試安全版", q=400.0, ndx=20000.0, e21=19800.0, s50=19500.0, s200=18000.0)


def legs(subs=None, f=None, dip=None, xr=None):
    return dict(trend=dict(val=1000.0, held=bool(f), f=f, subs=subs, pend=None, why=None, epx=80.0 if f else None, edate="2026-01-02" if f else None,
                           epx_ief=None, edate_ief=None),
                dip=dict(dict(val=100.0, pos=False, pend=None, why=None, epx=None, edate=None, days=0), **(dip or {})),
                xr=dict(dict(val=100.0, hold="CASH", pend=None, why=None, epx=None, edate=None), **(xr or {})), trades=[], start="2026-01-02", last="2026-01-05")


for subs, kw, want, what in (([False] * 4, dict(vol=0.26), [True, True, False, False], "冇揸、波幅 26%：低過 30%、27.5% → 買 2／4 份"),
                             ([True, True, False, False], dict(vol=0.24), [True, True, True, False], "揸 2 份、波幅 24%：再加 25% 嗰份 → 3／4"),
                             ([True] * 4, dict(vol=0.36), [False] * 4, "揸滿、波幅 36% ≥ 35%：一次過賣晒"),
                             ([True] * 4, dict(green=False), [False] * 4, "揸滿、大市紅燈：一次過賣晒"),
                             ([True] * 4, dict(vol=0.34), None, "揸滿、波幅 34%：照揸（唔使郁）")):
    s = legs(subs=subs)
    v24.decide(s, rr(**kw))
    check(s["trend"]["pend"] == want, f"趨勢腳：{what}")
for dip, kw, want, what in (({}, dict(rsi2=20.0), "buy", "冇倉、綠燈、2 日 RSI 20 < 25：開市低吸"), ({}, dict(rsi2=20.0, green=False), None, "紅燈唔低吸"),
                            (dict(pos=True, days=3), dict(rsi2=75.0), "sell", "RSI 75 > 70：賣"), (dict(pos=True, days=10), {}, "sell", "揸滿 10 日：時間止蝕賣")):
    s = legs(subs=[False] * 4, dip=dip)
    v24.decide(s, rr(**kw))
    check(s["dip"]["pend"] == want, f"低吸腳：{what}")
for xr, kw, want, what in (({}, dict(me=True, pick="TQQQ"), "TQQQ", "月尾揀中 QQQ、綠燈：揸 TQQQ"),
                           ({}, dict(me=True, pick="TQQQ", pick_safe="UGL", green=False), "UGL", "安全版：月尾紅燈唔揀 TQQQ，揀其餘最好嗰樣"),
                           (dict(hold="TQQQ"), dict(vol=0.36), "CASH", "安全版：月中波幅 > 35%，揸緊 TQQQ 轉現金")):
    s = legs(subs=[False] * 4, xr=xr)
    v24.decide(s, rr(**kw))
    check(s["xr"]["pend"] == want, f"輪動腳：{what}")

s = legs(subs=[True, True, False, False], f=0.5)
s["trend"]["pend"] = [True, True, True, False]
v24.step(s, rr(px={"TQQQ": 110.0, "IEF": 101.0}), rr(d="2026-01-05"), [])
check(near(s["trend"]["val"], 1000 * (0.5 * 1.1 + 0.5 * 1.01) * (1 - C * 0.25)) and s["trend"]["f"] == 0.75 and near(s["trend"]["epx"], 90.0),
      "趨勢腳一半 TQQQ（+10%）一半 IEF（+1%），再加到 ¾：成本只計郁咗嘅 ¼；平均入貨價 (½×80 + ¼×110) ÷ ¾ = 90")
s = legs(subs=[False] * 4, dip=dict(pend="buy", why="測試"))
v24.step(s, rr(px={"TQQQ": 55.0, "IEF": 100.0}, op=50.0), rr(d="2026-01-05"), [])
check(near(s["dip"]["val"], 100 * (1 - C) * 55 / 50) and s["dip"]["pos"] and s["dip"]["epx"] == 50.0, "低吸：開市 50 買、收市 55")
s = legs(subs=[False] * 4, dip=dict(pos=True, pend="sell", why="測試", epx=50.0, edate="2026-01-02", days=3))
v24.step(s, rr(px={"TQQQ": 58.0, "IEF": 100.0}, op=60.0), rr(d="2026-01-05", px={"TQQQ": 55.0, "IEF": 100.0}), [])
check(near(s["dip"]["val"], 100 * 60 / 55 * (1 - C)) and not s["dip"]["pos"] and near(s["trades"][-1]["ret"], 0.2), "低吸賣：開市 60 賣（入貨 50，回報 +20%）")
s = legs(subs=[False] * 4, xr=dict(hold="TQQQ", pend="CASH", why="測試", epx=80.0, edate="2026-01-02"))
v24.step(s, rr(px={"TQQQ": 90.0, "IEF": 100.0}), rr(d="2026-01-05", px={"TQQQ": 100.0, "IEF": 100.0}), [])
check(near(s["xr"]["val"], 90 * (1 - C)) and s["xr"]["hold"] == "CASH" and near(s["trades"][-1]["ret"], 0.125), "輪動腳 TQQQ 跌 10% 後轉現金：只計賣出一邊成本")

s = dict(trend=dict(val=45.0), dip=dict(val=5.0), xr=dict(val=10.0))
mv = v25.rebalance(s, 40.0, 3.0, "2026-01-30", f := [])
turn = 3 + sum(abs(w / 0.65 * 63 - v) for w, v in ((0.45, 45), (0.05, 5), (0.15, 10)))
check(mv == -3.0 and near(v25.legs_val(s), 63 - C * turn) and near(s["trend"]["val"] / s["xr"]["val"], 3.0) and "唔會為咗比例賣股" in f[0]["reason"],
      "月尾再平衡：領導股 40 > 目標 35，但現金得 3 → 只俾出 3（唔賣股）；ETF 腳按 45：5：15 分")
s = dict(trend=dict(val=50.0), dip=dict(val=10.0), xr=dict(val=20.0))
check(v25.rebalance(s, 20.0, 20.0, "2026-01-30", []) == 15.0, "領導股 20 < 目標 35：由 ETF 腳俾 15 返領導股")

# ============================================================ 2. 冇事後數據
def make_F(n=320, end="2026-03-06", seed=7, extra=0):
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    sig = np.where((np.arange(n) // 40) % 2 == 0, 0.009, 0.026)          # 每 40 日轉一次波幅，令趨勢腳有買有賣
    rq = rng.normal(0.0008, sig)
    qqq = 300 * np.exp(np.cumsum(rq))
    tlt = 90 * np.exp(np.cumsum(rng.normal(0.0002, 0.009, n)))
    gld = 180 * np.exp(np.cumsum(rng.normal(0.0004, 0.008, n)))
    F = pd.DataFrame({"ndx": qqq * 40 * np.exp(rng.normal(0, 0.001, n)), "qqq": qqq, "tlt": tlt, "gld": gld, "irx": 4.5,
                      "TQQQ": 50 * np.cumprod(1 + 3 * rq), "IEF": 95 * np.exp(np.cumsum(rng.normal(0.0001, 0.003, n))),
                      "TMF": 30 * np.cumprod(1 + 3 * np.r_[0, np.diff(np.log(tlt))]), "UGL": 40 * np.cumprod(1 + 2 * np.r_[0, np.diff(np.log(gld))])}, index=idx)
    F["tq_open"] = F["TQQQ"].shift(1).fillna(F["TQQQ"]) * (1 + rng.normal(0, 0.004, n))
    if extra:                                                          # T 日之後再加啲亂數據（大跌、大升）
        fut = pd.bdate_range(start=idx[-1] + pd.offsets.BDay(1), periods=extra)
        G = pd.DataFrame({c: F[c].iloc[-1] * np.linspace(1, 0.4 if c in ("TQQQ", "qqq", "ndx", "tq_open") else 1.6, extra) for c in F.columns}, index=fut)
        F = pd.concat([F, G])
    return F


F0 = make_F()
full = {r["d"]: r for r in v24.rows(make_F(extra=15), "2026-03-30")}
same = True
for k in (230, 260, 300, 319):
    cut = F0.iloc[:k + 1]
    last = v24.rows(cut, str(F0.index[k + 1].date()) if k + 1 < len(F0) else "2026-03-09")[-1]
    same &= all(last[f] == full[last["d"]][f] for f in ("green", "vol", "rsi2", "pick", "pick_safe", "me", "bill", "ndx", "e21", "s50", "s200", "px", "op"))
check(same, "v24 訊號：T 日只用到 T 日之前嘅數據（加咗之後 15 日大升大跌，T 日燈號、波幅、RSI、輪動揀法都唔變）")

a1, a2 = lst(pending=pend(buy("AAA", 100.0, 90.0))), lst(pending=pend(buy("AAA", 100.0, 90.0)))
base = {"AAA": dict(o10=[95, 98, 70], h10=[99, 105, 71], l10=[94, 97, 60], c10=[96, 104, 65])}
twin = copy.deepcopy(base)
twin["AAA"].update(o10=[95, 98, 200], h10=[99, 105, 210], l10=[94, 97, 190], c10=[96, 104, 205])
sc1, sc2 = lsc(base), lsc(twin)
sc1["days"] = sc2["days"] = DAYS + ["2026-01-07"]
lead.step(a1, sc1, 1, acts())
lead.step(a2, sc2, 1, acts())
check(a1 == a2, "領導股：處理 T 日只睇 T 日同之前（聽日嘅價唔同，今日嘅買入、止蝕、現金都一樣）")


# ============================================================ 3. 黃金檔：model.run 由頭行（假數據）
def scenario(F):
    R = v24.rows(F, "2026-03-09")
    i0 = [r["d"] for r in R].index(str(F0.index[-41].date()))
    days = [str(d.date()) for d in F0.index[-10:]]
    S = {"AAA": ([100, 101.5, 102, 101, 99, 96, 95.5, 96, 97, 98], [102, 103, 103, 102, 100, 97, 96.5, 97, 98, 99],
                 [99, 100.5, 101, 99.5, 97, 94, 94.5, 95.5, 96, 97], [101.5, 102.5, 101.5, 99.8, 97.5, 95.2, 96, 96.8, 97.5, 98.2]),
         "BBB": ([112, 113, 114, 115, 116, 115, 116, 117, 118, 117], [114, 115, 116, 117, 118, 117, 118, 119, 119.5, 118.5],
                 [111, 112, 113, 114, 115, 114, 115, 116, 117, 116], [113, 114, 115, 116, 117, 116, 117, 118, 118, 117.5]),
         "CCC": ([52, 53, 54, 55.5, 57, 58, 60, 61.5, 63, 64], [53.5, 54.5, 56, 57.5, 58.5, 60.5, 62, 63.5, 65, 66],
                 [51.5, 52.5, 53.5, 55, 56.5, 57.5, 59.5, 61, 62.5, 63.5], [53, 54, 55.5, 57, 58, 60, 61.5, 63, 64.5, 65.5])}
    stocks = {s: dict(o10=o, h10=h, l10=lo, c10=c, close=c[-1], sma200=40.0, swing_low=min(lo[-5:]), atr=2.0) for s, (o, h, lo, c) in S.items()}
    stocks.update({s: dict(o10=[px] * 10, h10=[px] * 10, l10=[px] * 10, c10=[px] * 10, close=px, sma200=20.0, swing_low=px * 0.9, atr=1.0)
                   for s, px in (("DDD", 68.0), ("EEE", 29.0))})
    sc = dict(days=days, date=days[-1], next_day="2026-03-09", week_end=True, green=True, rank1="DDD", stocks=stocks,
              ranking=[dict(rank=1, sym="DDD", status="候選", pivot=70.0, stop=63.0), dict(rank=2, sym="CCC", status="收市高過前高，唔追", pivot=64.0, stop=58.0),
                       dict(rank=3, sym="AAA", status="唔合格", pivot=103.0, stop=95.0), dict(rank=4, sym="EEE", status="候選", pivot=30.0, stop=27.0)],
              cash=dict(green10=[True] * 10, ief10=[float(x) for x in F0["IEF"].iloc[-10:]], irx10=[4.5] * 10))
    st = v25.new_legs(100000.0, R[i0], note="測試帳戶")
    st.update(cash=35000.0, positions=[], peak=None, braking=False, slots=0, sleeve=None, last_green=True,
              pending={"for": days[0], "buys": [dict(sym="AAA", rank=3, trigger=101.0, stop=95.0, frac=0.2), dict(sym="BBB", rank=5, trigger=120.0, stop=110.0, frac=0.2),
                                                 dict(sym="CCC", rank=2, trigger=50.0, stop=46.0, frac=0.2)], "sells": []})
    return st, sc


def run_model(F, tag):
    st, sc = scenario(F)
    path = OUT / f"model_{tag}.json"
    path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        model.run(path, sc=sc, F=F)
    m = json.loads(path.read_text(encoding="utf-8"))
    m["view"].pop("generated", None)
    return m


M = run_model(F0, "base")
check(M == run_model(make_F(extra=15), "future"), "成個模型：加咗之後 15 日大升大跌，帳戶、持倉、要做全部一樣（冇偷睇）")
tr = {t["sym"]: t for t in M["trades"] if t["leg"] == "lead"}
pos = {p["sym"]: p for p in M["positions"]}
check(tr["AAA"]["entry"] == 101.0 and tr["AAA"]["sell"] == 95.0 and "打止蝕" in tr["AAA"]["reason"] and "BBB" not in tr and "BBB" not in pos,
      "黃金情境：AAA 升穿 101 買、跌穿止蝕 95 賣；BBB 冇升穿 120 冇買")
check(pos["CCC"]["entry"] == 52.0 and pos["CCC"]["be"] and near(pos["CCC"]["stop"], 57.1),
      f"黃金情境：CCC 跳空 52 買，收市 65.5 ≥ 52 + 2 × 6 保本，止蝕跟 swing low 57.5 − 0.2 × 2 = 57.1（{pos['CCC']['stop']}）")
check([(b["sym"], round(b["frac"], 9)) for b in M["pending"]["buys"]] == [("DDD", 0.3), ("EEE", 0.2)] and M["slots"] == 4,
      "黃金情境：下一日掛 DDD（排第 1，30%）同 EEE（20%）")
reb = [h["d"] for h in M["hist"] if any(f["s"] == "再平衡" for f in h["f"])]
check(len(M["hist"]) == 40 and reb == ["2026-03-02"],
      f"黃金情境：行咗 40 日；2 月尾再平衡喺下一個交易日收市做（{reb}；1 月尾偏離唔夠 1%，唔使郁）")
check(abs(sum(h["weight"] for h in M["view"]["holdings"]) + M["view"]["cash_frac"] - 1) < 0.002, "黃金情境：比重加現金 = 100%")


def diff(a, b, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            diff(a.get(k, "（冇）"), b.get(k, "（冇）"), f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
    elif isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        if not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6):
            out.append(f"{path}：{b} → {a}")
    elif a != b:
        out.append(f"{path}：{str(b)[:80]} → {str(a)[:80]}")
    return out


if os.environ.get("UPDATE_GOLDEN") == "1" or not GOLD.exists():
    GOLD.write_text(json.dumps(M, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"⚠ 寫咗黃金檔 {GOLD.name}（有意改規則先好咁做，要講清楚點解）")
d = diff(M, json.loads(GOLD.read_text(encoding="utf-8")))
check(not d, "同黃金檔一樣（帳戶值、每筆買賣、持倉、要做、每日快照）" + ("" if not d else "：\n  " + "\n  ".join(d[:15])))
print(f"\n全部 {ok} 項通過")
