"""商品（2026-10-05 用戶：除咗債息，貴金屬同油價都會影響股市，加入 app 幫助分析）。只係資訊，唔改 V2.3 規則。

來源：Yahoo 期貨日線（1 年）同最新價：紐約原油 CL=F、布蘭特原油 BZ=F、黃金 GC=F、白銀 SI=F、銅 HG=F。
輸出 <out>/commod.json：每樣最新價、當日／1 週／1 個月／1 年升跌、52 週高低；銅金比率（銅 ÷ 金，經濟訊號，走勢通常似 10 年債息）同佢 3 個月變化；
alert = 油價單日 ±5% 或者 1 個月 ≥ +20%、金價／銀價創 52 週新高、銅單日 ±4% → AI 今日重點要解釋（scanner/ai.py commod_alert）。
用法：python scanner/commod.py out
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
HK = ZoneInfo("Asia/Hong_Kong")
ITEMS = [("CL=F", "紐約原油", "美元／桶"), ("BZ=F", "布蘭特原油", "美元／桶"), ("GC=F", "黃金", "美元／盎司"),
         ("SI=F", "白銀", "美元／盎司"), ("HG=F", "銅", "美元／磅")]


def chart(sym):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d", headers=UA), timeout=30).read())["chart"]["result"][0]
    closes = [c for c in d["indicators"]["quote"][0]["close"] if c is not None]
    live = d["meta"].get("regularMarketPrice")
    t = datetime.fromtimestamp(d["meta"].get("regularMarketTime", 0)).astimezone(HK).strftime("%m-%d %H:%M")
    if live and closes and abs(live / closes[-1] - 1) > 1e-9:
        closes = closes + [live] if d["meta"].get("regularMarketTime", 0) > d["timestamp"][-1] + 3600 else closes[:-1] + [live]
    return closes, t


def main(out):
    rows, errs, S = [], [], {}
    for sym, nm, unit in ITEMS:
        try:
            c, t = chart(sym)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{nm}：{str(e)[:60]}")
            continue
        if len(c) < 30:
            errs.append(f"{nm}：數據唔夠")
            continue
        S[sym] = c
        ch = lambda n: round(c[-1] / c[-1 - n] - 1, 4) if len(c) > n else None
        rows.append(dict(sym=sym, name=nm, unit=unit, px=round(c[-1], 3), d=ch(1), w=ch(5), m=ch(21), yr=round(c[-1] / c[0] - 1, 4),
                         hi52=round(max(c), 3), lo52=round(min(c), 3), at=t))
    by = {r["sym"]: r for r in rows}
    cg = None
    if "HG=F" in S and "GC=F" in S:
        n = min(len(S["HG=F"]), len(S["GC=F"]))
        ratio = [h / g * 1000 for h, g in zip(S["HG=F"][-n:], S["GC=F"][-n:])]
        cg = dict(now=round(ratio[-1], 3), m3=round(ratio[-1] / ratio[-64] - 1, 4) if n > 64 else None, yr=round(ratio[-1] / ratio[0] - 1, 4))
    alert = []
    for s in ("CL=F", "BZ=F"):
        r = by.get(s)
        if r and r["d"] is not None and abs(r["d"]) >= 0.05:
            alert.append(f"{r['name']}單日{'急升' if r['d'] > 0 else '急跌'} {abs(r['d']) * 100:.1f}% 至 {r['px']:.2f}")
        if r and r["m"] is not None and r["m"] >= 0.20:
            alert.append(f"{r['name']}一個月升 {r['m'] * 100:.0f}%（通脹同減息預期受壓）")
    for s in ("GC=F", "SI=F"):
        r = by.get(s)
        if r and r["px"] >= r["hi52"] * 0.998:
            alert.append(f"{r['name']} {r['px']:,.2f} 創 52 週新高（一年 {r['yr'] * 100:+.0f}%）")
    r = by.get("HG=F")
    if r and r["d"] is not None and abs(r["d"]) >= 0.04:
        alert.append(f"銅價單日{'急升' if r['d'] > 0 else '急跌'} {abs(r['d']) * 100:.1f}%（經濟預期變化）")
    if not rows:
        raise SystemExit(f"[commod] 全部攞唔到：{errs}")
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), rows=rows, cg=cg, alert=alert or None, errs=errs)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "commod.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[commod] {len(rows)} 樣；alert：{alert or '冇'}；錯誤：{errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
