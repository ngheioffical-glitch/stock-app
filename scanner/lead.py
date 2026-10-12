"""領導股部分（比重睇 v25.W["lead"]；V2.7 = 35%）：V2.2 規則，雲端每日讀 docs/scan.json 行（由 V2.3 model.py 搬過嚟，規則一樣）。[quant-risk]

每個交易日（model.py 按次序調用）：
  1. 開市：執行上一日收市決定嘅賣出（開市價）
  2. 盤中：上一日掛嘅 buy-stop，最高 >= 買入價就買（成交 = max(開市, 買入價)），排名高先用現金，
     每隻 = 呢部分帳戶值 × 20%（排第 1 用 30%）
  3. 盤中：最低 <= 止蝕就賣（開市已穿用開市價，否則止蝕價；當日先買嘅用止蝕價）
  4. 收市：記收市價；連續 5 個交易日冇價 = 退市／被收購（AI 查證）；現金：上一日綠燈收國債息（SGOV／BIL），紅燈跟 IEF
最新一日收市（plan）：2R 保本、跟 swing low − 0.2 ATR 上移；大市紅燈／跌穿 200 日線／星期五排名跌出頭 15（剎車中頭 6）→ 下一日開市賣；
  星期五記呢部分帳戶值做回撤剎車（由高位跌 25% → 最多揸 2 隻，返到高位 − 12.5% 恢復）；有空位就對排名頭嘅候選股掛 buy-stop（空位 × 2 張）。
成本每邊 0.1%。價錢係 Yahoo 拆股調整價；拆股自動換算持倉（Yahoo 拆股紀錄／AI 查證）。
狀態放喺帳戶頂層（cash、positions、peak、braking、pending、slots、sleeve、last_green），scan.py 嘅 must_have() 靠 positions／pending 揀股下載。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

RULE = dict(cap=5, cap_brake=2, frac=0.20, boost=1.5, rank_exit=15.0, rank_exit_brake=6.0, sleeve_cost=0.001, be_R=2.0, atr_buf=0.2,
            brake_down=0.75, brake_up=0.875, cost=0.001, mult=2,
            delist_days=5,       # 持倉連續 5 個交易日冇價：當退市／被收購（同回測引擎一樣）；停牌幾日唔會誤判
            split_tol=0.03)      # 同一日收市價被 Yahoo 追溯改咗 > 3% = 拆股／合股
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def _ai(prompt):
    import model
    return model.ai_search(prompt)


def nav_at(st, px):
    """領導股部分嘅帳戶值（注碼、剎車用呢個）。"""
    return st["cash"] + sum(p["shares"] * px(p) for p in st["positions"])


def value(st):
    return nav_at(st, lambda p: p["last_close"])


def close_pos(st, p, price, d, reason, actions):
    fill = price * (1 - RULE["cost"])
    st["cash"] += p["shares"] * fill
    st["positions"].remove(p)
    ret = fill / (p["entry"] * (1 + RULE["cost"])) - 1
    st["trades"].append(dict(leg="lead", sym=p["sym"], date=p["date"], entry=p["entry"], sell_date=d, sell=round(price, 2),
                             ret=round(ret, 4), reason=reason))
    actions["fills"].append(dict(date=d, leg="lead", sym=p["sym"], side="賣出", px=round(price, 2), ret=round(ret, 4), when="開市／盤中",
                                 reason=f"領導股：{reason}"))


def step(st, sc, i, actions):
    """處理 scan 入面第 i 個交易日（開市賣 → buy-stop → 止蝕 → 收市 → 現金）。"""
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
            val = min(b["frac"] * nav_prev, st["cash"])
            if val <= nav_prev * 1e-4:
                continue
            px = fill * (1 + R["cost"])
            sh = val / px
            st["cash"] -= sh * px
            st["positions"].append(dict(sym=s, date=d, entry=round(fill, 4), shares=sh, stop=b["stop"], R=round(fill - b["stop"], 4),
                                        be=False, last_close=arr(s, "c10") or fill, frac=b["frac"]))
            actions["fills"].append(dict(date=d, leg="lead", sym=s, side="買入", px=round(fill, 2), frac=b["frac"], when="盤中",
                                         reason=f"領導股：升穿前高 {b['trigger']:.2f}（buy-stop），排第 {b['rank']}，止蝕 {b['stop']:.2f}"))
        st["pending"] = {}
    for p in list(st["positions"]):                            # 3. 止蝕
        lo, o = arr(p["sym"], "l10"), arr(p["sym"], "o10")
        if lo is not None and lo <= p["stop"]:
            px = o if (o is not None and o <= p["stop"] and p["date"] != d) else p["stop"]
            close_pos(st, p, px, d, f"打止蝕 {p['stop']:.2f}", actions)
    for p in list(st["positions"]):                            # 4. 收市（冇價就數日子）
        c = arr(p["sym"], "c10")
        if c is not None:
            p["last_close"], p["miss"] = c, 0
        else:
            p["miss"] = p.get("miss", 0) + 1
            if p["miss"] >= R["delist_days"]:
                delisted(st, p, d, actions)
    cash_sleeve(st, sc, i)


def cash_sleeve(st, sc, i):
    """領導股現金：上一日收市綠燈 → 收短期國債息（^IRX ÷ 252，即 SGOV／BIL）；紅燈 → 跟 IEF 升跌。轉換嗰日扣 0.1%。"""
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
    old = st.get("sleeve")
    if st["cash"] > 0:
        if old and old != mode:
            st["cash"] -= st["cash"] * RULE["sleeve_cost"]
        st["cash"] *= 1 + r
    st["sleeve"], st["last_green"] = mode, g10[i]


def plan(st, sc, actions):
    """最新收市：更新止蝕、決定賣出、掛下一日 buy-stop。"""
    stocks, R = sc["stocks"], RULE
    rank = {r["sym"]: r["rank"] for r in sc["ranking"]}
    sells = []
    for p in st["positions"]:
        s = stocks.get(p["sym"])
        if not s or s.get("close") is None:
            actions["warn"].append(f"{p['sym']} 今日冇數據（已連續 {p.get('miss', 0)} 日）：連續 {R['delist_days']} 日冇數據就當退市，按最後收市價自動賣出")
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
            why.append(f"排名第 {rank[p['sym']]}（要頭 {int(lim)}）" if p["sym"] in rank else "跌出股票池頭 50")
        if why:
            sells.append(dict(sym=p["sym"], reason="、".join(why)))
    px = lambda p: stocks[p["sym"]]["close"] if p["sym"] in stocks else p["last_close"]
    if sc["week_end"]:                                       # 回撤剎車：星期五呢部分帳戶值
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
            sells.append(dict(sym=p["sym"], reason="回撤剎車減倉（呢部分由高位跌 25%，最多揸 2 隻）")); sold.add(p["sym"])
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


def delisted(st, p, d, actions):
    """持倉連續冇數據：AI（Google 搜尋）查咩事。收購 → 收購價；改代號 → 轉新代號；停牌 → 等（最多 20 日）；其他 → 最後收市價。"""
    if p.get("ai_checked") == d:
        return
    p["ai_checked"] = d
    r, src = _ai(f"美股代號 {p['sym']}（最後有價：{p['last_close']:.2f} 美元）由 {d} 前幾日開始冇交易數據。查下發生咩事："
                 '回覆 JSON：{"status": "acquired" 或 "renamed" 或 "halted" 或 "delisted" 或 "bankrupt" 或 "trading" 或 "unknown", '
                 '"cash_per_share": 收購現金價（每股美元，冇就 null）, "new_ticker": 新代號（改名先有，冇就 null）, "note": "一句中文講發生咩事"}')
    st_ = (r or {}).get("status")
    note = (r or {}).get("note", "")
    if st_ == "renamed" and r.get("new_ticker"):
        old, p["sym"], p["miss"] = p["sym"], str(r["new_ticker"]).upper().strip("$ "), 0
        actions["warn"].append(f"{old} 改咗代號做 {p['sym']}（{src}：{note}），模型已轉用新代號繼續揸")
        return
    if st_ in ("halted", "trading") and p["miss"] < 20:
        actions["warn"].append(f"{p['sym']} 連續 {p['miss']} 日冇數據，AI 查到係「{'停牌' if st_ == 'halted' else '仲有交易'}」（{src}：{note}），繼續揸住等；20 日都冇數據先會按最後收市價賣")
        return
    px, why = p["last_close"], f"連續 {p['miss']} 日冇數據"
    if st_ == "acquired" and r.get("cash_per_share"):
        try:
            px, why = float(r["cash_per_share"]), "被收購（現金收購價）"
        except (TypeError, ValueError):
            pass
    elif st_ in ("delisted", "bankrupt"):
        why = "退市" if st_ == "delisted" else "破產"
    close_pos(st, p, px, d, f"{why}，按 {px:.2f} 賣", actions)
    actions["warn"].append(f"{p['sym']}：{why}（{src if r else 'AI 查唔到：' + src}{'：' + note if note else ''}），模型已按 {px:.2f} 賣出；你實際戶口通常會由券商自動處理（收購會轉現金）")


def yahoo_splits(sym, days=45):
    """Yahoo 官方拆股紀錄：回傳 [(日期, 價錢倍數)]；2 拆 1 = 0.5（價錢減半），1 合 10 = 10。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range={'3mo' if days <= 80 else '5y'}&interval=1d&events=split"
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())
        ev = ((d["chart"]["result"][0].get("events") or {}).get("splits") or {}).values()
        cut = datetime.now(timezone.utc).timestamp() - days * 86400
        return [(datetime.fromtimestamp(e["date"], timezone.utc).date().isoformat(), e["denominator"] / e["numerator"])
                for e in ev if e.get("date", 0) >= cut and e.get("numerator")]
    except Exception as e:  # noqa: BLE001
        print(f"[lead] Yahoo 拆股紀錄攞唔到 {sym}：{e}")
        return []


