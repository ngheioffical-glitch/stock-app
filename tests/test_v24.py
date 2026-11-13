# -*- coding: utf-8 -*-
"""2026-11-13 scanner/v24.py、v25.py 行為測試（流程審計 S6：之前靠 test_model_logic 嘅黃金檔間接測，好多分支冇直接斷言）。
假數據、唔上網、唔改規則。用 V2.7 設定（import v25：趨勢腳 4 個再買門檻、輪動腳安全版）；V2.4 嘅嘢臨時改返 RULE 再還原。
1. trend_target：加份、減份、全買、全賣、唔變。
2. rows：頭 199 日（200 日線未有）唔出；月尾；輪動揀法（最高而且高過國債息）同安全版；波幅、價錢缺就唔寫。
3. step：趨勢腳現金 → TQQQ／一半、IEF → TQQQ、加份、賣晒、減份（每次成交、成本、入貨價、IEF 入貨日）；_r 冇價當唔郁；V2.4 月尾再平衡 1% 門檻。
4. decide：原因文字、低吸邊界（RSI 25、70、揸滿 10 日）、輪動安全版（波幅啱啱 35% 照揸）、第一日。
5. 顯示：trend_positions、trend_todo、todo、tq_view、trend_info、cash_frac、規則文字。
6. v25：new_legs、rebalance（1% 門檻、領導股收／俾現金）、leg_cash、leg_positions、leg_todo、step_legs、leg_view。
用法：python tests/test_v24.py"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import v25  # noqa: E402  （V2.7 設定）
import v24  # noqa: E402

ok = 0
C = v24.RULE["cost"]


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


near = lambda a, b, tol=1e-9: a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))

# ============================================================ 1. trend_target
tt = lambda subs, pend, f: v24.trend_target(dict(subs=subs, pend=pend), f)
F_, T_ = False, True
for args, want, what in ((([T_, T_, F_, F_], [T_] * 4, 0.6), (1.0, 0.4), "加到 4／4 份：全部轉 TQQQ（轉 IEF 嗰 40%）"),
                         (([T_, T_, F_, F_], [F_] * 4, 0.6), (0.0, 0.6), "減到 0 份：TQQQ 全部賣"),
                         (([T_, F_, F_, F_], [T_, T_, F_, F_], 0.3), (0.3 + 0.7 / 3, 0.7 / 3), "1 → 2 份：未買嗰 70% 按餘下 3 份轉 1 份"),
                         (([T_, T_, T_, F_], [T_, F_, F_, F_], 0.75), (0.25, 0.5), "3 → 1 份：TQQQ 75% 賣 2／3"),
                         (([T_, F_, F_, F_], [F_, T_, F_, F_], 0.4), (0.4, 0.0), "份數唔變：唔郁"),
                         ((None, [T_, T_, F_, F_], 0.0), (0.5, 0.5), "第一次（冇 subs）：2／4 份 → 一半"),
                         (([T_, T_, F_, F_], [T_, T_, F_, F_], 0.55), (0.55, 0.0), "同上一日一樣：唔郁")):
    got = tt(*args)
    check(near(got[0], want[0]) and near(got[1], want[1]), f"trend_target：{what}")


# ============================================================ 2. rows
def make_F(n=330, end="2026-03-31", qd=0.003, td=-0.001, gd=0.001, seed=1):
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    rq = qd + rng.normal(0, 0.01, n)
    qqq = 300 * np.exp(np.cumsum(rq))
    tlt = 90 * np.exp(np.cumsum(td + rng.normal(0, 0.004, n)))
    gld = 180 * np.exp(np.cumsum(gd + rng.normal(0, 0.004, n)))
    F = pd.DataFrame({"ndx": qqq * 40, "qqq": qqq, "tlt": tlt, "gld": gld, "irx": 4.5, "TQQQ": 50 * np.cumprod(1 + 3 * rq), "IEF": 95.0,
                      "TMF": 30 * tlt / tlt[0], "UGL": 40 * gld / gld[0]}, index=idx)
    F["tq_open"] = F["TQQQ"] * 0.99
    return F


F = make_F()
R = v24.rows(F, "2026-04-01")
check(len(R) == len(F) - 199 and R[0]["d"] == str(F.index[199].date()), "rows：頭 199 日 200 日線未有，唔出；第 200 日開始")
by = {r["d"]: r for r in R}
check(by["2026-01-30"]["me"] and not by["2026-01-29"]["me"] and R[-1]["me"] and v24.rows(F.iloc[:-1], "2026-03-31")[-1]["me"] is False,
      "月尾：下一個交易日（最後一日用 next_day）係下個月先算（1-30 係、1-29 唔係；3-30 之後係 3-31 唔係）")
last = R[-1]
check(last["pick"] == "TQQQ" and "最高係 QQQ 而且高過國債息 → 揸 TQQQ" in last["why_pick"] and last["pick_safe"] == "UGL"
      and "最高係 黃金 而且高過國債息 → 揸 UGL" in last["why_safe"], "輪動：QQQ 回報最高 → TQQQ；安全版唔揀 QQQ，揀黃金 → UGL")
q = F["qqq"]
vol = float(np.std(q.pct_change().iloc[-20:].values, ddof=1) * np.sqrt(252))
check(abs(last["vol"] - vol) < 1.5e-4 and near(last["bill"], 4.5 / 100 / 252) and last["green"] and near(last["q"], float(q.iloc[-1]))
      and near(last["s200"], float(F["ndx"].iloc[-200:].mean()), 1e-9), "波幅 = 近 20 日 QQQ 日回報標準差 × √252；國債息每日 = 年息 ÷ 252；綠燈")
down = v24.rows(make_F(qd=-0.003, td=-0.002, gd=-0.002), "2026-04-01")[-1]
check(down["pick"] == "CASH" and "冇一樣高過國債息 → 揸現金" in down["why_pick"] and down["pick_safe"] == "CASH" and not down["green"],
      "全部跌：輪動揸現金；大市紅燈")
G = make_F()
G.iloc[-1, G.columns.get_loc("UGL")] = np.nan
G.iloc[-1, G.columns.get_loc("tq_open")] = np.nan
g = v24.rows(G, "2026-04-01")[-1]
check("UGL" not in g["px"] and g["op"] is None and set(g["px"]) == {"TQQQ", "IEF", "TMF"}, "缺價：嗰隻唔寫入 px；冇開市價 op = None")


# ============================================================ 3. step（趨勢腳）
def st0(subs=None, f=None, epx=None, edate=None, val=1000.0, dip=None, xr=None, ief=(None, None)):
    return dict(trend=dict(val=val, held=bool(f), f=f, subs=subs, pend=None, why="測試", epx=epx, edate=edate, epx_ief=ief[0], edate_ief=ief[1]),
                dip=dict(dict(val=100.0, pos=False, pend=None, why=None, epx=None, edate=None, days=0), **(dip or {})),
                xr=dict(dict(val=100.0, hold="CASH", pend=None, why=None, epx=None, edate=None), **(xr or {})),
                trades=[], start="2026-01-02", last="2026-01-05", capital=1200.0)


def rr(d="2026-01-06", px=None, op=None, green=True, vol=0.20, rsi2=50.0, me=False, pick="CASH", pick_safe="CASH", bill=0.0):
    return dict(d=d, px=px or {"TQQQ": 100.0, "IEF": 100.0}, op=op, bill=bill, green=green, vol=vol, rsi2=rsi2, me=me, pick=pick, why_pick="測試",
                pick_safe=pick_safe, why_safe="測試安全版", q=400.0, ndx=20000.0, e21=19800.0, s50=19500.0, s200=18000.0)


P = rr(d="2026-01-05")
fl = lambda fills: [(x["sym"], x["side"], x["px"]) for x in fills if x["leg"] == "trend"]


def go(s, pend, r):
    s["trend"]["pend"] = pend
    f = []
    v24.step(s, r, P, f)
    return s["trend"], f


t, f = go(st0(), [T_] * 4, rr(px={"TQQQ": 110.0, "IEF": 101.0}))
check(fl(f) == [("TQQQ", "買入", 110.0)] and near(t["val"], 1000 * (1 - C)) and t["f"] == 1.0 and t["epx"] == 110.0 and t["edate"] == "2026-01-06"
      and t["epx_ief"] is None and t["subs"] == [T_] * 4 and t["held"], "現金 → 全部 TQQQ：只買 TQQQ（冇 IEF 賣買），成本一邊")
t, f = go(st0(), [T_, T_, F_, F_], rr(px={"TQQQ": 110.0, "IEF": 101.0}))
check(fl(f) == [("TQQQ", "買入", 110.0), ("IEF", "買入", 101.0)] and t["f"] == 0.5 and t["epx_ief"] == 101.0 and t["edate_ief"] == "2026-01-06"
      and near(t["val"], 1000 * (1 - C)), "現金 → 2／4 份：一半 TQQQ、一半 IEF（記低 IEF 入貨價同日子）")
t, f = go(st0(subs=[F_] * 4, f=0.0, ief=(99.0, "2025-12-01")), [T_, T_, F_, F_], rr(px={"TQQQ": 110.0, "IEF": 101.0}))
check(fl(f) == [("IEF", "賣出", 101.0), ("TQQQ", "買入", 110.0)] and near(t["val"], 1010 * (1 - C * 2 * 0.5)) and t["f"] == 0.5 and t["edate"] == "2026-01-06"
      and t["epx"] == 110.0 and t["epx_ief"] == 99.0 and t["edate_ief"] == "2025-12-01", "全 IEF（+1%）→ 2／4 份：賣一半 IEF 買 TQQQ，兩邊成本；IEF 舊入貨價照留")
t, f = go(st0(subs=[T_, T_, F_, F_], f=0.5, epx=80.0, edate="2026-01-02"), [T_, T_, T_, F_], rr(px={"TQQQ": 110.0, "IEF": 101.0}))
a = 550 / 1055
mv = (1 - a) / 2
check(fl(f) == [("IEF", "賣出", 101.0), ("TQQQ", "買入", 110.0)] and near(t["f"], a + mv) and t["edate"] == "2026-01-02"
      and near(t["epx"], (a * 80 + mv * 110) / (a + mv)) and near(t["val"], 1055 * (1 - 2 * C * mv)), "已揸 TQQQ 再加份：入貨價按比例平均，入貨日照舊")
t, f = go(st0(subs=[T_] * 4, f=1.0, epx=80.0, edate="2026-01-02"), [F_] * 4, rr(px={"TQQQ": 90.0, "IEF": 100.0}, green=False))
s5 = t
check(fl(f) == [("TQQQ", "賣出", 90.0), ("IEF", "買入", 100.0)] and near(t["val"], 900 * (1 - 2 * C)) and t["f"] == 0.0 and t["epx"] is None
      and t["edate"] is None and t["epx_ief"] == 100.0 and t["edate_ief"] == "2026-01-06" and not t["held"], "全 TQQQ（−10%）→ 賣晒：轉 IEF，清走 TQQQ 入貨價")
t, f = go(st0(subs=[T_] * 4, f=1.0, epx=80.0, edate="2026-01-02"), [T_, T_, F_, F_], rr(px={"TQQQ": 90.0, "IEF": 100.0}, green=False))
check(fl(f) == [("TQQQ", "賣出", 90.0), ("IEF", "買入", 100.0)] and t["f"] == 0.5 and t["epx"] == 80.0 and t["edate"] == "2026-01-02"
      and t["epx_ief"] == 100.0 and near(t["val"], 900 * (1 - 2 * C * 0.5)) and t["subs"] == [T_, T_, F_, F_], "4 → 2 份：賣一半 TQQQ（入貨價照留），IEF 由今日計")
t, f = go(st0(subs=[T_, T_, T_, F_], f=0.75, epx=80.0, edate="2026-01-02", ief=(99.0, "2025-12-01")), [T_, F_, F_, F_], rr(green=False))
check(fl(f) == [("TQQQ", "賣出", 100.0), ("IEF", "買入", 100.0)] and near(t["f"], 0.25) and t["epx_ief"] == 99.0 and t["edate_ief"] == "2025-12-01",
      "3 → 1 份（本身有 IEF）：IEF 舊入貨價同日子照留")
s = st0(subs=[T_] * 4, f=1.0, epx=80.0, edate="2026-01-02")
s["trend"]["pend"] = [F_] * 4
v24.step(s, rr(px={"TQQQ": 90.0, "IEF": 100.0}, green=False), P, [])
check(s["trades"][-1] == dict(leg="trend", sym="TQQQ", date="2026-01-02", entry=80.0, sell_date="2026-01-06", sell=90.0, ret=0.125, reason="測試"),
      "賣出記入交易：入貨 80、賣 90、+12.5%")
check(v24._r(rr(px={"TQQQ": 110.0}), None, "TQQQ") == 1.0 and v24._r(rr(px={"IEF": 1.0}), P, "TQQQ") == 1.0
      and v24._r(rr(px={"TQQQ": 110.0}), rr(px={"IEF": 1.0}), "TQQQ") == 1.0 and v24._r(rr(px={"TQQQ": 110.0}), P, "TQQQ") == 1.1,
      "_r：今日或上日冇價 = 當冇郁（1.0）；有價 = 今日 ÷ 上日")

# ---- V2.4 月尾再平衡（v24 自己嗰個；V2.7 用 v25.rebalance）
s = st0(val=900.0, dip=dict(val=50.0), xr=dict(val=50.0))
s["rebal"] = True
f = []
v24.step(s, rr(green=False), P, f)
check([x["sym"] for x in f] == ["再平衡"] and "趨勢腳 減 10.0%" in f[0]["reason"] and "低吸腳 加 5.0%" in f[0]["reason"]
      and near(s["trend"]["val"], 0.8 * (1000 - C * 200)) and near(s["dip"]["val"], 0.1 * (1000 - C * 200)) and not s["rebal"],
      "V2.4 月尾再平衡：900／50／50 → 80／10／10（偏離 20% > 1%：有成交記錄，扣成本）")
s = st0(val=805.0, dip=dict(val=97.5), xr=dict(val=97.5))
s["rebal"] = True
f = []
v24.step(s, rr(green=False), P, f)
check(f == [] and near(s["trend"]["val"], 0.8 * (1000 - C * 10)) and near(s["xr"]["val"], 0.1 * (1000 - C * 10)),
      "V2.4：偏離啱啱 1%（805／97.5／97.5）：唔記成交，但照調返比例")

# ============================================================ 4. decide
v24.RULE["vol_ins"], keep = (0.35,), v24.RULE["vol_ins"]
s = st0(subs=None)
v24.decide(s, rr(vol=0.2))
check(s["trend"]["pend"] == [T_] and s["trend"]["why"] == "大市綠燈 + QQQ 20 日波幅 20.0% < 35% → 揸 TQQQ", "V2.4 單一門檻：綠燈 + 波幅 20% → 揸 TQQQ")
v24.RULE["vol_ins"] = keep
for subs, kw, pend, why, what in (
        (None, dict(vol=0.26), [T_, T_, F_, F_], "TQQQ 加到 2／4 份", "第一日波幅 26%：買 2／4 份"),
        (None, dict(vol=0.32), [F_] * 4, "大市綠燈但 QQQ 20 日波幅 32.0% 未低過 30% → 先揸 IEF", "第一日波幅 32%：一份都未買"),
        ([T_] * 4, dict(green=False), [F_] * 4, "大市轉紅燈", "紅燈：全賣"),
        ([T_, T_, F_, F_], dict(vol=0.35), [F_] * 4, "QQQ 20 日波幅 35.0% ≥ 35%", "波幅啱啱 35%：全賣"),
        ([F_] * 4, dict(vol=0.30), None, None, "冇揸、波幅啱啱 30%（唔低過）：唔買"),
        ([F_] * 4, dict(vol=0.2999), [T_, F_, F_, F_], "TQQQ 加到 1／4 份", "波幅 29.99%：買第 1 份")):
    s = st0(subs=subs)
    v24.decide(s, rr(**kw))
    check(s["trend"]["pend"] == pend and (why is None or why in s["trend"]["why"]), f"趨勢腳決定：{what}")
for dip, kw, pend, what in (({}, dict(rsi2=25.0), None, "RSI 啱啱 25：唔低吸（要 < 25）"), ({}, dict(rsi2=24.9), "buy", "RSI 24.9：低吸"),
                            (dict(pos=True, days=3), dict(rsi2=70.0), None, "RSI 啱啱 70：唔賣（要 > 70）"),
                            (dict(pos=True, days=9), {}, None, "揸咗 9 日：未到時間止蝕"), (dict(pos=True, days=10), {}, "sell", "揸滿 10 日：賣")):
    s = st0(subs=[F_] * 4, dip=dip)
    v24.decide(s, rr(**kw))
    check(s["dip"]["pend"] == pend, f"低吸腳：{what}")
for xr, kw, first, pend, reb, what in (({}, dict(me=False, pick="TMF"), True, "TMF", False, "第一日：唔係月尾都揀（但唔使再平衡）"),
                                       ({}, dict(me=True, pick="TMF"), False, "TMF", True, "月尾揀 TMF：聽日換，同埋再平衡"),
                                       (dict(hold="TMF"), dict(me=True, pick="TMF"), False, None, True, "月尾揀返同一樣：唔使換"),
                                       (dict(hold="TQQQ"), dict(vol=0.35), False, None, False, "安全版：揸 TQQQ、波幅啱啱 35%（唔 > 35%）：照揸"),
                                       (dict(hold="TQQQ"), dict(vol=0.351), False, "CASH", False, "安全版：波幅 35.1% → 轉現金"),
                                       (dict(hold="TMF"), dict(green=False), False, None, False, "安全版只管 TQQQ：揸 TMF 紅燈唔郁"),
                                       ({}, dict(me=True, pick="TQQQ", pick_safe="UGL", vol=0.36), False, "UGL", True, "月尾揀中 TQQQ 但波幅 36%：改揀 UGL")):
    s = st0(subs=[F_] * 4, xr=xr)
    v24.decide(s, rr(**kw), first=first)
    check(s["xr"]["pend"] == pend and bool(s.get("rebal")) == reb, f"輪動腳：{what}")
check(v24.xr_ok(rr(vol=0.35)) and not v24.xr_ok(rr(vol=0.36)) and not v24.xr_ok(rr(green=False)), "xr_ok：綠燈而且波幅 ≤ 35% 先揸得 TQQQ")
v24.RULE["xr_safe"] = False
check(v24.xr_ok(rr(green=False)) and v24.xr_pick(rr(pick="TQQQ", green=False)) == ("TQQQ", "測試"), "冇開安全版：紅燈都可以揀 TQQQ")
v24.RULE["xr_safe"] = True

# ============================================================ 5. 顯示
px = {"TQQQ": 120.0, "IEF": 102.0, "TMF": 33.0}
tp = lambda f_: v24.trend_positions(dict(f=f_, val=1000.0, epx=100.0, edate="2026-01-02", epx_ief=100.0, edate_ief="2026-01-03"), px, 2000.0)
check([x[1] for x in tp(1.0)] == ["TQQQ"] and [x[1] for x in tp(0.0)] == ["IEF"], "trend_positions：全 TQQQ 只列 TQQQ；全 IEF 只列 IEF")
two = tp(0.4)
check([(x[1], round(x[2], 4), round(x[5], 4), x[6]) for x in two] == [("TQQQ", 0.2, 0.2, "2026-01-02"), ("IEF", 0.3, 0.02, "2026-01-03")]
      and v24.trend_positions(dict(f=None, val=1.0), px, 1.0) == [], "trend_positions：40% TQQQ（帳戶 20%、+20%）、60% IEF（30%、+2%）；現金唔列")
td = lambda **k: v24.trend_todo(dict(dict(val=1000.0, f=None, subs=None, pend=None, why="原因"), **k), 2000.0)
check(td() == [], "trend_todo：冇決定 = 冇嘢做")
check(td(pend=[T_] * 4)[0]["sym"] == "現金 → TQQQ" and td(pend=[F_] * 4)[0]["sym"] == "現金 → IEF"
      and td(pend=[T_, T_, F_, F_])[0]["sym"] == "現金 → TQQQ 50%、IEF 50%" and td(pend=[T_] * 4)[0]["frac"] == 0.5, "trend_todo：由現金開始")
up = td(f=0.25, subs=[T_, F_, F_, F_], pend=[T_, T_, F_, F_])[0]
dn = td(f=1.0, subs=[T_] * 4, pend=[F_] * 4)[0]
check(up["sym"] == "IEF → TQQQ" and near(up["frac"], 1000 * 0.25 / 2000) and dn["sym"] == "TQQQ → IEF" and near(dn["frac"], 0.5) and dn["reason"] == "原因",
      "trend_todo：加份 IEF → TQQQ（轉 25%）；賣晒 TQQQ → IEF")
s = st0(subs=[F_] * 4, f=0.0, dip=dict(pend="buy", why="低吸"), xr=dict(hold="CASH", pend="TMF", why="輪動"))
s["rebal"] = True
todo = v24.todo(s, rr(), None, 1200.0)
check([(x["leg"], x["side"], x["sym"]) for x in todo] == [("dip", "買入", "TQQQ"), ("xr", "轉", "現金 → TMF"), ("all", "調整", "再平衡")]
      and near(todo[0]["frac"], 100 / 1200), "todo：低吸開市買、輪動現金 → TMF、月尾再平衡")
s = st0(subs=[F_] * 4, f=0.0, dip=dict(pos=True, pend="sell", why="賣"), xr=dict(hold="TQQQ", pend="CASH", why="轉現金"))
check([(x["side"], x["sym"]) for x in v24.todo(s, rr(), None)] == [("賣出", "TQQQ"), ("轉", "TQQQ → 現金")], "todo：低吸開市賣、輪動 TQQQ → 現金")
T0 = dict(val=1000.0, f=0.5, subs=[T_, T_, F_, F_], pend=None, why="w", held=True)
tv = lambda pend: v24.tq_view(dict(T0, pend=pend), rr(), 2000.0, 0.45, 0.03)["pend"]
check(tv(None) is None and tv([T_, T_, T_, F_]) is True and tv([F_] * 4) is False
      and v24.tq_view(T0, rr(), 2000.0, 0.45, 0.03)["frac"] == 0.25, "tq_view：冇決定 None、加份 True、減份 False；TQQQ 佔帳戶 25%")
ti = v24.trend_info(dict(subs=[T_, F_, F_, F_], held=True, f=0.25), rr(vol=0.28))
check(ti["n_on"] == 1 and ti["n"] == 4 and ti["next_in"] == 0.275 and ti["vol_in"] == 0.30 and ti["vol_max"] == 0.35
      and v24.trend_info(dict(subs=[T_] * 4), rr())["next_in"] is None, "trend_info：揸 1／4 份，下一份門檻 27.5%；揸滿冇下一份")
check(v24.cash_frac(st0(f=None, dip=dict(val=100.0), xr=dict(hold="CASH"))) == 1.0
      and near(v24.cash_frac(st0(f=0.5, dip=dict(pos=True), xr=dict(hold="CASH"))), 100 / 1200), "cash_frac：現金 = 未入市趨勢腳 + 冇倉低吸 + 現金輪動")
check("≥ 35%" in v24.trend_rule("TQQQ") and "30%、27.5%、25%、22.5%" in v24.trend_rule("IEF") and "共 4 份" in v24.trend_rule("IEF")
      and "> 35%" in v24.xr_rule(), "規則文字：TQQQ 賣出條件、IEF 分 4 份買返、輪動安全版")

# ============================================================ 6. v25
r0 = rr()
s = v25.new_legs(1000.0, r0)
check(near(s["trend"]["val"], 450) and near(s["dip"]["val"], 50) and near(s["xr"]["val"], 150) and s["ver"] == "V2.7" and near(v25.legs_val(s), 650),
      "new_legs：三隻 ETF 腳 = 總資金 × 45％／5％／15％（領導股 35% 另計）")
s = dict(trend=dict(val=45.0), dip=dict(val=5.0), xr=dict(val=15.0))
check(v25.rebalance(s, 35.0, 10.0, "2026-01-30", f := []) == 0.0 and f == [] and near(s["trend"]["val"], 45.0), "rebalance：啱啱 35／45／5／15：唔郁")
s = dict(trend=dict(val=45.4), dip=dict(val=5.0), xr=dict(val=14.6))
check(v25.rebalance(s, 35.0, 10.0, "2026-01-30", f := []) == 0.0 and f == [] and near(s["xr"]["val"], 15 / 65 * (65 - C * 0.8)),
      "rebalance：偏離 0.8%（< 1%）：唔記成交，但照調返比例")
s = dict(trend=dict(val=45.6), dip=dict(val=5.0), xr=dict(val=14.4))
v25.rebalance(s, 35.0, 10.0, "2026-01-30", f := [])
check(len(f) == 1 and "趨勢腳 減 0.6%" in f[0]["reason"] and "輪動腳 加 0.6%" in f[0]["reason"] and "領導股" not in f[0]["reason"].split("（")[1]
      and "唔會為咗比例賣股" not in f[0]["reason"], "rebalance：偏離 1.2%：記成交（只講 ETF 腳）")
s = dict(trend=dict(val=50.0), dip=dict(val=10.0), xr=dict(val=20.0))
mv = v25.rebalance(s, 20.0, 20.0, "2026-01-30", f := [])
check(mv == 15.0 and "領導股 收現金 15.0%" in f[0]["reason"] and near(v25.legs_val(s), 65 - C * (15 + 10 + 5 + 0)), "rebalance：領導股得 20%：ETF 腳俾 15 返去")
st = dict(trend=dict(val=300.0, f=None), dip=dict(val=50.0, pos=False), xr=dict(val=150.0, hold="CASH"))
check(v25.leg_cash(st) == 500.0 and v25.leg_cash(dict(trend=dict(val=300.0, f=0.5), dip=dict(val=50.0, pos=True), xr=dict(val=150.0, hold="TMF"))) == 0,
      "leg_cash：未入市趨勢腳、冇倉低吸、現金輪動 = 現金；入咗市 = 0")
st = dict(trend=dict(val=450.0, f=1.0, epx=100.0, edate="2026-01-02"), dip=dict(val=50.0, pos=True, epx=100.0, edate="2026-01-05"),
          xr=dict(val=150.0, hold="TMF", epx=30.0, edate="2026-01-03"))
lp = v25.leg_positions(st, dict(px=px), 1000.0)
check([(x[0], x[1], round(x[2], 4), round(x[5], 4)) for x in lp] == [("trend", "TQQQ", 0.45, 0.2), ("dip", "TQQQ", 0.05, 0.2), ("xr", "TMF", 0.15, 0.1)]
      and [x["leg"] for x in v25.leg_rows(st, dict(px=px), 1000.0)] == ["趨勢腳", "低吸腳", "輪動腳"], "leg_positions：三隻腳揸緊咩、佔帳戶幾多、回報")
s = st0(subs=[T_] * 4, f=1.0)
s["rebal"] = True
lt = v25.leg_todo(s, rr(), 1200.0)
check(lt[-1]["leg"] == "all" and v25.TXT in lt[-1]["reason"] and "領導股部分只用現金調" in lt[-1]["reason"], "leg_todo：月尾再平衡改用 V2.7 文字")
s = st0(subs=[T_] * 4, f=1.0)
s["rebal"] = True
f = []
check(v25.step_legs(s, rr(), P, f) is True and not s.get("rebal") and not any(x["sym"] == "再平衡" for x in f),
      "step_legs：返「今日要再平衡」，唔會喺 v24 入面再做一次 80／10／10")
s = st0(subs=[T_] * 4, f=1.0)
check(v25.step_legs(s, rr(), P, []) is False, "step_legs：平日 = 唔使再平衡")
rv = dict(rr(), ndx=21000.0, e21=20000.0, s50=19000.0, s200=22000.0)
hold, legs, tqv = v25.leg_view(st0(subs=[T_] * 4, f=1.0, epx=80.0, edate="2026-01-02"), rv, 1200.0)
check(near(tqv["margin"], round(max(21000 / 22000 - 1, min(21000 / 20000 - 1, 20000 / 19000 - 1)), 4)) and legs["xr"]["safe"] and legs["dip"]["rsi_in"] == 25.0
      and near(tqv["target"], 0.45) and hold[0]["sym"] == "TQQQ" and hold[0]["leg"] == "趨勢腳", "leg_view：黃燈距離、輪動安全版、TQQQ 目標 45%")
print(f"\n全部 {ok} 項通過")
