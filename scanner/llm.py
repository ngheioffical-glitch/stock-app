"""AI 接駁層（2026-10-20 用戶：「將 gemini 換成 opus 5.5，effort 用 high」「要預計可能會轉 AI，功能維持不變」；
退返 Gemini 要標明；用 API key；新聞都用 Opus high）。

所有 AI 功能經呢度叫，換供應商只改環境變數，唔使改功能：
  ask(prompt, gem_models=None, timeout=None)    → (dict, 型號標籤)：要一個 JSON object；全部供應商都失敗就 raise RuntimeError。
      schema=（JSON Schema）：Claude 用官方固定格式（output_config.format），保證格式啱；後備供應商就將格式寫入提示。
  search(prompt, gem_models=None, timeout=None) → (dict 或 None, 標籤, 有冇真係上網查證, 來源清單)：
      Claude 分兩步（先搜尋、再用另一個請求寫 JSON），因為佢嘅搜尋引用同固定 JSON 格式唔可以喺同一個請求。
  gather(prompt, max_search, timeout, first)    → (筆記, 來源清單, 標籤, 搜尋次數)：淨係上網搜尋同寫筆記，
      筆記每句後面標 [S#]（由 first 開始編號），俾研究報告（research.py）之後幾步用同一套來源編號。
供應商次序：AI_PROVIDER（2026-10-21 起預設 gemini，用戶「AI唔好轉住」）先，再試 AI_FALLBACK（預設冇，唔會自動轉去收費供應商）；
  個別功能可以設 llm.ORDER（研究報告 = ["claude", "gemini"]）。用咗後備，標籤寫明「後備」同原因。timeout 係成個調用嘅總上限。
Claude：key 只由環境變數 ANTHROPIC_API_KEY 讀（GitHub Secrets）；AI_MODEL 預設 claude-opus-5-5、AI_EFFORT 預設 high
  （Opus 5.5 預設係 medium，所以一定要寫明）；開 server-side fallback（拒答時 Anthropic 自己轉後備型號，標籤會照實際型號寫）；全部用串流。
Gemini：GEMINI_API_KEY。DeepSeek（2026-10-23，收錢、預付）：DEEPSEEK_API_KEY，有就自動做主力（ask＝Chat Completions；search／gather＝
  Search API 搵資料再叫佢寫），每日 AI_PAID_DAILY_USD／試用 AI_PAID_TOTAL_USD 上限（跨流程帳本 AI_LEDGER），超咗退 Gemini。Mistral（2026-10-22）：MISTRAL_API_KEY，有就做主力（ask），冇上網搜尋。Groq 封香港用唔到。GitHub Models 2026-07-30 停用，已經拎走。
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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
# 2026-10-21 用戶：「AI唔好轉住」→ 預設照用 Gemini、唔自動轉去其他供應商（唔會靜靜雞用錢）；轉 Claude 就設 AI_PROVIDER=claude。
# GitHub Models 2026-07-30 已經停用，拎走咗。
# 2026-10-22 用戶：「gemini 每次都爆哂」想用 Groq，但 Groq 封香港（開唔到帳戶）→ 改用 Mistral 免費模式（香港用得）：有 MISTRAL_API_KEY 就由
# Mistral 做唔使上網嘅工作（翻譯、今日重點、雷達、研究分析），Gemini 做後備；要上網搜尋嘅（search／gather）照用 Gemini（Mistral 搜尋要錢）。
# 2026-10-22 用戶：「試qwen」→ 接咗 Qwen 香港區（commit c4d97cc，未 push 過）；2026-10-23 用戶：「我決定用deepseek」→ 換做 DeepSeek，
# Qwen 代碼拎走（要返可以由 c4d97cc 抄）。有 DEEPSEEK_API_KEY 就由 DeepSeek 做晒（普通對答 + 上網搜尋 + 研究），Gemini 做後備；
# 收錢（預付增值），所以有每日／試用總額上限（AI_PAID_DAILY_USD、AI_PAID_TOTAL_USD），超咗自動退 Gemini 並標明。
_MIS_ON = bool(os.environ.get("MISTRAL_API_KEY", "").strip())
_DS_ON = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
PROVIDER = os.environ.get("AI_PROVIDER", "deepseek" if _DS_ON else "mistral" if _MIS_ON else "gemini").strip().lower()
FALLBACK = [x.strip().lower() for x in os.environ.get("AI_FALLBACK", "gemini" if PROVIDER != "gemini" else "").split(",") if x.strip()]
ORDER: list[str] | None = None   # 個別功能指定次序（例如研究報告要 Claude 起頭：research.py 設 ["claude", "gemini"]）
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

# DeepSeek（2026-10-23 官方價目表）：每百萬 token（讀緩存輸入, 冇緩存輸入, 輸出），繁忙時段價；非繁忙半價。
# 繁忙 = UTC 01–04、06–10 時（香港 09–12、14–18 時），星期一至五；中國公眾假期本身係非繁忙，程式照當繁忙計（寧願高估）。
DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DS_FAST = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash").strip()            # 翻譯、今日重點、雷達、上網搜尋查證
DS_SMART = os.environ.get("DEEPSEEK_MODEL_SMART", "deepseek-v4-pro").strip()    # 研究報告（搵資料筆記 + 分析）
DS_PRICE = {"flash": (0.006, 0.30, 1.20), "pro": (0.044, 1.32, 3.96)}
DS_SEARCH_USD = float(os.environ.get("DEEPSEEK_PRICE_SEARCH", "0.00075"))     # Search API：有結果先收錢，每千次 US$0.75
DS_QUERIES = int(os.environ.get("DEEPSEEK_MAX_SEARCH", "5"))                  # 每個答案最多搜幾次（研究搵資料最多 +3）
DS_RESULTS = int(os.environ.get("DEEPSEEK_SEARCH_COUNT", "6"))                # 每次搜尋攞幾多條結果（唔影響價錢）
# 收錢 AI 嘅上限（2026-10-22 Qwen 試用時定：每日 US$1、試用總額 US$10，老師冇反對；DeepSeek 照用）
PAID = ("deepseek",)
PAID_DAY_USD = float(os.environ.get("AI_PAID_DAILY_USD", "1"))                # 每日（香港時間）上限，所有流程加埋
PAID_TOTAL_USD = float(os.environ.get("AI_PAID_TOTAL_USD", "10"))             # 試用總額上限，所有流程加埋
# 跨流程帳本：每個 workflow 寫自己嘅 ai_usage（paid.today／total 只計自己），開始時讀晒其他流程嘅加埋，上限先準（2026-10-22 Codex 改卷）
LEDGER = os.environ.get("AI_LEDGER", "feeds").strip()
LEDGERS = {"feeds": "feeds/ai_usage.json", "radar": "radar/ai_usage.json", "scan": "main/docs/ai_usage_scan.json",
           "research": "main/docs/ai_usage_research.json"}
_PD = dict(own_today=0.0, own_total=0.0, other_today=0.0, other_total=0.0, loaded=False)

USAGE: list[dict] = []           # 今次運行每個收錢 AI 請求（Claude、DeepSeek；prov 欄分）
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


def label_claude(msgs=None):
    """型號標籤。Anthropic server-side fallback 自動轉咗型號，就照實際回覆嘅型號寫，標明後備（2026-10-21 Codex 改卷）。"""
    used = sorted({str(getattr(m, "model", "") or "") for m in (msgs or [])} - {""})
    other = [u for u in used if not u.startswith(MODEL)]
    if other:
        return "、".join(NAMES.get(u, u) for u in other) + f"（後備：Anthropic 自動由 {NAMES.get(MODEL, MODEL)} 轉型號）"
    return f"{NAMES.get(MODEL, MODEL)}（effort {EFFORT}）"


def spent_today():
    return SPENT_BEFORE + sum(u["usd"] for u in USAGE)


def available():
    """有冇任何一個供應商有 key（冇就成個 AI 步驟跳過）。"""
    return any(has_key(p) for p in _order())


def has_key(p):
    return bool(os.environ.get({"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "mistral": "MISTRAL_API_KEY",
                            "deepseek": "DEEPSEEK_API_KEY"}.get(p, "_"), "").strip())


def _order():
    if ORDER:
        return list(ORDER)
    return [PROVIDER] + [p for p in FALLBACK if p != PROVIDER]


def _why(err):
    """後備原因（俾 app 顯示）：寫明係邊個供應商出事（2026-10-21：之前一律寫 Claude）。"""
    e = str(err)
    who = {"gemini": "Gemini", "mistral": "Mistral", "deepseek": "DeepSeek"}.get(e.split("：", 1)[0].strip().lower(), "Claude")
    if "試用總預算" in e:
        return f"{who} 試用預算用晒"
    if "預算" in e:
        return f"{who} 今日預算用晒"
    if "冇 ANTHROPIC_API_KEY" in e:
        return "未設定 Claude key"
    if "冇 GEMINI_API_KEY" in e:
        return "未設定 Gemini key"
    if "冇 MISTRAL_API_KEY" in e:
        return "未設定 Mistral key"
    if "冇 DEEPSEEK_API_KEY" in e:
        return "未設定 DeepSeek key"
    if "HTTP 402" in e:
        return f"{who} 餘額用晒（要增值）"
    if "拒答" in e:
        return f"{who} 拒答"
    if re.search(r"429|rate|overloaded|529|額度", e, re.I):
        return f"{who} 繁忙／額度"
    return f"{who} 出錯"


# ---------------------------------------------------------------- 用量
def load_usage(d):
    """d：上一份 ai_usage.json（dict 或 None）。同一日（香港時間）就接住計。"""
    global SPENT_BEFORE
    SPENT_BEFORE = float(d.get("spent", 0)) if d and d.get("day") == DAY else 0.0


def usage_record(prev=None):
    """寫入 ai_usage.json 嘅內容：今日累計、今次運行、最近 40 個請求；paid = 呢個流程自己嘅收錢 AI（DeepSeek）用量（今日、試用至今）。
    冇讀收錢 AI 帳本（冇 key）就抄返之前嗰份，唔好寫 0 洗走試用累計（抄錯咗只會令上限早啲到，唔會多用錢）。"""
    calls = ((prev or {}).get("calls", []) if (prev or {}).get("day") == DAY else []) + USAGE
    run = _paid_run()
    return dict(day=DAY, spent=round(spent_today(), 4), budget=BUDGET, model=MODEL, effort=EFFORT,
                provider=PROVIDER, fallback=FALLBACK, runs=int(((prev or {}).get("runs", 0) if (prev or {}).get("day") == DAY else 0)) + 1,
                calls=calls[-40:], paid=dict(day=DAY, today=round(_PD["own_today"] + run, 5), total=round(_PD["own_total"] + run, 5),
                                             cap_day=PAID_DAY_USD, cap_total=PAID_TOTAL_USD) if _PD["loaded"] else (prev or {}).get("paid"))


_PREV = None


def _raw(path):
    repo = os.environ.get("GITHUB_REPOSITORY") or "ngheioffical-glitch/stock-app"
    return json.loads(urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{path}", timeout=15).read())


def start(out=None, fname="ai_usage.json"):
    """開始時讀今日用量：今次運行之前嘅步驟（out/fname）→ 自己流程上一次運行（LEDGERS[AI_LEDGER]；2026-10-23 之前一律讀 feeds，
    雷達帳本會抄埋新聞嘅請求，app「AI 用量」加埋就重複計）。讀唔到就由 0 計。
    有收錢 AI（DeepSeek）key 就順便讀晒各流程嘅收錢 AI 帳本（_paid_load）。"""
    global _PREV
    from pathlib import Path
    f = Path(out) / fname if out else None
    try:
        if f and f.exists():
            _PREV = json.loads(f.read_text(encoding="utf-8"))
        elif os.environ.get("GITHUB_REPOSITORY"):
            _PREV = _raw(LEDGERS.get(LEDGER, "feeds/ai_usage.json"))
    except Exception as e:  # noqa: BLE001
        print(f"[llm] 讀唔到之前用量（由 0 計）：{str(e)[:80]}")
        _PREV = None
    load_usage(_PREV)
    if any(has_key(p) for p in PAID):
        _paid_load(out, fname)


def finish(out, fname="ai_usage.json"):
    """寫 out/fname（feeds、radar 推上自己分支；每日掃描、研究 commit 落 main），俾下一次運行同其他流程接住計。"""
    from pathlib import Path
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / fname).write_text(json.dumps(usage_record(_PREV), ensure_ascii=False), encoding="utf-8")


def _paid_load(out=None, fname="ai_usage.json"):
    """讀各流程帳本：自己（本機 out/fname 優先）同其他流程（GitHub 上面最新嗰份）今日同試用至今用咗幾多收錢 AI。讀唔到當 0。"""
    from pathlib import Path
    own_t = own_all = oth_t = oth_all = 0.0
    for name, path in LEDGERS.items():
        d = None
        try:
            f = Path(out) / fname if out else None
            if name == LEDGER and f and f.exists():
                d = json.loads(f.read_text(encoding="utf-8"))
            else:
                d = _raw(path)
        except Exception:  # noqa: BLE001
            d = None
        q = (d or {}).get("paid") or {}
        today = float(q.get("today") or 0) if q.get("day") == DAY else 0.0
        total = float(q.get("total") or 0)
        if name == LEDGER:
            own_t, own_all = today, total
        else:
            oth_t, oth_all = oth_t + today, oth_all + total
    _PD.update(own_today=own_t, own_total=own_all, other_today=oth_t, other_total=oth_all, loaded=True)


def _paid_run():
    return sum(u["usd"] for u in USAGE if u.get("prov") in PAID)


def paid_spent():
    """(今日, 試用至今) 所有流程加埋嘅收錢 AI 用量（美元）。"""
    run = _paid_run()
    return _PD["own_today"] + _PD["other_today"] + run, _PD["own_total"] + _PD["other_total"] + run


def status():
    """俾 app 顯示嘅 AI 狀態（DeepSeek 做主力就顯示今日用量、每日上限同試用累計）。"""
    if PROVIDER in PAID:
        d, a = paid_spent()
        return dict(provider=PROVIDER, model=f"DeepSeek（{DS_FAST}／{DS_SMART}）", spent=round(d, 2), budget=PAID_DAY_USD,
                    total=round(a, 2), total_budget=PAID_TOTAL_USD, day=DAY, calls=len(USAGE))
    return dict(provider=PROVIDER, model=label_claude() if PROVIDER == "claude" else PROVIDER, spent=round(spent_today(), 2),
                budget=BUDGET, day=DAY, calls=len(USAGE))


def _log(msg, secs, kind):
    u = msg.usage
    st = getattr(u, "server_tool_use", None)
    n_search = int(getattr(st, "web_search_requests", 0) or 0) if st else 0
    rec = dict(prov="claude", t=datetime.now(HKT).strftime("%H:%M:%S"), kind=kind, model=getattr(msg, "model", MODEL), secs=round(secs, 1),
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


def _claude_call(messages, system, timeout, kind, tools=None, max_tokens=None, schema=None):
    cl = _claude_client(timeout)
    oc = {"effort": EFFORT}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}       # 固定 JSON 格式（同搜尋工具嘅引用唔可以一齊用）
    kw = dict(model=MODEL, max_tokens=max_tokens or MAX_TOKENS, system=system, messages=messages,
              output_config=oc, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
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


def _sources(msgs, limit=12, cited_only=False):
    """由搜尋結果同引用攞來源（網址去重；有引用嘅排先）：[{title, url, age}]。cited_only：淨係要 AI 真係引用過嘅。"""
    out, seen = [], set()

    def add(url, title, age=None):
        if url and url not in seen:
            seen.add(url)
            out.append(dict(title=(title or "").strip()[:160], url=url, age=age))
    for m in msgs:
        for b in m.content:
            for ci in (getattr(b, "citations", None) or []):
                add(getattr(ci, "url", None), getattr(ci, "title", ""))
    if not cited_only:
        for m in msgs:
            for b in m.content:
                if getattr(b, "type", "") == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
                    for r in b.content:
                        if getattr(r, "type", "") == "web_search_result":
                            add(r.url, r.title, getattr(r, "page_age", None))
    return out[:limit]


def schema_hint(schema):
    """後備供應商冇固定 JSON 格式：將 JSON Schema 寫入提示（description 入面有每格要寫乜）。"""
    return "\n\n回覆嘅 JSON 一定要跟呢個 JSON Schema（每個欄位都要有）：\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def _schema_rejected(e):
    return getattr(e, "status_code", None) == 400 and re.search(r"schema|output_config|format|grammar", str(e), re.I)


def _claude_ask(prompt, timeout, schema=None, system=None, max_tokens=None, kind="ask"):
    msgs = [{"role": "user", "content": prompt}]
    try:
        msg = _claude_call(msgs, system or JSON_SYS, timeout, kind, max_tokens=max_tokens, schema=schema)
    except Exception as e:  # noqa: BLE001
        if getattr(e, "status_code", None) == 400 and "max_tokens" in str(e) and (max_tokens or 0) > MAX_TOKENS:
            print(f"[llm] max_tokens {max_tokens} 太大（{str(e)[:120]}），改用 {MAX_TOKENS}")
            return _claude_ask(prompt, timeout, schema=schema, system=system, max_tokens=MAX_TOKENS, kind=kind)
        if not (schema and _schema_rejected(e)):
            raise
        print(f"[llm] Claude 唔收呢個固定格式（{str(e)[:160]}），改用提示要求 JSON")
        msg = _claude_call([{"role": "user", "content": prompt + schema_hint(schema)}], system or JSON_SYS, timeout, kind,
                           max_tokens=max_tokens)
    return _json(_text(msg)), label_claude([msg])


GATHER_SYS = ("你係財經研究員。用網上搜尋搵最新、可靠嘅資料（公司公告、財報、監管文件、主要財經媒體優先），"
              "然後用文字寫研究筆記：每一點都要有具體數字或者日期，同埋要引用搜尋結果。搵唔到就寫搵唔到，唔好估。")


def _claude_gather(prompt, timeout, max_search, first):
    deadline = time.time() + timeout
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_search}]
    msgs, got = [{"role": "user", "content": prompt}], []
    for _ in range(6):                                   # 搜尋太耐會 pause_turn：將回覆接返落去繼續
        m = _claude_call(msgs, GATHER_SYS, _left(deadline, timeout), "gather", tools=tools)
        got.append(m)
        if m.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": m.content}]
    src = _sources(got, limit=40, cited_only=True) or _sources(got, limit=15)
    idx = {s["url"]: k for k, s in enumerate(src)}
    parts = []
    for m in got:
        for b in m.content:
            if getattr(b, "type", "") != "text":
                continue
            refs = sorted({idx[c.url] for c in (getattr(b, "citations", None) or []) if getattr(c, "url", None) in idx})
            parts.append(b.text + "".join(f" [S{first + k}]" for k in refs))
    n_search = sum(u["search"] for u in USAGE[-len(got):])
    return "".join(parts).strip(), src, f"{label_claude(got)}（上網搜尋 {n_search} 次）", n_search


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
    return _json(_text(m2)), f"{label_claude(got + [m2])}（上網搜尋 {n_search} 次：{tag}）", grounded, src


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


def _gemini_gather(prompt, timeout, first):
    """Gemini + Google 搜尋寫筆記（後備）：筆記冇逐句引用，來源清單由 groundingChunks 嚟，接住 first 編號列喺筆記尾。"""
    key, deadline = _gem_key(), time.time() + timeout
    body = {"contents": [{"parts": [{"text": GATHER_SYS + "\n\n" + prompt}]}], "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.3}}
    last = ""
    for m in gem_pick(key, GEM_D):
        try:
            req = urllib.request.Request(GEM_API.format(m=m), data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
            d = json.loads(urllib.request.urlopen(req, timeout=_left(deadline, 240)).read())
            c = d["candidates"][0]
            txt = "".join(x.get("text", "") for x in c["content"]["parts"] if not x.get("thought")).strip()
            chunks = (c.get("groundingMetadata") or {}).get("groundingChunks", [])
            src = [dict(title=w.get("web", {}).get("title", ""), url=w.get("web", {}).get("uri", ""), age=None) for w in chunks][:30]
            if src:
                txt += "\n\n（呢份筆記嘅來源：" + "、".join(f"[S{first + k}] {s['title']}" for k, s in enumerate(src)) + "）"
            return txt, src, f"{m}（Google 搜尋）", len(src)
        except Exception as e:  # noqa: BLE001
            last = f"{m}：{str(e)[:80]}"
    raise RuntimeError(f"gemini：搜尋失敗（{last}）")


# ---------------------------------------------------------------- Mistral（2026-10-22；免費模式，冇上網搜尋）
MIS_API = "https://api.mistral.ai/v1/chat/completions"
MIS_MODELS = [m for m in (os.environ.get("MISTRAL_MODEL"), "mistral-medium-latest", "mistral-small-latest") if m]
MIS_GAP = float(os.environ.get("MISTRAL_GAP_SECS", "1.2"))   # 免費模式大約每秒 1 個請求
_MIS_LAST = [0.0]


def _mistral(prompt, timeout, max_tokens=None):
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("mistral：冇 MISTRAL_API_KEY")
    deadline, errs = time.time() + timeout, []
    for m in MIS_MODELS:
        body = json.dumps({"model": m, "temperature": 0.3, "response_format": {"type": "json_object"}, "max_tokens": min(int(max_tokens or 8000), 16000),
                           "messages": [{"role": "system", "content": JSON_SYS}, {"role": "user", "content": prompt}]}).encode()
        for attempt in range(2):
            wait = MIS_GAP - (time.time() - _MIS_LAST[0])
            if wait > 0:
                time.sleep(wait)
            _MIS_LAST[0] = time.time()
            req = urllib.request.Request(MIS_API, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {key}"})
            try:
                with urllib.request.urlopen(req, timeout=_left(deadline, 150)) as r:
                    d = json.loads(r.read())
                return _json(d["choices"][0]["message"]["content"]), "mistral:" + m
            except urllib.error.HTTPError as e:
                errs.append(f"{m} HTTP {e.code}")
                if e.code == 429 and attempt == 0 and deadline - time.time() > 40:
                    time.sleep(8)                 # 超咗每秒／每分鐘上限：等陣再試一次
                    continue
                break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{m} {type(e).__name__}")
                break
    raise RuntimeError("mistral：" + "、".join(errs))


# ---------------------------------------------------------------- DeepSeek（2026-10-23；收錢、預付增值）
def _ds_peak():
    """而家係咪 DeepSeek 繁忙時段（UTC 01–04、06–10 時，星期一至五；繁忙價係非繁忙兩倍）。"""
    u = datetime.now(timezone.utc)
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


def _ds_usd(model, hit, miss, out, n_search=0):
    ph, pm, po = DS_PRICE["flash"] if "flash" in str(model).lower() else DS_PRICE["pro"]   # 認唔到型號就當 pro（寧願高估）
    f = 1.0 if _ds_peak() else 0.5
    return (hit * ph + miss * pm + out * po) * f / 1e6 + n_search * DS_SEARCH_USD


def _dlog(kind, model, secs, hit, miss, out, n_search=0):
    rec = dict(prov="deepseek", t=datetime.now(HKT).strftime("%H:%M:%S"), kind=kind, model=model, secs=round(secs, 1),
               inp=int(hit + miss), cr=int(hit), out=int(out), search=int(n_search), usd=round(_ds_usd(model, hit, miss, out, n_search), 6))
    USAGE.append(rec)
    d, a = paid_spent()
    print(f"[llm] deepseek {kind} {model} {secs:.0f} 秒｜輸入 {rec['inp']:,}（緩存 {rec['cr']:,}）｜輸出 {rec['out']:,}｜搜尋 {n_search}｜約 US${rec['usd']:.4f}"
          f"（今日 US${d:.3f}／上限 {PAID_DAY_USD:g}；試用 US${a:.2f}／{PAID_TOTAL_USD:g}）")
    return rec


def _paid_check(prov):
    if not _PD["loaded"]:
        _paid_load()                                     # 冇行 start() 嘅程式都要讀帳本先查上限
    d, a = paid_spent()
    if a >= PAID_TOTAL_USD:
        raise RuntimeError(f"{prov}：試用總預算 US${PAID_TOTAL_USD:g} 用晒")
    if d >= PAID_DAY_USD:
        raise RuntimeError(f"{prov}：今日預算 US${PAID_DAY_USD:g} 用晒")


def _ds_post(path, body, timeout):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("deepseek：冇 DEEPSEEK_API_KEY")
    _paid_check("deepseek")
    deadline = time.time() + timeout
    for attempt in range(2):
        req = urllib.request.Request(DS_BASE + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=_left(deadline, timeout)) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = (e.read() or b"")[:300].decode("utf-8", "ignore")
            if e.code in (429, 500, 503, 504) and attempt == 0 and deadline - time.time() > 40:
                time.sleep(5)                            # 繁忙／超咗每秒上限：等陣再試一次（402 餘額不足就唔試）
                continue
            raise RuntimeError(f"deepseek：HTTP {e.code} {msg[:160]}")
    raise RuntimeError("deepseek：請求失敗")


def _ds_chat(prompt, timeout, max_tokens=None, kind="ask", model=None):
    """Chat Completions：JSON 模式（官方要求提示有 "json" 字）、唔開思考（快、平、唔會食晒輸出上限）、限輸出長度。返 (dict, 實際型號)。"""
    m = model or DS_FAST
    body = {"model": m, "temperature": 0.3, "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
            "max_tokens": min(int(max_tokens or 8000), 16000),
            "messages": [{"role": "system", "content": JSON_SYS + "（只回覆 json）"}, {"role": "user", "content": prompt}]}
    deadline = time.time() + timeout
    for attempt in range(2):
        t0 = time.time()
        d = _ds_post("/chat/completions", body, _left(deadline, timeout))
        u = d.get("usage") or {}
        hit = int(u.get("prompt_cache_hit_tokens") or 0)
        miss = u.get("prompt_cache_miss_tokens")
        miss = int(miss if miss is not None else (u.get("prompt_tokens") or 0) - hit)
        real = d.get("model") or m
        _dlog(kind, real, time.time() - t0, hit, miss, u.get("completion_tokens") or 0)
        c = (d.get("choices") or [{}])[0]
        if c.get("finish_reason") == "length":
            raise RuntimeError("deepseek：回覆太長（max_tokens）")
        txt = (c.get("message") or {}).get("content") or ""
        if txt.strip() or attempt:
            return _json(txt), real
        print("[llm] deepseek 回咗空白（官方話 JSON 模式間中會咁），再試一次")
    raise RuntimeError("deepseek：回覆空白")


def _ds_ask(prompt, timeout, max_tokens=None, kind="ask"):
    res, real = _ds_chat(prompt, timeout, max_tokens, kind, DS_SMART if str(kind).startswith("research") else DS_FAST)
    return res, f"deepseek:{real}"


def _ds_queries(prompt, n, timeout):
    """叫 Flash 由問題寫網上搜尋關鍵字（Search API 每個最多 128 字）。"""
    res, _ = _ds_chat(f"今日係 {DAY}。下面係一條要上網查證嘅問題。寫 1 至 {n} 個網上搜尋關鍵字：每個 80 字以內，針對問題入面嘅公司、代號、日子同事件"
                      f"（涉及幾多個唔同日子或者事件，就盡量每個寫一個；英文財經新聞通常最齊）。回覆 json：{{\"queries\": [\"...\"]}}\n\n"
                      f"【問題】\n{prompt[:6000]}", timeout, 800, "search-q", DS_FAST)
    qs = [str(x).strip()[:128] for x in (res.get("queries") or []) if str(x).strip()]
    if not qs:
        raise RuntimeError("deepseek：寫唔到搜尋關鍵字")
    return qs[:n]


def _ds_web(queries, timeout, count=None):
    """DeepSeek Search API（POST /v1/tools/search）：逐個關鍵字搜，結果輪流攞（每個關鍵字都有份）、網址去重。
    返 (結果, 有結果嘅搜尋次數)；有結果先收錢（每千次 US$0.75），所以記帳只計有結果嗰啲。"""
    deadline, t0, per, n, errs = time.time() + timeout, time.time(), [], 0, []
    for q in queries:
        try:
            rs = _ds_post("/v1/tools/search", {"query": q, "count": int(count or DS_RESULTS)}, _left(deadline, 60)).get("results") or []
        except Exception as e:  # noqa: BLE001
            errs.append(str(e)[:120])
            continue
        n += 1 if rs else 0
        per.append([r for r in rs if re.match(r"https?://", str(r.get("url") or ""))])
    if n:
        _dlog("web", "search-api", time.time() - t0, 0, 0, 0, n)
    out, seen = [], set()
    for i in range(max((len(x) for x in per), default=0)):
        for rs in per:
            if i < len(rs) and rs[i]["url"] not in seen:
                seen.add(rs[i]["url"])
                out.append(rs[i])
    if not out:
        raise RuntimeError("deepseek：搜尋冇結果" + (f"（{errs[0]}）" if errs else ""))
    return out, n


def _ds_ctx(rs, first=1, limit=15, chars=20000):
    """搜尋結果 → 俾 AI 讀嘅文字（[S#] 由 first 開始編號）同來源清單（同一次序）。"""
    lines, src, size = [], [], 0
    for r in rs[:limit]:
        date = str(r.get("date") or "")[:10]
        title = str(r.get("title") or r["url"]).strip()[:160]
        line = (f"[S{first + len(src)}] {title}（{r.get('site_name') or ''}{'，' + date if date else ''}）{r['url']}\n"
                f"{str(r.get('summary') or r.get('snippet') or '').strip()}")
        if src and size + len(line) > chars:
            break
        size += len(line)
        lines.append(line)
        src.append(dict(title=title, url=r["url"], age=date or None))
    return "\n\n".join(lines), src


def _ds_search(prompt, timeout):
    deadline = time.time() + timeout
    qs = _ds_queries(prompt, DS_QUERIES, _left(deadline, 90))
    rs, n = _ds_web(qs, _left(deadline, 150))
    ctx, src = _ds_ctx(rs)
    srct = "\n".join(f"[S{i + 1}] {s['title']} — {s['url']}" for i, s in enumerate(src))
    res, real = _ds_chat(prompt + JSON_ASK.format(day=DAY, find=ctx, src=srct), _left(deadline, timeout), None, "search", DS_FAST)
    tag = "、".join(s["title"] for s in src[:3] if s["title"]) or "冇列出來源"
    return res, f"deepseek:{real}（上網搜尋 {n} 次：{tag}）", bool(src) and n > 0, src


def _ds_gather(prompt, timeout, max_search, first):
    deadline = time.time() + timeout
    qs = _ds_queries(GATHER_SYS + "\n\n" + prompt, max(1, min(int(max_search), DS_QUERIES + 3)), _left(deadline, 90))
    rs, n = _ds_web(qs, _left(deadline, 180), count=8)
    ctx, src = _ds_ctx(rs, first, limit=24, chars=30000)
    res, real = _ds_chat(prompt + f"\n\n【網上搜尋結果（{DAY}）】\n{ctx}\n\n只根據上面搜尋結果寫研究筆記：每一點都要有具體數字或者日期，句尾標返來源編號"
                         f"（例如 [S{first}]）；公司公告、財報、監管文件、主要財經媒體優先；搜尋結果冇講嘅就寫搵唔到，唔好估。"
                         "回覆 json：{\"notes\": \"筆記全文\"}", _left(deadline, timeout), 8000, "gather", DS_SMART)
    notes = res.get("notes")
    notes = "\n".join(map(str, notes)) if isinstance(notes, list) else str(notes or "")
    if not notes.strip():
        raise RuntimeError("deepseek：筆記係空白")
    return notes.strip(), src, f"deepseek:{real}（上網搜尋 {n} 次）", n


def _schema_check(res, schema):
    """後備供應商冇官方固定格式：起碼檢查 schema 頂層必填欄齊唔齊（2026-10-22 Codex 改卷：之前唔啱格式都照收）。"""
    miss = [k for k in (schema or {}).get("required") or [] if k not in res]
    if miss:
        raise RuntimeError(f"回覆格式唔啱：缺 {'、'.join(miss[:5])}")
    return res


# ---------------------------------------------------------------- 對外
# 2026-10-21 Codex 改卷：timeout 係成個調用嘅總上限（之前每個供應商都由頭攞足，三個加埋可以超過 workflow 時限）
MIN_LEFT = 15                    # 剩低少過呢個秒數就唔再試下一個供應商


def _left_or_stop(deadline, p, timeout, errs):
    left = deadline - time.time()
    if left < MIN_LEFT:
        errs.append(f"{p}：AI 時間用晒（總上限 {timeout:.0f} 秒）")
        return None
    return left


def ask(prompt, gem_models=None, timeout=None, schema=None, system=None, max_tokens=None, kind="ask"):
    """要一個 JSON object。返 (dict, 型號標籤)；用咗後備，標籤會寫「後備：原因」。全部失敗 raise RuntimeError（訊息有齊每個供應商嘅錯）。
    schema：JSON Schema（Claude 用固定格式；後備寫入提示）。system：Claude 嘅 system 提示（預設淨係要求 JSON）。"""
    timeout = timeout or 300
    deadline, errs = time.time() + timeout, []
    other = prompt + schema_hint(schema) if schema else prompt
    if system:
        other = system + "\n\n" + other
    for p in _order():
        left = _left_or_stop(deadline, p, timeout, errs)
        if left is None:
            break
        try:
            if p == "claude":
                res, lab = _claude_ask(prompt, left, schema=schema, system=system, max_tokens=max_tokens, kind=kind)
            elif p == "gemini":
                res, lab = _gemini_ask(other, gem_models, left)
            elif p == "mistral":
                res, lab = _mistral(other, left, max_tokens)
            elif p == "deepseek":
                res, lab = _ds_ask(other, left, max_tokens, kind)
            else:
                continue
            if schema and p != "claude":
                _schema_check(res, schema)
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
    deadline, errs = time.time() + timeout, []
    for p in _order():
        left = _left_or_stop(deadline, p, timeout, errs)
        if left is None:
            break
        try:
            if p == "claude":
                res, lab, g, src = _claude_search(prompt, left)
            elif p == "gemini":
                res, lab, g, src = _gemini_search(prompt, left)
            elif p == "deepseek":
                res, lab, g, src = _ds_search(prompt, left)
            else:
                continue                                     # 其他供應商冇上網搜尋
            if errs:
                lab += f"（後備：{_why(errs[0])}）"
            return res, lab, g, src
        except Exception as e:  # noqa: BLE001
            errs.append(f"{p}：{str(e)[:240]}" if not str(e).startswith(p) else str(e)[:260])
    return None, "；".join(errs) or "冇可以上網搜尋嘅 AI 供應商", False, []


def gather(prompt, max_search=None, timeout=None, first=1):
    """淨係上網搜尋同寫筆記（研究報告第一步）。返 (筆記, 來源, 標籤, 搜尋次數)；筆記入面 [S#] 由 first 開始，
    對應來源清單次序。全部有搜尋嘅供應商都失敗就 raise RuntimeError。"""
    timeout, max_search = timeout or 480, max_search or MAX_SEARCH
    deadline, errs = time.time() + timeout, []
    for p in _order():
        left = _left_or_stop(deadline, p, timeout, errs)
        if left is None:
            break
        try:
            if p == "claude":
                notes, src, lab, n = _claude_gather(prompt, left, max_search, first)
            elif p == "gemini":
                notes, src, lab, n = _gemini_gather(prompt, left, first)
            elif p == "deepseek":
                notes, src, lab, n = _ds_gather(prompt, left, max_search, first)
            else:
                continue                                     # 其他供應商冇上網搜尋
            if errs:
                lab += f"（後備：{_why(errs[0])}）"
            return notes, src, lab, n
        except Exception as e:  # noqa: BLE001
            errs.append(f"{p}：{str(e)[:240]}" if not str(e).startswith(p) else str(e)[:260])
    raise RuntimeError("；".join(errs) or "冇可以上網搜尋嘅 AI 供應商")