def fix_splits(st, sc, i0, actions=None):
    """拆股／合股：Yahoo 會追溯調整舊價。新數據入面「上次處理嗰日」嘅收市，同存低嘅收市唔同 → 按比例換算持倉。"""
    if i0 < 1 or sc["days"][i0 - 1] != st["last"]:
        return
    for p in st["positions"]:
        c = (sc["stocks"].get(p["sym"]) or {}).get("c10", [None] * 10)[i0 - 1]
        if c and p["last_close"] and not p.get("miss") and abs(c / p["last_close"] - 1) > RULE["split_tol"]:
            k = c / p["last_close"]
            near = lambda f: abs(f / k - 1) < 0.05
            ok, src = any(near(f) for _, f in yahoo_splits(p["sym"])), "Yahoo 官方拆股紀錄"
            if not ok:
                r, src = _ai(f"美股 {p['sym']} 喺 {st['last']} 前後 30 日內有冇拆股或者合股（reverse split）？"
                             '回覆 JSON：{"split": true/false/"unknown", "ratio_new_per_old": 每 1 股舊股變幾多股新股（例如 2 拆 1 = 2，1 合 10 = 0.1）, "date": "YYYY-MM-DD", "note": "一句中文"}')
                if r and r.get("split") is True and r.get("ratio_new_per_old"):
                    ok = near(1 / float(r["ratio_new_per_old"]))
                    src = f"AI 查證 {src}：{r.get('note', '')}"
            msg = f"{p['sym']} 同一日收市由 {p['last_close']:.2f} 變 {c:.2f}（× {k:.4f}）"
            if not ok:
                print(f"[lead] {msg}：Yahoo 同 AI 都確認唔到係拆股，唔調整")
                if actions is not None:
                    actions["warn"].append(f"{msg}，但 Yahoo 同 AI 都確認唔到係拆股，模型冇調整持倉；可能係數據修正")
                continue
            print(f"[lead] {msg}：拆股／合股（{src}），換算持倉")
            if actions is not None:
                actions["warn"].append(f"{msg}：確認係拆股／合股（{src}），已自動換算股數、入場價同止蝕；你券商戶口會自動換算，止蝕單記得睇下")
            p["entry"], p["stop"], p["R"], p["last_close"] = p["entry"] * k, p["stop"] * k, p["R"] * k, c
            p["shares"] /= k


