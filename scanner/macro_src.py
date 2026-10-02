"""宏觀思考嘅外部來源（2026-10-02 用戶：配合知名人士 X 發文、Polymarket 等，睇真實宏觀市場）。只係資訊。

1. X 知名宏觀人士最新原創帖（api.fxtwitter.com 搜尋 from:帳戶，唔使 key；同 Serenity 一樣）：最近 36 小時、唔要回覆、> 60 字。
   每 30 分鐘先抓一次（其餘時間沿用上一份）。帳戶清單喺 ACCOUNTS，可以自己加減。
2. Polymarket 預測市場（gamma-api.polymarket.com，公開）：按 24 小時成交額排，揀同宏觀有關嘅（聯儲局、通脹、衰退、股市、債息、關稅、選舉、地緣、加密）頭 15 個，
   顯示「是」嘅概率同 24 小時變化。每次都抓。
輸出 <out>/macro_src.json：{generated, x_checked, x: [...], pm: [...], errs}；scanner/ai.py think() 用。
用法：python scanner/macro_src.py out
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
ACCOUNTS = [("NickTimiraos", "Nick Timiraos（WSJ 聯儲局記者）"), ("elerianm", "Mohamed El-Erian"), ("LizAnnSonders", "Liz Ann Sonders（Schwab）"),
            ("biancoresearch", "Jim Bianco"), ("DiMartinoBooth", "Danielle DiMartino Booth"), ("LynAldenContact", "Lyn Alden"),
            ("charliebilello", "Charlie Bilello"), ("KobeissiLetter", "Kobeissi Letter"), ("RayDalio", "Ray Dalio"), ("BillAckman", "Bill Ackman"),
            ("NorthmanTrader", "Sven Henrich"), ("DeItaone", "Walter Bloomberg（快訊）")]
X_EVERY_MIN, X_HOURS = 30, 36
PM_KEEP = re.compile(r"\bFed\b|interest rate|rate (cut|hike)|recession|inflation|CPI|unemployment|jobs report|GDP|S&P|Nasdaq|stock market|Treasury|yield|"
                     r"tariff|shutdown|debt ceiling|Powell|Warsh|Hassett|midterm|House|Senate|Balance of Power|Trump|China|Taiwan|Iran|Russia|Ukraine|oil|"
                     r"Bitcoin|BTC|Ethereum|ETH|crypto|dollar|gold|NVIDIA|Nvidia|AI ", re.I)
PM_DROP = re.compile(r" vs\.? |Open:|Championship|League|Cup|win the .*(game|match|race)|NFL|NBA|MLB|NHL|UFC|F1|Tennis|Grand Prix|Oscars|Eurovision|"
                     r"Brazil|Lula|Bolsonaro|Colombia|Peru|Chile|Argentina|Mexico|Canada|Japan|Korea|India|Australia|"
                     r"price of .* (be )?(above|below|between)|(up|down) or (up|down)|on (January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}\?", re.I)


def get(url, timeout=30):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8"))


def x_posts(now):
    out, errs = [], []
    for u, nm in ACCOUNTS:
        try:
            d = get("https://api.fxtwitter.com/2/search?" + urllib.parse.urlencode({"q": f"from:{u}", "feed": "latest", "count": "20"}))
            for t in d.get("results") or []:
                txt = (t.get("text") or "").strip()
                ts = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y")
                if txt.startswith("@") or len(txt) < 60 or now - ts > timedelta(hours=X_HOURS) or t.get("replying_to"):
                    continue
                out.append(dict(user=u, name=nm, text=txt[:600], ts=int(ts.timestamp()), id=str(t.get("id")),
                                likes=t.get("likes") or 0, url=f"https://x.com/{u}/status/{t.get('id')}"))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{u}：{str(e)[:60]}")
    per = {}
    keep = []
    for t in sorted(out, key=lambda t: -t["ts"]):
        if per.get(t["user"], 0) < 5:
            keep.append(t)
            per[t["user"]] = per.get(t["user"], 0) + 1
    return keep, errs


def polymarket():
    d = get("https://gamma-api.polymarket.com/markets?" + urllib.parse.urlencode({"closed": "false", "order": "volume24hr", "ascending": "false", "limit": 300}))
    out = []
    for m in d:
        q = m.get("question") or ""
        if not PM_KEEP.search(q) or PM_DROP.search(q):
            continue
        try:
            oc, px = json.loads(m.get("outcomes") or "[]"), [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
        except Exception:  # noqa: BLE001
            continue
        if not px or oc[:1] != ["Yes"]:
            continue
        out.append(dict(q=q, yes=round(px[0], 3), chg1d=m.get("oneDayPriceChange"), vol24=round(float(m.get("volume24hr") or 0)),
                        end=(m.get("endDate") or "")[:10], slug=m.get("slug")))
        if len(out) >= 15:
            break
    return out


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "macro_src.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    errs = []
    res = dict(prev)
    if not prev.get("x_checked") or now - datetime.fromisoformat(prev["x_checked"]) >= timedelta(minutes=X_EVERY_MIN):
        x, e = x_posts(now)
        errs += e
        if x or not prev.get("x"):
            res.update(x=x, x_checked=now.isoformat(timespec="seconds"))
    try:
        res["pm"] = polymarket()
    except Exception as e:  # noqa: BLE001
        errs.append(f"Polymarket：{str(e)[:80]}")
    res.update(generated=now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"), errs=errs)
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[macro] X {len(res.get('x') or [])} 條（{res.get('x_checked')}）；Polymarket {len(res.get('pm') or [])} 個；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
