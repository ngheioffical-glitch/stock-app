"""X（Twitter）帳戶最新帖：經 api.fxtwitter.com 讀帳戶時間線，唔使 key。

2026-10-14：fxtwitter 嘅搜尋（/2/search?q=from:帳戶）開始一律 404，Trump 後備、Serenity、宏觀人士、雷達研究人士、Whale Alert 全部攞唔到；
改用帳戶時間線 /2/profile/{帳戶}/statuses（帖嘅格式同 cursor 同以前搜尋一樣）。
時間線會包埋轉發（reposted_by／作者唔係本人），呢度剔走，等同以前 from: 搜尋。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
BASE = "https://api.fxtwitter.com/2/profile/{}/statuses"


def page(user, count=40, cursor="", timeout=30, tries=3):
    """一頁時間線：{"results": [本人原創帖, ...], "cursor": {...}, "raw_n": 未剔轉發前幾多條}。"""
    q = {"count": str(min(int(count), 100)), **({"cursor": cursor} if cursor else {})}
    url = BASE.format(urllib.parse.quote(user)) + "?" + urllib.parse.urlencode(q)
    last = None
    for k in range(tries):
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8"))
            raw = d.get("results") or []
            mine = [r for r in raw if r.get("type") == "status" and not r.get("reposted_by")
                    and ((r.get("author") or {}).get("screen_name") or user).lower() == user.lower()]
            return {"results": mine, "cursor": d.get("cursor") or {}, "raw_n": len(raw)}
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 3 * k)
    raise RuntimeError(f"fxtwitter 時間線攞唔到：{str(last)[:80]}")


def posts(user, count=40, since_ts=None, pages=1, timeout=30):
    """帳戶最新帖（新到舊，格式同以前搜尋結果）。since_ts（秒）：翻到早過呢個時間就停；pages：最多翻幾頁。"""
    out, cur, seen = [], "", set()
    for _ in range(pages):
        d = page(user, count, cur, timeout)
        out += d["results"]
        cur = d["cursor"].get("bottom") or ""
        old = bool(since_ts and d["results"] and min(r.get("created_timestamp") or 0 for r in d["results"]) < since_ts)
        if not d["raw_n"] or not cur or cur in seen or old:
            break
        seen.add(cur)
        time.sleep(0.8)
    return {"results": out}
