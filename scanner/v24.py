"""V2.4 模型（2026-10-09 用戶揀「最高回報組合」：唔揀股、冇孖展、全部用 ETF）。[quant-risk]
研究（stock-strategy/src/v24_hist.py：2000 年起歷史）同雲端（scanner/model.py：每日接落去行）共用呢份規則，唔好兩邊各改各。

點揀出嚟：stock-strategy/LAB_MAXRET.md 揀法 D（每年 1 月只用之前數據，揀之前年化最高嘅組合，唔限回撤），2026 年揀中
  80% 趨勢腳 + 10% 低吸腳 + 10% 輪動腳。每年 1 月重跑 lab_maxret.py，揀中有變就改 W（RESTORE.md）。
資金：三隻腳各自計帳；每月最後一個交易日收市決定、下一個交易日收市調返 80／10／10（變動部分每邊 0.1%）。
1. 趨勢腳（80%）：收市「大市綠燈 + QQQ 20 日波幅（年化）< 35%」→ 下一個交易日收市前揸 TQQQ；唔成立 → 下一個交易日收市前轉 IEF。
   大市綠燈 = NDX 收市 > 200 日線，或者 NDX > 21 日 EMA 而且 21 日 EMA > 50 日線（同 V2.2 一樣）。
   賣出原因只有兩個：大市轉紅燈；QQQ 波幅 ≥ 35%（大上大落時 3 倍 ETF 耗損大）。
2. 低吸腳（10%）：冇倉時收市「大市綠燈 + NDX 2 日 RSI < 25（短線超賣）」→ 下一個交易日開市買 TQQQ；
   有倉時收市 RSI > 70（反彈完成）或者已經揸滿 10 個交易日（時間止蝕：反彈冇嚟）→ 下一個交易日開市賣。
   冇價錢止蝕（測過：逆向買入加止蝕會喺反彈前被洗走）；最多蝕呢 10%。冇倉時現金收國債息。
3. 輪動腳（10%）：每月最後一個交易日收市，QQQ、TLT（20 年以上美債）、黃金各自計 1、3、6 個月回報平均；
   最高嗰樣高過國債息同期平均，就揸佢嘅槓桿版（QQQ→TQQQ、TLT→TMF、黃金→UGL），否則揸現金；下一個交易日收市前換。
成本：每次轉換每邊 0.1%（趨勢腳一次轉換當 0.1%，同回測一樣）。所有價錢係連派息調整價。

V2.7（2026-10-12，v25.py 開）：
  趨勢腳分段買返：RULE["vol_ins"] 每個門檻一份（V2.7 = 30%、27.5%、25%、22.5% 各四分一）。每份：揸緊時紅燈或波幅 ≥ 35% 先賣；
    冇揸時要綠燈而且波幅低過自己嘅門檻先買。所以賣係一次過賣晒，買返係分 4 次（波幅越低買越多）。未買返嗰部分揸 IEF。
    V2.4 = (35%,)、V2.6 = (25%,)：只得一份，同以前一樣。
  V2.8（2026-10-12）：RULE["xr_on"] = False = 冇輪動腳（比重 0，永遠唔買賣；月尾再平衡照做）。
  輪動腳安全版：RULE["xr_safe"] = True 時，大市紅燈或 QQQ 20 日波幅 > 35% 就唔揸 TQQQ（月尾唔揀佢；月中揸緊就下一個交易日收市前轉現金，等月尾再揀）。
"""
from __future__ import annotations

import math

W = dict(trend=0.80, dip=0.10, xr=0.10)
RULE = dict(vol=0.35, vol_ins=(0.35,), xr_safe=False, xr_on=True, rsi_in=25.0, rsi_out=70.0, hold=10, cost=0.001)   # vol_ins：趨勢腳每份嘅再買門檻（由高到低）；v25.py 會改
LEV = {"QQQ": "TQQQ", "TLT": "TMF", "GLD": "UGL"}
LEG = {"trend": "趨勢腳", "dip": "低吸腳", "xr": "輪動腳"}
UNDER = {"QQQ": "QQQ", "TLT": "TLT（長債）", "GLD": "黃金"}
pc = lambda x: f"{x * 100:+.1f}%"
pv = lambda x: f"{x * 100:.1f}".rstrip("0").rstrip(".") + "%"
frac_of = lambda subs: sum(subs) / len(subs)


