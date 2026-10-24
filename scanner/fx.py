"""外匯（2026-10-25 老師：「外匯要加…分析呢啲因素對股市影響幾大」；/codex 兩邊同意：只係資訊，唔改 V2.7 規則）。

來源：Yahoo 日線（1 年）同最新價：美元指數 DX-Y.NYB、美元兌日圓 JPY=X、歐元兌美元 EURUSD=X、美元兌人民幣（在岸）CNY=X、美元兌瑞郎 CHF=X；
      ^NDX 只用嚟計相關。
輸出 <out>/fx.json：每樣最新價、今日／1 週／1 個月／1 年升跌、52 週高低同位置、近 1 年每星期同納指 100 嘅相關系數（會變，唔係規則）；
alert（門檻同研究 stock-strategy/LAB_FX.md 同一條公式）：美元兌日圓 5 個交易日跌 ≥ 3%（日圓急升）、美元指數 20 個交易日升或跌 ≥ 3%；
haven = 過去 5 日避險跡象：黃金升、日圓升、瑞郎升、10 年債息跌（債價升）有幾多樣同時發生，而納指跌 → 「可能反映避險需求」
      （讀同一次 workflow 嘅 out/commod.json、out/rates.json；價格同步唔等於資金流向，只寫「可能」）。
AI 分析同商品合併（scanner/ai.py commod_ai，寫入 commod.json 嘅 ai）。跟 feeds 全部更新排程（唔係新聞，唔密）。
用法：python scanner/fx.py out
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
HK = ZoneInfo("Asia/Hong_Kong")
ITEMS = [("DX-Y.NYB", "美元指數", 2), ("JPY=X", "美元兌日圓", 2), ("EURUSD=X", "歐元兌美元", 4), ("CNY=X", "美元兌人民幣", 4),
         ("CHF=X", "美元兌瑞郎", 4)]     # 人民幣用在岸 CNY=X：Yahoo 離岸 CNH=X 冇歷史數據（2026-10-25 試過得 1 日）；同研究一樣
JPY_5D, DXY_20D = -0.03, 0.03          # 同研究一樣：USDJPY 5 日變化 ≤ −3%；美元指數 20 日變化 ≥ +3% 或 ≤ −3%


def chart(sym):
    """[(日期, 收市)]（最新價補落最後）同報價時間。"""
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d", headers=UA), timeout=30).read())["chart"]["result"][0]
    pts = [(datetime.fromtimestamp(t, timezone.utc).date(), c) for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"]) if c is not None]
    live, lt = d["meta"].get("regularMarketPrice"), d["meta"].get("regularMarketTime", 0)
    if live and pts:
        day = datetime.fromtimestamp(lt, timezone.utc).date()
        pts = pts[:-1] + [(day, live)] if day == pts[-1][0] else pts + [(day, live)]
    return pts, datetime.fromtimestamp(lt, timezone.utc).astimezone(HK).strftime("%m-%d %H:%M")


def weekly(pts):
    """每星期最後一個收市：{(ISO 年, 週): 價}。"""
    w = {}
    for day, c in pts:
        y, k, _ = day.isocalendar()
        w[(y, k)] = c
    return w


def corr(a, b):
    n = len(a)
    if n < 20:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if not va or not vb:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5, 2)


def corr_ndx(pts, ndx, weeks=52):
    """近 1 年每星期回報同納指 100 嘅相關系數（星期對齊；外匯同美股收市時間唔同，每星期錯位細啲）。"""
    a, b = weekly(pts), weekly(ndx)
    ks = sorted(set(a) & set(b))[-(weeks + 1):]
    ra = [a[k] / a[j] - 1 for j, k in zip(ks, ks[1:])]
    rb = [b[k] / b[j] - 1 for j, k in zip(ks, ks[1:])]
    return corr(ra, rb)


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def haven(by, ndx5, out):
    """過去 5 日避險跡象。返 dict（signs = 每樣升唔升；hit = 納指跌而且 ≥ 3 樣同時發生）。"""
    C = {r["sym"]: r for r in _load(Path(out) / "commod.json").get("rows", [])}
    R = {r["name"]: r for r in _load(Path(out) / "rates.json").get("rows", [])}
    g, y10 = C.get("GC=F", {}).get("w"), R.get("10 年", {}).get("w")
    jp, ch = (by.get("JPY=X") or {}).get("w"), (by.get("CHF=X") or {}).get("w")
    signs = {"黃金升": None if g is None else g > 0, "日圓升": None if jp is None else jp < 0,
             "瑞郎升": None if ch is None else ch < 0, "美債價升（10 年債息跌）": None if y10 is None else y10 < 0}
    n = sum(1 for v in signs.values() if v)
    hit = ndx5 is not None and ndx5 < 0 and n >= 3
    text = (f"過去 5 日{'、'.join(k for k, v in signs.items() if v)}，納指 {ndx5 * 100:+.1f}%：可能反映避險需求（價格同步唔等於資金流向，要睇新聞）"
            if hit else "")
    return dict(signs=signs, n=n, ndx5=None if ndx5 is None else round(ndx5, 4), hit=hit, text=text)


def main(out):
    rows, errs, alert = [], [], []
    try:
        ndx, _ = chart("^NDX")
    except Exception as e:  # noqa: BLE001
        ndx = []
        errs.append(f"納指（計相關用）：{str(e)[:60]}")
    for sym, nm, dp in ITEMS:
        try:
            pts, t = chart(sym)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{nm}：{str(e)[:60]}")
            continue
        c = [x for _, x in pts]
        if len(c) < 30:
            errs.append(f"{nm}：數據唔夠")
            continue
        ch = lambda n: round(c[-1] / c[-1 - n] - 1, 4) if len(c) > n else None
        hi, lo = max(c), min(c)
        rows.append(dict(sym=sym, name=nm, dp=dp, px=round(c[-1], dp + 2), d=ch(1), w=ch(5), m=ch(21), m20=ch(20), yr=round(c[-1] / c[0] - 1, 4),
                         hi52=round(hi, dp + 2), lo52=round(lo, dp + 2), pos52=round((c[-1] - lo) / (hi - lo), 2) if hi > lo else None,
                         corr=corr_ndx(pts, ndx) if ndx else None, at=t))
    by = {r["sym"]: r for r in rows}
    j = by.get("JPY=X")
    if j and j["w"] is not None and j["w"] <= JPY_5D:
        alert.append(f"日圓 5 日急升（美元兌日圓 5 日 {j['w'] * 100:+.1f}% 至 {j['px']:.2f}）：可能有借日圓嘅套利交易平倉，股市波動可能加大（要睇新聞先確定原因）")
    x = by.get("DX-Y.NYB")
    if x and x["m20"] is not None and abs(x["m20"]) >= DXY_20D:
        alert.append(f"美元指數 20 日{'急升' if x['m20'] > 0 else '急跌'} {abs(x['m20']) * 100:.1f}% 至 {x['px']:.2f}")
    nc = [x for _, x in ndx]
    ndx5 = round(nc[-1] / nc[-6] - 1, 4) if len(nc) > 5 else None
    hv = haven(by, ndx5, out)
    if not rows:
        raise SystemExit(f"[fx] 全部攞唔到：{errs}")
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), rows=rows, alert=alert or None, haven=hv, errs=errs)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "fx.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[fx] {len(rows)} 樣；alert：{alert or '冇'}；避險跡象 {hv['n']}／4{'（可能避險）' if hv['hit'] else ''}；錯誤：{errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
