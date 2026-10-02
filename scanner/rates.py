"""美債息（2026-10-02 用戶：想 app 睇到債息，例如 30 年長債息上升）。只係資訊，唔改 V2.3 規則。

來源：美國財政部官方每日孳息曲線（home.treasury.gov，收市後更新，今年 + 舊年）：3 個月、2 年、5 年、10 年、30 年；
盤中：Yahoo（^IRX、^FVX、^TNX、^TYX）最新價比財政部最後一日新就用嚟做「最新」（2 年冇可靠盤中來源，只用收市）。
輸出 <out>/rates.json：每年期最新孳息、當日／1 週／1 個月／1 年變動（基點）、52 週高低；息差（10 年 − 2 年、10 年 − 3 個月）；
alert = 10 年或者 30 年單日郁 ≥ 10 基點，或者創 52 週新高 → AI 今日重點要解釋（scanner/ai.py rates_alert）。
用法：python scanner/rates.py out
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
TSY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
       "?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
YQ = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m"
TEN = [("3 Mo", "3 個月", "^IRX"), ("2 Yr", "2 年", None), ("5 Yr", "5 年", "^FVX"), ("10 Yr", "10 年", "^TNX"), ("30 Yr", "30 年", "^TYX")]
BIG_BP = 10.0
ET, HK = ZoneInfo("America/New_York"), ZoneInfo("Asia/Hong_Kong")


def treasury():
    rows = {}
    y = date.today().year
    for yr in (y - 1, y):
        txt = urllib.request.urlopen(urllib.request.Request(TSY.format(y=yr), headers=UA), timeout=30).read().decode("utf-8-sig")
        for r in csv.DictReader(io.StringIO(txt)):
            d = datetime.strptime(r["Date"], "%m/%d/%Y").date()
            rows[d] = {k: float(r[k]) for k, _, _ in TEN if r.get(k)}
    return dict(sorted(rows.items()))


def live(sym):
    d = json.loads(urllib.request.urlopen(urllib.request.Request(YQ.format(s=urllib.request.quote(sym)), headers=UA), timeout=20).read())
    m = d["chart"]["result"][0]["meta"]
    return m.get("regularMarketPrice"), datetime.fromtimestamp(m.get("regularMarketTime", 0), timezone.utc)


def main(out):
    T = treasury()
    days = list(T)
    cut = days[-1].replace(year=days[-1].year - 1)
    errs, rows = [], []
    for k, nm, ys in TEN:
        hist = [(d, v[k]) for d, v in T.items() if k in v and d >= cut]
        if len(hist) < 30:
            errs.append(f"{nm}：財政部數據唔夠")
            continue
        vals = [v for _, v in hist]
        last_d, y, src = hist[-1][0], vals[-1], "財政部收市"
        base = vals
        if ys:
            try:
                px, t = live(ys)
                td = t.astimezone(ET).date()
                if px and td > last_d:
                    y, src, base = px, f"盤中 {t.astimezone(HK).strftime('%m-%d %H:%M')}", vals + [px]
            except Exception as e:  # noqa: BLE001
                errs.append(f"{nm} 盤中：{str(e)[:60]}")
        ch = lambda n: round((base[-1] - base[-1 - n]) * 100, 1) if len(base) > n else None
        rows.append(dict(name=nm, y=round(y, 3), d=ch(1), w=ch(5), m=ch(21), yr=round((base[-1] - base[0]) * 100, 1),
                         hi52=round(max(base), 3), lo52=round(min(base), 3), src=src, close_date=str(last_d)))
    by = {r["name"]: r for r in rows}
    curve = {}
    if "10 年" in by and "2 年" in by:
        curve["10y_2y"] = round((by["10 年"]["y"] - by["2 年"]["y"]) * 100, 1)
    if "10 年" in by and "3 個月" in by:
        curve["10y_3m"] = round((by["10 年"]["y"] - by["3 個月"]["y"]) * 100, 1)
    alert = []
    for nm in ("10 年", "30 年"):
        r = by.get(nm)
        if not r:
            continue
        if r["d"] is not None and abs(r["d"]) >= BIG_BP:
            alert.append(f"{nm}債息{'急升' if r['d'] > 0 else '急跌'} {abs(r['d']):.0f} 基點至 {r['y']:.2f}%")
        if r["y"] >= r["hi52"] - 0.005:
            alert.append(f"{nm}債息 {r['y']:.2f}% 創 52 週新高（一年前大約 {r['y'] - r['yr'] / 100:.2f}%）")
    if not rows:
        raise SystemExit(f"[rates] 全部攞唔到：{errs}")
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), rows=rows, curve=curve, alert=alert or None, errs=errs)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "rates.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[rates] {len(rows)} 個年期；alert：{alert or '冇'}；錯誤：{errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
