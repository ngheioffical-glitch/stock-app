# -*- coding: utf-8 -*-
"""llm.py 測試（假 Claude 回覆，唔會真係叫 API、唔使錢）。用法：python tests/test_llm.py（python tests/run_all.py 跑晒）"""
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

T = Path(__file__).resolve().parent
SC = T.parent / "scanner"
OUT = Path(os.environ.get("TEST_OUT") or T / "_out")   # 測試輸出（git 唔收）
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SC))
sys.stdout.reconfigure(encoding="utf-8")
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GITHUB_TOKEN", None)
# 2026-10-21：app 預設改返 Gemini（用戶「AI唔好轉住」）。第 1–8 項測「轉咗 Claude 之後」嘅行為，所以明確設 Claude 模式；第 9 項起測預設
os.environ["AI_PROVIDER"] = "claude"
os.environ["AI_FALLBACK"] = "gemini"

CALLS = []
QUEUE = []


def blk(**kw):
    return NS(**kw)


def msg(content, stop="end_turn", inp=1000, out=500, search=0):
    return NS(content=content, stop_reason=stop, model="claude-opus-5-5",
              usage=NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                       server_tool_use=NS(web_search_requests=search, web_fetch_requests=0)))


class _Stream:
    def __init__(self, kw):
        CALLS.append(kw)
        item = QUEUE.pop(0)
        if isinstance(item, Exception):
            raise item
        self.m = item

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.m


class _Anthropic:
    def __init__(self, **kw):
        self.kw = kw
        self.beta = NS(messages=NS(stream=lambda **k: _Stream(k)))


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=_Anthropic)
import llm  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# 1. 一般 ask：參數同計錢
QUEUE[:] = [msg([blk(type="text", text='```json\n{"a": 1}\n```')])]
res, lab = llm.ask("寫個 JSON", timeout=60)
k = CALLS[-1]
check(res == {"a": 1}, "Claude 回覆 JSON（連 ``` 都讀到）")
check(k["model"] == "claude-opus-5-5" and k["output_config"] == {"effort": "high"}, "型號 claude-opus-5-5、effort high")
check(k["betas"] == ["server-side-fallback-2026-07-01"] and k["fallbacks"] == "default", "開咗 server-side fallback")
check("tools" not in k and "JSON" in k["system"], "一般請求冇搜尋工具、system 要求 JSON")
check(lab == "Claude Opus 5.5（effort high）", "標籤寫明型號同 effort")
check(abs(llm.USAGE[-1]["usd"] - (1000 * 4 + 500 * 20) / 1e6) < 1e-9, "計錢：輸入 4／輸出 20 每百萬 token")

# 2. Claude 出錯 → 退 Gemini（標明）
llm._gemini_ask = lambda p, m, t: ({"b": 2}, "gemini-2.5-flash")
os.environ["GEMINI_API_KEY"] = "x"
QUEUE[:] = [RuntimeError("Error code: 529 overloaded")]
res, lab = llm.ask("x", timeout=60)
check(res == {"b": 2} and "後備：Claude 繁忙／額度" in lab, f"Claude 出錯退 Gemini 並標明：{lab}")

# 3. 拒答 → 退 Gemini
QUEUE[:] = [msg([blk(type="text", text="")], stop="refusal")]
res, lab = llm.ask("x", timeout=60)
check("後備：Claude 拒答" in lab, f"拒答退 Gemini：{lab}")

# 4. 預算用晒 → 唔叫 Claude
n0 = len(CALLS)
llm.SPENT_BEFORE = 999
res, lab = llm.ask("x", timeout=60)
check(len(CALLS) == n0 and "Claude 今日預算用晒" in lab, f"超預算唔叫 Claude：{lab}")
llm.SPENT_BEFORE = 0

# 5. 全部失敗 → raise，訊息有齊供應商
llm._gemini_ask = lambda p, m, t: (_ for _ in ()).throw(RuntimeError("gemini：HTTP 429"))
QUEUE[:] = [RuntimeError("boom")]
try:
    llm.ask("x", timeout=60)
    check(False, "應該 raise")
