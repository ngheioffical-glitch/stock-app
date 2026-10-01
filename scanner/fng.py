"""恐慌貪婪指數（2026-10-01）：股市 = CNN Fear & Greed；加密 = alternative.me。輸出 out/fng.json（feeds 分支）。
CNN 要瀏覽器 User-Agent，否則 418。任何一邊出錯就沿用上一份（feeds.yml 會先下載舊 fng.json）。
用法：python scanner/fng.py out
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json", "Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}
RATING = {"extreme fear": "極度恐慌", "fear": "恐慌", "neutral": "中性", "greed": "貪婪", "extreme greed": "極度貪婪"}
PARTS = {"market_momentum_sp500": "S&P 500 對 125 日線（動能）", "stock_price_strength": "52 週新高 vs 新低",
         "stock_price_breadth": "升跌成交量（市寬）", "put_call_options": "Put／Call 比率",
         "market_volatility_vix": "VIX 波幅", "junk_bond_demand": "垃圾債需求", "safe_haven_demand": "股票 vs 國債（避險）"}


def get(url, headers=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers or {"User-Agent": "signals-app"}), timeout=30).read())


def rating(v):
    return "極度恐慌" if v < 25 else "恐慌" if v < 45 else "中性" if v <= 55 else "貪婪" if v <= 75 else "極度貪婪"


def stock():
    since = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    j = get(f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{since}", UA)
    f = j["fear_and_greed"]
    hist = [[dt.datetime.fromtimestamp(r["x"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d"), round(r["y"], 1)]
            for r in j["fear_and_greed_historical"]["data"]]
    parts = [{"name": n, "score": round(j[k]["score"], 1), "rating": RATING.get(j[k]["rating"], j[k]["rating"])}
             for k, n in PARTS.items() if isinstance(j.get(k), dict) and j[k].get("score") is not None]
    return {"score": round(f["score"], 1), "rating": RATING.get(f["rating"], rating(f["score"])), "at": f["timestamp"],
            "prev": round(f["previous_close"], 1), "week": round(f["previous_1_week"], 1), "month": round(f["previous_1_month"], 1),
            "year": round(f["previous_1_year"], 1), "parts": parts, "hist": hist[-260:], "src": "CNN Fear & Greed"}


def crypto():
    d = get("https://api.alternative.me/fng/?limit=370")["data"]
    v = [(dt.datetime.fromtimestamp(int(r["timestamp"]), dt.timezone.utc).strftime("%Y-%m-%d"), int(r["value"])) for r in d]
    v.sort()
    val = v[-1][1]
    pick = lambda n: v[-1 - n][1] if len(v) > n else None
    return {"score": val, "rating": rating(val), "at": v[-1][0], "prev": pick(1), "week": pick(7), "month": pick(30), "year": pick(365),
            "hist": [list(x) for x in v[-365:]], "src": "alternative.me Crypto Fear & Greed"}


def main(out):
    p = Path(out, "fng.json")
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    o = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "err": {}}
    for k, fn in (("stock", stock), ("crypto", crypto)):
        try:
            o[k] = fn()
        except Exception as e:
            o["err"][k] = f"{type(e).__name__}: {e}"[:200]
            if prev.get(k):
                o[k] = prev[k]
    p.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({k: (o.get(k) or {}).get("score") for k in ("stock", "crypto")}, o["err"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
