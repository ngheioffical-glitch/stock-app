"""個股 2 倍做多 ETF 對照（2026-09-30 用戶要求：app 註明邊隻股有 2 倍 ETF，唔借錢加槓桿，買唔買用戶自己決定）。

來源：Nasdaq ETF 名單（api.nasdaq.com/api/screener/etf），由名稱抽出正股代號，例如
  「GraniteShares 2x Long NVDA Daily ETF」、「Direxion Daily AAPL Bull 2X ETF」、「Corgi ETF Trust I Corgi LITE 2x Daily ETF」。
淨係要做多（冇 Bear／Short／Inverse）、名稱有「2X」嘅；同一隻股按發行商排先後（大發行商流動性通常好啲）。
輸出 docs/lev2x.json：{"generated", "map": {"NVDA": ["NVDU", "NVDL", ...]}}。攞唔到就唔覆蓋舊檔。
用法：python scanner/lev2x.py
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "lev2x.json"
URL = "https://api.nasdaq.com/api/screener/etf?download=true"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "application/json"}
NAMES = {"APPLE": "AAPL", "ALPHABET": "GOOGL", "NVIDIA": "NVDA", "MICROSOFT": "MSFT", "TESLA": "TSLA", "SK HYNIX": "SKHY"}
ALIAS = {"BRKB": "BRK-B"}
ISSUER = ["Direxion", "GraniteShares", "T-Rex", "T-REX", "Defiance", "Leverage Shares", "Tradr", "KraneShares", "Corgi"]
PAT = [re.compile(r"2X Long ([A-Z][A-Z.\-]{0,5}|SK Hynix|Apple|Alphabet|NVIDIA|Microsoft|Tesla) Daily", re.I),
       re.compile(r"Daily ([A-Z]{1,5}) Bull 2X", re.I),
       re.compile(r"Corgi ([A-Z]{1,5}) 2x Daily", re.I),
       re.compile(r"Daily Target 2X Long ([A-Z]{1,5}) ETF", re.I)]


def underlying(name):
    if re.search(r"bear|short|inverse", name, re.I) or not re.search(r"2x", name, re.I):
        return None
    hits = []
    for p in PAT:
        for m in p.finditer(name):
            hits.append((m.start(), m.group(1)))
    if not hits:
        return None
    pos, tk = max(hits)
    tail = name[pos:]
    if re.search(r"2X Long\s*$|ETF\s+\S.*2X Long\s*$", name, re.I):     # 名稱截斷咗（兩隻 ETF 名黐埋）：唔要
        return None
    tk = NAMES.get(tk.upper(), tk.upper())
    if not re.fullmatch(r"[A-Z][A-Z\-]{0,5}", tk) or tk in ("SPY", "QQQ", "SPCX"):
        return None
    return ALIAS.get(tk, tk)


def rank(name):
    return next((i for i, s in enumerate(ISSUER) if s.lower() in name.lower()), len(ISSUER))


def main():
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read())
        data = d["data"]
        rows = data["data"]["rows"] if "data" in data else data["rows"]
    except Exception as e:  # noqa: BLE001
        print(f"[lev2x] 攞唔到 ETF 名單，唔覆蓋舊檔：{e}")
        return
    m = {}
    for r in rows:
        tk = underlying(r.get("companyName", ""))
        if tk:
            m.setdefault(tk, []).append((rank(r["companyName"]), r["symbol"]))
    out = {k: [s for _, s in sorted(v)] for k, v in sorted(m.items())}
    if len(out) < 50:
        print(f"[lev2x] 只搵到 {len(out)} 隻，唔覆蓋舊檔")
        return
    gen = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    OUT.write_text(json.dumps({"generated": gen, "map": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[lev2x] {len(out)} 隻股有 2 倍 ETF；例：NVDA {out.get('NVDA')}、AAPL {out.get('AAPL')}、LITE {out.get('LITE')}")


if __name__ == "__main__":
    main()
