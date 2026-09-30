"""Gemini：快訊翻譯做廣東話 + 「今日重點」總結（2026-09-30 用戶要求，方案 A：喺 GitHub 跑，key 唔會落 app）。

喺 feeds.py 之後跑：讀 out/news.json、out/econ.json，寫返同一個檔：
  - 快訊／市場／經濟新聞加 "zh"（廣東話標題）；舊標題嘅翻譯由上一份 feeds 分支 news.json 沿用，慳額度
  - news.json 加 "digest"：{"generated", "model", "points": [..], "econ": ".."}；新聞冇變就沿用上一份
key 只由環境變數 GEMINI_API_KEY 讀（GitHub Secrets）；冇 key、額度用完或者出錯都只係跳過，唔影響新聞更新。
用法：python scanner/ai.py out
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREV = "https://raw.githubusercontent.com/{repo}/feeds/news.json"
MODELS = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash") if m]
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
CATS = ("快訊", "市場", "經濟")
STYLE = "用香港廣東話口語、繁體中文。專有名詞（公司、指數、人名）保留英文或通用中譯。"


def gemini(key, prompt):
    gen = {"responseMimeType": "application/json", "temperature": 0.3}
    last = None
    for m in MODELS:
        for think_off in (True, False):       # 先試關閉「思考」（快好多）；型號唔支援就用預設
            g = dict(gen, thinkingConfig={"thinkingBudget": 0}) if think_off else gen
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": g}).encode()
            for attempt in range(2):
                req = urllib.request.Request(API.format(m=m), data=body, method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                try:
                    with urllib.request.urlopen(req, timeout=180) as r:
                        d = json.loads(r.read())
                    parts = d["candidates"][0]["content"]["parts"]
                    txt = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    return json.loads(txt), m
                except urllib.error.HTTPError as e:
                    last = f"{m}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'ignore')}"
                    if e.code in (429, 500, 503) and attempt == 0:
                        time.sleep(15)            # 限流／伺服器忙：等陣再試一次
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    last = f"{m}: {type(e).__name__} {e}"
                    break
            if last and "HTTP 400" not in last:
                break                             # 唔係參數問題：唔使再試冇 thinkingConfig 嘅版本
        if last and "HTTP 404" not in last and "HTTP 400" not in last:
            break                                 # 限流／網絡問題：換型號都冇用
    raise RuntimeError(last)


def prev_news():
    repo = os.environ.get("GITHUB_REPOSITORY", "ngheioffical-glitch/stock-app")
    try:
        return json.loads(urllib.request.urlopen(PREV.format(repo=repo), timeout=20).read())
    except Exception:  # noqa: BLE001
        return {}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "feeds_out"
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("[ai] 冇 GEMINI_API_KEY，跳過")
        return
    N = json.loads((out / "news.json").read_text(encoding="utf-8"))
    E = json.loads((out / "econ.json").read_text(encoding="utf-8"))
    P = prev_news()
    cache = {x["title"]: x["zh"] for x in P.get("items", []) if x.get("zh")}
    items = N["items"]
    for x in items:
        if x["title"] in cache:
            x["zh"] = cache[x["title"]]
    # 1. 翻譯（淨係未翻過、屬於快訊／市場／經濟嘅，最多 100 條一次）
    todo = [x for x in items if x["cat"] in CATS and not x.get("zh")][:100]
    model = None
    if todo:
        prompt = (f"將以下英文財經新聞標題翻譯成簡潔嘅中文標題。{STYLE}唔好加內容、唔好評論。"
                  "回覆 JSON：{\"t\": [對應每條嘅翻譯，次序同數量同輸入一樣]}。\n"
                  + json.dumps([x["title"] for x in todo], ensure_ascii=False))
        try:
            res, model = gemini(key, prompt)
            zh = res.get("t", [])
            for x, z in zip(todo, zh):
                if isinstance(z, str) and z.strip():
                    x["zh"] = z.strip()
            print(f"[ai] 翻譯 {len(zh)} 條（{model}）")
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 翻譯失敗：{e}")
            N["ai_err"] = f"翻譯：{str(e)[:300]}"
    # 2. 今日重點（新聞同已公佈數據冇變就沿用上一份）
    now = datetime.now(timezone.utc)
    recent = [x for x in items if x["cat"] in CATS and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=18)]
    recent.sort(key=lambda x: x["t"], reverse=True)                  # 新嘅先，再按影響排（穩定排序）
    recent.sort(key=lambda x: -(x.get("imp") or 0))
    heads = [f"[{x['cat']}{'・高影響' if x.get('imp') == 3 else ''}] {x['title']}" for x in recent[:40]]
    done = [r for r in E.get("rows", []) if r.get("actual") and r.get("imp", 0) >= 2][-12:]
    econ = [f"{r['t']} {r.get('zh') or r['name']}：實際 {r['actual']}／預測 {r.get('forecast') or '—'}／上次 {r.get('previous') or '—'}" for r in done]
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
        md = json.loads((ROOT / "docs" / "model.json").read_text(encoding="utf-8"))
        watch = sorted({r["sym"] for r in sc.get("ranking", [])[:15]} | {p["sym"] for p in md.get("positions", [])})
        light = "綠燈" if sc.get("green") else "紅燈"
    except Exception:  # noqa: BLE001
        watch, light = [], "未知"
    sig = hashlib.sha1(json.dumps([heads, econ, watch], ensure_ascii=False).encode()).hexdigest()
    old = P.get("digest") or {}
    if old.get("sig") == sig:
        N["digest"] = old
        print("[ai] 新聞冇變，沿用上一份重點")
    elif heads or econ:
        prompt = (f"你係美股市場助手，幫一個做美股大型科技龍頭動能策略嘅香港散戶睇新聞。{STYLE}\n"
                  f"大市燈號而家係{light}；佢關注嘅股：{', '.join(watch) or '（冇）'}。\n"
                  "根據下面最近 18 小時嘅新聞標題同已公佈經濟數據，寫：\n"
                  "1. points：3–6 點今日最重要嘅事，每點一句講「發生咩 → 對美股／科技股可能有咩影響」；有提到佢關注嘅股就講埋；\n"
                  "2. econ：一至兩句總結已公佈經濟數據對息口預期嘅意思（冇數據就寫空字串）。\n"
                  "只根據提供嘅資料，唔好估未發生嘅事，唔好叫人買賣。回覆 JSON：{\"points\": [..], \"econ\": \"..\"}。\n"
                  "新聞：\n" + "\n".join(heads) + "\n經濟數據：\n" + ("\n".join(econ) or "（冇）"))
        try:
            res, model = gemini(key, prompt)
            pts = [p for p in res.get("points", []) if isinstance(p, str) and p.strip()][:6]
            if not pts:
                N["ai_err"] = f"重點：回覆冇 points（{json.dumps(res, ensure_ascii=False)[:200]}）"
            if pts:
                N["digest"] = {"generated": now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"),
                               "model": model, "points": pts, "econ": str(res.get("econ") or "").strip(), "sig": sig}
                print(f"[ai] 今日重點 {len(pts)} 點（{model}）")
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 重點失敗：{e}")
            N["ai_err"] = f"重點：{str(e)[:300]}"
            if old:
                N["digest"] = old
    (out / "news.json").write_text(json.dumps(N, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
