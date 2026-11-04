# -*- coding: utf-8 -*-
"""2026-11-04 V2.7 檢查（/codex）搵到嘅執行漏洞：每個一個重現，修好之後防返轉頭。唔上網、唔使錢。
用法：python tests/test_model_bugs.py"""
import contextlib
import io
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
import lead  # noqa: E402
import v25  # noqa: E402,F401  （設定 V2.7）
import v24  # noqa: E402
import model  # noqa: E402

OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "model_bugs" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


near = lambda a, b, tol=1e-9: abs(a - b) <= tol * max(1.0, abs(b))
C = lead.RULE["cost"]
DAYS = ["2026-01-05", "2026-01-06"]
acts = lambda: dict(fills=[], stops=[], warn=[])


def lst(cash=10000.0, positions=None, pending=None, braking=False):
    return dict(cash=cash, positions=positions or [], trades=[], peak=None, braking=braking, pending=pending or {}, slots=0, sleeve=None, last_green=True)


def bar(o, h, lo, c, **k):
    return dict(o10=list(o), h10=list(h), l10=list(lo), c10=list(c), **k)


def sc(stocks, cash=None, days=DAYS):
    return dict(days=days, stocks=stocks, ranking=[], green=True, week_end=False, rank1=None, next_day="2026-01-07", date=days[-1], cash=cash or {})


pos = lambda **k: dict(dict(sym="AAA", date="2026-01-02", entry=100.0, shares=100.0, stop=0.0, R=0.0, be=False, last_close=100.0, frac=1.0), **k)
order = lambda s, i=1: dict(sym=s, rank=i, trigger=100.0, stop=90.0, frac=0.2)
sell = lambda s: {"for": DAYS[1], "buys": [], "sells": [dict(sym=s, reason="測試")]}

# ---- 1. 持股上限要限制成交，唔係淨係限制掛單
SYMS = ["AAA", "BBB", "CCC", "DDD"]
stocks = {s: bar((99, 100), (100, 105), (98, 99), (99, 104)) for s in SYMS}
st = lst(braking=True, pending={"for": DAYS[1], "sells": [], "buys": [order(s, i + 1) for i, s in enumerate(SYMS)]})
lead.step(st, sc(stocks), 1, acts())
check(len(st["positions"]) == 2 and [p["sym"] for p in st["positions"]] == ["AAA", "BBB"], "剎車中上限 2 隻：4 張買單都觸發，都只係買排名頭 2 隻")
st = lst(cash=30000.0, positions=[pos(sym=f"H{i}") for i in range(4)], pending={"for": DAYS[1], "sells": [], "buys": [order(s, i + 1) for i, s in enumerate(SYMS)]})
stocks2 = dict(stocks, **{f"H{i}": bar((100, 100), (100, 100), (100, 100), (100, 100)) for i in range(4)})
lead.step(st, sc(stocks2), 1, acts())
check(len(st["positions"]) == 5, "正常上限 5 隻：已經揸 4 隻，4 張買單觸發都只買 1 隻")

# ---- 2. 開市價缺失：唔可以當收市價成交，要等下一日開市
st = lst(cash=0.0, positions=[pos()], pending=sell("AAA"))
a = acts()
lead.step(st, sc({"AAA": bar((100, None), (101, None), (99, None), (100, 110))}), 1, a)
check(len(st["positions"]) == 1 and not st["trades"] and st.get("carry_sells") and any("開市價" in w for w in a["warn"]),
      "賣出嗰日冇開市價（收市 110）：唔賣、留到下一日、有警告")
d2 = ["2026-01-06", "2026-01-07"]
lead.step(st, sc({"AAA": bar((None, 108), (None, 109), (None, 107), (110, 108))}, days=d2), 1, acts())
check(not st["positions"] and st["trades"][-1]["sell"] == 108 and not st.get("carry_sells"), "下一日有開市價 108：按 108 賣，唔再留")

