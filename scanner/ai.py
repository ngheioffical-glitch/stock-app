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
CATS = ("快訊", "市場", "經濟", "加密")
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


# GitHub Models（2026-09-30 用戶要求：Gemini 唔穩定時嘅後備）：用 Actions 內置 GITHUB_TOKEN（workflow 要 permissions: models: read），唔使另外申請 key
GH_API = "https://models.github.ai/inference/chat/completions"
GH_MODELS = [m for m in (os.environ.get("GH_MODEL"), "openai/gpt-4.1-mini", "openai/gpt-4o-mini", "deepseek/deepseek-v3-0324") if m]


def github_models(prompt):
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("冇 GITHUB_TOKEN")
    errs = []
    for m in GH_MODELS:
        for fmt in (True, False):                  # 先要求 JSON 格式；型號唔支援（400）就唔要
            body = {"model": m, "temperature": 0.3,
                    "messages": [{"role": "system", "content": "你只可以回覆一個 JSON object，唔好加其他文字。"},
                                 {"role": "user", "content": prompt}]}
            if fmt:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(GH_API, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                                  "Authorization": f"Bearer {tok}", "X-GitHub-Api-Version": "2022-11-28"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read())
                txt = d["choices"][0]["message"]["content"].strip()
                txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
                return json.loads(txt), "github:" + m
            except urllib.error.HTTPError as e:
                errs.append(f"{m} {e.code}")
                if e.code == 400 and fmt:
                    continue
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{m} {type(e).__name__}")
                break
    raise RuntimeError("GitHub Models 失敗（" + "、".join(errs) + "）")


def gemini(key, prompt, models_):
    """先用 Gemini（逐個型號試）；全部失敗就用 GitHub Models 後備。"""
    try:
        return _gemini(key, prompt, models_)
    except Exception as e:  # noqa: BLE001
        try:
            res, m = github_models(prompt)
            print(f"[ai] Gemini 失敗，改用 {m}：{str(e)[:160]}")
            return res, m
        except Exception as e2:  # noqa: BLE001
            raise RuntimeError(f"{e}｜{e2}") from None


def _gemini(key, prompt, models_):
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


def translate(key, N, S, P, PS, T=None, PT=None):
    """新聞標題、Serenity 推文、Trump 貼文：沿用舊翻譯，新嘅一次過譯。"""
    cache = {x["title"]: (x["zh"], x.get("zm")) for x in P.get("items", []) if x.get("zh")}
    for x in N["items"]:
        if x["title"] in cache:
            x["zh"], x["zm"] = cache[x["title"]]
    tw = (S or {}).get("tweets", [])
    scache = {t["id"]: (t["zh"], t.get("zm")) for t in PS.get("tweets", []) if t.get("zh")}
    for t in tw:
        if t["id"] in scache:
            t["zh"], t["zm"] = scache[t["id"]]
    tp = (T or {}).get("posts", [])
    tcache = {t["id"]: (t["zh"], t.get("zm")) for t in (PT or {}).get("posts", []) if t.get("zh")}
    for t in tp:
        if t["id"] in tcache:
            t["zh"], t["zm"] = tcache[t["id"]]
    todo_n = [x for x in N["items"] if x["cat"] in CATS and not x.get("zh")][:100]
    todo_s = [t for t in tw if not t.get("zh")][:40]
    todo_t = [t for t in tp if not t.get("zh") and t.get("text")][:25]
    if not todo_n and not todo_s and not todo_t:
        return "冇新嘢要譯"
    prompt = (f"將以下英文翻譯成中文。{STYLE}唔好加內容、唔好評論、唔好刪走 $股票代號同網址。\n"
              "news = 財經新聞標題（譯做簡潔標題）；tweets = 美股分析師 Serenity 嘅推文（照意思譯晒，保持原本語氣）；"
              "trump = 美國總統 Trump 喺 Truth Social 嘅貼文（照意思譯晒，保留佢誇張、大楷嘅語氣）。\n"
              "回覆 JSON：{\"news\": [..], \"tweets\": [..], \"trump\": [..]}，每個陣列次序同數量同輸入一樣。\n"
              + json.dumps({"news": [x["title"] for x in todo_n], "tweets": [t["text"] for t in todo_s],
                            "trump": [t["text"][:900] for t in todo_t]}, ensure_ascii=False))
    res, model = gemini(key, prompt, MODELS_T)
    zn, zs, zt = res.get("news", []), res.get("tweets", []), res.get("trump", [])
    for t, z in zip(todo_t, zt):
        if isinstance(z, str) and z.strip():
            t["zh"], t["zm"] = z.strip(), model
    for x, z in zip(todo_n, zn):
        if isinstance(z, str) and z.strip():
            x["zh"], x["zm"] = z.strip(), model
    for t, z in zip(todo_s, zs):
        if isinstance(z, str) and z.strip():
            t["zh"], t["zm"] = z.strip(), model
    return f"新聞 {len(zn)}／{len(todo_n)} 條、Serenity {len(zs)}／{len(todo_s)} 條、Trump {len(zt)}／{len(todo_t)} 條（{model}）"


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