except RuntimeError as e:
    check("claude" in str(e) and "gemini" in str(e), f"全部失敗 raise：{str(e)[:80]}")
os.environ.pop("GEMINI_API_KEY", None)

# 6. 搜尋兩步：pause_turn 接駁、來源、grounded
r1 = msg([blk(type="server_tool_use"), blk(type="web_search_tool_result", content=[
          blk(type="web_search_result", url="https://a.com/x", title="A 新聞", page_age="1 day")]),
          blk(type="text", text="重點一", citations=None)], stop="pause_turn", search=2)
r2 = msg([blk(type="text", text="重點二", citations=[NS(url="https://b.com/y", title="B 報道")])], search=1)
r3 = msg([blk(type="text", text='{"status": "acquired", "cash_per_share": 50}')])
QUEUE[:] = [r1, r2, r3]
res, lab, g, src = llm.search("查下 XYZ", timeout=120)
s1, s2, s3 = CALLS[-3:]
check(s1["tools"][0]["type"] == "web_search_20260209" and s1["tools"][0]["max_uses"] == 5, "搜尋用 web_search_20260209")
check(s2["messages"][-1]["role"] == "assistant", "pause_turn 會將回覆接返落去繼續")
check("tools" not in s3 and "[S1]" in s3["messages"][0]["content"], "第二步冇工具、用自己編號嘅來源寫 JSON")
check(g and res["status"] == "acquired" and [x["url"] for x in src] == ["https://b.com/y", "https://a.com/x"], "grounded + 來源（引用先）")
check("上網搜尋 3 次" in lab, f"標籤：{lab}")

# 7. 冇來源 → 唔當查證（model.ai_search 回 None）
QUEUE[:] = [msg([blk(type="text", text="冇搜到", citations=None)], search=0), msg([blk(type="text", text='{"status": "acquired", "cash_per_share": 123}')])]
import model  # noqa: E402
r, why = model.ai_search("XYZ 被收購？")
check(r is None and "唔當查證" in why, f"冇來源唔當查證：{why[:60]}")

# 8. 用量紀錄
rec = llm.usage_record(None)
check(rec["day"] == llm.DAY and rec["calls"] and rec["model"] == "claude-opus-5-5", "ai_usage.json 內容")

# 9. Anthropic server-side fallback 轉咗型號 → 標籤照實際型號寫、標明後備（2026-10-21 Codex 改卷）
m9 = msg([blk(type="text", text='{"a": 9}')])
m9.model = "claude-sonnet-5-5"
QUEUE[:] = [m9]
res, lab = llm.ask("x", timeout=60)
check("Claude Sonnet 5.5" in lab and "後備" in lab and "Opus" in lab, f"自動轉型號標籤：{lab}")

# 10. 總時間上限：Claude 用咗 25 秒先失敗，timeout 30 → 唔再試 Gemini（之前每個供應商都由頭攞足 30 秒）
CLOCK = [1000.0]
real_time = llm.time
llm.time = NS(time=lambda: CLOCK[0], sleep=lambda s: None)
called = []
def slow_claude(*a, **k):
    CLOCK[0] += 25
    raise RuntimeError("claude：慢")
real_claude_ask, real_gem = llm._claude_ask, llm._gemini_ask
llm._claude_ask = slow_claude
llm._gemini_ask = lambda p, m, t: called.append(t) or ({"g": 1}, "gemini")
os.environ["GEMINI_API_KEY"] = "x"
try:
    llm.ask("x", timeout=30)
    check(False, "應該 raise")
except RuntimeError as e:
    check(not called and "時間用晒" in str(e), f"總時間上限：Gemini 冇被叫（{str(e)[:60]}）")
CLOCK[0] = 2000.0
llm._claude_ask = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("claude：HTTP 500"))
res, lab = llm.ask("x", timeout=30)
check(called and called[-1] <= 30, f"Gemini 只攞剩低時間（{called[-1] if called else None} 秒）")
llm.time, llm._claude_ask, llm._gemini_ask = real_time, real_claude_ask, real_gem
os.environ.pop("GEMINI_API_KEY", None)