def rows(st, tot):
    """快照用持倉行（leg = 領導股，st = 止蝕）。"""
    return [dict(s=p["sym"], w=round(p["shares"] * p["last_close"] / tot, 4) if tot else 0, ret=round(p["last_close"] / p["entry"] - 1, 4),
                 e=round(p["entry"], 2), c=round(p["last_close"], 2), st=round(p["stop"], 2), leg="領導股") for p in st["positions"]]


def holdings(st, sc, tot):
    """app 持倉表：每隻股幾時賣。"""
    lim = int(RULE["rank_exit_brake"] if st["braking"] else RULE["rank_exit"])
    out = []
    for p in st["positions"]:
        c10 = (sc["stocks"].get(p["sym"]) or {}).get("c10") or []
        out.append(dict(sym=p["sym"], leg="領導股", legk="lead", date=p["date"], entry=round(p["entry"], 2), close=round(p["last_close"], 2),
                        ret=round(p["last_close"] / p["entry"] - 1, 4), stop=round(p["stop"], 2), be=p["be"],
                        weight=round(p["shares"] * p["last_close"] / tot, 4) if tot else 0,
                        day_chg=round(c10[-1] / c10[-2] - 1, 4) if len(c10) > 1 and c10[-1] and c10[-2] else None,
                        rule=f"盤中跌穿止蝕 {p['stop']:.2f} 即賣{'（已保本）' if p['be'] else ''}；收市跌穿 200 日線、星期五排名跌出頭 {lim}、大市紅燈 → 下一日開市賣"))
    return out


def todo(st, tot):
    """下一個交易日領導股要做（frac 按成個帳戶計）。"""
    pend = st.get("pending") or {}
    held = {p["sym"]: p for p in st["positions"]}
    lv = value(st)
    out = []
    for x in pend.get("sells", []):
        p = held.get(x["sym"])
        out.append(dict(when="開市", leg="lead", side="賣出", sym=x["sym"], frac=(p["shares"] * p["last_close"] / tot) if p and tot else None,
                        reason=f"領導股：{x['reason']}"))
    for b in pend.get("buys", []):
        out.append(dict(when="盤中（buy-stop）", leg="lead", side="買入", sym=b["sym"], frac=b["frac"] * lv / tot if tot else None,
                        trigger=round(b["trigger"], 2), stop=round(b["stop"], 2), rank=b["rank"],
                        reason=f"領導股：排第 {b['rank']}，升穿前高 {b['trigger']:.2f} 先買（掛 buy-stop），止蝕 {b['stop']:.2f}；"
                               f"每隻用領導股部分 {int(b['frac'] * 100)}%（現金唔夠就買少啲，排名高先）"))
    return out