# ---------------------------------------------------------------- 今日市場實際數字同事實核對（2026-09-30 用戶：AI 講美元回落，但實際美元升）
SNAP = [("QQQ", "QQQ", "%"), ("^TNX", "10 年債息", "bp"), ("^TYX", "30 年債息", "bp"), ("DX-Y.NYB", "美元指數", "%"), ("CL=F", "紐約原油", "%"), ("GC=F", "金價", "%")]
YQ = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=5m&includePrePost=false"


def snapshot():
    """最近一個美股交易日：最新價 vs 上一日收市。回傳 [{s, name, chg, unit, at}]。"""
    out = []
    for s, nm, unit in SNAP:
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(YQ.format(s=urllib.request.quote(s)), headers=UA), timeout=20).read())
            m = d["chart"]["result"][0]["meta"]
            pc, px = m.get("chartPreviousClose") or m.get("previousClose"), m.get("regularMarketPrice")
            if not pc or not px:
                continue
            chg = (px - pc) * 100 if unit == "bp" else (px / pc - 1) * 100
            out.append(dict(s=s, name=nm, chg=round(chg, 2), unit=unit,
                            at=datetime.fromtimestamp(m.get("regularMarketTime", 0), timezone.utc).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%m-%d %H:%M")))
        except Exception as e:  # noqa: BLE001
            print(f"[ai] {s} 市場數字攞唔到：{e}")
    return out


def snap_text(sn):
    return "、".join(f"{x['name']} {x['chg']:+.1f} 基點" if x["unit"] == "bp" else f"{x['name']} {x['chg']:+.2f}%" for x in sn) or "（攞唔到）"


FC_KEYS = {"DX-Y.NYB": r"美元指數|美元|美金|美匯", "^TNX": r"債息|孳息|收益率", "QQQ": r"納指|納斯達克|QQQ", "CL=F": r"油價|原油", "GC=F": r"金價|黃金"}
FC_UP = r"上升|抽升|攀升|走強|造好|上揚|反彈|上漲|升|漲|彈"
FC_DN = r"回落|下跌|下降|走弱|回軟|受壓|下滑|挫|跌|落"
FC_MIN = {"%": 0.05, "bp": 1.0}


def factcheck(texts, sn):
    """AI 文字入面講嘅市場方向，同實際數字核對；回傳唔符合嘅說明。"""
    act = {x["s"]: x for x in sn}
    bad = []
    for t in texts:
        for s, pat in FC_KEYS.items():
            x = act.get(s)
            if not x or abs(x["chg"]) < FC_MIN[x["unit"]]:
                continue
            for m in re.finditer(rf"({pat})[^，。；、,.;]{{0,8}}?({FC_UP}|{FC_DN})", t):
                up = re.fullmatch(FC_UP, m.group(2)) is not None
                if up != (x["chg"] > 0):
                    val = f"{x['chg']:+.1f} 基點" if x["unit"] == "bp" else f"{x['chg']:+.2f}%"
                    bad.append(f"寫咗「{m.group(0)}」，但實際{x['name']} {val}")
    return sorted(set(bad))


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
            r["ai"], r["ai_at"], r["ai_stage"], r["ai_model"] = o["ai"], o.get("ai_at"), o.get("ai_stage", 1), o.get("ai_model")
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
            r["ai_model"] = model
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


def digest(key, N, E, P, now, force=False, T=None, Sr=None):
    items = N["items"]
    recent = [x for x in items if x["cat"] in CATS and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=18)]
    recent.sort(key=lambda x: x["t"], reverse=True)                  # 新嘅先，再按影響排（穩定排序）
    recent.sort(key=lambda x: -(x.get("imp") or 0))
    heads = [f"[{x['cat']}{'・高影響' if x.get('imp') == 3 else ''}] {x['title']}" for x in recent[:40]]
    heads += [f"[Trump Truth Social 貼文] {t['text'][:220]}" for t in (T or {}).get("posts", [])
              if t.get("text") and now.timestamp() - t["ts"] < 18 * 3600 and len(t["text"]) > 40][:8]
    heads += [f"[Serenity（美股分析師，X @aleabitoreddit）推文，提到 {' '.join('$' + x for x in t.get('syms', []))}] {t['text'][:220]}"
              for t in sorted((Sr or {}).get("tweets", []), key=lambda t: -t["ts"])
              if now.timestamp() - t["ts"] < 18 * 3600 and not t.get("reply")][:6]
    done = [r for r in E.get("rows", []) if r.get("actual") and r.get("imp", 0) >= 2][-12:]
    econ = [f"{r['t']} {r.get('zh') or r['name']}：實際 {r['actual']}／預測 {r.get('forecast') or '—'}／上次 {r.get('previous') or '—'}" for r in done]
    light, watch = context()
    lc = light_change()
    ta = tq_alert()
    ra = rates_alert()
    sn = snapshot()
    sig = hashlib.sha1(json.dumps([heads, econ, watch, lc, ta, ra], ensure_ascii=False).encode()).hexdigest()
    old = P.get("digest") or {}
    if (old.get("sig") == sig and not force) or not (heads or econ):
        return old, "新聞冇變，沿用上一份重點"
    lc_txt = ""
    if lc:
        lc_txt = (f"重要：大市燈號喺 {lc['date']} 收市由{lc['frm']}轉咗{lc['to']}（{lc['detail']}；規則：綠燈 = NDX 高過 200 日線，或者 NDX > 21 日 EMA > 50 日線）。"
                  f"points 第一點一定要講：根據下面新聞同數據，點解大市會轉{lc['to']}（邊單新聞、數據或者事件最有關），"
                  + ("同埋規則下一個交易日開市會賣晒股、現金轉 IEF。" if lc["to"] == "紅燈" else "同埋規則下一個交易日開始可以買突破股。") + chr(10))
    if ta:
        if ta["kind"] == "switch":
            lc_txt += (f"重要：佢嘅模型 {ta['date']} 收市出咗 TQQQ 轉換訊號：下一個交易日收市前，佔帳戶 40% 嘅 TQQQ 腳要轉做 {ta['to']}"
                       + (f"（原因：{'、'.join(w for w in ta['why'] if w)}）" if ta["why"] else "（大市綠燈而且 QQQ 波幅回落）")
                       + f"。{ta['detail']}。points 要有一點講：根據新聞同數據，點解市況會變成咁，同埋呢個轉換係規則決定。" + NL)
        else:
            lc_txt += (f"重要：佢嘅模型 TQQQ 腳（佔帳戶 40%，3 倍納指 ETF）出咗黃燈（只係提示，規則未叫佢郁）："
                       + "、".join(ta["why"]) + f"。{ta['detail']}。points 要有一點講：根據新聞同數據，點解市況會出現呢啲變化（邊單新聞、數據或者事件最有關），"
                       + ("同埋如果轉紅燈或者 QQQ 波幅去到 35%，規則下一個交易日收市前會賣晒 TQQQ 轉 IEF。" if ta["kind"] == "sell"
                          else "同埋如果轉返綠燈而且 QQQ 波幅低過 35%，規則下一個交易日收市前會買返 TQQQ。") + NL)
    if ra:
        lc_txt += (f"重要：美債息有大變動：{'；'.join(ra['alert'])}（{ra['detail']}；10 年減 2 年息差 {(ra.get('curve') or {}).get('10y_2y', '—')} 基點）。"
                   "points 要有一點講：根據下面新聞同數據，點解債息會咁郁（例如通脹、聯儲局、財政赤字、發債、經濟數據），同埋對科技股估值有咩影響。" + NL)
    base = (f"你係美股市場助手，幫一個做美股大型科技龍頭動能策略嘅香港散戶睇新聞。{STYLE}\n"
            f"大市燈號而家係{light}；佢留意嘅股（排名頭 15 同模型帳戶持倉，唔一定係佢自己持有，唔好寫「你持有」）：{', '.join(watch) or '（冇）'}。\n"
            f"今日市場實際數字（最近一個交易日，最新 vs 上日收市）：{snap_text(sn)}。\n"
            f"{lc_txt}"
            "根據下面最近 18 小時嘅新聞標題、Trump 貼文（如有，只揀對市場有影響嘅，例如關稅、公司、聯儲局、股市）、"
            "Serenity 推文（如有，佢係 X 上面嘅美股分析師，講邊隻股同點解；有重要觀點就寫一點，註明係 Serenity 嘅睇法）同已公佈經濟數據，寫：\n"
            "1. points：3–6 點今日最重要嘅事，每點一句講「發生咩 → 對美股／科技股可能有咩影響」；有提到佢留意嘅股就講埋；\n"
            "2. econ：一至兩句總結已公佈經濟數據對息口預期嘅意思（冇數據就寫空字串）。\n"
            "事實規則：講到美元、債息、納指、油價、金價嘅升跌，只可以用上面嘅實際數字；新聞標題可能係幾個鐘前嘅走勢，同實際數字唔同就以實際數字為準，"
            "唔好寫相反方向。只根據提供嘅資料，唔好估未發生嘅事，唔好叫人買賣。回覆 JSON：{\"points\": [..], \"econ\": \"..\"}。\n"
            "新聞：\n" + "\n".join(heads) + "\n經濟數據：\n" + ("\n".join(econ) or "（冇）"))
    prompt, bad, tries = base, [], 0
    while True:
        res, model = gemini(key, prompt, MODELS_D)
        pts = [p for p in res.get("points", []) if isinstance(p, str) and p.strip()][:6]
        if not pts:
            raise RuntimeError(f"回覆冇 points（{json.dumps(res, ensure_ascii=False)[:200]}）")
        ec = str(res.get("econ") or "").strip()
        bad = factcheck(pts + [ec], sn)
        tries += 1
        if not bad or tries >= 2:
            break
        print(f"[ai] 事實核對唔符合，重寫：{bad}")
        prompt = base + "\n\n你上一版有錯，要改正：" + "；".join(bad) + "。"
    return ({"generated": now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"),
             "model": model, "points": pts, "econ": ec, "sig": sig, "hi": hi_titles(N, now),
             "econ_done": [r["name"] for r in fresh_econ(E, now)], "snap": sn, "checked": True, "warn": bad, "tries": tries,
             "light_change": lc, "tq_alert": ta, "rates_alert": ra},
            f"今日重點 {len(pts)} 點（{model}，核對{'有 ' + str(len(bad)) + ' 處唔符' if bad else '通過'}，寫咗 {tries} 次）")


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
        md = json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8"))   # 2026-10-01 刪咗新帳戶
        watch = sorted({r["sym"] for r in sc.get("ranking", [])[:15]} | {p["sym"] for p in md.get("positions", [])})
        return ("綠燈" if sc.get("green") else "紅燈"), watch
    except Exception:  # noqa: BLE001
        return "未知", []


def light_change():
    """大市燈號啱啱轉咗（scan.json 最近兩個交易日 green10 唔同）就返轉燈資料，否則 None（2026-10-01 用戶：無啦啦轉紅燈，今日重點要講點解）。"""
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
        g = (sc.get("cash") or {}).get("green10") or []
        if len(g) < 2 or g[-1] == g[-2]:
            return None
        to = "綠燈" if g[-1] else "紅燈"
        return dict(date=sc["date"], to=to, frm="紅燈" if g[-1] else "綠燈", next_day=sc.get("next_day"),
                    detail=f"NDX 收市 {sc['ndx']:,.0f}；200 日線 {sc['ndx_s200']:,.0f}；21 日 EMA {sc['ndx_e21']:,.0f}；50 日線 {sc['ndx_s50']:,.0f}")
    except Exception:  # noqa: BLE001
        return None


OUTDIR = None


def rates_alert():
    """美債息急升／急跌（10 年或 30 年單日 ≥ 10 基點）或者創 52 週新高（2026-10-02 用戶）：返 dict，否則 None。scanner/rates.py 同一次 feeds 寫嘅 rates.json。"""
    try:
        R = load(OUTDIR / "rates.json") if OUTDIR else None
        if not R or not R.get("alert"):
            return None
        rows = {r["name"]: r for r in R.get("rows", [])}
        txt = "；".join(f"{n} {r['y']:.2f}%（今日 {r['d']:+.0f} 基點、1 個月 {r['m']:+.0f} 基點、一年 {r['yr']:+.0f} 基點）"
                       for n, r in rows.items() if n in ("2 年", "10 年", "30 年") and r.get("d") is not None)
        return dict(alert=R["alert"], detail=txt, curve=R.get("curve"))
    except Exception:  # noqa: BLE001
        return None


def tq_alert():
    """V2.3 TQQQ 腳（2026-10-02 用戶：黃燈要話我知發生咩事）：有轉換要做 → kind=switch；黃燈 → kind=sell／buy；否則 None。
    條件同 app 嘅 tqYellow() 一樣（只係提示，唔改規則）。"""
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
        T = (json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8")).get("view") or {}).get("tq")
        if not T or T.get("margin") is None:
            return None
        f = lambda x: f"{abs(x) * 100:.1f}%"
        vm = T.get("vol_max", 0.35)
        lv = f"NDX 收市 {sc['ndx']:,.0f}（200 日線 {sc['ndx_s200']:,.0f}、21 日 EMA {sc['ndx_e21']:,.0f}、50 日線 {sc['ndx_s50']:,.0f}）；QQQ 20 日波幅 {f(T.get('vol') or 0)}"
        if T.get("pend") is not None and T["pend"] != T["held"]:
            return dict(date=sc["date"], kind="switch", to="TQQQ" if T["pend"] else "IEF", why=[T.get("why_off") or ""] if not T["pend"] else [], detail=lv)
        why = []
        if T["held"]:
            if (T.get("vol") or 0) >= 0.30:
                why.append(f"QQQ 20 日波幅 {f(T['vol'])}，就快到 {int(vm * 100)}% 賣出線")
            if T["margin"] < 0.02:
                why.append(f"NDX 再跌大約 {f(T['margin'])} 就轉紅燈")
            if (T.get("gap21") or 0) < 0:
                why.append(f"NDX 跌穿 21 日 EMA（{f(T['gap21'])}）")
            if (T.get("gap50") or 0) < 0:
                why.append(f"NDX 跌穿 50 日線（{f(T['gap50'])}）")
            kind = "sell"
        else:
            if -0.02 < T["margin"] < 0 and (T.get("vol") or 0) < vm:
                why.append(f"NDX 再升大約 {f(T['margin'])} 就轉綠燈")
            if T["margin"] >= 0 and vm <= (T.get("vol") or 0) < vm + 0.05:
                why.append(f"大市綠燈，QQQ 20 日波幅 {f(T['vol'])} 回落到 {int(vm * 100)}% 以下就買")
            kind = "buy"
        return dict(date=sc["date"], kind=kind, why=why, detail=lv) if why else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- AI 宏觀思考（2026-10-02 用戶：想 AI 好似評論文章咁，畀多啲角度思考；冇客觀答案）
NL = chr(10)
THINK_GAP = int(os.environ.get("THINK_GAP_MIN", "360"))   # 分鐘：最少隔 6 個鐘先再寫；債息異動、轉燈就即刻寫
THINK_SYMS = [("SPY", "S&P 500"), ("RSP", "S&P 500 等權"), ("QQQ", "納指 100"), ("SMH", "半導體"), ("IWM", "羅素 2000 細價股"), ("^VIX", "VIX")]


def mkt_perf():
    """1 個月、3 個月表現（Yahoo 日線 6 個月）；VIX 用水平。"""
    out = []
    for s_, nm in THINK_SYMS:
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(s_)}?range=6mo&interval=1d", headers=UA), timeout=20).read())
            c = [x for x in d["chart"]["result"][0]["indicators"]["quote"][0]["close"] if x is not None]
            if s_ == "^VIX":
                out.append(f"VIX {c[-1]:.1f}（3 個月前 {c[-63]:.1f}）")
            else:
                out.append(f"{nm} 1 個月 {(c[-1] / c[-22] - 1) * 100:+.1f}%、3 個月 {(c[-1] / c[-64] - 1) * 100:+.1f}%")
        except Exception as e:  # noqa: BLE001
            print(f"[ai] {s_} 表現攞唔到：{e}")
    return out


def breadth():
    """scan.json 嘅股票（Nasdaq 成交額／市值頭幾百隻）有幾多高過 200 日線。"""
    try:
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
        v = [x for x in sc.get("stocks", {}).values() if x.get("sma200") and x.get("close")]
        return f"Nasdaq 大型股 {len(v)} 隻入面 {sum(1 for x in v if x['close'] > x['sma200']) / len(v) * 100:.0f}% 高過 200 日線" if v else ""
    except Exception:  # noqa: BLE001
        return ""


def gemini_search(key, prompt):
    """Gemini + Google 搜尋（grounding）；返 (dict, 型號)。唔得就退返冇搜尋嘅 gemini()。"""
    body = {"contents": [{"parts": [{"text": prompt + NL + "用 Google 搜尋補充最新背景，只根據搜尋結果同上面數據；最後只回覆一個 JSON object，唔好加其他文字。"}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.5}}
    last = ""
    for m in pick(key, MODELS_D):
        try:
            req = urllib.request.Request(API.format(m=m), data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
            d = json.loads(urllib.request.urlopen(req, timeout=180).read())
            txt = "".join(x.get("text", "") for x in d["candidates"][0]["content"]["parts"] if not x.get("thought"))
            j = re.search(r"\{.*\}", txt, re.S)
            if j:
                return json.loads(j.group(0)), m + "（Google 搜尋）"
            last = f"{m} 冇 JSON"
        except Exception as e:  # noqa: BLE001
            last = f"{m}：{str(e)[:80]}"
    print(f"[ai] 宏觀思考 Google 搜尋失敗（{last}），改用冇搜尋版本")
    return gemini(key, prompt, MODELS_D)


def think(key, N, P, now, force=False):
    """AI 宏觀思考：現象、核心問題、2–3 個情景（會點、確認訊號、對我哋規則嘅影響）、反方、要留意。返 (dict 或 None, 訊息)。"""
    old = P.get("think") or {}
    ra, lc = rates_alert(), light_change()
    trig = json.dumps([ra, lc], ensure_ascii=False)
    last = datetime.fromisoformat(old["at"]) if old.get("at") else None
    if not force and last and now - last < timedelta(minutes=THINK_GAP) and old.get("trig") == trig:
        return None, f"宏觀思考：上次 {int((now - last).total_seconds() // 60)} 分鐘前，沿用"
    heads = [x.get("zh") or x["title"] for x in N["items"] if x.get("cat") in ("市場", "經濟", "快訊", "國際")
             and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=36)][:45]
    R = load(OUTDIR / "rates.json") if OUTDIR else None
    rates = "；".join(f"{r['name']} {r['y']:.2f}%（1 個月 {r['m']:+.0f} 基點、一年 {r['yr']:+.0f} 基點）" for r in (R or {}).get("rows", [])) or "（冇）"
    F = load(OUTDIR / "fng.json") if OUTDIR else None
    fng = ""
    try:
        st_ = F["stock"]
        fng = (f"CNN 恐慌貪婪指數 {st_['score']:.0f}（{st_['rating']}；1 星期前 {st_['week']:.0f}、1 個月前 {st_['month']:.0f}、1 年前 {st_['year']:.0f}；"
               + "、".join(f"{x['name']} {x['score']:.0f}" for x in st_.get("parts", [])) + "）")
        if F.get("crypto") and F["crypto"].get("score") is not None:
            fng += f"；加密恐慌貪婪 {F['crypto']['score']:.0f}"
    except Exception:  # noqa: BLE001
        pass
    light, watch = context()
    tq = (lambda t: f"V2.3 TQQQ 腳而家{'揸 TQQQ' if t and t.get('held') else '揸 IEF'}" if t else "")(
        (json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8")).get("view") or {}).get("tq") if (ROOT / "docs" / "model_cont.json").exists() else None)
    prompt = (f"你係一個有獨立思考嘅美股宏觀評論人，幫一個香港散戶從多個角度諗而家個市。{STYLE}{NL}"
              f"佢嘅策略（規則唔會因為你嘅分析改變）：60% 美股大型科技龍頭動能（突破買、大市紅燈清倉）+ 40% TQQQ（綠燈而且 QQQ 波幅 < 35% 先揸）；加密睇 BTC 100 日線。"
              f"大市燈號而家係{light}；{tq}。{NL}"
              f"市場數據：{'；'.join(mkt_perf())}；{breadth()}；美債息：{rates}；{fng}。{NL}"
              f"今日實際數字：{snap_text(snapshot())}。{NL}"
              + (f"債息異動：{'；'.join(ra['alert'])}。{NL}" if ra else "") + (f"大市啱啱轉{lc['to']}。{NL}" if lc else "")
              + "最近 36 小時新聞標題：" + NL + NL.join(heads[:45]) + NL
              + "寫一份「宏觀思考」，好似專欄咁有觀點，但要講清楚冇客觀答案：" + NL
              + "1. phenomena：3–5 點而家最值得留意嘅現象（例如指數係咪靠少數大股撐住、市寬、債息、情緒去到幾極端），每點一句，要有上面嘅數字；" + NL
              + "2. question：而家投資最重要嘅一個問題（一句）；" + NL
              + "3. scenarios：2–3 個可能情景，每個有 name（短名）、what（會點發展，一至兩句）、signals（2–3 個睇到就代表呢個情景發生緊嘅具體訊號，例如某個數據、債息去到幾多、某條線）、"
              + "lean（你主觀覺得機會 較大／一半半／較細，同一句點解）、impact（對佢策略嘅影響：邊個燈號或者部分會先郁；規則照做，唔好叫人買賣）；" + NL
              + "4. contrarian：一段反方睇法（市場主流諗法可能錯喺邊）；" + NL
              + "5. watch：之後 1–2 星期要留意嘅數據或者事件（有日期就寫）。" + NL
              + "數字只可以用上面提供嘅或者搜尋到嘅，唔好作。回覆 JSON：{\"phenomena\": [..], \"question\": \"..\", \"scenarios\": [{\"name\": \"..\", \"what\": \"..\", "
              + "\"signals\": [..], \"lean\": \"..\", \"impact\": \"..\"}], \"contrarian\": \"..\", \"watch\": [..]}")
    res, model = gemini_search(key, prompt)
    if not res.get("scenarios"):
        raise RuntimeError(f"宏觀思考冇 scenarios：{json.dumps(res, ensure_ascii=False)[:200]}")
    d = dict(res, model=model, at=now.isoformat(timespec="seconds"), trig=trig,
             generated=now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"))
    return d, f"宏觀思考：用 {model} 寫好"


def crypto_digest(key, N, H, PH, out, now, force=False):
    """加密重點（2026-10-01）：加密快訊 + Hyperliquid 巨鯨持倉變動 + 市場數字 → 廣東話「發生咩 → 對 BTC／ETH／加密股可能有咩影響」。
    寫入 hyper.json 嘅 ai；最少隔 GAP 分鐘，有 ≥ 500 萬美元嘅新巨鯨事件或者手動更新就即刻重寫。"""
    old = PH.get("ai") or {}
    news = [x for x in N["items"] if x["cat"] == "加密" and datetime.fromisoformat(x["t"].replace("Z", "+00:00")) > now - timedelta(hours=18)]
    news.sort(key=lambda x: x["t"], reverse=True)
    ev = [e for e in H.get("events", []) if datetime.fromisoformat(e["t"].replace("Z", "+00:00")) > now - timedelta(hours=12)][:25]
    big = [e for e in ev if e["usd"] >= 5e6 and e["t"] == H.get("generated")]
    try:
        last = datetime.fromisoformat(old["at"])
    except Exception:  # noqa: BLE001
        last = None
    if last and now - last < timedelta(minutes=GAP) and not force and not big:
        return old, f"加密重點：上次係 {int((now - last).total_seconds() // 60)} 分鐘前，今次沿用"
    heads = [f"[{x['src']}] {x['title']}" for x in news[:30]]
    whales = [f"{e['who']} {e['act']} {e['coin']} 約 ${e['usd'] / 1e6:.1f}M（而家倉位 ${e['pos_usd'] / 1e6:.1f}M，{e.get('lev') or '?'} 倍）" for e in ev]
    agg = [f"{g['coin']}：巨鯨多倉 ${g['long'] / 1e6:.0f}M（{g['n_long']} 個）vs 空倉 ${g['short'] / 1e6:.0f}M（{g['n_short']} 個）" for g in H.get("agg", [])[:8]]
    C = H.get("ctx") or {}
    fmt = lambda v: f"{v:,.0f}" if v >= 100 else f"{v:.4g}"
    mk = [f"{c} {fmt(C[c]['px'])}（24 小時 {C[c]['chg'] * 100:+.1f}%，資金費率年化 {C[c]['fund_ann'] * 100:+.1f}%）" for c in ("BTC", "ETH", "SOL", "HYPE") if c in C and C[c].get("chg") is not None]
    F = load(out / "fng.json") or {}
    fg = (F.get("crypto") or {}).get("score")
    sig = hashlib.sha1(json.dumps([heads, whales], ensure_ascii=False).encode()).hexdigest()
    if old.get("sig") == sig and not force:
        return old, "加密新聞同巨鯨冇變，沿用"
    if not heads and not whales:
        return old, "冇加密新聞同巨鯨事件"
    prompt = (f"你係加密貨幣市場助手，幫一個香港散戶睇加密市場。{STYLE}佢用 BTC 做市場情緒（BTC > 365 日線 = 綠燈），只買賣 ETH，亦會留意 MSTR、COIN 呢類加密股。\n"
              f"市場實際數字（Hyperliquid 永續合約）：{'；'.join(mk) or '（冇）'}。加密恐慌貪婪指數：{fg if fg is not None else '—'}。\n"
              "根據下面最近 18 小時嘅加密新聞同 12 小時內 Hyperliquid 歷史盈利最高嘅巨鯨嘅倉位變動，寫：\n"
              "1. points：3–6 點最重要嘅事，每點一句「發生咩 → 對 BTC／ETH／加密股可能有咩影響」；\n"
              "2. whales：一至兩句總結巨鯨整體偏多定偏空、主要喺邊隻幣加減倉（冇資料就寫空字串）。\n"
              "事實規則：價錢升跌只可以用上面嘅實際數字；只根據提供嘅資料，唔好估未發生嘅事，唔好叫人買賣；巨鯨倉位只係參考，唔代表一定啱。\n"
              "回覆 JSON：{\"points\": [..], \"whales\": \"..\"}。\n"
              "新聞：\n" + ("\n".join(heads) or "（冇）") + "\n巨鯨倉位變動：\n" + ("\n".join(whales) or "（冇）")
              + "\n巨鯨而家總倉位：\n" + ("\n".join(agg) or "（冇）"))
    res, model = gemini(key, prompt, MODELS_D)
    pts = [x for x in res.get("points", []) if isinstance(x, str) and x.strip()][:6]
    if not pts:
        raise RuntimeError(f"回覆冇 points（{json.dumps(res, ensure_ascii=False)[:200]}）")
    return ({"at": now.isoformat(timespec="seconds"), "generated": now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"),
             "model": model, "points": pts, "whales": str(res.get("whales") or "").strip(), "sig": sig},
            f"加密重點 {len(pts)} 點（{model}）")


def main():
    global OUTDIR
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "feeds_out"
    OUTDIR = out
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("[ai] 冇 GEMINI_API_KEY，跳過")
        return
    N = load(out / "news.json")
    E = load(out / "econ.json") or {}
    S = load(out / "serenity_recent.json")
    T = load(out / "trump_recent.json")
    P, PS, PT = prev("news.json"), prev("serenity_recent.json"), prev("trump_recent.json")
    now = datetime.now(timezone.utc)
    errs = []
    # 1. 翻譯：每次都做（有新嘢先會用 Gemini）
    try:
        print("[ai] 翻譯：" + translate(key, N, S, P, PS, T, PT))
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
                r["ai"], r["ai_at"], r["ai_stage"], r["ai_model"] = o["ai"], o.get("ai_at"), o.get("ai_stage", 1), o.get("ai_model")
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
    lc = light_change()                                                  # 大市啱啱轉燈而上一份重點未講：即刻重寫
    if lc and (P.get("digest") or {}).get("light_change") != lc and last_ai:
        print(f"[ai] 大市 {lc['date']} 轉{lc['to']}，即刻重寫今日重點")
        last_ai = None
    ra = rates_alert()                                                   # 債息急升／新高而上一份重點未講：即刻重寫
    if ra and (P.get("digest") or {}).get("rates_alert") != ra and last_ai:
        print(f"[ai] 債息 {ra['alert']}，即刻重寫今日重點")
        last_ai = None
    ta = tq_alert()                                                      # TQQQ 黃燈／轉換而上一份重點未講：即刻重寫
    if ta and (P.get("digest") or {}).get("tq_alert") != ta and last_ai:
        print(f"[ai] TQQQ {ta['kind']}（{ta['date']}），即刻重寫今日重點")
        last_ai = None
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"   # app 撳「重新整理」叫嘅：即刻重寫
    if manual:
        print("[ai] 手動更新：即刻重寫今日重點")
        last_ai = None
    if last_ai and now - last_ai < timedelta(minutes=GAP):
        if P.get("digest"):
            N["digest"] = P["digest"]
        N["ai_at"] = P["ai_at"]
        print(f"[ai] 今日重點：上次係 {int((now - last_ai).total_seconds() // 60)} 分鐘前，今次沿用")
    else:
        N["ai_at"] = now.isoformat(timespec="seconds")
        try:
            d, msg = digest(key, N, E, P, now, force=manual, T=T, Sr=S)
            if d:
                N["digest"] = d
            print("[ai] " + msg)
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 重點失敗：{e}")
            errs.append(f"重點：{str(e)[:300]}")
            if P.get("digest"):
                N["digest"] = P["digest"]
    # 3b. AI 宏觀思考：每 6 個鐘；債息異動或者轉燈就即刻寫；失敗沿用上一份
    try:
        d, msg = think(key, N, P, now, force=manual)
        N["think"] = d or P.get("think")
        print("[ai] " + msg)
    except Exception as e:  # noqa: BLE001
        print(f"[ai] 宏觀思考失敗：{e}")
        errs.append(f"宏觀思考：{str(e)[:300]}")
        if P.get("think"):
            N["think"] = P["think"]
    # 4. 加密重點（hyper.json 嘅 ai）
    H = load(out / "hyper.json")
    if H is not None:
        PH = prev("hyper.json")
        try:
            d, msg = crypto_digest(key, N, H, PH, out, now, force=manual)
            if d:
                H["ai"] = d
            print("[ai] " + msg)
        except Exception as e:  # noqa: BLE001
            print(f"[ai] 加密重點失敗：{e}")
            errs.append(f"加密重點：{str(e)[:300]}")
            if PH.get("ai"):
                H["ai"] = PH["ai"]
        (out / "hyper.json").write_text(json.dumps(H, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if errs:
        N["ai_err"] = "；".join(errs)
    (out / "news.json").write_text(json.dumps(N, ensure_ascii=False), encoding="utf-8")
    if E:
        (out / "econ.json").write_text(json.dumps(E, ensure_ascii=False), encoding="utf-8")
    if T is not None:
        (out / "trump_recent.json").write_text(json.dumps(T, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if S is not None:
        (out / "serenity_recent.json").write_text(json.dumps(S, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