# ---- 3. 當日賣股所得唔可以賺當日 IEF 回報
st = lst(cash=0.0, positions=[pos()], pending=sell("AAA"))
lead.step(st, sc({"AAA": bar((100, 100), (101, 101), (99, 99), (100, 100))}, cash=dict(green10=[False, False], ief10=[100.0, 110.0], irx10=[0.0, 0.0])), 1, acts())
check(near(st["cash"], 9990.0), f"股票開市賣得 9,990，IEF 前晚升 10%：呢筆新現金唔賺嗰 10%（{st['cash']:.2f}）")
st = lst(cash=5000.0)
lead.step(st, sc({}, cash=dict(green10=[False, False], ief10=[100.0, 101.0], irx10=[0.0, 0.0])), 1, acts())
check(near(st["cash"], 5050.0), "全日都揸住嘅現金照跟 IEF 升 1%")
st = lst(cash=10000.0, pending={"for": DAYS[1], "sells": [], "buys": [order("AAA")]})
lead.step(st, sc({"AAA": bar((99, 100), (100, 105), (98, 99), (99, 104))}, cash=dict(green10=[False, False], ief10=[100.0, 110.0], irx10=[0.0, 0.0])), 1, acts())
check(near(st["cash"], 8000.0 * 1.10), "今日用咗 2,000 買股：淨低嘅 8,000 先跟 IEF 升")

# ---- 4. 除息日：前一日收市揸住先有息，記應收，到期先入現金，帳戶值唔會漏
st = lst(cash=0.0, positions=[pos()])
lead.step(st, sc({"AAA": bar((100, 99.75), (100, 100), (100, 99), (100, 99.75), div10=[0.0, 0.25])}), 1, acts())
check(near(st["recv"][0]["amt"], 25.0) and st["cash"] == 0.0 and near(lead.value(st), 100 * 99.75 + 25.0), "100 股除息 0.25：應收 25（未入現金），帳戶值連應收")
d3 = ["2026-01-19", "2026-01-20"]
lead.step(st, sc({"AAA": bar((99.75, 99.75), (100, 100), (99, 99), (99.75, 99.75), div10=[0.0, 0.0])}, days=d3), 1, acts())
check(near(st["cash"], 25.0) and not st["recv"], "到期應收入現金，帳戶值唔變")
st = lst(cash=10000.0, pending={"for": DAYS[1], "sells": [], "buys": [order("AAA")]})
lead.step(st, sc({"AAA": bar((99, 100), (100, 105), (98, 99), (99, 104), div10=[0.0, 0.25])}), 1, acts())
check(not st.get("recv"), "除息日先買入：冇息")
st = lst(cash=0.0, positions=[pos()], pending=sell("AAA"))
lead.step(st, sc({"AAA": bar((100, 99.75), (100, 100), (100, 99), (100, 99.75), div10=[0.0, 0.25])}), 1, acts())
check(not st["positions"] and near(st["recv"][0]["amt"], 25.0), "除息日開市賣：前一日收市揸住，照收息")

# ---- 5. 拆股要連掛單一齊調
real_splits = lead.yahoo_splits
lead.yahoo_splits = lambda s, days=45: [("2026-01-05", 0.1)]
st = lst(pending={"for": DAYS[1], "sells": [], "buys": [dict(order("NVX"), trigger=1219.94, stop=1100.0, ref=1200.0)]})
st["last"] = DAYS[0]
s_ = {"NVX": bar((120.0, 121.0), (122.0, 123.0), (119.0, 120.0), (120.0, 122.0))}
a = acts()
lead.fix_splits(st, sc(s_), 1, a)
b = st["pending"]["buys"][0]
check(near(b["trigger"], 121.994) and near(b["stop"], 110.0) and near(b["ref"], 120.0), "10 拆 1：掛單前高 1219.94 → 121.994、止蝕 1100 → 110")
lead.step(st, sc(s_), 1, a)
check(len(st["positions"]) == 1 and near(st["positions"][0]["entry"], 121.994), "拆股後最高 123 ≥ 121.994：觸發買入（冇調嘅話永遠唔會觸發）")
lead.yahoo_splits = lambda s, days=45: []
real_ai = lead._ai
lead._ai = lambda p: (None, "冇 key")
st = lst(pending={"for": DAYS[1], "sells": [], "buys": [dict(order("NVX"), trigger=1219.94, stop=1100.0, ref=1200.0)]})
st["last"] = DAYS[0]
a = acts()
lead.fix_splits(st, sc(s_), 1, a)
check(st["pending"]["buys"][0]["trigger"] == 1219.94 and any("掛單" in w for w in a["warn"]), "確認唔到係拆股：掛單唔調，有警告")
lead.yahoo_splits, lead._ai = real_splits, real_ai

