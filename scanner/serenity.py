"""Serenity（X @aleabitoreddit）近期提過邊啲股，app 用嚟標示「Serenity 關注緊」（2026-09-29 用戶要求）。

來源：api.fxtwitter.com 搜尋（from:aleabitoreddit since/until），唔使 key。淨係留有 cashtag 嘅推文。
回測（stock-strategy/LAB_SERENITY.md）：佢提嘅時候技術面已經合格嘅股，之後 60 日平均好過 QQQ；技術面唔合格嘅就差過 QQQ。
所以只係參考標示，唔改 V2.1 規則。

用法：python scanner/serenity.py                 → docs/serenity.json（近 60 日，每日跑）；同時併入 docs/serenity_all.json（2025-07 起全部）
      python scanner/serenity.py recent 輸出資料夾  → serenity_recent.json（近 3 日，每 30 分鐘跑，推去 feeds 分支）
      python scanner/serenity.py seed 檔案         → 用 stock-strategy/data/ext/serenity_tweets.json 建立 serenity_all.json（只做一次）
攞唔到數據就唔覆蓋舊檔，唔會令 workflow 失敗。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SKIP = {"SPY", "QQQ", "BTC", "ETH", "SOL", "DOGE", "XRP"}
ALL = ROOT / "docs" / "serenity_all.json"


def short(text, n):
    text = " ".join((text or "").split())
    return text[:n - 1] + "…" if len(text) > n else text


def save_all(new):
    """全部歷史（app 撳股票睇 Serenity 由 2025 年起講過乜）：舊檔 + 新推文，按 id 去重。"""
    old = json.loads(ALL.read_text(encoding="utf-8"))["tweets"] if ALL.exists() else []
    tw = {t["id"]: t for t in old}
    for t in new:
        tw[t["id"]] = dict(t, text=short(t.get("full") or t["text"], 280))
        tw[t["id"]].pop("full", None)
    gen = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    ALL.write_text(json.dumps({"generated": gen, "tweets": sorted(tw.values(), key=lambda t: -t["ts"])},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(tw)


def get(q, cursor=""):
    p = dict(q=q, feed="latest", count="100", **({"cursor": cursor} if cursor else {}))
    url = "https://api.fxtwitter.com/2/search?" + urllib.parse.urlencode(p)
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[serenity] 重試 {k}：{e}")
            time.sleep(3 + 5 * k)
    raise RuntimeError("fxtwitter 攞唔到")


def fetch(a, b):
    out, cur, seen = {}, "", set()
    for _ in range(60):
        d = get(f"from:aleabitoreddit since:{a} until:{b}", cur)
        res = [x for x in d.get("results", []) if x.get("type") == "status"]
        for s in res:
            if (s.get("author") or {}).get("screen_name", "").lower() != "aleabitoreddit":
                continue
            facets = (s.get("raw_text") or {}).get("facets") or []
            syms = sorted({f["original"].upper() for f in facets if f.get("type") == "symbol"} - SKIP)
            if syms:
                out[s["id"]] = dict(id=s["id"], ts=s["created_timestamp"], syms=syms, reply=bool(s.get("replying_to")),
                                    text=short(s.get("text"), 160), full=s.get("text") or "")
        cur = (d.get("cursor") or {}).get("bottom") or ""
        if not res or not cur or cur in seen:
            break
        seen.add(cur)
        time.sleep(0.8)
    return out


def seed(path):
    src = json.loads(Path(path).read_text(encoding="utf-8"))["tweets"]
    new = [dict(id=t["id"], ts=t["ts"], syms=sorted(set(t["syms"]) - SKIP), reply=t["reply"], text=t["text"])
           for t in src if set(t["syms"]) - SKIP]
    print(f"[serenity] serenity_all.json：{save_all(new)} 條")


def main():
    if sys.argv[1:2] == ["seed"]:
        return seed(sys.argv[2])
    recent = sys.argv[1:2] == ["recent"]
    days = 3 if recent else 60
    out = (Path(sys.argv[2]) / "serenity_recent.json") if recent else ROOT / "docs" / "serenity.json"
    now = datetime.now(timezone.utc)
    tw = {}
    try:
        a = (now - timedelta(days=days)).date()
        while a <= now.date():
            b = min(a + timedelta(days=10), now.date() + timedelta(days=1))
            tw.update(fetch(a.isoformat(), b.isoformat()))
            a = b
    except Exception as e:  # noqa: BLE001
        print(f"[serenity] 失敗，唔覆蓋舊檔：{e}")
        return
    if not tw and not recent:
        print("[serenity] 冇數據，唔覆蓋舊檔")
        return
    gen = now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = sorted(({k: v for k, v in t.items() if k != "full"} for t in tw.values()), key=lambda t: -t["ts"])
    out.write_text(json.dumps({"generated": gen, "days": days, "tweets": lst}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    if not recent:
        print(f"[serenity] serenity_all.json 共 {save_all(tw.values())} 條")
    n = {}
    for t in tw.values():
        for s in t["syms"]:
            n[s] = n.get(s, 0) + 1
    top = sorted(n.items(), key=lambda x: -x[1])[:10]
    print(f"[serenity] {len(tw)} 條有 cashtag 嘅推文（近 {days} 日）；最多：{top}")


if __name__ == "__main__":
    main()
