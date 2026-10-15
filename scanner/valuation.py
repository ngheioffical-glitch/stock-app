"""估值資訊（2026-10-15 用戶：「每個個股同股市同指數都想加埋估值比我，順便話我知估值高定低」）。只係資訊，唔改 V2.7 買賣規則。

大市／指數：
  Nasdaq 100、S&P 500：worldperatio.com（用 QQQ／SPY 計嘅市盈率，有 1／5／10／20 年平均同標準差）。
    判斷用 10 年：高過平均 + 2 個標準差 = 好貴；+1 = 偏貴；平均 ± 1 = 正常；−1 = 偏平；−2 = 好平。
  S&P 500 市盈率長期歷史、Shiller CAPE（10 年經通脹調整盈利）：multpl.com 每月數據（1871 年起），計 1990 年後嘅百分位。
個股（排名頭 50 + 模型持倉；Yahoo）：預期市盈率（未來 12 個月盈利）、過去市盈率、PEG（市盈率 ÷ 盈利增長）、市銷率。
  判斷：有 PEG 用 PEG（< 1 偏平、1–2 合理、2–3 偏貴、≥ 3 好貴）；冇 PEG 就同 Nasdaq 100 市盈率比（< 0.7 倍偏平、0.7–1.3 倍同大市差唔多、
  1.3–2 倍偏貴、≥ 2 倍好貴）；冇盈利預測就話估唔到。周期股（記憶體、航運等）盈利高峰時市盈率會好低，唔一定係平。
輸出 docs/valuation.json；daily-scan.yml 每日跑（失敗唔影響其他）。
用法：python scanner/valuation.py
"""
from __future__ import annotations

import json
import re
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "valuation.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
ETF = {"TQQQ", "IEF", "TMF", "UGL", "SGOV", "BIL", "QQQ", "SPY", "QLD", "SQQQ"}


def get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "ignore")


def band(pe, mu, sd):
    if pe is None or mu is None or not sd:
        return None
    z = (pe - mu) / sd
    return "好貴" if z >= 2 else "偏貴" if z >= 1 else "好平" if z <= -2 else "偏平" if z <= -1 else "正常"


def worldpe(slug, name):
    """worldperatio.com：而家市盈率同 1／5／10／20 年平均、1 個標準差範圍。"""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", get(f"https://worldperatio.com/index/{slug}/"), flags=re.S)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    cur = re.search(r"P/E\) Ratio for [^.]*? is ([\d.]+)", t)
    out = dict(name=name, pe=float(cur.group(1)) if cur else None, avg={})
    for y in (1, 5, 10, 20):
        m = re.search(rf"{y}Y Average: ([\d.]+) · 1 Std Dev range: \[([\d.]+) , ([\d.]+)\]", t)
        if m:
            mu, lo, hi = map(float, m.groups())
            out["avg"][str(y)] = dict(mu=mu, lo=lo, hi=hi)
    a10 = out["avg"].get("10")
    out["label"] = band(out["pe"], a10["mu"], (a10["hi"] - a10["lo"]) / 2) if a10 else None
    return out


def multpl(path, name):
    """multpl.com 每月歷史：而家、1990 年後百分位同中位數、全期中位數。"""
    h = get(f"https://www.multpl.com/{path}/table/by-month")
    rows = re.findall(r"<td>([A-Za-z]{3} \d{1,2}, \d{4})</td>\s*<td>\s*(?:<abbr[^>]*>[^<]*</abbr>|&#x2002;)?\s*([\d.]+)\s*</td>", h)
    vals = [(d, float(v)) for d, v in rows]
    if len(vals) < 100:
        raise RuntimeError(f"{path} 歷史得 {len(vals)} 行")
    cur, v90 = vals[0][1], [v for d, v in vals if int(d[-4:]) >= 1990]
    pct = sum(x < cur for x in v90) / len(v90)
    return dict(name=name, value=cur, date=vals[0][0], pct1990=round(pct * 100), med1990=round(statistics.median(v90), 1),
                med_all=round(statistics.median(v for _, v in vals), 1), max1990=max(v90),
                label="歷史好高" if pct >= 0.9 else "偏高" if pct >= 0.7 else "歷史好低" if pct <= 0.1 else "偏低" if pct <= 0.3 else "中間")


