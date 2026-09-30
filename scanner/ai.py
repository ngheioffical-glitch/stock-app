"""Gemini：新聞同 Serenity 推文翻譯做廣東話 + 「今日重點」總結（2026-09-30 用戶要求，方案 A：喺 GitHub 跑，key 唔會落 app）。

喺 feeds.py 同 serenity.py recent 之後跑（每 5 分鐘），讀／寫 out/news.json、out/serenity_recent.json：
  - 翻譯：快訊／市場／經濟新聞標題加 "zh"；Serenity 推文加 "zh"。一有新嘢就即刻譯（用 Flash-Lite，獨立免費額度）；
    舊嘅由上一份 feeds 分支沿用，唔會重複譯
  - 今日重點：news.json 加 "digest"，最少隔 GAP 分鐘（預設 28）先重新寫；新聞冇變就沿用
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
RAW = "https://raw.githubusercontent.com/{repo}/feeds/{f}"
MODELS_D = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash") if m]
MODELS_T = [m for m in (os.environ.get("GEMINI_MODEL_T"), "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite",
                        "gemini-flash-latest") if m]
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
CATS = ("快訊", "市場", "經濟")
GAP = int(os.environ.get("GEMINI_GAP_MIN", "28"))   # 分鐘：今日重點最少隔幾耐先再寫（慳免費額度）
STYLE = "用香港廣東話口語、繁體中文。專有名詞（公司、指數、人名、股票代號）保留英文或通用中譯。"


def gemini(key, prompt, models):
    gen = {"responseMimeType": "application/json", "temperature": 0.3}
    last = None
    for m in models:
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
        if last and not any(c in last for c in ("HTTP 404", "HTTP 400", "HTTP 429")):
            break                                 # 網絡問題：換型號都冇用（429 就試下一個型號，佢哋額度分開）
    raise RuntimeError(last)


def prev(f):
    repo = os.environ.get("GITHUB_REPOSITORY", "ngheioffical-glitch/stock-app")
    try:
        return json.loads(urllib.request.urlopen(RAW.format(repo=repo, f=f), timeout=20).read())
    except Exception:  # noqa: BLE001
        return {}


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def translate(key, N, S, P, PS):
    """新聞標題同 Serenity 推文：沿用舊翻譯，新嘅一次過譯。"""
    cache = {x["title"]: x["zh"] for x in P.get("items", []) if x.get("zh")}
    for x in N["items"]:
        if x["title"] in cache:
            x["zh"] = cache[x["title"]]
    tw = (S or {}).get("tweets", [])
    scache = {t["id"]: t["zh"] for t in PS.get("tweets", []) if t.get("zh")}
    for t in tw:
        if t["id"] in scache:
            t["zh"] = scache[t["id"]]
    todo_n = [x for x in N["items"] if x["cat"] in CATS and not x.get("zh")][:100]
    todo_s = [t for t in tw if not t.get("zh")][:40]
    if not todo_n and not todo_s:
        return "冇新嘢要譯"
    prompt = (f"將以下英文翻譯成中文。{STYLE}唔好加內容、唔好評論、唔好刪走 $股票代號。\n"
              "news = 財經新聞標題（譯做簡潔標題）；tweets = 美股分析師 Serenity 嘅推文（照意思譯晒，保持原本語氣）。\n"
              "回覆 JSON：{\"news\": [..], \"tweets\": [..]}，每個陣列次序同數量同輸入一樣。\n"
              + json.dumps({"news": [x["title"] for x in todo_n], "tweets": [t["text"] for t in todo_s]}, ensure_ascii=False))
    res, model = gemini(key, prompt, MODELS_T)
    zn, zs = res.get("news", []), res.get("tweets", [])
    for x, z in zip(todo_n, zn):
        if isinstance(z, str) and z.strip():
            x["zh"] = z.strip()
    for t, z in zip(todo_s, zs):
        if isinstance(z, str) and z.strip():
            t["zh"] = z.strip()
    return f"新聞 {len(zn)}／{len(todo_n)} 條、Serenity {len(zs)}／{len(todo_s)} 條（{model}）"


def digest(key, N, E, P, now):
    items = N["items"]
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
    if old.get("sig") == sig or not (heads or econ):
        return old, "新聞冇變，沿用上一份重點"
    prompt = (f"你係美股市場助手，幫一個做美股大型科技龍頭動能策略嘅香港散戶睇新聞。{STYLE}\n"
              f"大市燈號而家係{light}；佢關注嘅股：{', '.join(watch) or '（冇）'}。\n"
              "根據下面最近 18 小時嘅新聞標題同已公佈經濟數據，寫：\n"
              "1. points：3–6 點今日最重要嘅事，每點一句講「發生咩 → 對美股／科技股可能有咩影響」；有提到佢關注嘅股就講埋；\n"
              "2. econ：一至兩句總結已公佈經濟數據對息口預期嘅意思（冇數據就寫空字串）。\n"
              "只根據提供嘅資料，唔好估未發生嘅事，唔好叫人買賣。回覆 JSON：{\"points\": [..], \"econ\": \"..\"}。\n"
              "新聞：\n" + "\n".join(heads) + "\n經濟數據：\n" + ("\n".join(econ) or "（冇）"))
    res, model = gemini(key, prompt, MODELS_D)
    pts = [p for p in res.get("points", []) if isinstance(p, str) and p.strip()][:6]
    if not pts:
        raise RuntimeError(f"回覆冇 points（{json.dumps(res, ensure_ascii=False)[:200]}）")
    return ({"generated": now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"),
             "model": model, "points": pts, "econ": str(res.get("econ") or "").strip(), "sig": sig},
            f"今日重點 {len(pts)} 點（{model}）")


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "feeds_out"
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("[ai] 冇 GEMINI_API_KEY，跳過")
        return
    N = load(out / "news.json")
    E = load(out / "econ.json") or {}
    S = load(out / "serenity_recent.json")
    P, PS = prev("news.json"), prev("serenity_recent.json")
    now = datetime.now(timezone.utc)
    errs = []
    # 1. 翻譯：每次都做（有新嘢先會用 Gemini）
    try:
        print("[ai] 翻譯：" + translate(key, N, S, P, PS))
    except Exception as e:  # noqa: BLE001
        print(f"[ai] 翻譯失敗：{e}")
        errs.append(f"翻譯：{str(e)[:300]}")
    # 2. 今日重點：最少隔 GAP 分鐘
    try:
        last_ai = datetime.fromisoformat(P["ai_at"])
    except Exception:  # noqa: BLE001
        last_ai = None
    if last_ai and now - last_ai < timedelta(minutes=GAP):
        if P.get("digest"):
            N["digest"] = P["digest"]
        N["ai_at"] = P["ai_at"]
        print(f"[ai] 今日重點：上次係 {int((now - last_ai).total_seconds() // 60)} 分鐘前，今次沿用")
    else:
        N["ai_at"] = now.isoformat(timespec="seconds")
        try:
            d, msg = digest(key, N, E, P, now)
            if d:
                N["digest"] = d
            print("[ai] " + msg)
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 重點失敗：{e}")
            errs.append(f"重點：{str(e)[:300]}")
            if P.get("digest"):
                N["digest"] = P["digest"]
    if errs:
        N["ai_err"] = "；".join(errs)
    (out / "news.json").write_text(json.dumps(N, ensure_ascii=False), encoding="utf-8")
    if S is not None:
        (out / "serenity_recent.json").write_text(json.dumps(S, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
