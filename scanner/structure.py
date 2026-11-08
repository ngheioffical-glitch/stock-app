"""技術結構：突破（BOS／MSS）（2026-11-09 老師：「淨係想你睇下pine script裡面嘅突破，咩SMT Liquidity sweep無需要」
「我都想做到ai分析裡面有技術分析，有Bos」「有BOS，MSS呢啲分析，可以當做純粹influence咁樣」；
同日再講：「依家暫時先試下BOS／MSS 線先，其他唔好掂住」「ADR、距 52 週高、距 50 日線幾多個 ATR呢個可以Keep住先」
→ 圖同 AI 淨係 BOS／MSS 同呢三個數字；FVG 方格、CE、轉角線、EMA 暫時拎走（git 01693bf 有舊版）。

規則照老師 Pine（Trading/NQ_Modular_Clean_Execution_v2.8.3.md「MSS + BREAK-CANDLE FVG」），參數全部用 script 預設，唔調：
  轉角位：左右各 1 支（ta.pivothigh(high, 1, 1)）；新轉角位出現就取代舊嘅。
  突破：一支 K 線實體收穿當時最近嘅轉角位（好：開 ≤ 位 < 收；淡：開 ≥ 位 > 收），實體 ≥ 全長 60%，
        而且佢本身係同方向 3 支 FVG 嘅中間支（第 3 支低位 > 第 1 支高位，最少 1 tick）。
  BOS／MSS：Pine 全部叫 MSS（佢喺掃完流動性先睇）。呢度老師要分開：同上一次突破同方向 = BOS（延續），反方向 = MSS（轉向）。
  冇 SMT、冇掃流動性、冇每日重設（日線每支 K 線就係一日）。
只係參考（純粹 influence）：LAB_ANSON（Trading/stock-strategy/LAB_ANSON.md）測過日線版本，對 V2.7 領導股同 TQQQ 冇幫助；唔改任何交易規則。
"""
from __future__ import annotations

import math

BODY = 0.60          # Pine mssBodyPct 60
GAP_TICKS = 1        # Pine minGapTicks
KEEP = 120           # app 圖顯示最近幾多支日 K（大約半年）


def _r(x, nd=None):
    """nd = None：價錢用有效數字（加密幣可以係 0.00001），一般股票 = 2 位小數。"""
    if x is None or not math.isfinite(x):
        return None
    if nd is None:
        nd = 2 if abs(x) >= 1 or x == 0 else max(2, 3 - int(math.floor(math.log10(abs(x)))))
    return round(float(x), nd)


def _px(x):
    v = _r(x)
    return f"{v:.2f}" if abs(v) >= 1 else f"{v:g}"


def _pc(x, nd=1):
    return f"{x * 100:+.{nd}f}%"