# 11. 後備原因寫啱供應商
check(llm._why("gemini：HTTP 429 Too Many Requests") == "Gemini 繁忙／額度", "Gemini 出錯原因唔會寫成 Claude")
check(llm._why("claude：拒答（refusal）") == "Claude 拒答", "Claude 拒答原因")

# 12. 研究指定次序（llm.ORDER）
llm.ORDER = ["claude", "gemini"]
check(llm._order() == ["claude", "gemini"], "llm.ORDER 蓋過預設次序")
llm.ORDER = None

# 13. 預設（冇設 AI_PROVIDER／AI_FALLBACK）= Gemini、唔自動轉、冇 GitHub Models
import importlib  # noqa: E402
os.environ.pop("AI_PROVIDER", None)
os.environ.pop("AI_FALLBACK", None)
llm2 = importlib.reload(llm)
check(llm2.PROVIDER == "gemini" and llm2.FALLBACK == [] and llm2._order() == ["gemini"], f"預設 Gemini、冇自動後備：{llm2._order()}")
src = (SC / "llm.py").read_text(encoding="utf-8")
check("models.github.ai" not in src and "def _github" not in src, "已經冇 GitHub Models 代碼（2026-07-30 停用）")
os.environ.pop("GEMINI_API_KEY", None)
check(not llm2.available() or os.environ.get("GEMINI_API_KEY"), "預設模式冇 Gemini key 就當冇 AI（唔會偷偷用 Claude）")
# 14. Mistral（2026-10-22）：有 MISTRAL_API_KEY 就自動做主力、Gemini 後備；搜尋照用 Gemini
import io, json as _j  # noqa: E401,E402
os.environ["MISTRAL_API_KEY"] = "fake-mistral"
os.environ["GEMINI_API_KEY"] = "fake-gem"
llm3 = importlib.reload(llm)
check(llm3._order() == ["mistral", "gemini"], f"有 Mistral key：先 Mistral 後 Gemini（{llm3._order()}）")
sent = []
class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake_open(req, timeout=None):
    sent.append((req.full_url, _j.loads(req.data), dict(req.header_items())))
    return _R(_j.dumps({"choices": [{"message": {"content": '{"zh": "測試"}'}}]}).encode())
llm3.urllib.request.urlopen = fake_open
llm3.MIS_GAP = 0
res, lab = llm3.ask("譯呢句", timeout=30)
url, body, hdr = sent[-1]
check(res == {"zh": "測試"} and lab.startswith("mistral:") and "mistral.ai" in url, f"ask 用 Mistral：{lab}")
check(body["response_format"] == {"type": "json_object"} and hdr.get("Authorization") == "Bearer fake-mistral", "要求 JSON、key 放 Authorization（唔寫入檔案）")
g = []
llm3._gemini_search = lambda prompt, t: (g.append(1) or ({"a": 1}, "gemini-x（Google 搜尋：A）", True, [{"title": "A", "url": "https://a"}]))
r2, lab2, gr, src = llm3.search("查下", timeout=30)
check(g and gr and "後備" not in lab2, f"search 唔經 Mistral（佢冇免費搜尋），直接 Gemini：{lab2}")
def fail_open(req, timeout=None):
    import urllib.error
    raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