# ---------------------------------------------------------------- 每日數據 → 訊號
def rsi(x, n):
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def rows(F, next_day):
    """F：DataFrame（index = 交易日），欄 ndx、qqq、tlt、gld、irx（%）、TQQQ、IEF、TMF、UGL（調整收市價）、tq_open（TQQQ 調整開市價）。
    next_day：最後一日之後嘅下一個交易日（YYYY-MM-DD），判斷月尾。返每日 dict（只返有齊訊號嘅日子）。"""
    import numpy as np
    import pandas as pd
    ndx = F["ndx"].ffill()
    e21, s50, s200 = ndx.ewm(span=21, adjust=False).mean(), ndx.rolling(50).mean(), ndx.rolling(200).mean()
    green = (ndx > s200) | ((ndx > e21) & (e21 > s50))
    q = F["qqq"].ffill()
    vol = q.pct_change().rolling(20).std() * np.sqrt(252)
    r2 = rsi(ndx, 2)
    bill = (F["irx"].ffill().fillna(0) / 100 / 252)
    B = (1 + bill).cumprod()
    hz = (21, 63, 126)
    mom = {a: sum(F[c].ffill() / F[c].ffill().shift(n) - 1 for n in hz) / 3 for a, c in (("QQQ", "qqq"), ("TLT", "tlt"), ("GLD", "gld"))}
    mb = sum(B / B.shift(n) - 1 for n in hz) / 3
    idx = list(F.index)
    out = []
    for i, t in enumerate(idx):
        if not (np.isfinite(s200.iloc[i]) and np.isfinite(vol.iloc[i]) and np.isfinite(r2.iloc[i]) and np.isfinite(mb.iloc[i])):
            continue
        nd = str(idx[i + 1].date()) if i + 1 < len(idx) else next_day
        m = {a: float(mom[a].iloc[i]) for a in mom if np.isfinite(mom[a].iloc[i])}
        best = max(m, key=m.get) if m else None
        pick = LEV[best] if best and m[best] > float(mb.iloc[i]) else "CASH"
        why = "、".join(f"{UNDER[a]} {pc(v)}" for a, v in sorted(m.items(), key=lambda kv: -kv[1])) + f"（國債息 {pc(float(mb.iloc[i]))}）"
        why = ("月尾輪動：1、3、6 個月平均回報 " + why + "，" +
               (f"最高係 {UNDER[best]} 而且高過國債息 → 揸 {pick}" if pick != "CASH" else "冇一樣高過國債息 → 揸現金"))
        m2 = {a: v for a, v in m.items() if a != "QQQ"}
        b2 = max(m2, key=m2.get) if m2 else None
        pick2 = LEV[b2] if b2 and m2[b2] > float(mb.iloc[i]) else "CASH"
        why2 = ("月尾輪動（安全版）：大市紅燈或 QQQ 波幅 > 35%，唔揀 TQQQ；其餘 1、3、6 個月平均回報 " +
                "、".join(f"{UNDER[a]} {pc(v)}" for a, v in sorted(m2.items(), key=lambda kv: -kv[1])) + f"（國債息 {pc(float(mb.iloc[i]))}），" +
                (f"最高係 {UNDER[b2]} 而且高過國債息 → 揸 {pick2}" if pick2 != "CASH" else "冇一樣高過國債息 → 揸現金"))
        px = {s: float(F[s].iloc[i]) for s in ("TQQQ", "IEF", "TMF", "UGL") if s in F and np.isfinite(F[s].iloc[i])}
        op = float(F["tq_open"].iloc[i]) if "tq_open" in F and np.isfinite(F["tq_open"].iloc[i]) else None
        out.append(dict(d=str(t.date()), green=bool(green.iloc[i]), vol=round(float(vol.iloc[i]), 4), rsi2=round(float(r2.iloc[i]), 1),
                        bill=float(bill.iloc[i]), px=px, op=op, me=nd[:7] != str(t.date())[:7], pick=pick, why_pick=why, pick_safe=pick2, why_safe=why2,
                        q=float(q.iloc[i]), ndx=float(ndx.iloc[i]), e21=float(e21.iloc[i]), s50=float(s50.iloc[i]), s200=float(s200.iloc[i])))
    return out


