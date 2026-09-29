"""模型帳戶（2026-09-29 用戶要求）：照 V2.2 規則自動行一個虛擬帳戶，新手照抄就得。[quant-risk]

V2.2（2026-09-30 用戶採用，stock-strategy/LAB_GRID2.md 嘅 B3）= V2.1 + 排名跌出頭 15 先賣（剎車時頭 6）
+ 現金用途：綠燈時未用嘅現金買短期國債（SGOV／BIL，按 ^IRX 計息）；紅燈時現金買 IEF（7–10 年國債）；轉換扣 0.1%。

每日收市後（daily-scan.yml 喺 scan.py 之後跑）讀 docs/scan.json，按次序處理新交易日：
  1. 開市：執行上一日收市決定嘅賣出（開市價）
  2. 盤中：上一日掛嘅 buy-stop，最高 >= 買入價就買（成交 = max(開市, 買入價)），排名高先用現金，每隻 20%（排第 1 用 30%）
  3. 盤中：最低 <= 止蝕就賣（開市已穿用開市價，否則止蝕價；當日先買嘅用止蝕價）
  4. 收市（只喺最新一日，因為要排名）：2R 保本、跟 swing low 上移；大市紅燈／跌穿 200 日線／星期五排名跌出頭 15 -> 下一日開市賣；
     星期五記帳戶值做回撤剎車（跌 25% 只揸 2 隻，返到 −12.5% 恢復）；有空位就對排名頭嘅候選股掛 buy-stop（空位 × 2 張）
成本每邊 0.1%。價錢係 Yahoo 拆股調整價（同 app 一樣）；拆股時自動換算持倉。
輸出 docs/model.json（狀態 + 下一個交易日要做嘅嘢 + hist 每日快照：帳戶值、現金、持倉、當日成交，app 用嚟拉條 bar 睇歷史）。
用法：python scanner/model.py            （每日）
      python scanner/model.py seed       （由而家份 scan.json 嘅下一個交易日開始，全現金）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN, OUT = ROOT / "docs" / "scan.json", ROOT / "docs" / "model.json"
RULE = dict(cap=5, cap_brake=2, frac=0.20, boost=1.5, rank_exit=15.0, rank_exit_brake=6.0, sleeve_cost=0.001, be_R=2.0, atr_buf=0.2,
            brake_down=0.75, brake_up=0.875, cost=0.001, mult=2)
CAPITAL = 100_000.0


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def nav_at(st, px):
    return st["cash"] + sum(p["shares"] * px(p) for p in st["positions"])


def snap(st, d, fills, green):
    """每日收市快照（同 stock-strategy/src/model_bt.py 嘅 days 格式一樣）。"""
    nav = nav_at(st, lambda p: p["last_close"])
    pos = sorted((dict(s=p["sym"], w=round(p["shares"] * p["last_close"] / nav, 4) if nav else 0,
                       ret=round(p["last_close"] / p["entry"] - 1, 4), e=round(p["entry"], 2), c=round(p["last_close"], 2),
                       st=round(p["stop"], 2)) for p in st["positions"]), key=lambda x: -x["w"])
    f = [dict(s=x["sym"], side=x["side"], px=x["px"], **({"ret": x["ret"]} if x.get("ret") is not None else {}),
              why=x.get("reason") or "突破買入") for x in fills if x["date"] == d]
    h = st.setdefault("hist", [])
    h[:] = [x for x in h if x["d"] != d]
    h.append(dict(d=d, nav=round(nav, 0), cash=round(st["cash"] / nav, 4) if nav else 1.0, green=green, pos=pos, f=f))


def plan(st, sc, actions):
    """最新收市：更新止蝕、決定賣出、掛下一日 buy-stop。"""
    stocks, R = sc["stocks"], RULE
    rank = {r["sym"]: r["rank"] for r in sc["ranking"]}
    sells = []
    for p in st["positions"]:
        s = stocks.get(p["sym"])
        if not s:
            actions["warn"].append(f"{p['sym']} 冇數據，請自己檢查")
            continue
        c, old = s["close"], p["stop"]
        if not p["be"] and p["R"] > 0 and c >= p["entry"] + R["be_R"] * p["R"]:
            p["be"], p["stop"] = True, max(p["stop"], p["entry"])
        if p["be"] and s.get("swing_low") is not None and s.get("atr") is not None:
            p["stop"] = max(p["stop"], s["swing_low"] - R["atr_buf"] * s["atr"])
        if p["stop"] > old + 1e-9:
            actions["stops"].append(dict(sym=p["sym"], old=round(old, 2), new=round(p["stop"], 2), be=p["be"]))
        why = []
        if not sc["green"]:
            why.append("大市紅燈")
        if s.get("sma200") and c < s["sma200"]:
            why.append("收市跌穿 200 日線")
        lim = R["rank_exit_brake"] if st["braking"] else R["rank_exit"]
        if sc["week_end"] and (rank.get(p["sym"]) is None or rank[p["sym"]] > lim):
            why.append(f"排名第 {rank[p['sym']]}" if p["sym"] in rank else "跌出股票池頭 50")
        if why:
            sells.append(dict(sym=p["sym"], reason="、".join(why)))
    px = lambda p: stocks[p["sym"]]["close"] if p["sym"] in stocks else p["last_close"]
    if sc["week_end"]:                                       # 回撤剎車：星期五帳戶值
        v = nav_at(st, px)
        st["peak"] = max(st["peak"] or v, v)
        if v <= st["peak"] * R["brake_down"]:
            st["braking"] = True
        elif v >= st["peak"] * R["brake_up"]:
            st["braking"] = False
    sold = {x["sym"] for x in sells}
    if st["braking"] and sc["week_end"]:
        keep = sorted([p for p in st["positions"] if p["sym"] not in sold], key=lambda p: rank.get(p["sym"], 999))
        for p in keep[R["cap_brake"]:]:
            sells.append(dict(sym=p["sym"], reason="回撤剎車減倉")); sold.add(p["sym"])
    cap = R["cap_brake"] if st["braking"] else R["cap"]
    held = [p["sym"] for p in st["positions"] if p["sym"] not in sold]
    slots = max(0, cap - len(held)) if sc["green"] else 0
    buys = []
    if slots:
        for r in sc["ranking"]:
            if r["status"] == "候選" and r["sym"] not in held and len(buys) < slots * R["mult"]:
                buys.append(dict(sym=r["sym"], rank=r["rank"], trigger=r["pivot"], stop=r["stop"],
                                 frac=R["frac"] * (R["boost"] if r["sym"] == sc["rank1"] else 1.0)))
    st["pending"] = {"for": sc["next_day"], "buys": buys, "sells": sells}
    st["slots"] = slots


def step(st, sc, i, actions):
    """處理 scan 入面第 i 個交易日（開市賣 -> buy-stop -> 止蝕 -> 收市值）。"""
    d, stocks, R = sc["days"][i], sc["stocks"], RULE
    arr = lambda s, k: (stocks.get(s) or {}).get(k, [None] * 10)[i]
    pend = st.get("pending") or {}
    prev_px = lambda p: (stocks.get(p["sym"]) or {}).get("c10", [None] * 10)[i - 1] if i > 0 else None
    nav_prev = nav_at(st, lambda p: prev_px(p) or p["last_close"])
    if pend.get("for") and pend["for"] <= d:
        for x in pend.get("sells", []):                        # 1. 開市賣
            p = next((p for p in st["positions"] if p["sym"] == x["sym"]), None)
            if p:
                o = arr(p["sym"], "o10") or arr(p["sym"], "c10") or p["last_close"]
                close_pos(st, p, o, d, x["reason"], actions)
        for b in pend.get("buys", []):                         # 2. buy-stop
            s = b["sym"]
            if any(p["sym"] == s for p in st["positions"]):
                continue
            o, h = arr(s, "o10"), arr(s, "h10")
            if o is None or h is None or h < b["trigger"]:
                continue
            fill = max(o, b["trigger"])
            if fill <= b["stop"]:
                continue
            value = min(b["frac"] * nav_prev, st["cash"])
            if value <= nav_prev * 1e-4:
                continue
            px = fill * (1 + R["cost"])
            sh = value / px
            st["cash"] -= sh * px
            st["positions"].append(dict(sym=s, date=d, entry=round(fill, 4), shares=sh, stop=b["stop"], R=round(fill - b["stop"], 4),
                                        be=False, last_close=arr(s, "c10") or fill, frac=b["frac"]))
            actions["fills"].append(dict(date=d, sym=s, side="買入", px=round(fill, 2), frac=b["frac"]))
        st["pending"] = {}
    for p in list(st["positions"]):                            # 3. 止蝕
        lo, o = arr(p["sym"], "l10"), arr(p["sym"], "o10")
        if lo is not None and lo <= p["stop"]:
            px = o if (o is not None and o <= p["stop"] and p["date"] != d) else p["stop"]
            close_pos(st, p, px, d, "打止蝕", actions)
    for p in st["positions"]:                                  # 4. 收市
        c = arr(p["sym"], "c10")
        if c is not None:
            p["last_close"] = c
    cash_sleeve(st, sc, i)
    st["nav"].append(dict(date=d, nav=round(nav_at(st, lambda p: p["last_close"]), 2)))
    snap(st, d, actions["fills"], sc["green"] if d == sc["date"] else None)


def cash_sleeve(st, sc, i):
    """V2.2 現金：上一日收市綠燈 -> 收短期國債息（^IRX ÷ 252）；紅燈 -> 跟 IEF 升跌。轉換嗰日扣 0.1%。"""
    cs = sc.get("cash") or {}
    g10, ief, irx = cs.get("green10"), cs.get("ief10"), cs.get("irx10")
    if not g10:
        return
    prev_green = g10[i - 1] if i > 0 else st.get("last_green", g10[i])
    mode = "bill" if prev_green else "ief"
    r = 0.0
    if mode == "bill" and irx and irx[i - 1 if i > 0 else i] is not None:
        r = irx[i - 1 if i > 0 else i] / 100 / 252
    elif mode == "ief" and ief and i > 0 and ief[i] and ief[i - 1]:
        r = ief[i] / ief[i - 1] - 1
    if st["cash"] > 0:
        if st.get("sleeve") and st["sleeve"] != mode:
            st["cash"] -= st["cash"] * RULE["sleeve_cost"]
        st["cash"] *= 1 + r
    st["sleeve"], st["last_green"] = mode, g10[i]


def close_pos(st, p, price, d, reason, actions):
    fill = price * (1 - RULE["cost"])
    st["cash"] += p["shares"] * fill
    st["positions"].remove(p)
    ret = fill / (p["entry"] * (1 + RULE["cost"])) - 1
    st["trades"].append(dict(sym=p["sym"], date=p["date"], entry=p["entry"], sell_date=d, sell=round(price, 2),
                             ret=round(ret, 4), reason=reason))
    actions["fills"].append(dict(date=d, sym=p["sym"], side="賣出", px=round(price, 2), ret=round(ret, 4), reason=reason))


def fix_splits(st, sc, i0):
    """拆股：新數據前一日收市同存低嘅收市差好遠 -> 按比例換算持倉。"""
    if i0 < 1:
        return
    for p in st["positions"]:
        c = (sc["stocks"].get(p["sym"]) or {}).get("c10", [None] * 10)[i0 - 1]
        if c and p["last_close"] and abs(c / p["last_close"] - 1) > 0.25:
            k = c / p["last_close"]
            p["entry"], p["stop"], p["R"], p["last_close"] = p["entry"] * k, p["stop"] * k, p["R"] * k, c
            p["shares"] /= k


def seed():
    sc = load(SCAN)
    st = dict(start=sc["next_day"], capital=CAPITAL, cash=CAPITAL, positions=[], trades=[], nav=[], peak=None, braking=False,
              last=sc["date"], ndx0=sc["ndx"], pending={}, slots=0)
    actions = dict(fills=[], stops=[], warn=[])
    plan(st, sc, actions)
    save(st, sc, actions)
    print(f"[model] 由 {st['start']} 開始，全現金 {CAPITAL:,.0f}；掛 {len(st['pending']['buys'])} 張 buy-stop")


def save(st, sc, actions):
    stocks = sc["stocks"]
    nav = nav_at(st, lambda p: p["last_close"])
    view = dict(generated=sc.get("generated"), data_date=sc["date"], next_day=sc["next_day"], green=sc["green"],
                sleeve="bill" if sc["green"] else "ief",
                nav=round(nav, 2), ret=round(nav / st["capital"] - 1, 4), ndx_ret=round(sc["ndx"] / st["ndx0"] - 1, 4),
                cash_frac=round(st["cash"] / nav, 4) if nav else 1.0,
                holdings=[dict(sym=p["sym"], date=p["date"], entry=round(p["entry"], 2), close=round(p["last_close"], 2),
                               ret=round(p["last_close"] / p["entry"] - 1, 4), stop=round(p["stop"], 2), be=p["be"],
                               weight=round(p["shares"] * p["last_close"] / nav, 4) if nav else 0,
                               day_chg=(lambda c: round(c[-1] / c[-2] - 1, 4) if c and len(c) > 1 and c[-2] else None)(
                                   (stocks.get(p["sym"]) or {}).get("c10")))
                          for p in st["positions"]],
                actions=actions)
    st["view"] = view
    OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    sc = load(SCAN)
    if not OUT.exists():
        return seed()
    st = load(OUT)
    if "hist" not in st and st["nav"]:                           # 2026-09-29 之前開嘅帳戶：用現況補第一日
        snap(st, st["last"], (st.get("view") or {}).get("actions", {}).get("fills", []), (st.get("view") or {}).get("green"))
        OUT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    if sc["date"] <= st["last"]:
        print(f"[model] 冇新數據（{sc['date']}）")
        return
    days = sc["days"]
    new = [i for i, d in enumerate(days) if d > st["last"]]
    if not new:
        print("[model] 新數據唔包括最近日子")
        return
    actions = dict(fills=[], stops=[], warn=[])
    if days[0] > st["last"]:
        actions["warn"].append(f"隔咗超過 10 個交易日先更新，{st['last']} 之後部分日子冇計")
    fix_splits(st, sc, new[0])
    for i in new:
        step(st, sc, i, actions)
    st["last"] = sc["date"]
    plan(st, sc, actions)
    snap(st, sc["date"], actions["fills"], sc["green"])          # 收市後止蝕上移都計埋
    save(st, sc, actions)
    v = st["view"]
    print(f"[model] {sc['date']}：帳戶 {v['nav']:,.0f}（{v['ret']:+.1%}，NDX {v['ndx_ret']:+.1%}）持股 {len(st['positions'])} 隻；"
          f"成交 {len(actions['fills'])}；下一日掛 {len(st['pending']['buys'])} 張、賣 {len(st['pending']['sells'])} 隻")


if __name__ == "__main__":
    seed() if sys.argv[1:] == ["seed"] else main()