llm3.urllib.request.urlopen = fail_open
llm3._gemini_ask = lambda p, m, t: ({"b": 2}, "gemini-x")
r3, lab3 = llm3.ask("x", timeout=30)
check(r3 == {"b": 2} and "後備：Mistral 出錯" in lab3, f"Mistral 出錯退 Gemini 並標明：{lab3}")
for k in ("MISTRAL_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)

# 15. DeepSeek（2026-10-23，收錢、預付）：有 DEEPSEEK_API_KEY 就主力、Gemini 後備；記帳、上限、跨流程帳本、Search API 來源
import urllib.error  # noqa: E402
os.environ["DEEPSEEK_API_KEY"] = "fake-ds"
os.environ["GEMINI_API_KEY"] = "fake-gem"
os.environ.pop("MISTRAL_API_KEY", None)
os.environ["AI_LEDGER"] = "feeds"
q = importlib.reload(llm)
check(q._order() == ["deepseek", "gemini"], f"有 DeepSeek key：先 DeepSeek 後 Gemini（{q._order()}）")
q._raw = lambda path: {}                              # 其他流程帳本：當冇
q._PD.update(loaded=True)
q._ds_peak = lambda: True                             # 測試固定用繁忙時段價
os.environ["DEEPSEEK_PEAK_OK"] = "1"                  # 價錢測試要喺繁忙時段照叫（正式行繁忙時段唔叫，見下面）
dsent = []
D = dict(reply='{"zh": "你好"}', empty=0, http=None, queries='{"queries": ["XYZ acquisition", "XYZ delisted"]}')


def d_open(req, timeout=None):
    body = _j.loads(req.data)
    dsent.append((req.full_url, body, dict(req.header_items())))
    if D["http"]:
        raise urllib.error.HTTPError(req.full_url, D["http"], "bad", {}, io.BytesIO(b'{"error":{"message":"Authentication Fails, Your api key: ****Oclg is invalid"}}' if D["http"] == 401 else b'{"error":{"message":"Insufficient Balance"}}'))
    if req.full_url.endswith("/v1/tools/search"):
        if "冇結果" in body["query"]:
            return _R(b'{"results": []}')
        k = sum(1 for x in dsent if x[0].endswith("/v1/tools/search"))
        return _R(_j.dumps({"results": [
            {"title": f"報道{k}", "url": f"https://n{k}.com/a", "summary": f"摘要{k}", "site_name": "N", "date": "2026-10-22T00:00:00+00:00"},
            {"title": "重複", "url": "https://dup.com/x", "summary": "重複摘要"}, {"title": "壞網址", "url": "javascript:alert(1)"}]}).encode())
    user = body["messages"][-1]["content"]
    content = (D["queries"] if "搜尋關鍵字" in user else '{"notes": "收購價 10 美元 [S5]"}' if "研究筆記" in user
               else '{"status": "acquired"}' if "網上搜尋結果" in user else D["reply"])
    if D["empty"]:
        D["empty"] -= 1
        content = ""
    return _R(_j.dumps({"model": body["model"], "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10000, "prompt_cache_hit_tokens": 4000, "prompt_cache_miss_tokens": 6000,
                                  "completion_tokens": 2000}}).encode())


q.urllib.request.urlopen = d_open
res, lab = q.ask("譯", timeout=60)
url, body, hdr = dsent[-1]
check(res == {"zh": "你好"} and lab == "deepseek:deepseek-flash" and url == "https://api.deepseek.com/chat/completions", f"ask 用 DeepSeek Flash：{lab}")
check(body["thinking"] == {"type": "disabled"} and body["response_format"] == {"type": "json_object"} and body["max_tokens"] <= 16000
      and "json" in body["messages"][0]["content"] and hdr.get("Authorization") == "Bearer fake-ds",
      "唔開思考、JSON 模式（提示有 json 字）、有輸出上限、key 只放 header")
