"""大額轉帳（2026-10-05 用戶：追大戶工具清單，Whale Alert）。只係資訊，唔改 BTC 100 日線規則：通知只係線索，唔係買賣訊號。

來源：Whale Alert 官方 X 帳戶 @whale_alert（api.fxtwitter.com 搜尋，唔使 key），近 48 小時。
每條帖解析：數量、幣、美元、由邊度到邊度、連結。方向：
  入交易所（由非交易所轉入 #交易所）= 可能準備賣；出交易所 = 可能長揸；交易所之間；穩定幣印發／銷毀（Treasury）；其他（錢包之間、DeFi）。
24 小時每隻幣：入交易所、出交易所、淨流入（美元）。穩定幣淨流入交易所 = 有新錢準備買；BTC／ETH 淨流入 = 可能有賣壓。
輸出 <out>/walert.json。用法：python scanner/walert.py out
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
HK = ZoneInfo("Asia/Hong_Kong")
EXCH = {"binance", "coinbase", "coinbaseinstitutional", "kraken", "okx", "okex", "bybit", "bitfinex", "bitstamp", "gemini", "htx", "huobi", "kucoin",
        "gate", "gateio", "bitget", "upbit", "robinhood", "cryptocom", "mexc", "deribit", "bithumb", "bitmex", "poloniex", "bitflyer", "bitso",
        "luno", "coincheck", "binanceus", "hyperliquid", "falconx", "cumberland", "wintermute", "bitvavo", "whitebit", "lbank", "bingx"}
STABLE = {"USDT", "USDC", "DAI", "FDUSD", "PYUSD", "USDE", "USD1", "RLUSD", "EURC", "TUSD"}
PAT = re.compile(r"([\d,\.]+)\s+\$?#?([A-Z0-9]{2,10})\s+\(([\d,\.]+)\s+USD\)\s+(transferred|minted|burned)\s*(?:from\s+(.+?))?\s*(?:to\s+(.+?))?(?:\s+https?://\S+|$)", re.S)


def side(name):
    """'#Coinbase' → ('Coinbase', True)；'unknown wallet' → ('未知錢包', False)"""
    if not name:
        return "", False
    n = name.strip().rstrip(".")
    tag = n.startswith("#")
    clean = n.lstrip("#").strip()
    key = re.sub(r"[^a-z]", "", clean.lower())
    is_ex = tag and (key in EXCH or any(key.startswith(e) for e in EXCH))
    zh = {"unknown wallet": "未知錢包", "unknown new wallet": "未知新錢包"}.get(clean.lower(), clean)
    return zh, is_ex


def parse(t):
    txt = (t.get("text") or "").replace("\n", " ")
    m = PAT.search(txt)
    if not m:
        return None
    amt, sym, usd, verb, frm, to = m.groups()
    usd = float(usd.replace(",", ""))
    link = re.search(r"https?://whale-alert\.io/\S+", txt)
    if verb in ("minted", "burned"):
        place = re.search(r"(?:at|from)\s+(.+?)(?:\s+https?://|$)", txt[m.start(4):])
        kind = "印發" if verb == "minted" else "銷毀"
        return dict(sym=sym, amt=amt, usd=usd, kind=kind, frm="", to=(place.group(1).strip() if place else ""), link=link.group(0) if link else None)
    f, fx = side(frm)
    g, gx = side(to)
    kind = "入交易所" if gx and not fx else "出交易所" if fx and not gx else "交易所之間" if fx and gx else "其他"
    return dict(sym=sym, amt=amt, usd=usd, kind=kind, frm=f, to=g, link=link.group(0) if link else None)


def main(out):
    now = datetime.now(timezone.utc)
    try:                                       # ai.py 定時寫嘅 AI 分析：沿用
        old_ai = json.loads((Path(out) / "walert.json").read_text(encoding="utf-8")).get("ai")
    except Exception:  # noqa: BLE001
        old_ai = None
    items, errs = [], []
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.fxtwitter.com/2/search?" + urllib.parse.urlencode({"q": "from:whale_alert", "feed": "latest", "count": "40"}), headers=UA), timeout=30).read())
        for t in d.get("results") or []:
            ts = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y")
            if now - ts > timedelta(hours=48):
                continue
            p = parse(t)
            if p:
                p.update(ts=int(ts.timestamp()), url=f"https://x.com/whale_alert/status/{t.get('id')}")
                items.append(p)
    except Exception as e:  # noqa: BLE001
        errs.append(f"Whale Alert：{str(e)[:80]}")
    if not items and errs:
        raise SystemExit(f"[walert] 攞唔到：{errs}")
    items.sort(key=lambda x: -x["ts"])
    net = {}
    for x in items:
        if now.timestamp() - x["ts"] > 86400:
            continue
        g = "穩定幣" if x["sym"] in STABLE else x["sym"]
        n = net.setdefault(g, {"in": 0.0, "out": 0.0, "mint": 0.0, "n": 0})
        n["n"] += 1
        if x["kind"] == "入交易所":
            n["in"] += x["usd"]
        elif x["kind"] == "出交易所":
            n["out"] += x["usd"]
        elif x["kind"] == "印發":
            n["mint"] += x["usd"]
        elif x["kind"] == "銷毀":
            n["mint"] -= x["usd"]
    for n in net.values():
        n["net"] = n["in"] - n["out"]
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), items=items[:40], net24=net, errs=errs, ai=old_ai)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "walert.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[walert] {len(items)} 條（48 小時）；24 小時：" + "、".join(f"{k} 淨 {v['net'] / 1e6:+.0f}M" for k, v in net.items()))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