# ---- 6. 冇可核實成交價，唔可以當賣咗
for status, note in (("bankrupt", "破產"), ("delisted", "退市"), ("unknown", "唔知")):
    lead._ai = lambda p, s=status, n=note: ({"status": s, "note": n}, "測試來源")
    st = lst(cash=0.0, positions=[pos(miss=4)])
    a = acts()
    lead.step(st, sc({"AAA": bar((100, None), (100, None), (100, None), (100, None))}), 1, a)
    check(len(st["positions"]) == 1 and not st["trades"] and st["cash"] == 0.0 and st["positions"][0].get("frozen") and a["warn"],
          f"AI 話{note}、冇可成交價：唔當賣咗，持倉凍結，有警告")
lead._ai = lambda p: (None, "冇 AI key")
st = lst(cash=0.0, positions=[pos(miss=4)])
lead.step(st, sc({"AAA": bar((100, None), (100, None), (100, None), (100, None))}), 1, acts())
check(len(st["positions"]) == 1 and st["cash"] == 0.0, "AI 查唔到：唔當賣咗")
n_ai = []
lead._ai = lambda p: (n_ai.append(1), ({"status": "unknown"}, "測試來源"))[1]
st = lst(cash=0.0, positions=[pos(miss=5, frozen="唔知", ai_checked="2026-01-02")])
lead.step(st, sc({"AAA": bar((100, None), (100, None), (100, None), (100, None))}), 1, acts())
check(not n_ai, "凍結咗嘅持倉唔會日日問 AI（每 5 日先再查）")
lead._ai = lambda p: ({"status": "acquired", "cash_per_share": 105.5, "note": "被收購"}, "測試來源")
st = lst(cash=0.0, positions=[pos(miss=4)])
lead.step(st, sc({"AAA": bar((100, None), (100, None), (100, None), (100, None))}), 1, acts())
check(not st["positions"] and st["trades"][-1]["sell"] == 105.5, "有來源嘅現金收購價：照按收購價變現")
st = lst(cash=0.0, positions=[pos(miss=0, frozen="唔知")])
lead.step(st, sc({"AAA": bar((100, 90), (100, 91), (100, 89), (100, 90))}), 1, acts())
check(not st["positions"][0].get("frozen") and st["positions"][0]["last_close"] == 90, "凍結咗嘅持倉又有價：解凍")
lead._ai = real_ai

# ---- 7. 趨勢腳：持股比例隨價錢漂移，唔係暗中每日再平衡；轉換計兩邊成本
leg = lambda f, subs: dict(trend=dict(val=1000.0, held=f > 0, f=f, subs=subs, pend=None, why=None, epx=100.0, edate="2026-01-02", epx_ief=100.0, edate_ief="2026-01-02"),
                           dip=dict(val=0.0, pos=False, pend=None, why=None, epx=None, edate=None, days=0), xr=dict(val=0.0, hold="CASH", pend=None, why=None, epx=None, edate=None),
                           trades=[], start="2026-01-02", last="2026-01-05")


def rr(d, tq, ief=100.0, op=None):
    return dict(d=d, px={"TQQQ": tq, "IEF": ief}, op=op, bill=0.0, green=True, vol=0.20, rsi2=50.0, me=False, pick="CASH", why_pick="測試", pick_safe="CASH", why_safe="測試",
                q=400.0, ndx=20000.0, e21=19800.0, s50=19500.0, s200=18000.0)


