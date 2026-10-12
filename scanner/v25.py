"""V2.7 模型（2026-10-12 用戶揀方向 A：「贏 QQQ 優先，回撤盡量細」；stock-strategy/LAB_LOSSMIN.md 第 2 輪冇偷睇揀法 LM2 2026 年揀中：
35／45／5／15｜趨勢腳分段買返｜輪動腳安全版）。之前 V2.6（30／50／10／10、再買門檻單一 25%，LAB_ROBUST25）、V2.5（40／40／10／10，LAB_BEST）。[quant-risk]
研究（stock-strategy/src/v25_hist.py：2000 年起歷史）同雲端（scanner/model.py：每日接落去行）共用呢份；三隻 ETF 腳嘅買賣規則喺 v24.py（照用）。

資金分 4 部分：
  35% 領導股：V2.2 規則（成交額頭 50、RS 排名、前高 buy-stop、swing low 止蝕、2R 保本後跟 swing low 上移、
       跌穿 200 日線／星期五排名跌出頭 15／大市紅燈賣、呢部分由高位跌 25% 剎車只揸 2 隻；現金綠燈收國債息、紅燈揸 IEF）。
       雲端：scanner/lead.py；研究：stock-strategy 引擎（src/model_bt.py run_days）。
  45% 趨勢腳：揸緊 TQQQ 時照舊（紅燈或 QQQ 20 日波幅 ≥ 35% 就一次過賣晒轉 IEF）；買返分 4 份：綠燈而且波幅低過 30%／27.5%／25%／22.5% 各買一份
       （V2.6 單一 25% 門檻係撞啱：改 22.5% 或 27.5% 就唔再全方位，LAB_V26_CHECK；四個門檻平均就冇呢個問題）。
  5% 低吸腳：同 V2.4 一樣。
  15% 輪動腳（安全版）：每月揀 TQQQ／TMF／UGL／現金；大市紅燈或 QQQ 20 日波幅 > 35% 就唔揸 TQQQ（月尾唔揀；月中揸緊就轉現金等月尾再揀）。
每月最後一個交易日收市決定、下一個交易日收市調返 35／45／5／15：領導股部分只用現金調（唔會為咗比例賣股），
  三隻 ETF 腳按 45：5：15 分餘下嘅錢；每個移動嘅美元每邊 0.1%。
"""
from __future__ import annotations

import v24

v24.RULE["vol_ins"] = (0.30, 0.275, 0.25, 0.225)     # V2.7：趨勢腳分 4 份買返，每份自己嘅波幅門檻
v24.RULE["xr_safe"] = True                          # V2.7：輪動腳安全版
W = dict(lead=0.35, trend=0.45, dip=0.05, xr=0.15)
LEGS = ("trend", "dip", "xr")
LEG = {"lead": "領導股", **v24.LEG}
COST = v24.RULE["cost"]
VER = "V2.7"
TXT = "35％ 領導股、45％ 趨勢、5％ 低吸、15％ 輪動"


def new_legs(capital, prev, note=""):
    """三隻 ETF 腳全現金開始（金額 = 總資金 × 比重）；領導股部分由調用者自己開（現金 = 總資金 × 領導股比重）。"""
    st = v24.new_state(capital, prev, note)
    for k in LEGS:
        st[k]["val"] = capital * W[k]
    st["ver"] = VER
    return st


def legs_val(st):
    return sum(st[k]["val"] for k in LEGS)


def step_legs(st, r, p, fills):
    """三隻 ETF 腳行一日（v24.step，但唔做 V2.4 嘅 80／10／10 再平衡）。返今日要唔要做月尾再平衡。"""
    reb = bool(st.pop("rebal", False))
    v24.step(st, r, p, fills)
    return reb