# ---------------------------------------------------------------- 帳戶
def new_state(capital, prev, note=""):
    """全現金開始：用上一個交易日（prev）收市嘅訊號決定第一日要做咩（同之後每日一樣）。"""
    st = dict(ver="V2.4", start=None, capital=capital, last=prev["d"], note=note, rebal=False,
              trend=dict(val=capital * W["trend"], held=None, f=None, subs=None, pend=None, why=None, epx=None, edate=None, epx_ief=None, edate_ief=None),
              dip=dict(val=capital * W["dip"], pos=False, pend=None, why=None, epx=None, edate=None, days=0),
              xr=dict(val=capital * W["xr"], hold="CASH", pend=None, why=None, epx=None, edate=None),
              trades=[], hist=[], nav=[])
    decide(st, prev, first=True)
    return st


def nav(st):
    return st["trend"]["val"] + st["dip"]["val"] + st["xr"]["val"]


def _r(r, p, s):
    a, b = r["px"].get(s), (p or {}).get("px", {}).get(s)
    return a / b if a and b else 1.0


def step(st, r, p, fills):
    """處理一個交易日 r（p = 上一個交易日）：開市（低吸腳）→ 收市升跌 → 收市執行上一日決定（趨勢腳、輪動腳、再平衡）→ 收市決定聽日。"""
    d, c = r["d"], RULE["cost"]
    if st.get("start") is None:
        st["start"] = d
    tq = r["px"].get("TQQQ")
    # ---- 低吸腳（開市成交）
    D = st["dip"]
    if D["pend"] == "buy" and r.get("op") and tq:
        D["val"] *= (1 - c) * tq / r["op"]
        D.update(pos=True, days=1, epx=r["op"], edate=d)
        fills.append(dict(date=d, leg="dip", sym="TQQQ", side="買入", px=round(r["op"], 2), when="開市", reason="低吸腳：" + D["why"]))
    elif D["pend"] == "sell" and r.get("op") and (p or {}).get("px", {}).get("TQQQ"):
        D["val"] *= r["op"] / p["px"]["TQQQ"] * (1 - c)
        ret = r["op"] / D["epx"] - 1 if D["epx"] else None
        fills.append(dict(date=d, leg="dip", sym="TQQQ", side="賣出", px=round(r["op"], 2), ret=ret, when="開市", reason="低吸腳：" + D["why"]))
        st["trades"].append(dict(leg="dip", sym="TQQQ", date=D["edate"], entry=D["epx"], sell_date=d, sell=r["op"], ret=ret, reason=D["why"]))
        D.update(pos=False, days=0, epx=None, edate=None)
    elif D["pos"]:
        D["val"] *= _r(r, p, "TQQQ")
        D["days"] += 1
    else:
        D["val"] *= 1 + r["bill"]
    # ---- 趨勢腳（收市升跌 → 收市執行）：f = TQQQ 佔呢隻腳幾多（分段買返時 0、¼、½、¾、1），其餘 IEF
    T = st["trend"]
    f0 = T["f"]
    T["val"] *= (1 + r["bill"]) if f0 is None else f0 * _r(r, p, "TQQQ") + (1 - f0) * _r(r, p, "IEF")
    if T["pend"] is not None:
        f1, a, ief, why = frac_of(T["pend"]), f0 or 0.0, r["px"].get("IEF"), "趨勢腳：" + (T["why"] or "")
        T["val"] *= 1 - c * (1.0 if f0 is None else abs(f1 - a))
        if f1 > a:
            if f0 is not None:
                fills.append(dict(date=d, leg="trend", sym="IEF", side="賣出", px=round(ief or 0, 2), when="收市", reason=why))
            fills.append(dict(date=d, leg="trend", sym="TQQQ", side="買入", px=round(tq, 2), when="收市", reason=why))
            T["epx"] = (a * T["epx"] + (f1 - a) * tq) / f1 if a > 0 and T["epx"] else tq
            if a == 0:
                T["edate"] = d
        elif f1 < a:
            ret = tq / T["epx"] - 1 if T["epx"] else None
            fills.append(dict(date=d, leg="trend", sym="TQQQ", side="賣出", px=round(tq, 2), ret=ret, when="收市", reason=why))
            st["trades"].append(dict(leg="trend", sym="TQQQ", date=T["edate"], entry=T["epx"], sell_date=d, sell=tq, ret=ret, reason=T["why"]))
            if f1 == 0:
                T["epx"], T["edate"] = None, None
        if f1 < 1 and (f0 is None or f1 < a):
            fills.append(dict(date=d, leg="trend", sym="IEF", side="買入", px=round(ief or 0, 2), when="收市", reason=why))
        if f1 >= 1:
            T["epx_ief"], T["edate_ief"] = None, None
        elif f0 is None or a >= 1:
            T["epx_ief"], T["edate_ief"] = ief, d
        T.update(subs=list(T["pend"]), f=f1, held=f1 > 0)
    # ---- 輪動腳（收市升跌 → 收市執行）
    X = st["xr"]
    X["val"] *= (1 + r["bill"]) if X["hold"] == "CASH" else _r(r, p, X["hold"])
    if X["pend"] is not None and X["pend"] != X["hold"]:
        X["val"] *= 1 - c * ((X["hold"] != "CASH") + (X["pend"] != "CASH"))
        if X["hold"] != "CASH":
            s, now = X["hold"], r["px"].get(X["hold"])
            ret = now / X["epx"] - 1 if X["epx"] and now else None
            fills.append(dict(date=d, leg="xr", sym=s, side="賣出", px=round(now or 0, 2), ret=ret, when="收市", reason="輪動腳：" + X["why"]))
            st["trades"].append(dict(leg="xr", sym=s, date=X["edate"], entry=X["epx"], sell_date=d, sell=now, ret=ret, reason=X["why"]))
        if X["pend"] != "CASH":
            fills.append(dict(date=d, leg="xr", sym=X["pend"], side="買入", px=round(r["px"].get(X["pend"], 0), 2), when="收市", reason="輪動腳：" + X["why"]))
        X.update(hold=X["pend"], epx=r["px"].get(X["pend"]) if X["pend"] != "CASH" else None, edate=d)
    # ---- 月尾再平衡（上一個交易日係月尾 → 今日收市調返 80／10／10）
    if st.get("rebal"):
        tot = nav(st)
        legs = ("trend", "dip", "xr")
        turn = sum(abs(W[k] * tot - st[k]["val"]) for k in legs)
        after = tot - c * turn
        if turn > 0.01 * tot:
            mv = "、".join(f"{LEG[k]} {'加' if W[k] * tot > st[k]['val'] else '減'} {abs(W[k] * tot - st[k]['val']) / tot:.1%}" for k in legs
                          if abs(W[k] * tot - st[k]["val"]) > 0.002 * tot)
            fills.append(dict(date=d, leg="all", sym="再平衡", side="調整", px=None, when="收市",
                              reason=f"月尾再平衡：三隻腳調返 80／10／10（{mv}，按帳戶值計）"))
        for k in legs:
            st[k]["val"] = W[k] * after
        st["rebal"] = False
    decide(st, r)
    st["last"] = d