peak = (4000 * 0.006 + 6000 * 0.30 + 2000 * 1.20) / 1e6
check(abs(q.USAGE[-1]["usd"] - peak) < 1e-9 and q.USAGE[-1]["prov"] == "deepseek", f"按繁忙價記帳（緩存分開計）：US${q.USAGE[-1]['usd']}")
q._ds_peak = lambda: False
q.ask("譯", timeout=60)
check(abs(q.USAGE[-1]["usd"] - peak / 2) < 1e-9, "非繁忙時段半價")
q._ds_peak = lambda: True
q.ask("研究", timeout=60, kind="research-a")
check(dsent[-1][1]["model"] == "deepseek-v4-pro" and q.USAGE[-1]["usd"] > peak, "研究分析用 v4-pro（價錢較貴）")
n0 = len(dsent)
D["empty"] = 1
res, lab = q.ask("再譯", timeout=60)
check(res == {"zh": "你好"} and len(dsent) == n0 + 2, "JSON 模式回空白：再試一次")
n0 = len(dsent)
r2, lab2, g2, src2 = q.search("XYZ 被收購？", timeout=60)
calls = dsent[n0:]
srch = [c for c in calls if c[0].endswith("/v1/tools/search")]
check(g2 and r2 == {"status": "acquired"} and len(srch) == 2 and all(len(c[1]["query"]) <= 128 and c[1]["count"] == q.DS_RESULTS for c in srch),
      f"搜尋：先寫關鍵字，再用 Search API 搜 2 次：{lab2}")
urls = [s["url"] for s in src2]
check(len(urls) == 3 and urls.count("https://dup.com/x") == 1 and not any(u.startswith("javascript") for u in urls) and "上網搜尋 2 次" in lab2,
      f"結果輪流攞、網址去重、壞網址唔要：{urls}")
check("[S1]" in calls[-1][1]["messages"][-1]["content"] and "摘要" in calls[-1][1]["messages"][-1]["content"], "最後一步只根據搜尋結果（有編號同摘要）答")
web = [u for u in q.USAGE if u["kind"] == "web"][-1]
check(abs(web["usd"] - 2 * 0.00075) < 1e-12 and web["search"] == 2, f"搜尋按次收錢：US${web['usd']}")
n0 = len(dsent)
notes, gsrc, glab, gn = q.gather("NVDA 最新", max_search=8, timeout=60, first=5)
last = dsent[-1][1]
check("[S5]" in notes and gn == 2 and len(gsrc) == 3 and last["model"] == "deepseek-v4-pro" and "[S5]" in last["messages"][-1]["content"],
      "研究搵資料：來源由 S5 開始編號、筆記用 v4-pro")
# 搜尋冇結果 → 唔收錢、退 Gemini
D["queries"] = '{"queries": ["冇結果 XYZ"]}'
q._gemini_search = lambda p, t: ({"status": "x"}, "gemini-x（Google 搜尋：A）", True, [{"title": "A", "url": "https://a.com"}])
nweb = len([u for u in q.USAGE if u["kind"] == "web"])
r3, lab3, g3, _ = q.search("ABC？", timeout=60)
check(r3 == {"status": "x"} and "後備：DeepSeek 出錯" in lab3 and len([u for u in q.USAGE if u["kind"] == "web"]) == nweb,
      f"搜尋冇結果：唔記搜尋費、退 Gemini（{lab3}）")
D["queries"] = '{"queries": ["XYZ acquisition", "XYZ delisted"]}'
# Schema：缺欄 → 唔收，退 Gemini
D["reply"] = '{"a": 1}'
q._gemini_ask = lambda p, m, t: ({"a": 1, "b": 2}, "gemini-x")
res, lab = q.ask("x", timeout=60, schema={"type": "object", "required": ["a", "b"]})
check(res == {"a": 1, "b": 2} and "後備：DeepSeek 出錯" in lab, f"格式缺欄唔收、退 Gemini：{lab}")
D["reply"] = '{"zh": "你好"}'
# 餘額用晒（HTTP 402）：唔重試，退 Gemini 並講要增值
n0 = len(dsent)
D["http"] = 402
res, lab = q.ask("x", timeout=60)
D["http"] = None
check(len(dsent) == n0 + 1 and "DeepSeek 餘額用晒（要增值）" in lab, f"餘額用晒：唔重試、標明要增值（{lab}）")
D["http"] = 401
try:
    q._ds_post("/chat/completions", {}, 30)
    e401 = ""
except RuntimeError as e:
    e401 = str(e)