s = leg(0.5, [True, True, False, False])
v24.step(s, rr("2026-01-06", 110.0), rr("2026-01-05", 100.0), [])
s["trend"]["pend"] = None
v24.step(s, rr("2026-01-07", 100.0), rr("2026-01-06", 110.0), [])
check(near(s["trend"]["val"], 1000.0), f"各半揸住，TQQQ 100 → 110 → 100、IEF 不變、冇成交：返到 1000（{s['trend']['val']:.2f}）")
s = leg(0.5, [True, True, False, False])
s["trend"]["pend"] = [True, True, True, False]
v24.step(s, rr("2026-01-06", 100.0), rr("2026-01-05", 100.0), [])
check(near(s["trend"]["val"], 1000.0 - 1000 * 0.25 * C * 2) and near(s["trend"]["f"], 0.75, 1e-3), "IEF 轉 TQQQ（郁 ¼ 隻腳）：賣 IEF、買 TQQQ 兩邊都計 0.1%")
s = leg(0.75, [True, True, True, False])
s["trend"]["val"] = 1000.0
s["trend"]["pend"] = [True, True, True, True]
v24.step(s, rr("2026-01-06", 100.0), rr("2026-01-05", 100.0), [])
check(near(s["trend"]["f"], 1.0, 1e-9), "最後一份：IEF 全部轉 TQQQ，f = 1")
s = leg(0.6, [True, True, False, False])
s["trend"]["pend"] = [True, True, True, False]
v24.step(s, rr("2026-01-06", 100.0), rr("2026-01-05", 100.0), [])
check(near(s["trend"]["f"], 0.8, 1e-3), "漂移到 60%／40%，加多 1 份（剩 2 份未買）：轉一半 IEF → 80%")
tq = v24.trend_todo(dict(leg(0.6, [True, True, False, False])["trend"], pend=[True, True, True, False]), 1000.0)
check(near(tq[0]["frac"], 0.2, 1e-9) and "IEF → TQQQ" in tq[0]["sym"], "要做嘅比例同實際轉嘅一樣（20%）")


# ---- 8. 補跑：逐日跑同一次補幾日結果要一樣
def frame():
    idx = pd.bdate_range("2024-12-01", "2026-01-07")
    n = len(idx)
    return pd.DataFrame(dict(ndx=np.arange(n) + 1000.0, qqq=np.arange(n) * 0.1 + 100.0, tlt=np.full(n, 100.0), gld=np.full(n, 100.0), irx=np.zeros(n), TQQQ=np.full(n, 100.0),
                             IEF=np.full(n, 100.0), TMF=np.full(n, 100.0), UGL=np.full(n, 100.0), tq_open=np.full(n, 100.0)), index=idx)


D3 = ["2026-01-05", "2026-01-06", "2026-01-07"]
CS = [100.0, 112.0, 95.0]
RK = [dict(sym="AAA", rank=1, status="唔合格", pivot=120.0, stop=90.0)]


def scan(k):
    s_ = dict(o10=[100.0, 108.0, 100.0][:k + 1], h10=[101.0, 113.0, 101.0][:k + 1], l10=[99.0, 107.0, 94.0][:k + 1], c10=CS[:k + 1], close=CS[k], sma200=80.0, swing_low=105.0, atr=5.0)
    plans = {D3[j]: dict(date=D3[j], next_day=(D3 + ["2026-01-08"])[j + 1], week_end=False, green=True, rank1="AAA", ranking=RK,
                         stocks={"AAA": dict(close=CS[j], sma200=80.0, swing_low=105.0, atr=5.0)}) for j in range(k + 1)}
    return dict(days=D3[:k + 1], date=D3[k], next_day=(D3 + ["2026-01-08"])[k + 1], week_end=False, green=True, rank1="AAA", stocks={"AAA": s_}, ranking=RK, cash={}, plans=plans)