def decide(st, r, first=False):
    """收市決定下一個交易日要做咩（存喺 pend + why）。"""
    T, D, X = st["trend"], st["dip"], st["xr"]
    vins = RULE["vol_ins"]
    cur = T["subs"] if T.get("subs") is not None else [False] * len(vins)
    hold = bool(r["green"] and r["vol"] < RULE["vol"])             # 揸緊嗰啲份：紅燈或波幅 ≥ 35% 先賣
    new = [hold if on else bool(r["green"] and r["vol"] < v) for on, v in zip(cur, vins)]      # 冇揸嗰啲份：綠燈而且波幅 < 自己門檻先買
    T["pend"] = None
    if T.get("subs") is None or new != cur:
        T["pend"] = new
        k0, k1, n = sum(cur), sum(new), len(vins)
        if k1 > k0:
            thr = min(v for on, v in zip(new, vins) if on)
            T["why"] = (f"大市綠燈 + QQQ 20 日波幅 {r['vol']:.1%} < {pv(thr)} → 揸 TQQQ" if n == 1 else
                        f"大市綠燈 + QQQ 20 日波幅 {r['vol']:.1%} < {pv(thr)} → TQQQ 加到 {k1}／{n} 份（分 {n} 份買返：波幅低過 "
                        f"{'、'.join(pv(v) for v in vins)} 各買一份；未買嗰部分揸 IEF）")
        elif not r["green"]:
            T["why"] = "大市轉紅燈（NDX 跌穿 200 日線，又唔係企喺 21 日 EMA > 50 日線上面）→ 轉 IEF"
        elif k0:
            T["why"] = f"QQQ 20 日波幅 {r['vol']:.1%} ≥ {pv(RULE['vol'])}（大上大落，3 倍 ETF 耗損大）→ 轉 IEF"
        else:
            T["why"] = f"大市綠燈但 QQQ 20 日波幅 {r['vol']:.1%} 未低過 {pv(max(vins))} → 先揸 IEF"
    D["pend"] = None
    if D["pos"]:
        if r["rsi2"] > RULE["rsi_out"]:
            D["pend"], D["why"] = "sell", f"NDX 2 日 RSI {r['rsi2']:.1f} > 70：反彈完成，賣"
        elif D["days"] >= RULE["hold"]:
            D["pend"], D["why"] = "sell", f"已經揸滿 {RULE['hold']} 個交易日：反彈冇嚟（時間止蝕），賣"
    elif r["green"] and r["rsi2"] < RULE["rsi_in"]:
        D["pend"], D["why"] = "buy", f"大市綠燈 + NDX 2 日 RSI {r['rsi2']:.1f} < 25（短線超賣）：低吸 TQQQ"
    ok_tq = xr_ok(r)
    if r["me"] or first:
        st["rebal"] = bool(r["me"] and not first)
    if not RULE.get("xr_on", True):                                # V2.8：冇輪動腳
        X["pend"] = None
    elif r["me"] or first:
        pick, why = xr_pick(r)
        X["pend"] = pick if pick != X["hold"] else None
        X["why"] = why
    elif not ok_tq and X["hold"] == "TQQQ":                        # 安全版：月中紅燈或波幅 > 35% → 轉現金，等月尾再揀
        X["pend"] = "CASH"
        X["why"] = ("大市轉紅燈" if not r["green"] else f"QQQ 20 日波幅 {r['vol']:.1%} > {pv(RULE['vol'])}") + "：輪動腳安全版唔揸 TQQQ → 轉現金，月尾再揀"
    else:
        X["pend"] = None


