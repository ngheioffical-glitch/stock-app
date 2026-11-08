"""技術結構：突破（BOS／MSS）、FVG、轉角位（2026-11-09 老師：「淨係想你睇下pine script裡面嘅突破，咩SMT Liquidity sweep無需要」
「做唔做到呢啲效果？」「我都想做到ai分析裡面有技術分析，有Bos」「有BOS，MSS呢啲分析，可以當做純粹influence咁樣」）。

規則照老師 Pine（Trading/NQ_Modular_Clean_Execution_v2.8.3.md「MSS + BREAK-CANDLE FVG」），參數全部用 script 預設，唔調：
  轉角位：左右各 1 支（ta.pivothigh(high, 1, 1)）；新轉角位出現就取代舊嘅。
  突破：一支 K 線實體收穿當時最近嘅轉角位（好：開 ≤ 位 < 收；淡：開 ≥ 位 > 收），實體 ≥ 全長 60%，
        而且佢本身係同方向 3 支 FVG 嘅中間支（第 3 支低位 > 第 1 支高位，最少 1 tick）。嗰個 FVG = 突破 FVG（Pine 叫 ENTRY FVG）。
  FVG：3 支 K 線缺口 ≥ 1 tick；之後影線入咗就縮細，穿晒（好：低位 ≤ 底；淡：高位 ≥ 頂）就刪；淨返少過 2 tick 都刪；
       CE = 原本 50%，縮咗超過一半就唔畫。
  BOS／MSS：Pine 全部叫 MSS（佢喺掃完流動性先睇）。呢度老師要分開：同上一次突破同方向 = BOS（延續），反方向 = MSS（轉向）。
  冇 SMT、冇掃流動性、冇每日重設（日線每支 K 線就係一日）。
只係參考（純粹 influence）：LAB_ANSON（Trading/stock-strategy/LAB_ANSON.md）測過日線版本，對 V2.7 領導股同 TQQQ 冇幫助；唔改任何交易規則。
"""
from __future__ import annotations

import math

BODY = 0.60          # Pine mssBodyPct 60
GAP_TICKS = 1        # Pine minGapTicks
REMAIN_TICKS = 2     # Pine minRemainTicks（deleteTinyZones）
KEEP = 120           # app 圖顯示最近幾多支日 K（大約半年）
MAX_ZONES = 35       # Pine maxZones
SHOW_ZONES = 6       # 手機圖最多畫幾多個未填 FVG（顯示用，唔影響計算）


def _ema(c, n):
    out, k, e = [], 2 / (n + 1), None
    for v in c:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def _r(x, nd=2):
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _pc(x, nd=1):
    return f"{x * 100:+.{nd}f}%"