def rebalance(st, lead_val, lead_cash, d, fills):
    """調返 W 嘅比重。領導股只可以用現金俾錢出去（lead_cash）。返領導股現金變動（+ = 收錢、− = 俾錢）。"""
    legs = legs_val(st)
    tot = lead_val + legs
    tgt = W["lead"] * tot
    mv = -min(lead_val - tgt, max(lead_cash, 0.0)) if lead_val > tgt else tgt - lead_val
    new = legs - mv
    wl = sum(W[k] for k in LEGS)
    chg = {k: W[k] / wl * new - st[k]["val"] for k in LEGS}
    turn = abs(mv) + sum(abs(v) for v in chg.values())
    after = new - COST * turn
    if turn > 0.01 * tot:
        parts = [f"領導股 {'收' if mv > 0 else '俾出'}現金 {abs(mv) / tot:.1%}"] if abs(mv) > 0.002 * tot else []
        parts += [f"{LEG[k]} {'加' if v > 0 else '減'} {abs(v) / tot:.1%}" for k, v in chg.items() if abs(v) > 0.002 * tot]
        short = " （領導股現金唔夠，唔會為咗比例賣股）" if lead_val > tgt and lead_val - tgt > lead_cash + 1e-9 else ""
        fills.append(dict(date=d, leg="all", sym="再平衡", side="調整", px=None, when="收市",
                          reason=f"月尾再平衡：調返 {TXT}（{'、'.join(parts)}，按帳戶值計）{short}"))
    for k in LEGS:
        st[k]["val"] = W[k] / wl * after
    return mv


def leg_positions(st, r, tot):
    """三隻 ETF 腳揸緊咩（現金唔列）：[(腳, 代號, 佔成個帳戶, 買入價, 收市, 回報, 買入日)]。趨勢腳分段買返時 TQQQ 同 IEF 各一行。"""
    D, X = st["dip"], st["xr"]
    px = r["px"]
    out = v24.trend_positions(st["trend"], px, tot)
    if D["pos"]:
        out.append(("dip", "TQQQ", D["val"] / tot, D["epx"], px.get("TQQQ"), px["TQQQ"] / D["epx"] - 1 if D["epx"] and px.get("TQQQ") else 0.0, D["edate"]))
    if X["hold"] != "CASH":
        s = X["hold"]
        out.append(("xr", s, X["val"] / tot, X["epx"], px.get(s), px.get(s) / X["epx"] - 1 if X["epx"] and px.get(s) else 0.0, X["edate"]))
    return out


def leg_cash(st):
    return ((0 if st["dip"]["pos"] else st["dip"]["val"]) + (st["xr"]["val"] if st["xr"]["hold"] == "CASH" else 0)
            + (st["trend"]["val"] if st["trend"].get("f") is None else 0))


def leg_rows(st, r, tot):
    """快照用（同 stock-strategy/src/model_bt.py 嘅 pos 格式 + leg）。"""
    return [dict(s=s, w=round(w, 4), ret=round(ret, 4), e=round(e, 2) if e else None, c=round(c, 2) if c else None, st=None, leg=LEG[k])
            for k, s, w, e, c, ret, _ in leg_positions(st, r, tot)]


def leg_todo(st, r, tot):
    """三隻 ETF 腳下一個交易日要做（frac 按成個帳戶計）。"""
    out = []
    for t in v24.todo(st, r, None, tot):
        if t["leg"] == "all":
            out.append(dict(t, reason=f"今日係月尾：調返 {TXT}（領導股部分只用現金調，唔賣股；ETF 腳照「每隻腳金額」買賣差額）"))
        else:
            out.append(t)
    return out


def leg_view(st, r, tot):
    T, D, X = st["trend"], st["dip"], st["xr"]
    rule = {"dip": f"RSI > 70 或揸滿 10 日（而家第 {D['days']} 日）→ 開市賣", "xr": v24.xr_rule()}
    hold = [dict(sym=s, leg=LEG[k], legk=k, weight=round(w, 4), entry=round(e, 2) if e else None, close=round(c, 2) if c else None,
                 ret=round(ret, 4), date=dt, rule=rule.get(k) or v24.trend_rule(s)) for k, s, w, e, c, ret, dt in leg_positions(st, r, tot)]
    margin = max(r["ndx"] / r["s200"] - 1, min(r["ndx"] / r["e21"] - 1, r["e21"] / r["s50"] - 1))
    legs = dict(trend=dict(v24.trend_info(T, r), w=W["trend"], frac=round(T["val"] / tot, 4)),
                dip=dict(w=W["dip"], frac=round(D["val"] / tot, 4), pos=D["pos"], days=D["days"], rsi2=r["rsi2"], rsi_in=v24.RULE["rsi_in"],
                         rsi_out=v24.RULE["rsi_out"], hold=v24.RULE["hold"]),
                xr=dict(w=W["xr"], frac=round(X["val"] / tot, 4), hold=X["hold"], why=v24.xr_pick(r)[1], me=r["me"], safe=bool(v24.RULE.get("xr_safe")),
                        ok_tq=v24.xr_ok(r)))
    return hold, legs, v24.tq_view(T, r, tot, W["trend"], margin)
