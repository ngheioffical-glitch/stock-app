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
"""
from __future__ import annotations

import math

W = dict(trend=0.80, dip=0.10, xr=0.10)
RULE = dict(vol=0.35, rsi_in=25.0, rsi_out=70.0, hold=10, cost=0.001)
LEV = {"QQQ": "TQQQ", "TLT": "TMF", "GLD": "UGL"}
LEG = {"trend": "趨勢腳", "dip": "低吸腳", "xr": "輪動腳"}
UNDER = {"QQQ": "QQQ", "TLT": "TLT（長債）", "GLD": "黃金"}
pc = lambda x: f"{x * 100:+.1f}%"


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
        px = {s: float(F[s].iloc[i]) for s in ("TQQQ", "IEF", "TMF", "UGL") if s in F and np.isfinite(F[s].iloc[i])}
        op = float(F["tq_open"].iloc[i]) if "tq_open" in F and np.isfinite(F["tq_open"].iloc[i]) else None
        out.append(dict(d=str(t.date()), green=bool(green.iloc[i]), vol=round(float(vol.iloc[i]), 4), rsi2=round(float(r2.iloc[i]), 1),
                        bill=float(bill.iloc[i]), px=px, op=op, me=nd[:7] != str(t.date())[:7], pick=pick, why_pick=why,
                        q=float(q.iloc[i]), ndx=float(ndx.iloc[i]), e21=float(e21.iloc[i]), s50=float(s50.iloc[i]), s200=float(s200.iloc[i])))
    return out


# ---------------------------------------------------------------- 帳戶
def new_state(capital, prev, note=""):
    """全現金開始：用上一個交易日（prev）收市嘅訊號決定第一日要做咩（同之後每日一樣）。"""
    st = dict(ver="V2.4", start=None, capital=capital, last=prev["d"], note=note, rebal=False,
              trend=dict(val=capital * W["trend"], held=None, pend=None, why=None, epx=None, edate=None),
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
    # ---- 趨勢腳（收市升跌 → 收市執行）
    T = st["trend"]
    T["val"] *= (1 + r["bill"]) if T["held"] is None else _r(r, p, "TQQQ" if T["held"] else "IEF")
    if T["pend"] is not None and T["pend"] != T["held"]:
        T["val"] *= 1 - c
        old = T["held"]
        if T["pend"]:
            if old is False:
                fills.append(dict(date=d, leg="trend", sym="IEF", side="賣出", px=round(r["px"].get("IEF", 0), 2), when="收市", reason="趨勢腳：" + T["why"]))
            fills.append(dict(date=d, leg="trend", sym="TQQQ", side="買入", px=round(tq, 2), when="收市", reason="趨勢腳：" + T["why"]))
            T.update(held=True, epx=tq, edate=d)
        else:
            if old:
                ret = tq / T["epx"] - 1 if T["epx"] else None
                fills.append(dict(date=d, leg="trend", sym="TQQQ", side="賣出", px=round(tq, 2), ret=ret, when="收市", reason="趨勢腳：" + T["why"]))
                st["trades"].append(dict(leg="trend", sym="TQQQ", date=T["edate"], entry=T["epx"], sell_date=d, sell=tq, ret=ret, reason=T["why"]))
            fills.append(dict(date=d, leg="trend", sym="IEF", side="買入", px=round(r["px"].get("IEF", 0), 2), when="收市", reason="趨勢腳：" + T["why"]))
            T.update(held=False, epx=r["px"].get("IEF"), edate=d)
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
    on = bool(r["green"] and r["vol"] < RULE["vol"])
    T["pend"] = None
    if on != T["held"]:
        T["pend"] = on
        T["why"] = (f"大市綠燈 + QQQ 20 日波幅 {r['vol']:.1%} < 35% → 揸 TQQQ" if on else
                    ("大市轉紅燈（NDX 跌穿 200 日線，又唔係企喺 21 日 EMA > 50 日線上面）→ 轉 IEF" if not r["green"] else
                     f"QQQ 20 日波幅 {r['vol']:.1%} ≥ 35%（大上大落，3 倍 ETF 耗損大）→ 轉 IEF"))
    D["pend"] = None
    if D["pos"]:
        if r["rsi2"] > RULE["rsi_out"]:
            D["pend"], D["why"] = "sell", f"NDX 2 日 RSI {r['rsi2']:.1f} > 70：反彈完成，賣"
        elif D["days"] >= RULE["hold"]:
            D["pend"], D["why"] = "sell", f"已經揸滿 {RULE['hold']} 個交易日：反彈冇嚟（時間止蝕），賣"
    elif r["green"] and r["rsi2"] < RULE["rsi_in"]:
        D["pend"], D["why"] = "buy", f"大市綠燈 + NDX 2 日 RSI {r['rsi2']:.1f} < 25（短線超賣）：低吸 TQQQ"
    if r["me"] or first:
        X["pend"] = r["pick"] if r["pick"] != X["hold"] else None
        X["why"] = r["why_pick"]
        st["rebal"] = bool(r["me"] and not first)
    else:
        X["pend"] = None


# ---------------------------------------------------------------- 顯示
def positions(st, r):
    """而家每隻腳揸緊咩（現金唔列）：[(腳, 代號, 佔比, 買入價, 收市, 回報, 買入日)]。"""
    tot = nav(st)
    out = []
    T, D, X = st["trend"], st["dip"], st["xr"]
    if T["held"] is not None:
        s = "TQQQ" if T["held"] else "IEF"
        out.append(("trend", s, T["val"] / tot, T["epx"], r["px"].get(s), r["px"].get(s) / T["epx"] - 1 if T["epx"] and r["px"].get(s) else 0.0, T["edate"]))
    if D["pos"]:
        out.append(("dip", "TQQQ", D["val"] / tot, D["epx"], r["px"].get("TQQQ"), r["px"]["TQQQ"] / D["epx"] - 1 if D["epx"] else 0.0, D["edate"]))
    if X["hold"] != "CASH":
        s = X["hold"]
        out.append(("xr", s, X["val"] / tot, X["epx"], r["px"].get(s), r["px"].get(s) / X["epx"] - 1 if X["epx"] and r["px"].get(s) else 0.0, X["edate"]))
    return out


def cash_frac(st):
    tot = nav(st)
    return ((0 if st["dip"]["pos"] else st["dip"]["val"]) + (st["xr"]["val"] if st["xr"]["hold"] == "CASH" else 0)
            + (st["trend"]["val"] if st["trend"]["held"] is None else 0)) / tot


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


def todo(st, r, next_day):
    """下一個交易日要做嘅嘢（有原因）。frac = 佔帳戶幾多。"""
    tot = nav(st)
    T, D, X = st["trend"], st["dip"], st["xr"]
    out = []
    if D["pend"] == "buy":
        out.append(dict(when="開市", leg="dip", side="買入", sym="TQQQ", frac=D["val"] / tot, reason=D["why"]))
    elif D["pend"] == "sell":
        out.append(dict(when="開市", leg="dip", side="賣出", sym="TQQQ", frac=D["val"] / tot, reason=D["why"]))
    if T["pend"] is not None and T["pend"] != T["held"]:
        if T["pend"]:
            out.append(dict(when="收市前", leg="trend", side="轉", sym="IEF → TQQQ" if T["held"] is False else "現金 → TQQQ", frac=T["val"] / tot, reason=T["why"]))
        else:
            out.append(dict(when="收市前", leg="trend", side="轉", sym="TQQQ → IEF" if T["held"] else "現金 → IEF", frac=T["val"] / tot, reason=T["why"]))
    if X["pend"] is not None and X["pend"] != X["hold"]:
        out.append(dict(when="收市前", leg="xr", side="轉", sym=f"{'現金' if X['hold'] == 'CASH' else X['hold']} → {'現金' if X['pend'] == 'CASH' else X['pend']}",
                        frac=X["val"] / tot, reason=X["why"]))
    if st.get("rebal"):
        out.append(dict(when="收市前", leg="all", side="調整", sym="再平衡", frac=None,
                        reason="今日係月尾：三隻腳調返 80％ 趨勢、10％ 低吸、10％ 輪動（照「每隻腳金額」買賣差額）"))
    return out


def view(st, r, next_day, fills, warn):
    """app 用嘅摘要：持倉（每隻腳）、要做、三隻腳狀態。"""
    tot = nav(st)
    T, D, X = st["trend"], st["dip"], st["xr"]
    rule = {"trend": "大市轉紅燈或 QQQ 波幅 ≥ 35% → 收市前轉 IEF" if T["held"] else "綠燈 + 波幅 < 35% → 收市前轉返 TQQQ",
            "dip": f"RSI > 70 或揸滿 10 日（而家第 {D['days']} 日）→ 開市賣", "xr": "月尾重新揀（1、3、6 個月回報最高嗰樣）"}
    hold = [dict(sym=s, leg=LEG[k], legk=k, weight=round(w, 4), entry=round(e, 2) if e else None, close=round(c, 2) if c else None,
                 ret=round(ret, 4), date=dt, rule=rule[k]) for k, s, w, e, c, ret, dt in positions(st, r)]
    margin = max(r["ndx"] / r["s200"] - 1, min(r["ndx"] / r["e21"] - 1, r["e21"] / r["s50"] - 1))
    return dict(ver="V2.4", data_date=r["d"], next_day=next_day, green=r["green"], nav=round(tot, 2), ret=round(tot / st["capital"] - 1, 4),
                cash_frac=round(cash_frac(st), 4), holdings=hold, todo=todo(st, r, next_day),
                legs=dict(trend=dict(w=W["trend"], frac=round(T["val"] / tot, 4), held=T["held"], green=r["green"], vol=r["vol"], vol_max=RULE["vol"]),
                          dip=dict(w=W["dip"], frac=round(D["val"] / tot, 4), pos=D["pos"], days=D["days"], rsi2=r["rsi2"], rsi_in=RULE["rsi_in"],
                                   rsi_out=RULE["rsi_out"], hold=RULE["hold"]),
                          xr=dict(w=W["xr"], frac=round(X["val"] / tot, 4), hold=X["hold"], why=r["why_pick"], me=r["me"])),
                tq=dict(held=bool(T["held"]), pend=T["pend"], frac=round(T["val"] / tot, 4), target=W["trend"], vol=r["vol"], vol_max=RULE["vol"],
                        green=r["green"], why_off=T["why"], margin=round(margin, 4), gap21=round(r["ndx"] / r["e21"] - 1, 4),
                        gap50=round(r["ndx"] / r["s50"] - 1, 4)),
                actions=dict(fills=[dict(x, ret=round(x["ret"], 4) if x.get("ret") is not None else None) for x in fills], warn=warn))