def analyze(d, o, h, l, c, keep=KEEP, tick=0.01):
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
    brk, zones = [], []
    last_dir = 0
    for i in range(n):
        k = i - 1                                      # 第 k 支係唔係轉角位，第 i 支收市先確認
        if k >= 1:
            if H[k] > H[k - 1] and H[k] >= H[i]:
                swh = (H[k], k)
            if L[k] < L[k - 1] and L[k] <= L[i]:
                swl = (L[k], k)
        lvl[i] = (swh, swl)
        # 舊 FVG：影線入就縮，穿晒就刪（出世嗰支唔計）
        alive = []
        for z in zones:
            if z["dir"] > 0:
                if L[i] <= z["bot"]:
                    z["end"] = i
                    continue
                if L[i] < z["top"]:
                    z["top"] = L[i]
            else:
                if H[i] >= z["top"]:
                    z["end"] = i
                    continue
                if H[i] > z["bot"]:
                    z["bot"] = H[i]
            if z["top"] - z["bot"] < tick * REMAIN_TICKS - 1e-9:
                z["end"] = i
                continue
            alive.append(z)
        zones = alive
        if i < 2:
            continue
        m = i - 1
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
            brk.append(dict(s=s, i=m, lv=lv, dir=hit, k="BOS" if hit == last_dir else "MSS" if last_dir else "BOS", body=round(bp, 2)))
            last_dir = hit
        for dr, ok, top, bot in ((1, bull_fvg, L[i], H[i - 2]), (-1, bear_fvg, L[i - 2], H[i])):
            if ok:
                zones.append(dict(i=i - 2, born=i, dir=dr, top=top, bot=bot, ot=top, ob=bot, brk=hit == dr))
        if len(zones) > MAX_ZONES:
            zones = zones[-MAX_ZONES:]
    # ───── app 圖：最近 keep 支
    a = max(0, n - keep)
    e21 = _ema(C, 21)
    W = lambda i: i - a                                # noqa: E731
    out_b = [dict(s=max(0, W(b["s"])), i=W(b["i"]), lv=_r(b["lv"]), dir=b["dir"], k=b["k"]) for b in brk if b["i"] >= a]
    # 未填 FVG：日線積落好多（Pine 1 分鐘圖最多 35 個），手機圖只畫價錢喺圖範圍入面、最近現價嘅 SHOW_ZONES 個
    lo_w, hi_w, px = min(L[a:]), max(H[a:]), C[-1]
    inr = [z for z in zones if z["bot"] >= lo_w and z["top"] <= hi_w]
    inr = sorted(sorted(inr, key=lambda z: min(abs(z["top"] - px), abs(z["bot"] - px)))[:SHOW_ZONES], key=lambda z: z["i"])
    out_z = [dict(i=max(0, W(z["i"])), dir=z["dir"], top=_r(z["top"]), bot=_r(z["bot"]), ot=_r(z["ot"]), ob=_r(z["ob"]), brk=z["brk"],
                  ce=(z["top"] - z["bot"]) >= 0.5 * (z["ot"] - z["ob"])) for z in inr]
    swh, swl = lvl[-1]
    piv = dict(hi=[max(0, W(swh[1])), _r(swh[0])] if swh else None, lo=[max(0, W(swl[1])), _r(swl[0])] if swl else None)
    # ───── 數字（同截圖右上角嗰類）：ADR%（20 日）、距 52 週高、距 50 日線幾多個 ATR
    adr = sum(H[j] / L[j] - 1 for j in range(n - 20, n)) / 20 if n >= 20 else None
    hi52 = max(H[-252:])
    tr = [max(H[j] - L[j], abs(H[j] - C[j - 1]), abs(L[j] - C[j - 1])) for j in range(max(1, n - 14), n)]
    atr = sum(tr) / len(tr) if tr else None
    sma50 = sum(C[-50:]) / 50 if n >= 50 else None
    stat = dict(adr=_r(adr * 100 if adr is not None else None, 1), off52=_r(C[-1] / hi52 - 1, 4),
                atr50=_r((C[-1] - sma50) / atr if atr and sma50 else None, 1))
    ta = dict(v=1, last=D[-1], d=D[a:], o=[_r(x) for x in O[a:]], h=[_r(x) for x in H[a:]], l=[_r(x) for x in L[a:]], c=[_r(x) for x in C[a:]],
              e21=[_r(x) for x in e21[a:]], brk=out_b, fvg=out_z, nz=len(zones), piv=piv, stat=stat)
    ta["facts"] = facts(D, C, brk, zones, lvl[-1], stat, a)
    return ta


def facts(D, C, brk, zones, last_lvl, stat, a):
    """俾 AI 同 app 白話用嘅幾句（只係描述，唔係訊號）。"""
    n, px, L = len(C), C[-1], []
    if brk:
        b = brk[-1]
        L.append(f"最近一次突破：{D[b['i']]} {'向上' if b['dir'] > 0 else '向下'} {b['k']}（{'延續之前方向' if b['k'] == 'BOS' else '同之前方向相反，結構轉向'}），"
                 f"實體收穿轉角位 {b['lv']:.2f}，距今 {n - 1 - b['i']} 個交易日")
        rec = [x for x in brk if x["i"] >= n - 60]
        up, dn = sum(1 for x in rec if x["dir"] > 0), sum(1 for x in rec if x["dir"] < 0)
        L.append(f"近 60 個交易日：向上突破 {up} 次、向下 {dn} 次")
    else:
        L.append("數據期內冇合規則嘅突破")
    swh, swl = last_lvl
    if swh:
        L.append(f"上面最近轉角高 {swh[0]:.2f}（{D[swh[1]]}），距現價 {_pc(swh[0] / px - 1)}")
    if swl:
        L.append(f"下面最近轉角低 {swl[0]:.2f}（{D[swl[1]]}），距現價 {_pc(swl[0] / px - 1)}")
    near = sorted(zones, key=lambda z: min(abs(z["top"] - px), abs(z["bot"] - px)))[:3]
    for z in near:
        L.append(f"未填{'向上' if z['dir'] > 0 else '向下'}{'突破' if z['brk'] else ''} FVG {z['bot']:.2f}–{z['top']:.2f}"
                 f"（{D[z['i']]} 起；距現價 {_pc(((z['top'] + z['bot']) / 2) / px - 1)}）")
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
