"""盤中 K 線：1 小時、4 小時（2026-11-09 老師：「K線冇4小時或者一小時嗎？」「K線要繼續更新，唔好淨係停留下載數據」）。[quant-data]

app K 線全螢幕（engine.html kv*）嘅「1H」「4H」同即時更新用：
  - 股票（大市 ^NDX + 事件線嗰批股，docs/events/index.json）：Yahoo 60 分鐘 K（yfinance），跟盤中掃描（intraday.yml）
    開市時間每個鐘一次（老師 10-24：「淨係新聞密就得」，所以唔再密過每個鐘），推去 live 分支 kline/<KEY>.json。
  - 加密（BTC、ETH、加密研究）：唔經呢度，app 直接攞 Coinbase（佢准網頁直接讀），每分鐘更新。
輸出 kline/<KEY>.json：{key, sym, at, tz: "America/New_York", h1: {t, o, h, l, c}, h4: {...}}；t = 紐約時間 "YYYY-MM-DD HH:MM"。
  h1 留最近 H1_DAYS 個交易日；h4 = 每日兩支（09:30–13:30、13:30–16:00，同 TradingView 美股 4 小時一樣），留 H4_DAYS 個交易日。
  每次淨係攞最近 5 日 60 分鐘 K 駁落上一份（live 分支）；冇上一份、上一份太舊或者對唔上（例如拆股）就攞返 730 日。
app 用 h1 砌「今日」嘅日 K，日 K／週 K／月 K 開市期間都會更新。只係顯示，唔改任何交易規則。

用法：python scanner/kline_live.py 輸出資料夾 [上一份 kline 資料夾]
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
H1_DAYS = 120
H4_DAYS = 500
MKT, MKT_KEY = "^NDX", "MARKET"


def keys():
    try:
        idx = json.loads((ROOT / "docs" / "events" / "index.json").read_text(encoding="utf-8"))
        ks = list((idx.get("items") or {}).keys())
    except Exception:  # noqa: BLE001
        ks = []
    return [MKT_KEY] + [k for k in ks if k != MKT_KEY]


def _r(x):
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), 2 if abs(x) >= 1 else 6)


def rows_of(df):
    """yfinance 60 分鐘 K（一隻）→ {"YYYY-MM-DD HH:MM"（紐約）: (o, h, l, c)}；淨係正常交易時段。"""
    out = {}
    if df is None or not len(df):
        return out
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    idx = df.index
    idx = idx.tz_convert(NY) if idx.tz is not None else idx.tz_localize("UTC").tz_convert(NY)
    for t, (o, h, lo, c) in zip(idx, df[["Open", "High", "Low", "Close"]].itertuples(index=False, name=None)):
        hm = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= hm < 16 * 60 and h >= lo > 0:
            out[t.strftime("%Y-%m-%d %H:%M")] = (_r(o), _r(h), _r(lo), _r(c))
    return out


def h4_of(h1):
    """1 小時 → 4 小時：每日 09:30（09:30–13:29 嗰 4 支）同 13:30（13:30–16:00 嗰 3 支）。"""
    out = {}
    for t in sorted(h1):
        o, h, lo, c = h1[t]
        k = t[:11] + ("09:30" if t[11:] < "13:30" else "13:30")
        if k not in out:
            out[k] = [o, h, lo, c]
        else:
            b = out[k]
            b[1], b[2], b[3] = max(b[1], h), min(b[2], lo), c
    return {k: tuple(v) for k, v in out.items()}


def trim(bars, days):
    ds = sorted({t[:10] for t in bars})[-days:]
    keep = set(ds)
    return {t: v for t, v in bars.items() if t[:10] in keep}


def pack(bars):
    ts = sorted(bars)
    return dict(t=ts, o=[bars[t][0] for t in ts], h=[bars[t][1] for t in ts], l=[bars[t][2] for t in ts], c=[bars[t][3] for t in ts])


def unpack(p):
    try:
        return {t: (o, h, lo, c) for t, o, h, lo, c in zip(p["t"], p["o"], p["h"], p["l"], p["c"])}
    except Exception:  # noqa: BLE001
        return {}


def merge(prev, new, days):
    """駁埋：新嘅蓋舊嘅。重疊嗰段收市差超過 2%（例如拆股）就當上一份唔啱，返 None（要攞返長歷史）。"""
    for t in set(prev) & set(new):
        a, b = prev[t][3], new[t][3]
        if a and b and abs(b / a - 1) > 0.02:
            return None
    m = dict(prev)
    m.update(new)
    return trim(m, days)


def download(tickers, period):
    import yfinance as yf
    if not tickers:
        return {}
    raw = yf.download(tickers, period=period, interval="60m", group_by="ticker", auto_adjust=True, prepost=False,
                      threads=True, progress=False)
    out = {}
    for s in tickers:
        try:
            out[s] = rows_of(raw[s] if len(tickers) > 1 or s in raw.columns.get_level_values(0) else raw)
        except Exception as e:  # noqa: BLE001
            print(f"[kline] {s} 讀唔到：{str(e)[:80]}")
            out[s] = {}
    return out


def main(out, prev_dir=None):
    out = Path(out) / "kline"
    out.mkdir(parents=True, exist_ok=True)
    prev_dir = Path(prev_dir) if prev_dir else None
    ks = keys()
    sym = {k: MKT if k == MKT_KEY else k for k in ks}
    prev = {}
    for k in ks:
        try:
            prev[k] = json.loads((prev_dir / f"{k}.json").read_text(encoding="utf-8")) if prev_dir else None
        except Exception:  # noqa: BLE001
            prev[k] = None
    now = datetime.now(timezone.utc)

    def fresh(p):
        try:
            return p and p.get("h1", {}).get("t") and (now - datetime.fromisoformat(p["at"])).days < 5
        except Exception:  # noqa: BLE001
            return False

    inc = [k for k in ks if fresh(prev[k])]
    full = [k for k in ks if k not in inc]
    got = download([sym[k] for k in inc], "5d")
    res, redo = {}, []
    for k in inc:
        new1 = got.get(sym[k]) or {}
        h1 = merge(unpack(prev[k]["h1"]), new1, H1_DAYS)
        h4p = unpack(prev[k].get("h4") or {})
        h4 = merge(h4p, {t: v for t, v in h4_of(new1).items()}, H4_DAYS) if h1 is not None else None
        if h1 is None or h4 is None:
            redo.append(k)
            continue
        res[k] = (h1, h4)
    full += redo
    if full:
        got = download([sym[k] for k in full], "730d")
        for k in full:
            b = got.get(sym[k]) or {}
            if b:
                res[k] = (trim(b, H1_DAYS), trim(h4_of(b), H4_DAYS))
    at = now.isoformat(timespec="seconds")
    n = 0
    for k, (h1, h4) in res.items():
        if not h1:
            continue
        (out / f"{k}.json").write_text(json.dumps(dict(key=k, sym=sym[k], at=at, tz="America/New_York", h1=pack(h1), h4=pack(h4)),
                                                  separators=(",", ":")), encoding="utf-8")
        n += 1
    # 攞唔到嘅沿用上一份（app 照有舊嘅 1H／4H）
    for k in ks:
        if k not in res and prev.get(k):
            (out / f"{k}.json").write_text(json.dumps(prev[k], separators=(",", ":")), encoding="utf-8")
    print(f"[kline] {n} 條更新（駁上一份 {len(inc) - len(redo)}、攞返長歷史 {len(full)}），{len(ks)} 條線；{at}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
