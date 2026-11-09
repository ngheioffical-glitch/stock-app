"""長歷史 K 線（2026-11-09 老師：「有冇可能可以將K線圖做到好似tradingview咁樣揀timeframe同埋放大縮小？同埋左右回放更遠的K線？」）。

app 嘅 K 線全螢幕（engine.html kv*）：日 K 用每份圖本身嘅日數據（大約兩年）；週 K、月 K 用呢度砌嘅長歷史（股票 2010 年起，加密有幾耐用幾耐），
咁先可以左右拖返去睇更遠。每支 K 線個日子 = 嗰個星期／月第一個交易日。週由星期一開始（同 app ckBars 一樣）。
BOS／MSS 喺 app 用同 structure.py 一樣嘅規則即場計（tests/test_kline_js.py 對過兩邊結果一樣）。只供參考。
"""
from __future__ import annotations

import math
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import structure

LONG_FROM = "2010-01-01"     # 股票長歷史由幾時開始（events.py）


def resample(d, o, h, l, c, per):
    """per = "W"（星期一開始）或者 "M"：返 dict(d, o, h, l, c)。唔啱嘅行（缺數、高 < 低）跳過。"""
    out = dict(d=[], o=[], h=[], l=[], c=[])
    key = None
    for a, b, e, f, g in zip(d, o, h, l, c):
        try:
            b, e, f, g = float(b), float(e), float(f), float(g)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (b, e, f, g)) or e < f or f <= 0:
            continue
        a = str(a)[:10]
        if per == "W":
            y, w, _ = date.fromisoformat(a).isocalendar()
            k = (y, w)
        else:
            k = a[:7]
        if k != key:
            key = k
            out["d"].append(a), out["o"].append(b), out["h"].append(e), out["l"].append(f), out["c"].append(g)
        else:
            out["h"][-1] = max(out["h"][-1], e)
            out["l"][-1] = min(out["l"][-1], f)
            out["c"][-1] = g
    for k in "ohlc":
        out[k] = [structure._r(x) for x in out[k]]
    return out


def long_bars(d, o, h, l, c):
    """週 K + 月 K（app 全螢幕 K 線用）；冇數據返 None。"""
    w, m = resample(d, o, h, l, c, "W"), resample(d, o, h, l, c, "M")
    if len(w["d"]) < 2:
        return None
    return dict(w=w, m=m, start=w["d"][0])


def coinbase_daily(sym, days, get, sleep=0.4):
    """Coinbase 日 K（{SYM}-USD）：[(日子, 開, 高, 低, 收)] 舊到新。get(u, timeout, tries) 返 JSON，404 返 None。
    幣未上市嗰段 Coinbase 返空 list：跳過繼續；成個產品冇（None）就返 []。今日未完嗰支唔要。每次最多 300 支。"""
    out, end = {}, datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    t = end - timedelta(days=days)
    while t < end:
        t2 = min(end, t + timedelta(days=299))
        u = (f"https://api.exchange.coinbase.com/products/{urllib.parse.quote(sym)}-USD/candles?granularity=86400"
             f"&start={t.strftime('%Y-%m-%dT%H:%M:%SZ')}&end={t2.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        try:
            rows = get(u, timeout=30, tries=2)
        except Exception as e:  # noqa: BLE001
            print(f"[bars] Coinbase {sym} 攞唔到：{str(e)[:80]}")
            return [(k, *out[k]) for k in sorted(out)]
        if rows is None:
            return []
        for ts, lo, hi, op, cl, _v in rows:
            dd = datetime.fromtimestamp(ts, timezone.utc).date()
            if dd < end.date():
                out[dd.isoformat()] = (float(op), float(hi), float(lo), float(cl))
        t = t2
        if sleep:
            time.sleep(sleep)
    return [(k, *out[k]) for k in sorted(out)]


def kline_block(k, keep_days=730, unit="日"):
    """加密（btc.py）：Coinbase 日 K → app 用嘅 dict(d,o,h,l,c 最近 keep_days 日, long 週月 K, ta BOS／MSS, tick)。"""
    if len(k) < 60:
        return None
    D, O, H, L, C = ([x[j] for x in k] for j in range(5))
    a = max(0, len(k) - keep_days)
    mid = sorted(C[a:])[len(C[a:]) // 2]
    tick = max(1e-12, mid * 1e-5)                         # 同 crypto_research.py 一樣（顯示嗰段收市中位數 × 0.00001）
    return dict(d=D[a:], o=[structure._r(x) for x in O[a:]], h=[structure._r(x) for x in H[a:]], l=[structure._r(x) for x in L[a:]],
                c=[structure._r(x) for x in C[a:]], long=long_bars(D, O, H, L, C), tick=tick,
                ta=structure.analyze(D[a:], O[a:], H[a:], L[a:], C[a:], tick=tick, unit=unit))
