"""Gemini：新聞同 Serenity 推文翻譯做廣東話 + 「今日重點」總結（2026-09-30 用戶要求，方案 A：喺 GitHub 跑，key 唔會落 app）。

喺 feeds.py 同 serenity.py recent 之後跑（每 5 分鐘），讀／寫 out/news.json、out/serenity_recent.json：
  - 翻譯：快訊／市場／經濟新聞標題加 "zh"；Serenity 推文加 "zh"。一有新嘢就即刻譯（用 Flash-Lite，獨立免費額度）；
    舊嘅由上一份 feeds 分支沿用，唔會重複譯
  - 經濟數據：重要數據一公佈就 AI 解讀（加埋公佈後 QQQ／10 年債息／美元嘅實際反應，判斷係咪已經 price in），
    45 分鐘後（6 個鐘內）再解讀一次；寫入 econ.json 每行嘅 "ai"
  - 今日重點：news.json 加 "digest"，最少隔 GAP 分鐘（預設 28）先重新寫；有新嘅高影響快訊就即刻重寫；新聞冇變就沿用
key 只由環境變數 GEMINI_API_KEY 讀（GitHub Secrets）；冇 key、額度用完或者出錯都只係跳過，唔影響新聞更新。
用法：python scanner/ai.py out
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/{repo}/feeds/{f}"
# 型號次序（2026-09-30：gemini-2.0-flash 已停用；每次運行先問 Google 有邊啲型號可用，見 models()）
MODELS_D = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest",
                        "gemini-2.5-flash-lite") if m]          # 重點／解讀：Flash 用完額度就退去 Lite（額度分開）
MODELS_T = [m for m in (os.environ.get("GEMINI_MODEL_T"), "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
                        "gemini-flash-latest") if m]
_AVAIL = None
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
CATS = ("快訊", "市場", "經濟")
GAP = int(os.environ.get("GEMINI_GAP_MIN", "28"))   # 分鐘：今日重點最少隔幾耐先再寫（慳免費額度）
STYLE = "用香港廣東話口語、繁體中文。專有名詞（公司、指數、人名、股票代號）保留英文或通用中譯。"


def models(key):
    """問 Google 呢條 key 有邊啲 generateContent 型號（每次運行問一次）；問唔到就回 None（照原本次序試）。
    新出嘅 gemini-X.Y-flash／flash-lite 會自動加入後備（版本新嘅排先）。"""
    global _AVAIL
    if _AVAIL is None:
        try:
            req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", headers={"x-goog-api-key": key})
            d = json.loads(urllib.request.urlopen(req, timeout=30).read())
            _AVAIL = [m["name"].split("/", 1)[1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 型號清單攞唔到：{e}")
            _AVAIL = []
    return _AVAIL


def pick(key, base):
    av = models(key)
    if not av:
        return base
    ver = lambda n: tuple(int(x) for x in re.findall(r"\d+", n)[:2])
    flash = sorted([m for m in av if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", m)], key=ver, reverse=True)
    lite = sorted([m for m in av if re.fullmatch(r"gemini-\d+(\.\d+)?-flash-lite", m)], key=ver, reverse=True)
    isl = lambda m: "lite" in m
    groups = [[m for m in base if m in av and not isl(m)] + [m for m in flash if m not in base],
              [m for m in base if m in av and isl(m)] + [m for m in lite if m not in base]]
    if base and isl(base[0]):
        groups.reverse()                               # 翻譯：Lite 先
    out = groups[0] + groups[1]
    return out or base


def gemini(key, prompt, models_):
    gen = {"responseMimeType": "application/json", "temperature": 0.3}
    last, errs = None, []
    for m in pick(key, models_):
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
                    if e.code in (500, 503) and attempt == 0:
                        time.sleep(10)            # 伺服器忙：等陣再試一次（429 額度用完就唔等，直接試下一個型號）
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    last = f"{m}: {type(e).__name__} {e}"
                    break
            if last and "HTTP 400" not in last:
                break                             # 唔係參數問題：唔使再試冇 thinkingConfig 嘅版本
        if last:
            code = re.search(r"HTTP (\d+)", last)
            errs.append(f"{m} {code.group(1) if code else last.split(':', 1)[-1].strip()[:40]}")
        if last and not any(c in last for c in ("HTTP 404", "HTTP 400", "HTTP 429", "HTTP 500", "HTTP 503")):
            break                                 # 網絡問題：換型號都冇用（429／503 就試下一個型號：額度分開、繁忙程度唔同）
    raise RuntimeError(f"全部型號失敗（{'、'.join(errs)}）；最後：{last}")


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


def hi_titles(N, now, hours=6):
    """最近幾個鐘嘅高影響快訊標題（有新嘅就即刻重寫今日重點）。"""
    return sorted({x["title"] for x in N["items"] if x["cat"] == "快訊" and (x.get("imp") or 0) >= 3
                   and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=hours)})


# ---------------------------------------------------------------- 經濟數據：AI 即時解讀（2026-09-30 用戶要求）
YH = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=5d&interval=5m&includePrePost=true"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
MKT = {"QQQ": "QQQ", "^TNX": "10 年美債孳息", "DX-Y.NYB": "美元指數"}
_YC = {}


def yseries(sym):
    if sym not in _YC:
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(YH.format(s=urllib.request.quote(sym)), headers=UA), timeout=20).read())
            r = d["chart"]["result"][0]
            _YC[sym] = [(t, c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None]
        except Exception:  # noqa: BLE001
            _YC[sym] = []
    return _YC[sym]


def reaction(t_utc):
    """公佈之後到而家：QQQ %、10 年債息（基點）、美元指數 %。"""
    ts = t_utc.timestamp()
    out = []
    for s, nm in MKT.items():
        ser = yseries(s)
        before = [c for t, c in ser if t <= ts]
        if not before or not ser:
            continue
        b, n = before[-1], ser[-1][1]
        out.append(f"{nm} {(n - b) * 100:+.1f} 基點" if s == "^TNX" else f"{nm} {(n / b - 1) * 100:+.2f}%")
    return "、".join(out) or "（攞唔到市場數據）"


def econ_ai(key, N, E, PE, now, light, watch):
    """已公佈嘅重要數據：公佈後第一次見到就解讀；45 分鐘後（6 個鐘內）再解讀一次，等市場反應明朗。"""
    old = {f"{r['t']}|{r['name']}": r for r in PE.get("rows", []) if r.get("ai")}
    et = ZoneInfo("America/New_York")
    due = []
    for r in E.get("rows", []):
        if not r.get("actual") or (r.get("imp") or 0) < 1 or len(r["t"]) <= 10:
            continue
        k = f"{r['t']}|{r['name']}"
        rel = datetime.fromisoformat(r["t"]).replace(tzinfo=et).astimezone(timezone.utc)
        if now - rel > timedelta(hours=24):
            continue
        o = old.get(k)
        if o:
            r["ai"], r["ai_at"], r["ai_stage"] = o["ai"], o.get("ai_at"), o.get("ai_stage", 1)
            try:
                age = now - datetime.fromisoformat(o["ai_at"])
            except Exception:  # noqa: BLE001
                age = timedelta(0)
            if r["ai_stage"] >= 2 or age < timedelta(minutes=45) or now - rel > timedelta(hours=6):
                continue
        due.append((r, rel))
    if not due:
        return "冇新數據要解讀"
    heads = [f"{x.get('zh') or x['title']}" for x in N["items"] if x["cat"] in ("快訊", "經濟")
             and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=4)][:20]
    lines = []
    for i, (r, rel) in enumerate(due):
        mins = int((now - rel).total_seconds() // 60)
        lines.append(f"{i}. {r.get('zh') or r['name']}（{r['name']}）｜公佈：{r['t']} 美東（{mins} 分鐘前）｜實際 {r['actual']}／預測 {r.get('forecast') or '—'}"
                     f"／上次 {r.get('previous') or '—'}｜公佈至今市場：{reaction(rel)}")
    prompt = (f"你係美股宏觀分析助手，幫一個做美股大型科技龍頭動能策略嘅香港散戶解讀啱啱公佈嘅經濟數據。{STYLE}\n"
              f"大市燈號而家係{light}；佢關注嘅股：{', '.join(watch) or '（冇）'}。\n"
              "每項數據寫 2–4 句：①同預測同上次比，代表咩（按數據本身嘅類別講：通脹、就業、消費、製造業、服務業、樓市、能源、貿易等，"
              "例如樓市數據講建築同按揭、原油庫存講油價同能源股、消費信心同零售講消費股同企業盈利、PMI 講工業同晶片需求）；"
              "②市場實際反應（只用提供嘅 QQQ、債息、美元數字）：如果數據偏離預測但市場反應細或者相反，要講可能已經 price in 或者市場睇緊其他嘢；"
              "③對美股（特別係科技股）同相關板塊嘅含意；息口預期只喺相關時先講，唔好每項都扯去加減息。細影響數據寫短啲。"
              "公佈唔夠 15 分鐘就講明反應未明朗。只根據提供資料，唔好作新聞，唔好叫人買賣。\n"
              "回覆 JSON：{\"items\": [{\"i\": 編號, \"text\": \"..\"}]}。\n數據：\n" + "\n".join(lines)
              + "\n近 4 個鐘相關快訊：\n" + ("\n".join(heads) or "（冇）"))
    res, model = gemini(key, prompt, MODELS_D)
    n = 0
    for it in res.get("items", []):
        try:
            r, _ = due[int(it["i"])]
        except Exception:  # noqa: BLE001
            continue
        if isinstance(it.get("text"), str) and it["text"].strip():
            r["ai"] = it["text"].strip()
            r["ai_stage"] = (r.get("ai_stage") or 0) + 1 if r.get("ai_at") else 1
            r["ai_at"] = now.isoformat(timespec="seconds")
            n += 1
    return f"經濟數據解讀 {n}／{len(due)} 項（{model}）"


# ---------------------------------------------------------------- 聯儲局文件總結（2026-09-30 用戶要求：FOMC minutes 講咗咩）
FED_PRESS = re.compile(r"FOMC|Federal Open Market Committee|monetary policy|Beige Book|discount rate", re.I)


def fed_text(url):
    """讀聯儲局網頁全文（去 HTML），最多 60,000 字。"""
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")
    full = re.search(r'href="(/monetarypolicy/(?:fomcminutes\d+|beigebook\d+)\.htm)"', raw)
    if full and "pressreleases" in url:          # 新聞稿只係公佈：跟連結去讀會議紀錄／褐皮書全文
        raw = urllib.request.urlopen(urllib.request.Request("https://www.federalreserve.gov" + full.group(1), headers=UA),
                                     timeout=30).read().decode("utf-8", "ignore")
    m = re.search(r'<div[^>]+id="article"[^>]*>(.*)', raw, re.S) or re.search(r"<main[^>]*>(.*)", raw, re.S)
    body = m.group(1) if m else raw
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"\s+", " ", txt).strip()[:60000]


def fed_ai(key, N, P, now):
    """新嘅聯儲局文件（FOMC 聲明／會議紀錄／褐皮書／官員講話）：讀全文做廣東話總結；舊嘅沿用（保留 45 日）。"""
    old = {f["link"]: f for f in P.get("fed", []) if f.get("link")}
    try:                                              # 直接讀聯儲局 RSS（新聞頁只留 72 個鐘，呢度要 45 日）
        from feeds import rss
        cands = rss("https://www.federalreserve.gov/feeds/press_all.xml", "聯儲局", "經濟") \
            + rss("https://www.federalreserve.gov/feeds/speeches.xml", "聯儲局講話", "經濟")
    except Exception:  # noqa: BLE001
        cands = [x for x in N["items"] if x.get("src") in ("聯儲局", "聯儲局講話")]
    cut = now - timedelta(days=45)
    cands = [x for x in cands if x.get("link") and (x["src"] == "聯儲局講話" or FED_PRESS.search(x["title"]))
             and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > cut]
    pri = lambda x: 0 if re.search(r"Minutes of the Federal Open|FOMC statement|Beige Book", x["title"]) else (1 if x["src"] == "聯儲局" else 2)
    cands.sort(key=lambda x: x["t"], reverse=True)
    cands.sort(key=pri)                               # 會議紀錄／聲明／褐皮書優先，其次其他新聞稿，再到講話
    new = [x for x in cands if x["link"] not in old][:2]          # 每次最多兩份（慳額度）
    done = []
    for x in new:
        try:
            txt = fed_text(x["link"])
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 讀唔到 {x['link']}：{e}")
            continue
        if len(txt) < 300:
            continue
        kind = "講話" if x["src"] == "聯儲局講話" else ("會議紀錄" if "Minutes" in x["title"] else ("褐皮書" if "Beige" in x["title"] else "聲明／公佈"))
        prompt = (f"總結以下美國聯儲局文件（類別：{kind}），俾做美股大型科技股嘅香港散戶睇。{STYLE}\n"
                  "回覆 JSON：{\"title\": \"中文標題\", \"tone\": \"鷹派／偏鷹／中性／偏鴿／鴿派 之一\", "
                  "\"points\": [4–8 點重點，每點一句，包括對通脹、就業、經濟、息口路徑嘅睇法同委員之間嘅分歧], "
                  "\"change\": \"同上次比有咩唔同（文件冇講就寫空字串）\", \"impact\": \"對息口預期、美元、美股科技股嘅含意（一至兩句）\"}。"
                  "只根據文件內容，唔好加外面資料，唔好叫人買賣。\n文件標題：" + x["title"] + "\n全文：\n" + txt)
        try:
            res, model = gemini(key, prompt, MODELS_D)
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 聯儲局總結失敗：{e}")
            break
        pts = [p for p in res.get("points", []) if isinstance(p, str) and p.strip()][:8]
        if not pts:
            continue
        done.append({"link": x["link"], "t": x["t"], "kind": kind, "src_title": x["title"], "title": str(res.get("title") or x["title"]),
                     "tone": str(res.get("tone") or ""), "points": pts, "change": str(res.get("change") or ""),
                     "impact": str(res.get("impact") or ""), "model": model})
    keep = done + [f for f in old.values() if datetime.fromisoformat(f["t"].replace("Z", "+00:00")) > now - timedelta(days=45)]
    keep.sort(key=lambda f: f["t"], reverse=True)
    N["fed"] = keep[:20]
    return f"聯儲局文件總結 新 {len(done)}／候選 {len(new)}，共 {len(N['fed'])} 份"


def digest(key, N, E, P, now):
    items = N["items"]
    recent = [x for x in items if x["cat"] in CATS and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=18)]
    recent.sort(key=lambda x: x["t"], reverse=True)                  # 新嘅先，再按影響排（穩定排序）
    recent.sort(key=lambda x: -(x.get("imp") or 0))
    heads = [f"[{x['cat']}{'・高影響' if x.get('imp') == 3 else ''}] {x['title']}" for x in recent[:40]]
    done = [r for r in E.get("rows", []) if r.get("actual") and r.get("imp", 0) >= 2][-12:]
    econ = [f"{r['t']} {r.get('zh') or r['name']}：實際 {r['actual']}／預測 {r.get('forecast') or '—'}／上次 {r.get('previous') or '—'}" for r in done]
    light, watch = context()
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
             "model": model, "points": pts, "econ": str(res.get("econ") or "").strip(), "sig": sig, "hi": hi_titles(N, now),
             "econ_done": [r["name"] for r in fresh_econ(E, now)]},
            f"今日重點 {len(pts)} 點（{model}）")


def fresh_econ(E, now):
    """近 18 個鐘已公佈、中／高影響嘅經濟數據。"""
    et = ZoneInfo("America/New_York")
    out = []
    for r in E.get("rows", []):
        if not r.get("actual") or (r.get("imp") or 0) < 2 or len(r["t"]) <= 10:
            continue
        rel = datetime.fromisoformat(r["t"]).replace(tzinfo=et).astimezone(timezone.utc)
        if timedelta(0) <= now - rel <= timedelta(hours=18):
            out.append(r)
    return out


def context():
    """大市燈號同關注股（排名頭 15 + 模型持倉）。"""
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
        md = json.loads((ROOT / "docs" / "model.json").read_text(encoding="utf-8"))
        watch = sorted({r["sym"] for r in sc.get("ranking", [])[:15]} | {p["sym"] for p in md.get("positions", [])})
        return ("綠燈" if sc.get("green") else "紅燈"), watch
    except Exception:  # noqa: BLE001
        return "未知", []


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
    # 2. 經濟數據 AI 解讀：一公佈就做（45 分鐘後再做一次）
    PE = prev("econ.json")
    try:
        light, watch = context()
        print("[ai] " + econ_ai(key, N, E, PE, now, light, watch))
    except Exception as e:  # noqa: BLE001
        print(f"[ai] 經濟數據解讀失敗：{e}")
        errs.append(f"數據解讀：{str(e)[:300]}")
        old = {f"{r['t']}|{r['name']}": r for r in PE.get("rows", []) if r.get("ai")}
        for r in E.get("rows", []):                      # 失敗就沿用上一份解讀
            o = old.get(f"{r['t']}|{r['name']}")
            if o and not r.get("ai"):
                r["ai"], r["ai_at"], r["ai_stage"] = o["ai"], o.get("ai_at"), o.get("ai_stage", 1)
    # 2b. 聯儲局文件總結：一出就做
    try:
        print("[ai] " + fed_ai(key, N, P, now))
    except Exception as e:  # noqa: BLE001
        print(f"[ai] 聯儲局總結失敗：{e}")
        errs.append(f"聯儲局：{str(e)[:300]}")
        if P.get("fed"):
            N["fed"] = P["fed"]
    # 3. 今日重點：最少隔 GAP 分鐘；有新嘅高影響快訊（而且上次係 5 分鐘前）就即刻重寫
    try:
        last_ai = datetime.fromisoformat(P["ai_at"])
    except Exception:  # noqa: BLE001
        last_ai = None
    breaking = [t for t in hi_titles(N, now) if t not in set((P.get("digest") or {}).get("hi", []))]
    if breaking and last_ai and now - last_ai >= timedelta(minutes=5):
        print(f"[ai] 有 {len(breaking)} 條新嘅高影響快訊，即刻重寫今日重點")
        last_ai = None
    # 重要經濟數據（中／高影響）喺上一份重點之後公佈：即刻重寫（2026-09-30 用戶：PCE 出咗重點都未更新）
    new_econ = [r["name"] for r in fresh_econ(E, now) if r["name"] not in set((P.get("digest") or {}).get("econ_done", []))]
    if new_econ and last_ai:
        print(f"[ai] 新公佈經濟數據 {new_econ}，即刻重寫今日重點")
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
    if E:
        (out / "econ.json").write_text(json.dumps(E, ensure_ascii=False), encoding="utf-8")
    if S is not None:
        (out / "serenity_recent.json").write_text(json.dumps(S, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