D["http"] = None
check("HTTP 401" in e401 and "Oclg" not in e401 and q._why(e401).startswith("DeepSeek key 唔啱"), f"key 唔啱：標明、唔留 key 尾（{e401[:80]}）")
# 繁忙時段：一律唔叫 DeepSeek，退 Gemini（2026-10-23 老師：「唔可以繁忙時段，節省成本」）
n0 = len(dsent)
os.environ.pop("DEEPSEEK_PEAK_OK")
res, lab = q.ask("x", timeout=60)
check(len(dsent) == n0 and "後備：DeepSeek 繁忙時段唔用（慳錢）" in lab and q.peak_now(), f"繁忙時段唔叫 DeepSeek（{lab}）")
q._ds_peak = lambda: False
res, lab = q.ask("x", timeout=60)
check(len(dsent) == n0 + 1 and lab.startswith("deepseek:"), "非繁忙時段照用 DeepSeek")
q._ds_peak = lambda: True
os.environ["DEEPSEEK_PEAK_OK"] = "1"
n0 = len(dsent)
res, lab = q.ask("x", timeout=60)
check(len(dsent) == n0 + 1 and lab.startswith("deepseek:") and not q.peak_now(),
      "繁忙時段用戶自己撳（DEEPSEEK_PEAK_OK=1）：照用 DeepSeek，排程程式（peak_now）都當非繁忙")
# 上限：今日（所有流程加埋）≥ US$1 → 唔叫 DeepSeek，退 Gemini 並標明
n0 = len(dsent)
q._PD.update(other_today=1.0)
res, lab = q.ask("x", timeout=60)
check(len(dsent) == n0 and "後備：DeepSeek 今日預算用晒" in lab, f"每日上限：唔再叫 DeepSeek（{lab}）")
q._PD.update(other_today=0.0, other_total=10.0)
res, lab = q.ask("x", timeout=60)
check(len(dsent) == n0 and "後備：DeepSeek 試用預算用晒" in lab, f"試用總額上限：唔再叫 DeepSeek（{lab}）")
q._PD.update(other_total=0.0)
# 跨流程帳本：自己本機檔 + 其他流程 GitHub 上面嗰份加埋；finish 只寫自己
import tempfile  # noqa: E402
td = Path(tempfile.mkdtemp(dir=str(OUT)))
(td / "ai_usage.json").write_text(_j.dumps({"day": q.DAY, "spent": 0, "paid": {"day": q.DAY, "today": 0.2, "total": 3.0}}), encoding="utf-8")
q._raw = lambda path: {"paid": {"day": q.DAY, "today": 0.3, "total": 4.0}} if "radar" in path else {"paid": {"day": "2000-01-01", "today": 9, "total": 1.0}}
q.USAGE.clear()
q.start(td)
d_sp, a_sp = q.paid_spent()
check(abs(d_sp - 0.5) < 1e-9 and abs(a_sp - 9.0) < 1e-9, f"跨流程加埋：今日 {d_sp}（自己 0.2 + 雷達 0.3，舊日子唔計）、試用 {a_sp}")
q.ask("x", timeout=60)
q.finish(td)
own = _j.loads((td / "ai_usage.json").read_text(encoding="utf-8"))["paid"]
run = q.USAGE[-1]["usd"]
check(abs(own["today"] - (0.2 + run)) < 1e-5 and abs(own["total"] - (3.0 + run)) < 1e-5, f"finish 只寫自己流程嘅用量（唔會重複計其他流程）：{own} run={run} usage={len(q.USAGE)}")
st = q.status()
check(st["provider"] == "deepseek" and st["budget"] == 1.0 and st["total_budget"] == 10.0 and "deepseek-flash" in st["model"],
      f"app 狀態顯示 DeepSeek 今日用量同上限：{st}")
for k in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "AI_LEDGER", "DEEPSEEK_PEAK_OK"):
    os.environ.pop(k, None)