def xr_ok(r):
    """輪動腳可唔可以揸 TQQQ（冇開安全版就一定得）。"""
    return not RULE.get("xr_safe") or bool(r["green"] and r["vol"] <= RULE["vol"])


def xr_pick(r):
    """月尾揀邊樣（安全版而且 TQQQ 唔揸得 → 喺其餘入面揀）。"""
    if r["pick"] == "TQQQ" and not xr_ok(r):
        return r.get("pick_safe", "CASH"), r.get("why_safe", r["why_pick"])
    return r["pick"], r["why_pick"]


# ---------------------------------------------------------------- 顯示
def positions(st, r):
    """而家每隻腳揸緊咩（現金唔列）：[(腳, 代號, 佔比, 買入價, 收市, 回報, 買入日)]。"""
    tot = nav(st)
    out = []
    T, D, X = st["trend"], st["dip"], st["xr"]
    out += trend_positions(T, r["px"], tot)
    if D["pos"]:
        out.append(("dip", "TQQQ", D["val"] / tot, D["epx"], r["px"].get("TQQQ"), r["px"]["TQQQ"] / D["epx"] - 1 if D["epx"] else 0.0, D["edate"]))
    if X["hold"] != "CASH":
        s = X["hold"]
        out.append(("xr", s, X["val"] / tot, X["epx"], r["px"].get(s), r["px"].get(s) / X["epx"] - 1 if X["epx"] and r["px"].get(s) else 0.0, X["edate"]))
    return out


