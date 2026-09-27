"""新聞 + 經濟數據（2026-09-27 用戶要求：似 World Monitor 咁睇新聞，經濟數據要有預測、上次同最新值）。

全部用公開 RSS／API，唔使任何 key：
- 新聞：CNBC、MarketWatch、BBC、Al Jazeera、香港電台、聯儲局新聞稿；持倉／候選股用 Yahoo 個股新聞 RSS。
- 經濟數據：Nasdaq 經濟日曆（實際、預測、上次）；Nasdaq 攞唔到就用 ForexFactory（冇實際值）。

用法：python scanner/feeds.py [輸出資料夾]   → news.json、econ.json
GitHub Actions 每 30 分鐘跑一次，推去 feeds 分支（每次覆蓋，唔留歷史），app 由 raw.githubusercontent.com 讀。
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ET_TZ = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*"}

# 分類 -> [(來源名, RSS)]
FEEDS = {
    "市場": [("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
             ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
             ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_bulletins"),
             ("港台財經", "https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml")],
    "經濟": [("Investing.com", "https://www.investing.com/rss/news_14.rss"),
             ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
             ("聯儲局", "https://www.federalreserve.gov/feeds/press_all.xml"),
             ("聯儲局講話", "https://www.federalreserve.gov/feeds/speeches.xml")],
    "國際": [("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
             ("CNBC", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
             ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
             ("港台國際", "https://rthk.hk/rthk/news/rss/c_expressnews_cinternational.xml")],
    "科技": [("CNBC", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
             ("BBC", "https://feeds.bbci.co.uk/news/technology/rss.xml")],
}
YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={s}&region=US&lang=en-US"
NASDAQ_CAL = "https://api.nasdaq.com/api/calendar/economicevents?date={d}"
FF_CAL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# 重要數據（關鍵字 -> 中文名）；冇列出嘅照顯示英文，標做一般
KEY_EVENTS = [
    (r"gdpnow", "亞特蘭大聯儲 GDPNow", 1),
    (r"nonfarm payrolls|non-farm (employment|payrolls)", "非農就業", 3),
    (r"^unemployment rate", "失業率", 3),
    (r"average hourly earnings", "平均時薪", 2),
    (r"^core cpi|core consumer price", "核心 CPI", 3),
    (r"^cpi|consumer price index", "CPI 通脹", 3),
    (r"core pce", "核心 PCE", 3),
    (r"pce price", "PCE 物價", 2),
    (r"^core ppi", "核心 PPI", 2),
    (r"^ppi|producer price", "PPI 生產物價", 2),
    (r"fed interest rate decision|fomc (statement|rate)|federal funds", "聯儲局議息", 3),
    (r"fomc (meeting )?minutes", "聯儲局會議紀錄", 2),
    (r"fed chair|powell", "聯儲局主席講話", 2),
    (r"gdp", "GDP", 3),
    (r"^core retail sales", "核心零售銷售", 2),
    (r"^retail sales", "零售銷售", 3),
    (r"ism manufacturing pmi|ism manufacturing index", "ISM 製造業", 3),
    (r"ism (non-manufacturing|services)", "ISM 服務業", 3),
    (r"s&p global .*manufacturing pmi|manufacturing pmi", "製造業 PMI", 2),
    (r"services pmi", "服務業 PMI", 2),
    (r"jolts", "JOLTS 職位空缺", 2),
    (r"initial jobless claims", "首次申領失業救濟", 2),
    (r"continuing jobless claims", "持續申領失業救濟", 1),
    (r"adp", "ADP 就業", 2),
    (r"(cb|conference board) consumer confidence", "諮商會消費信心", 2),
    (r"michigan.*(sentiment|consumer)", "密歇根消費信心", 2),
    (r"michigan.*inflation expectations", "密歇根通脹預期", 2),
    (r"durable goods", "耐用品訂單", 2),
    (r"new home sales", "新屋銷售", 1),
    (r"existing home sales", "成屋銷售", 1),
    (r"housing starts", "新屋動工", 1),
    (r"building permits", "建築許可", 1),
    (r"industrial production", "工業生產", 1),
    (r"trade balance", "貿易差額", 1),
    (r"crude oil inventories|crude oil stock", "原油庫存", 1),
    (r"philadelphia fed|philly fed", "費城聯儲製造業", 1),
    (r"empire state|ny empire", "紐約製造業", 1),
    (r"(\d+)-year note auction|(\d+)-year bond auction", "國債拍賣", 1),
]
SKIP = re.compile(r"bill auction|redbook|balance sheet|reserve balances|4-week avg", re.I)


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


# ---------------------------------------------------------------- 新聞
def _text(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def _clean(s, n=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return (s[: n - 1] + "…") if n and len(s) > n else s


def rss(url, source, cat, sym=None):
    try:
        root = ET.fromstring(get(url))
    except Exception as e:
        print(f"[news] {source} {cat} 攞唔到：{e}")
        return []
    out = []
    for it in root.iter("item"):
        t = _clean(_text(it, "title"))
        if not t:
            continue
        ts = None
        for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date"):
            v = _text(it, tag)
            if v:
                try:
                    ts = parsedate_to_datetime(v)
                except Exception:
                    try:
                        ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    except Exception:
                        ts = None
                break
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone(timedelta(hours=8)) if "rthk" in url else timezone.utc)
        out.append({"t": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": t,
                    "link": _text(it, "link"), "src": source, "cat": cat,
                    "sum": _clean(_text(it, "description"), 220), **({"sym": sym} if sym else {})})
    return out


def stock_syms():
    """持倉由手機記錄，雲端唔知；用成個排名表（頭 50，持倉跌出頭 12 就要賣，所以一定喺入面）。"""
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(dict.fromkeys(r["sym"] for r in sc.get("ranking", [])))


def news(now):
    jobs = [(u, s, c, None) for c, lst in FEEDS.items() for s, u in lst]
    jobs += [(YAHOO.format(s=s), "Yahoo", "個股", s) for s in stock_syms()]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: rss(*j), jobs))
    cut = now - timedelta(hours=72)
    items, seen = [], set()
    for lst in res:
        for x in lst:
            k = (x["cat"], x.get("sym"), re.sub(r"\W", "", x["title"].lower())[:80])
            if k in seen or datetime.fromisoformat(x["t"].replace("Z", "+00:00")) < cut:
                continue
            seen.add(k)
            items.append(x)
    items.sort(key=lambda x: x["t"], reverse=True)
    keep, cnt = [], {}
    for x in items:                                  # 每類最多 60 條、每隻股最多 6 條
        k = x.get("sym") or x["cat"]
        lim = 6 if x.get("sym") else 60
        if cnt.get(k, 0) < lim:
            cnt[k] = cnt.get(k, 0) + 1
            keep.append(x)
    return keep


# ---------------------------------------------------------------- 經濟數據
def _v(s):
    s = html.unescape(str(s or "")).replace("\xa0", " ").strip()
    return s or None


def _label(name):
    for pat, zh, imp in KEY_EVENTS:
        if re.search(pat, name, re.I):
            return zh, imp
    return None, 0


def econ_nasdaq(today):
    """Nasdaq 日曆：date 參數返嘅係前一日嘅美國數據（2026-09 實測），時間係美東。"""
    rows = []
    for k in range(-4, 9):
        d = today + timedelta(days=k)
        try:
            data = json.loads(get(NASDAQ_CAL.format(d=(d + timedelta(days=1)).isoformat())))
        except Exception as e:
            print(f"[econ] Nasdaq {d} 攞唔到：{e}")
            if k == 0:
                raise
            continue
        for r in (data.get("data") or {}).get("rows") or []:
            if r.get("country") != "United States" or SKIP.search(r.get("eventName", "")):
                continue
            name = _clean(r.get("eventName"))
            if re.search(r"speaks|testifies", name, re.I) and not re.search(r"powell|fed chair", name, re.I):
                continue
            hm = str(r.get("gmt") or "")
            t = f"{d.isoformat()}T{hm}" if re.fullmatch(r"\d\d:\d\d", hm) else d.isoformat()
            zh, imp = _label(name)
            rows.append({"t": t, "name": name, "zh": zh, "imp": imp, "actual": _v(r.get("actual")),
                         "forecast": _v(r.get("consensus")), "previous": _v(r.get("previous"))})
    return rows, "Nasdaq"


def econ_ff():
    rows = []
    for r in json.loads(get(FF_CAL)):
        if r.get("country") != "USD" or SKIP.search(r.get("title", "")):
            continue
        ts = datetime.fromisoformat(r["date"]).astimezone(ET_TZ)
        zh, imp = _label(r["title"])
        imp = max(imp, {"High": 3, "Medium": 2, "Low": 1}.get(r.get("impact"), 0))
        rows.append({"t": ts.strftime("%Y-%m-%dT%H:%M"), "name": r["title"], "zh": zh, "imp": imp, "actual": None,
                     "forecast": _v(r.get("forecast")), "previous": _v(r.get("previous"))})
    return rows, "ForexFactory（冇實際值）"


def econ(now):
    today = now.astimezone(ET_TZ).date()
    try:
        rows, src = econ_nasdaq(today)
    except Exception:
        rows, src = econ_ff()
    rows.sort(key=lambda r: r["t"])
    return {"src": src, "tz": "美東時間", "rows": rows}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "feeds_out"
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    gen = now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    n = news(now)
    e = econ(now)
    (out / "news.json").write_text(json.dumps({"generated": gen, "items": n}, ensure_ascii=False), encoding="utf-8")
    (out / "econ.json").write_text(json.dumps({"generated": gen, **e}, ensure_ascii=False), encoding="utf-8")
    cats = {}
    for x in n:
        cats[x["cat"]] = cats.get(x["cat"], 0) + 1
    print(f"[feeds] 新聞 {len(n)} 條 {cats}；經濟數據 {len(e['rows'])} 項（{e['src']}）")


if __name__ == "__main__":
    main()