q = importlib.reload(llm)                              # 冇收錢 AI key：帳本抄返之前嗰份，唔會寫 0 洗走試用累計
keep = {"day": "2026-10-01", "today": 0.4, "total": 6.5}
check(q.usage_record({"day": q.DAY, "paid": keep})["paid"] == keep, "冇 DeepSeek key 都保留試用累計")
os.environ.update(AI_LEDGER="radar", GITHUB_REPOSITORY="x/y")   # 冇本機帳本：讀自己流程上一次嘅（雷達唔好抄新聞嘅請求）
q = importlib.reload(llm)
asked = []
q._raw = lambda path: asked.append(path) or {"day": q.DAY, "spent": 0, "calls": [{"t": "01:00:00", "usd": 0.1}]}
q.start(Path(tempfile.mkdtemp(dir=str(OUT))))
check(asked == ["radar/ai_usage.json"] and len(q.usage_record(q._PREV)["calls"]) == 1, f"雷達開始時讀雷達自己嘅帳本：{asked}")
for k in ("AI_LEDGER", "GITHUB_REPOSITORY"):
    os.environ.pop(k, None)

# 16. 輕鬆嘢先用 Gemini（2026-10-24 老師：「都用埋gemini，可以比輕鬆嘢佢做，唔好浪費」）
os.environ.update(DEEPSEEK_API_KEY="fake-ds", GEMINI_API_KEY="fake-gem")
q = importlib.reload(llm)
check(q._order(light=True) == ["gemini", "deepseek"] and q._order() == ["deepseek", "gemini"], f"輕鬆嘢 Gemini 先、主力後備；其他照 DeepSeek 先（{q._order(light=True)}）")
hit = []
q._gemini_ask = lambda p, m, t: (hit.append("gem") or ({"zh": "免費"}, "gemini-flash-lite"))
q._ds_ask = lambda *a, **k: (hit.append("ds") or ({"zh": "收錢"}, "deepseek:deepseek-flash"))
res, lab = q.ask("譯", timeout=60, light=True)
check(res == {"zh": "免費"} and hit == ["gem"] and "後備" not in lab, f"輕鬆嘢：Gemini 做咗就唔使叫 DeepSeek（{lab}）")
q._gemini_ask = lambda p, m, t: (_ for _ in ()).throw(RuntimeError("gemini：全部型號失敗（HTTP 429）"))
hit.clear()
res, lab = q.ask("譯", timeout=60, light=True)
check(res == {"zh": "收錢"} and hit == ["ds"] and "後備：Gemini 繁忙／額度" in lab, f"Gemini 額度爆：轉 DeepSeek 並標明（{lab}）")
hit.clear()
res, lab = q.ask("今日重點", timeout=60)
check(hit == ["ds"], "唔係輕鬆嘢：照用 DeepSeek")
os.environ.pop("GEMINI_API_KEY")
check(q._order(light=True) == ["deepseek", "gemini"], "冇 Gemini key：輕鬆嘢都照 DeepSeek 先")
os.environ["GEMINI_API_KEY"] = "fake-gem"
q.ORDER = ["claude", "gemini"]
check(q._order(light=True) == ["claude", "gemini"], "功能指定咗次序（例如研究）：唔受輕鬆嘢影響")
q.ORDER = None
os.environ["AI_LIGHT"] = ""
check(importlib.reload(llm)._order(light=True) == ["deepseek", "gemini"], "AI_LIGHT 留空：關咗輕鬆嘢分流")
for k in ("AI_LIGHT", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)
import ast  # noqa: E402
lights = {}
for f in ("ai.py", "radar.py", "meme.py", "theme.py"):
    tree = ast.parse((SC / f).read_text(encoding="utf-8"))
    funcs = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)]
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and any(k.arg == "light" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords):
            fn = min((x for x in funcs if x.lineno <= n.lineno <= x.end_lineno), key=lambda x: x.end_lineno - x.lineno).name
            lights.setdefault(f, set()).add(fn)
check(lights == {"ai.py": {"translate", "econ_ai", "fed_ai"}, "radar.py": {"ai_guide"}, "meme.py": {"main"}, "theme.py": {"main"}},
      f"邊啲係輕鬆嘢：翻譯、經濟數據解讀、聯儲局總結、雷達／Meme／題材導讀（{lights}）")
print(f"\n全部 {ok} 項通過")