def stock_label(fpe, peg, ndx_pe):
    if not fpe or fpe <= 0:
        return "冇盈利預測", "未有正數嘅預期盈利，睇唔到市盈率（可以睇市銷率）"
    if peg and peg > 0:
        lab = "偏平" if peg < 1 else "合理" if peg < 2 else "偏貴" if peg < 3 else "好貴"
        return lab, f"PEG {peg:.2f}（市盈率 ÷ 預期盈利增長；< 1 偏平、1–2 合理、2–3 偏貴、≥ 3 好貴）"
    if ndx_pe:
        r = fpe / ndx_pe
        lab = "偏平" if r < 0.7 else "同大市差唔多" if r < 1.3 else "偏貴" if r < 2 else "好貴"
        return lab, f"預期市盈率係 Nasdaq 100 嘅 {r:.1f} 倍（冇 PEG）"
    return "未有判斷", ""


def stocks(syms, ndx_pe):
    import yfinance as yf
    out, errs = {}, []
    for s in syms:
        for k in range(2):
            try:
                i = yf.Ticker(s).info
                fpe, tpe = i.get("forwardPE"), i.get("trailingPE")
                peg = i.get("trailingPegRatio") or i.get("pegRatio")
                lab, why = stock_label(fpe, peg, ndx_pe)
                r = lambda x, n=1: round(x, n) if isinstance(x, (int, float)) else None
                out[s] = dict(fpe=r(fpe), tpe=r(tpe), peg=r(peg, 2), ps=r(i.get("priceToSalesTrailing12Months")),
                              eg=r(i.get("earningsGrowth"), 3), rg=r(i.get("revenueGrowth"), 3), label=lab, why=why,
                              vs_ndx=r(fpe / ndx_pe, 2) if fpe and fpe > 0 and ndx_pe else None)
                break
            except Exception as e:  # noqa: BLE001
                if k:
                    errs.append(f"{s}：{str(e)[:60]}")
                time.sleep(3)
        time.sleep(0.4)
    return out, errs


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    errs, market = [], {}
    for key, fn in (("ndx", lambda: worldpe("nasdaq-100", "Nasdaq 100")), ("spx", lambda: worldpe("sp-500", "S&P 500")),
                    ("spx_hist", lambda: multpl("s-p-500-pe-ratio", "S&P 500 市盈率（長期）")), ("cape", lambda: multpl("shiller-pe", "Shiller CAPE"))):
        try:
            market[key] = fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{key}：{str(e)[:80]}")
            if (old.get("market") or {}).get(key):
                market[key] = dict(old["market"][key], stale=True)
    scan = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
    syms = [r["sym"] for r in scan.get("ranking", [])]
    try:
        held = [h["sym"] for h in json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8"))["view"]["holdings"]]
    except Exception:  # noqa: BLE001
        held = []
    syms = [s for s in dict.fromkeys(syms + held) if s not in ETF]
    st, e2 = stocks(syms, (market.get("ndx") or {}).get("pe"))
    errs += e2
    for s, v in (old.get("stocks") or {}).items():            # 今次攞唔到就沿用上一次
        if s in syms and s not in st:
            st[s] = dict(v, stale=True)
    res = dict(generated=datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"), market=market, stocks=st, errs=errs)
    OUT.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    m = market
    print(f"[valuation] Nasdaq 100 {(m.get('ndx') or {}).get('pe')}（{(m.get('ndx') or {}).get('label')}）、S&P 500 {(m.get('spx') or {}).get('pe')}"
          f"（{(m.get('spx') or {}).get('label')}）、CAPE {(m.get('cape') or {}).get('value')}（1990 後第 {(m.get('cape') or {}).get('pct1990')} 百分位）；"
          f"個股 {len(st)}／{len(syms)}；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main()
