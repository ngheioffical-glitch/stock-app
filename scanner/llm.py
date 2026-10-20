"""AI 接駁層（2026-10-20 用戶：「將 gemini 換成 opus 5.5，effort 用 high」「要預計可能會轉 AI，功能維持不變」；
退返 Gemini 要標明；用 API key；新聞都用 Opus high）。

所有 AI 功能經呢度叫，換供應商只改環境變數，唔使改功能：
  ask(prompt, gem_models=None, timeout=None)    → (dict, 型號標籤)：要一個 JSON object；全部供應商都失敗就 raise RuntimeError。
  search(prompt, gem_models=None, timeout=None) → (dict 或 None, 標籤, 有冇真係上網查證, 來源清單)：
      Claude 分兩步（先搜尋、再用另一個請求寫 JSON），因為佢嘅搜尋引用同固定 JSON 格式唔可以喺同一個請求。
供應商次序：AI_PROVIDER（預設 claude）先，再試 AI_FALLBACK（預設 gemini,github）。用咗後備，標籤寫明「後備」同原因。
Claude：key 只由環境變數 ANTHROPIC_API_KEY 讀（GitHub Secrets）；AI_MODEL 預設 claude-opus-5-5、AI_EFFORT 預設 high
  （Opus 5.5 預設係 medium，所以一定要寫明）；開 server-side fallback（拒答時 Anthropic 自己轉後備型號）；全部用串流。
Gemini：GEMINI_API_KEY；GitHub Models：GITHUB_TOKEN（workflow 要 permissions: models: read）。
用量：每次 Claude 請求記 token、搜尋次數同估計美元（USAGE）；AI_DAILY_BUDGET_USD（預設 20，香港時間每日計）用晒就唔再叫 Claude，
  退後備並標明。跨運行嘅累計要由調用者用 load_usage()／usage_record() 讀寫（ai.py 放喺 feeds 分支 ai_usage.json）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
PROVIDER = os.environ.get("AI_PROVIDER", "claude").strip().lower()
FALLBACK = [x.strip().lower() for x in os.environ.get("AI_FALLBACK", "gemini,github").split(",") if x.strip()]
MODEL = os.environ.get("AI_MODEL", "claude-opus-5-5").strip()
EFFORT = os.environ.get("AI_EFFORT", "high").strip()
MAX_SEARCH = int(os.environ.get("AI_MAX_SEARCH", "5"))
MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "32000"))     # effort high 嘅思考都計入輸出；太細會截斷（只按實際用量收費）
BUDGET = float(os.environ.get("AI_DAILY_BUDGET_USD", "20"))
# 價錢（美元）：Opus 5.5 官方每百萬 token 輸入 4、輸出 20、讀緩存 0.2（2026-10）；寫緩存 5、搜尋每次 0.01 係估計。可以用環境變數改。
PRICE = dict(inp=float(os.environ.get("AI_PRICE_IN", "4")), out=float(os.environ.get("AI_PRICE_OUT", "20")),
             cache_read=float(os.environ.get("AI_PRICE_CACHE_READ", "0.2")), cache_write=float(os.environ.get("AI_PRICE_CACHE_WRITE", "5")),
             search=float(os.environ.get("AI_PRICE_SEARCH", "0.01")))
NAMES = {"claude-opus-5-5": "Claude Opus 5.5", "claude-opus-5": "Claude Opus 5", "claude-sonnet-5-5": "Claude Sonnet 5.5",
         "claude-haiku-5-5": "Claude Haiku 5.5", "claude-fable-5-1": "Claude Fable 5.1"}
JSON_SYS = "你只可以回覆一個 JSON object，唔好加其他文字。"
SEARCH_SYS = "你係財經研究助手。先用網上搜尋查證同補充最新資料，再用文字列出重點；每一點都要註明來源網址。唔肯定就講唔肯定，唔好估。"
SEARCH_ASK = "\n\n請先用網上搜尋查證同補充最新背景（最多 {n} 次），然後用文字列出你搵到嘅重點，每點註明來源網址。今次唔使寫 JSON。"
JSON_ASK = ("\n\n【網上搜尋結果（{day}）】\n{find}\n\n【來源】\n{src}\n\n只根據上面數據同搜尋結果答；唔肯定就答 unknown。"
            "最後只回覆一個 JSON object，唔好加其他文字。")

USAGE: list[dict] = []           # 今次運行每個 Claude 請求
SPENT_BEFORE = 0.0                # 今日（香港時間）之前運行已用
DAY = datetime.now(HKT).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 共用
def _json(txt):
    """由 AI 回覆攞出 JSON object：直接讀 → 去 ``` → 搵第一個 {…}。"""
    t = (txt or "").strip()
    for cand in (t, re.sub(r"^```(?:json)?\s*|\s*```$", "", t)):
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        v = json.loads(m.group(0))
        if isinstance(v, dict):
            return v
    raise ValueError("回覆唔係 JSON object")


def _left(deadline, cap):
    left = deadline - time.time()
    if left < 10:
        raise RuntimeError("AI 時間用晒")
    return min(cap, left)


def label_claude():
    return f"{NAMES.get(MODEL, MODEL)}（effort {EFFORT}）"


def spent_today():
    return SPENT_BEFORE + sum(u["usd"] for u in USAGE)


def available():
    """有冇任何一個供應商有 key（冇就成個 AI 步驟跳過）。"""
    return any((p == "claude" and os.environ.get("ANTHROPIC_API_KEY", "").strip()) or
               (p == "gemini" and os.environ.get("GEMINI_API_KEY", "").strip()) or
               (p == "github" and os.environ.get("GITHUB_TOKEN", "").strip()) for p in _order())


def _order():
    return [PROVIDER] + [p for p in FALLBACK if p != PROVIDER]


def _why(err):
    """後備原因（俾 app 顯示）。"""
    e = str(err)
    if "預算" in e:
        return "Claude 今日預算用晒"
    if "冇 ANTHROPIC_API_KEY" in e:
        return "未設定 Claude key"
    if "拒答" in e:
        return "Claude 拒答"
    if re.search(r"429|rate|overloaded|529", e, re.I):
        return "Claude 繁忙／額度"
    return "Claude 出錯"


# ---------------------------------------------------------------- 用量
def load_usage(d):
    """d：上一份 ai_usage.json（dict 或 None）。同一日（香港時間）就接住計。"""
    global SPENT_BEFORE
    SPENT_BEFORE = float(d.get("spent", 0)) if d and d.get("day") == DAY else 0.0


def usage_record(prev=None):
    """寫入 ai_usage.json 嘅內容：今日累計、今次運行、最近 40 個請求。"""
    calls = ((prev or {}).get("calls", []) if (prev or {}).get("day") == DAY else []) + USAGE
    return dict(day=DAY, spent=round(spent_today(), 4), budget=BUDGET, model=MODEL, effort=EFFORT,
                provider=PROVIDER, fallback=FALLBACK, runs=int(((prev or {}).get("runs", 0) if (prev or {}).get("day") == DAY else 0)) + 1,
                calls=calls[-40:])


_PREV = None


def start(out=None):
    """開始時讀今日用量：今次運行之前嘅步驟（out/ai_usage.json）→ 上一次 feeds 運行（feeds 分支）。讀唔到就由 0 計。"""
    global _PREV
    from pathlib import Path
    f = Path(out) / "ai_usage.json" if out else None
    try:
        if f and f.exists():
            _PREV = json.loads(f.read_text(encoding="utf-8"))
        elif os.environ.get("GITHUB_REPOSITORY"):
            url = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/feeds/ai_usage.json"
            _PREV = json.loads(urllib.request.urlopen(url, timeout=15).read())
    except Exception as e:  # noqa: BLE001
        print(f"[llm] 讀唔到之前用量（由 0 計）：{str(e)[:80]}")
        _PREV = None
    load_usage(_PREV)


def finish(out):
    """寫 out/ai_usage.json（feeds workflow 會推上 feeds 分支，俾下一次運行接住計）。"""
    from pathlib import Path
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "ai_usage.json").write_text(json.dumps(usage_record(_PREV), ensure_ascii=False), encoding="utf-8")


def status():
    """俾 app 顯示嘅 AI 狀態。"""
    return dict(provider=PROVIDER, model=label_claude() if PROVIDER == "claude" else PROVIDER, spent=round(spent_today(), 2),
                budget=BUDGET, day=DAY, calls=len(USAGE))


def _log(msg, secs, kind):
    u = msg.usage
    st = getattr(u, "server_tool_use", None)
    n_search = int(getattr(st, "web_search_requests", 0) or 0) if st else 0
    rec = dict(t=datetime.now(HKT).strftime("%H:%M:%S"), kind=kind, model=getattr(msg, "model", MODEL), secs=round(secs, 1),
               inp=int(u.input_tokens or 0), out=int(u.output_tokens or 0),
               cr=int(getattr(u, "cache_read_input_tokens", 0) or 0), cw=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
               search=n_search, stop=getattr(msg, "stop_reason", None))
    rec["usd"] = round((rec["inp"] * PRICE["inp"] + rec["out"] * PRICE["out"] + rec["cr"] * PRICE["cache_read"] +
                        rec["cw"] * PRICE["cache_write"]) / 1e6 + n_search * PRICE["search"], 5)
    USAGE.append(rec)
    print(f"[llm] {kind} {rec['model']} {secs:.0f} 秒｜輸入 {rec['inp']:,}｜輸出 {rec['out']:,}｜搜尋 {n_search}｜約 US${rec['usd']:.3f}"
          f"（今日 US${spent_today():.2f}／上限 {BUDGET:g}）")
    return rec


# ---------------------------------------------------------------- Claude（Anthropic 官方 SDK）
def _claude_client(timeout):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("claude：冇 ANTHROPIC_API_KEY")
    if spent_today() >= BUDGET:
        raise RuntimeError(f"claude：今日預算 US${BUDGET:g} 用晒")
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=1, timeout=timeout)


def _claude_call(messages, system, timeout, kind, tools=None, max_tokens=None):
    cl = _claude_client(timeout)
    kw = dict(model=MODEL, max_tokens=max_tokens or MAX_TOKENS, system=system, messages=messages,
              output_config={"effort": EFFORT}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if tools:
        kw["tools"] = tools
    t0 = time.time()
    with cl.beta.messages.stream(**kw) as s:
        msg = s.get_final_message()
    _log(msg, time.time() - t0, kind)
    if msg.stop_reason == "refusal":
        raise RuntimeError("claude：拒答（refusal）")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("claude：回覆太長（max_tokens）")
    return msg


def _text(msg):
    return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


def _sources(msgs):
    """由搜尋結果同引用攞來源（網址去重，最多 12 個）：[{title, url, age}]。"""
    out, seen = [], set()

    def add(url, title, age=None):
        if url and url not in seen:
            seen.add(url)
            out.append(dict(title=(title or "").strip()[:160], url=url, age=age))
    for m in msgs:
        for b in m.content:
            for ci in (getattr(b, "citations", None) or []):
                add(getattr(ci, "url", None), getattr(ci, "title", ""))
    for m in msgs:
        for b in m.content:
            if getattr(b, "type", "") == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
                for r in b.content:
                    if getattr(r, "type", "") == "web_search_result":
                        add(r.url, r.title, getattr(r, "page_age", None))
    return out[:12]


def _claude_ask(prompt, timeout):
    msg = _claude_call([{"role": "user", "content": prompt}], JSON_SYS, timeout, "ask")
    return _json(_text(msg)), label_claude()


def _claude_search(prompt, timeout):
    deadline = time.time() + timeout
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCH}]
    msgs, got = [{"role": "user", "content": prompt + SEARCH_ASK.format(n=MAX_SEARCH)}], []
    for _ in range(4):                                   # 搜尋太耐會 pause_turn：將回覆接返落去繼續
        m = _claude_call(msgs, SEARCH_SYS, _left(deadline, timeout * 0.65), "search", tools=tools)
        got.append(m)
        if m.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": m.content}]
    find = "\n".join(_text(m) for m in got).strip() or "（搜尋冇結果）"
    src = _sources(got)
    n_search = sum(u["search"] for u in USAGE[-len(got):])
    grounded = bool(src) and n_search > 0
    srct = "\n".join(f"[S{i + 1}] {s['title']} — {s['url']}" for i, s in enumerate(src)) or "（冇）"
    m2 = _claude_call([{"role": "user", "content": prompt + JSON_ASK.format(day=DAY, find=find[:12000], src=srct)}],
                      JSON_SYS, _left(deadline, timeout), "json")
    tag = "、".join(s["title"] for s in src[:3] if s["title"]) or "冇列出來源"
    return _json(_text(m2)), f"{label_claude()}（上網搜尋 {n_search} 次：{tag}）", grounded, src


# ---------------------------------------------------------------- Gemini（後備；2026-10-20 前係主力，代碼由 ai.py 搬過嚟）
GEM_API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
GEM_D = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest",
                     "gemini-2.5-flash-lite") if m]
GEM_T = [m for m in (os.environ.get("GEMINI_MODEL_T"), "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
                     "gemini-flash-latest") if m]
_AVAIL = None


def gem_models(key):
    """問 Google 呢條 key 有邊啲 generateContent 型號（每次運行問一次）；問唔到就回 []（照原本次序試）。"""
    global _AVAIL
    if _AVAIL is None:
        try:
            req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", headers={"x-goog-api-key": key})
            d = json.loads(urllib.request.urlopen(req, timeout=30).read())
            _AVAIL = [m["name"].split("/", 1)[1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception as e:  # noqa: BLE001
            print(f"[llm] Gemini 型號清單攞唔到：{e}")
            _AVAIL = []
    return _AVAIL


def gem_pick(key, base):
    av = gem_models(key)
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
    return (groups[0] + groups[1]) or base


def _gem_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("gemini：冇 GEMINI_API_KEY")
    return key


def _gemini_ask(prompt, models_, timeout):
    key, deadline = _gem_key(), time.time() + timeout
    gen = {"responseMimeType": "application/json", "temperature": 0.3}
    last, errs = None, []
    for m in gem_pick(key, models_ or GEM_D):
        for think_off in (True, False):       # 先試關閉「思考」（快好多）；型號唔支援就用預設
            g = dict(gen, thinkingConfig={"thinkingBudget": 0}) if think_off else gen
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": g}).encode()
            for attempt in range(2):
                req = urllib.request.Request(GEM_API.format(m=m), data=body, method="POST",
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                try:
                    with urllib.request.urlopen(req, timeout=_left(deadline, 180)) as r:
                        d = json.loads(r.read())
                    parts = d["candidates"][0]["content"]["parts"]
                    return _json("".join(p.get("text", "") for p in parts if not p.get("thought"))), m
                except urllib.error.HTTPError as e:
                    last = f"{m}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'ignore')}"
                    if e.code in (500, 503) and attempt == 0 and deadline - time.time() > 60:
                        time.sleep(10)            # 伺服器忙：等陣再試一次（429 額度用完就唔等，直接試下一個型號）
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    last = f"{m}: {type(e).__name__} {e}"
                    break
            if last and "HTTP 400" not in last:
                break
        if last:
            code = re.search(r"HTTP (\d+)", last)
            errs.append(f"{m} {code.group(1) if code else last.split(':', 1)[-1].strip()[:40]}")
        if last and not any(c in last for c in ("HTTP 404", "HTTP 400", "HTTP 429", "HTTP 500", "HTTP 503")):
            break                                 # 網絡問題：換型號都冇用
    raise RuntimeError(f"gemini：全部型號失敗（{'、'.join(errs)}）；最後：{last}")


def _gemini_search(prompt, timeout):
    key, deadline = _gem_key(), time.time() + timeout
    body = {"contents": [{"parts": [{"text": prompt + "\n用 Google 搜尋補充最新背景同查證，只根據搜尋結果同上面數據；唔肯定就答 unknown。"
                                                      "最後只回覆一個 JSON object，唔好加其他文字。"}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.3}}
    last = ""
    for m in gem_pick(key, GEM_D):
        try:
            req = urllib.request.Request(GEM_API.format(m=m), data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
            d = json.loads(urllib.request.urlopen(req, timeout=_left(deadline, 180)).read())
            c = d["candidates"][0]
            txt = "".join(x.get("text", "") for x in c["content"]["parts"] if not x.get("thought"))
            chunks = (c.get("groundingMetadata") or {}).get("groundingChunks", [])
            src = [dict(title=w.get("web", {}).get("title", ""), url=w.get("web", {}).get("uri", ""), age=None) for w in chunks][:12]
            tag = "、".join(s["title"] for s in src[:3] if s["title"]) or "冇列出來源"
            return _json(txt), f"{m}（Google 搜尋：{tag}）", bool(src), src
        except Exception as e:  # noqa: BLE001
            last = f"{m}：{str(e)[:80]}"
    raise RuntimeError(f"gemini：搜尋失敗（{last}）")


# ---------------------------------------------------------------- GitHub Models（最後後備；冇上網）
GH_API = "https://models.github.ai/inference/chat/completions"
GH_MODELS = [m for m in (os.environ.get("GH_MODEL"), "openai/gpt-4.1-mini", "openai/gpt-4o-mini", "deepseek/deepseek-v3-0324") if m]


def _github(prompt, timeout):
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("github：冇 GITHUB_TOKEN")
    deadline, errs = time.time() + timeout, []
    for m in GH_MODELS:
        for fmt in (True, False):                  # 先要求 JSON 格式；型號唔支援（400）就唔要
            body = {"model": m, "temperature": 0.3,
                    "messages": [{"role": "system", "content": JSON_SYS}, {"role": "user", "content": prompt}]}
            if fmt:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(GH_API, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                                  "Authorization": f"Bearer {tok}", "X-GitHub-Api-Version": "2022-11-28"})
            try:
                with urllib.request.urlopen(req, timeout=_left(deadline, 120)) as r:
                    d = json.loads(r.read())
                return _json(d["choices"][0]["message"]["content"]), "github:" + m
            except urllib.error.HTTPError as e:
                errs.append(f"{m} {e.code}")
                if e.code == 400 and fmt:
                    continue
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{m} {type(e).__name__}")
                break
    raise RuntimeError("github：GitHub Models 失敗（" + "、".join(errs) + "）")


# ---------------------------------------------------------------- 對外
def ask(prompt, gem_models=None, timeout=None):
    """要一個 JSON object。返 (dict, 型號標籤)；用咗後備，標籤會寫「後備：原因」。全部失敗 raise RuntimeError（訊息有齊每個供應商嘅錯）。"""
    timeout = timeout or 300
    errs = []
    for p in _order():
        try:
            if p == "claude":
                res, lab = _claude_ask(prompt, timeout)
            elif p == "gemini":
                res, lab = _gemini_ask(prompt, gem_models, timeout)
            elif p == "github":
                res, lab = _github(prompt, timeout)
            else:
                continue
            if errs:
                lab += f"（後備：{_why(errs[0])}）"
                print(f"[llm] 用咗後備 {lab}；之前：{'；'.join(errs)[:300]}")
            return res, lab
        except Exception as e:  # noqa: BLE001
            errs.append(f"{p}：{str(e)[:240]}" if not str(e).startswith(p) else str(e)[:260])
    raise RuntimeError("；".join(errs) or "冇可用嘅 AI 供應商")


def search(prompt, gem_models=None, timeout=None):
    """先上網搜尋再寫 JSON。返 (dict 或 None, 標籤, grounded, 來源)；grounded = 真係搜尋過而且有來源。
    全部有搜尋嘅供應商都失敗就回 (None, 原因, False, [])，由調用者決定要唔要用冇上網嘅 ask()。"""
    timeout = timeout or 420
    errs = []
    for p in _order():
        try:
            if p == "claude":
                res, lab, g, src = _claude_search(prompt, timeout)
            elif p == "gemini":
                res, lab, g, src = _gemini_search(prompt, timeout)
            else:
                continue                                     # GitHub Models 冇上網搜尋
            if errs:
                lab += f"（後備：{_why(errs[0])}）"
            return res, lab, g, src
        except Exception as e:  # noqa: BLE001
            errs.append(f"{p}：{str(e)[:240]}" if not str(e).startswith(p) else str(e)[:260])
    return None, "；".join(errs) or "冇可以上網搜尋嘅 AI 供應商", False, []