def analyze(d, o, h, l, c, keep=KEEP, tick=0.01, unit="個交易日"):
    """d：日子字串；o h l c：每日開高低收（同一個調整口徑）。返 app 畫圖同 AI 用嘅結構；數據唔夠返 None。"""
    rows = [(str(a), float(b), float(e), float(f), float(g)) for a, b, e, f, g in zip(d, o, h, l, c)
            if all(math.isfinite(float(x)) for x in (b, e, f, g)) and float(e) >= float(f) > 0]
    n = len(rows)
    if n < 30:
        return None
    D = [x[0] for x in rows]
    O, H, L, C = ([x[k] for x in rows] for k in (1, 2, 3, 4))
    swh = swl = None                                   # (價, 第幾支)
    lvl = [None] * n                                   # 處理完第 i 支之後嘅 (轉角高, 轉角低)
    brk, last_dir = [], 0
    for i in range(n):
        k = i - 1                                      # 第 k 支係唔係轉角位，第 i 支收市先確認
        if k >= 1:
            if H[k] > H[k - 1] and H[k] >= H[i]:
                swh = (H[k], k)
            if L[k] < L[k - 1] and L[k] <= L[i]:
                swl = (L[k], k)
        lvl[i] = (swh, swl)
        if i < 2:
            continue
        m = i - 1                                      # 今支係 FVG 第 3 支，m 係中間支（收穿嗰支）
        rng = H[m] - L[m]
        bp = abs(C[m] - O[m]) / rng if rng > 0 else 0.0
        bull_fvg = L[i] > H[i - 2] and L[i] - H[i - 2] >= tick * GAP_TICKS - 1e-9
        bear_fvg = H[i] < L[i - 2] and L[i - 2] - H[i] >= tick * GAP_TICKS - 1e-9
        bh, bl = lvl[m]
        hit = 0
        if bull_fvg and bh and O[m] <= bh[0] < C[m] and C[m] > O[m] and bp >= BODY:
            hit, lv, s = 1, bh[0], bh[1]
        elif bear_fvg and bl and O[m] >= bl[0] > C[m] and C[m] < O[m] and bp >= BODY:
            hit, lv, s = -1, bl[0], bl[1]
        if hit:
            brk.append(dict(s=s, i=m, lv=lv, dir=hit, k="BOS" if hit == last_dir else "MSS" if last_dir else "BOS"))
            last_dir = hit
    # ───── app 圖：最近 keep 支
    a = max(0, n - keep)
    out_b = [dict(s=max(0, b["s"] - a), i=b["i"] - a, lv=_r(b["lv"]), dir=b["dir"], k=b["k"]) for b in brk if b["i"] >= a]
    # ───── 數字（同老師截圖右上角嗰類）：ADR%（20 日）、距 52 週高、距 50 日線幾多個 ATR（14 日）
    adr = sum(H[j] / L[j] - 1 for j in range(n - 20, n)) / 20 if n >= 20 else None
    hi52 = max(H[-252:])
    tr = [max(H[j] - L[j], abs(H[j] - C[j - 1]), abs(L[j] - C[j - 1])) for j in range(max(1, n - 14), n)]
    atr = sum(tr) / len(tr) if tr else None
    sma50 = sum(C[-50:]) / 50 if n >= 50 else None
    stat = dict(adr=_r(adr * 100 if adr is not None else None, 1), off52=_r(C[-1] / hi52 - 1, 4),
                atr50=_r((C[-1] - sma50) / atr if atr and sma50 else None, 1))
    ta = dict(v=2, last=D[-1], d=D[a:], o=[_r(x) for x in O[a:]], h=[_r(x) for x in H[a:]], l=[_r(x) for x in L[a:]],
              c=[_r(x) for x in C[a:]], brk=out_b, stat=stat)
    ta["facts"] = facts(D, brk, stat, unit)
    return ta


def facts(D, brk, stat, unit="個交易日"):
    """俾 AI 同 app 白話用嘅幾句（只係描述，唔係訊號）。"""
    n, L = len(D), []
    if brk:
        b = brk[-1]
        L.append(f"最近一次突破：{D[b['i']]} {'向上' if b['dir'] > 0 else '向下'} {b['k']}（{'延續之前方向' if b['k'] == 'BOS' else '同之前方向相反，結構轉向'}），"
                 f"實體收穿轉角位 {_px(b['lv'])}，距今 {n - 1 - b['i']} {unit}")
        if len(brk) > 1:
            p = brk[-2]
            L.append(f"再之前一次：{D[p['i']]} {'向上' if p['dir'] > 0 else '向下'} {p['k']}（收穿 {_px(p['lv'])}）")
        rec = [x for x in brk if x["i"] >= n - 60]
        up, dn = sum(1 for x in rec if x["dir"] > 0), sum(1 for x in rec if x["dir"] < 0)
        L.append(f"近 60 {unit}：向上突破 {up} 次、向下 {dn} 次")
    else:
        L.append("數據期內冇合規則嘅突破")
    if stat.get("adr") is not None:
        L.append(f"ADR（20 日平均日內波幅）{stat['adr']}%；距 52 週高 {_pc(stat['off52'])}"
                 + (f"；距 50 日線 {stat['atr50']} 個 ATR" if stat.get("atr50") is not None else ""))
    return L


def facts_line(ta):
    """一行俾 AI：寫明只係參考。"""
    if not ta:
        return ""
    return ("技術結構（程式按老師 Pine 突破規則計：轉角位左右各 1 支、實體 ≥60% 收穿、要係 FVG 中間支；同上次突破同方向 = BOS，反方向 = MSS。"
            "只係參考，回測冇證明有用，唔係 V2.7 規則）：" + "；".join(ta.get("facts") or []))