def trend_positions(T, px, tot):
    """趨勢腳揸緊咩：TQQQ（f）同 IEF（1 − f）各一行。"""
    out = []
    if T.get("f") is None:
        return out
    for s, w, e, dt in (("TQQQ", T["f"], T["epx"], T["edate"]), ("IEF", 1 - T["f"], T.get("epx_ief"), T.get("edate_ief"))):
        if w > 1e-9:
            out.append(("trend", s, T["val"] * w / tot, e, px.get(s), px.get(s) / e - 1 if e and px.get(s) else 0.0, dt))
    return out


def trend_todo(T, tot):
    """趨勢腳下一個交易日要做（frac = 佔 tot 幾多）。"""
    if T["pend"] is None:
        return []
    f1, a = frac_of(T["pend"]), T["f"] or 0.0
    if T["f"] is None:
        sym, fr = ("現金 → TQQQ" if f1 >= 1 else "現金 → IEF" if f1 <= 0 else f"現金 → TQQQ {f1:.0%}、IEF {1 - f1:.0%}"), 1.0
    elif f1 > a:
        sym, fr = "IEF → TQQQ", f1 - a
    else:
        sym, fr = "TQQQ → IEF", a - f1
    return [dict(when="收市前", leg="trend", side="轉", sym=sym, frac=T["val"] * fr / tot, reason=T["why"])]


def cash_frac(st):
    tot = nav(st)
    return ((0 if st["dip"]["pos"] else st["dip"]["val"]) + (st["xr"]["val"] if st["xr"]["hold"] == "CASH" else 0)
            + (st["trend"]["val"] if st["trend"].get("f") is None else 0)) / tot


def snap(st, r, fills):
    """每日收市快照（app 歷史回看用；格式同 stock-strategy/src/model_bt.py）。"""
    tot = nav(st)
    pos = [dict(s=s, w=round(w, 4), ret=round(ret, 4), e=round(e, 2) if e else None, c=round(c, 2) if c else None, st=None, leg=LEG[k])
           for k, s, w, e, c, ret, _ in positions(st, r)]
    pos.sort(key=lambda x: -x["w"])
    f = [dict(s=x["sym"], side=x["side"], px=x["px"], **({"ret": round(x["ret"], 4)} if x.get("ret") is not None else {}), why=x["reason"])
         for x in fills if x["date"] == r["d"]]
    h = st.setdefault("hist", [])
    h[:] = [x for x in h if x["d"] != r["d"]]
    h.append(dict(d=r["d"], nav=round(tot, 0), cash=round(cash_frac(st), 4), green=r["green"], pos=pos, f=f, q=round(r["q"], 4)))
    st.setdefault("nav", []).append(dict(date=r["d"], nav=round(tot, 2)))


def todo(st, r, next_day, tot=None):
    """下一個交易日要做嘅嘢（有原因）。frac = 佔帳戶幾多（tot：成個帳戶；冇俾就係三隻腳合計）。"""
    tot = tot or nav(st)
    T, D, X = st["trend"], st["dip"], st["xr"]
    out = []
    if D["pend"] == "buy":
        out.append(dict(when="開市", leg="dip", side="買入", sym="TQQQ", frac=D["val"] / tot, reason=D["why"]))
    elif D["pend"] == "sell":
        out.append(dict(when="開市", leg="dip", side="賣出", sym="TQQQ", frac=D["val"] / tot, reason=D["why"]))
    out += trend_todo(T, tot)
    if X["pend"] is not None and X["pend"] != X["hold"]:
        out.append(dict(when="收市前", leg="xr", side="轉", sym=f"{'現金' if X['hold'] == 'CASH' else X['hold']} → {'現金' if X['pend'] == 'CASH' else X['pend']}",
                        frac=X["val"] / tot, reason=X["why"]))
    if st.get("rebal"):
        out.append(dict(when="收市前", leg="all", side="調整", sym="再平衡", frac=None,
                        reason="今日係月尾：三隻腳調返 80％ 趨勢、10％ 低吸、10％ 輪動（照「每隻腳金額」買賣差額）"))
    return out