def run_model(F, seq, tag):
    R = v24.rows(F, "2026-01-08")
    prev = next(r for r in R if r["d"] == "2026-01-05")
    st = v25.new_legs(0.0, prev)
    st["capital"] = 10000.0
    st.update(cash=0.0, positions=[dict(sym="AAA", date="2026-01-02", entry=100.0, shares=100.0, stop=90.0, R=5.0, be=False, last_close=100.0, frac=1.0)], peak=10000.0,
              braking=False, slots=0, sleeve=None, last_green=True, pending={})
    p = OUT / f"{tag}.json"
    p.write_text(json.dumps(st), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        for k in seq:
            model.run(p, sc=scan(k), F=F)
    return json.loads(p.read_text(encoding="utf-8"))


F = frame()
daily, batch = run_model(F, [1, 2], "daily"), run_model(F, [2], "batch")
check(not daily["positions"] and not batch["positions"], "逐日跑（1 月 6 日收 112 推高止蝕到 104，1 月 7 日最低 94 打止蝕）同一次補兩日：都賣咗")
check(near(lead.value(daily), lead.value(batch)) and daily["trades"][-1]["sell"] == batch["trades"][-1]["sell"], f"兩種跑法帳戶值、賣出價一樣（{lead.value(batch):,.2f}）")

SC4 = scan(2)
SC4["plans"] = {}
p = OUT / "noplan.json"
base = run_model(F, [], "base0")
p.write_text(json.dumps(base), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    model.run(p, sc=SC4, F=F)
m = json.loads(p.read_text(encoding="utf-8"))
check(any("決策資料" in w for w in m["view"]["actions"]["warn"]), "補跑冇中間日決策資料：要警告，唔可以扮完整重播")

old = run_model(F, [], "base1")
old["last"] = "2025-12-05"
p = OUT / "gap.json"
p.write_text(json.dumps(old), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    model.run(p, sc=scan(2), F=F)
m = json.loads(p.read_text(encoding="utf-8"))
check(m["last"] == "2025-12-05" and any("手動補" in w for w in m["view"]["actions"]["warn"]), "隔咗超過 10 個交易日：帳戶停喺原來日子、要手動補，唔會淨係推 ETF 腳")


# ---- 9. scan.py 每日決策資料：格式啱 lead.plan 用，同冇偷睇
import scan as SC  # noqa: E402


def frames(n=320, extra=0):
    idx = pd.bdate_range(end="2026-03-06", periods=n)
    if extra:
        idx = idx.append(pd.bdate_range(start=idx[-1] + pd.offsets.BDay(1), periods=extra))
    rng = np.random.default_rng(3)
    syms = [f"S{i:02d}" for i in range(60)]
    base = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, (n + extra, 60)), axis=0))
    if extra:
        base[n:] = base[n - 1] * np.linspace(1, 0.3, extra)[:, None]       # 之後大跌，唔應該影響之前
    C = pd.DataFrame(base, index=idx, columns=syms)
    return C, C * 1.01, C * 0.99, C.copy(), (C * 1e6).rolling(50, min_periods=50).mean()


def plans(C, H, L, AC, adv, ndays=10, n=320):
    days = C.index[n - ndays:n]
    after = list(days[1:]) + [C.index[n] if len(C) > n else days[-1] + pd.offsets.BDay(1)]
    ndx = C.iloc[:, 0] * 100
    e21, s50, s200 = ndx.ewm(span=21, adjust=False).mean(), ndx.rolling(50).mean(), ndx.rolling(200).mean()
    return SC.day_plans(days, [False] * ndays, after, C, AC, H, L, adv, ndx, e21, s50, s200, {"S00"})


C0, H0, L0, AC0, A0 = frames()
P0 = plans(C0, H0, L0, AC0, A0)
d0 = sorted(P0)[-1]
x = P0[d0]
check(len(P0) == 9 and x["ranking"] and {"close", "sma200", "swing_low", "atr"} <= set(x["stocks"]["S00"]) and {"rank", "sym", "status", "pivot", "stop", "close"} <= set(x["ranking"][0]),
      "scan.py 俾最近 9 個中間日決策資料，格式啱 lead.plan")
st = lst(cash=10000.0, positions=[pos(sym="S00", last_close=x["stocks"]["S00"]["close"])])
lead.plan(st, x, acts())
check(st["pending"]["for"] == x["next_day"], "lead.plan 食到中間日資料，掛單日子係嗰日嘅下一個交易日")
P1 = plans(*frames(extra=15))
same = all(P0[d]["ranking"] == P1[d]["ranking"] and P0[d]["stocks"] == P1[d]["stocks"] and P0[d]["green"] == P1[d]["green"] for d in P0)
check(same, "之後 15 日大跌：中間日排名、狀態、止蝕全部唔變（冇偷睇）")

print(f"\n全部 {ok} 項通過")