def trend_rule(sym):
    vins = RULE["vol_ins"]
    if sym == "TQQQ":
        return f"大市轉紅燈或 QQQ 波幅 ≥ {pv(RULE['vol'])} → 收市前轉 IEF"
    return (f"綠燈 + 波幅 < {pv(vins[0])} → 收市前轉返 TQQQ" if len(vins) == 1 else
            f"綠燈 + 波幅低過 {'、'.join(pv(v) for v in vins)} → 每過一個門檻，收市前轉多一份（共 {len(vins)} 份）去 TQQQ")


def xr_rule():
    return "月尾重新揀（1、3、6 個月回報最高嗰樣）" + (f"；揸 TQQQ 時大市轉紅燈或 QQQ 波幅 > {pv(RULE['vol'])} → 收市前轉現金" if RULE.get("xr_safe") else "")


def trend_info(T, r):
    """app 用：趨勢腳而家幾多份揸 TQQQ、下一份嘅門檻。"""
    vins = list(RULE["vol_ins"])
    subs = T.get("subs") or [False] * len(vins)
    off = [v for on, v in zip(subs, vins) if not on]
    return dict(held=T.get("held"), f=T.get("f"), n_on=sum(subs), n=len(vins), vol_ins=vins, vol_in=max(vins), next_in=max(off) if off else None,
                green=r["green"], vol=r["vol"], vol_max=RULE["vol"])


def view(st, r, next_day, fills, warn):
    """app 用嘅摘要：持倉（每隻腳）、要做、三隻腳狀態。"""
    tot = nav(st)
    T, D, X = st["trend"], st["dip"], st["xr"]
    rule = {"dip": f"RSI > 70 或揸滿 10 日（而家第 {D['days']} 日）→ 開市賣", "xr": xr_rule()}
    hold = [dict(sym=s, leg=LEG[k], legk=k, weight=round(w, 4), entry=round(e, 2) if e else None, close=round(c, 2) if c else None,
                 ret=round(ret, 4), date=dt, rule=rule.get(k) or trend_rule(s)) for k, s, w, e, c, ret, dt in positions(st, r)]
    margin = max(r["ndx"] / r["s200"] - 1, min(r["ndx"] / r["e21"] - 1, r["e21"] / r["s50"] - 1))
    return dict(ver="V2.4", data_date=r["d"], next_day=next_day, green=r["green"], nav=round(tot, 2), ret=round(tot / st["capital"] - 1, 4),
                cash_frac=round(cash_frac(st), 4), holdings=hold, todo=todo(st, r, next_day),
                legs=dict(trend=dict(trend_info(T, r), w=W["trend"], frac=round(T["val"] / tot, 4)),
                          dip=dict(w=W["dip"], frac=round(D["val"] / tot, 4), pos=D["pos"], days=D["days"], rsi2=r["rsi2"], rsi_in=RULE["rsi_in"],
                                   rsi_out=RULE["rsi_out"], hold=RULE["hold"]),
                          xr=dict(w=W["xr"], frac=round(X["val"] / tot, 4), hold=X["hold"], why=xr_pick(r)[1], me=r["me"], safe=bool(RULE.get("xr_safe")), ok_tq=xr_ok(r))
                          if RULE.get("xr_on", True) else None),
                tq=tq_view(T, r, tot, W["trend"], margin),
                actions=dict(fills=[dict(x, ret=round(x["ret"], 4) if x.get("ret") is not None else None) for x in fills], warn=warn))


def tq_view(T, r, tot, target, margin):
    """app TQQQ 黃燈同 AI 提示用。pend：None = 冇變、True = 下一日加 TQQQ、False = 下一日賣 TQQQ。frac = 而家 TQQQ 佔帳戶幾多。"""
    pend = None if T["pend"] is None else frac_of(T["pend"]) > (T["f"] or 0.0)
    return dict(trend_info(T, r), held=bool(T.get("held")), pend=pend, frac=round(T["val"] * (T.get("f") or 0.0) / tot, 4), target=target, why_off=T["why"],
                margin=round(margin, 4), gap21=round(r["ndx"] / r["e21"] - 1, 4), gap50=round(r["ndx"] / r["s50"] - 1, 4))
