# -*- coding: utf-8 -*-
"""2026-11-13 scanner/llm.py 細節行為測試（流程審計 S6：test_llm.py 將 _ds_peak／_claude_call／urlopen 成個換走，
繁忙時段界線、來源去重、固定格式被拒先改提示、Gemini 型號次序、各家「有時間先重試」都冇直接測）。假回覆、唔上網、唔使錢。
1. _ds_peak：UTC 星期一至五 01–04、06–10 時；peak_now 可以用 DEEPSEEK_PEAK_OK=1 當非繁忙；繁忙時段 _paid_check 唔俾用
2. _sources：網址去重、冇網址唔要、引用排先、cited_only、limit
3. _claude_ask：固定格式被拒（400 schema）先改提示再試；其他錯誤、冇 schema 都唔再試；max_tokens 太大退返預設
4. gem_pick：Flash 先（翻譯 Lite 先）、新版本排前、冇開放嘅型號唔用、問唔到清單照原本次序
5. 重試：Gemini 500／503、Mistral 429、DeepSeek 429／5xx 只喺仲有時間先等陣再試；DeepSeek 錯誤訊息遮走 key
用法：python tests/test_llm_small.py"""
import io
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import llm  # noqa: E402

SLEPT = []
llm.time.sleep = lambda s: SLEPT.append(s)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. 繁忙時段
class NowDT(datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW


llm.datetime = NowDT


def peak(y, m, d, hh, mm=0):
    NowDT.NOW = datetime(y, m, d, hh, mm, tzinfo=timezone.utc)
    return llm._ds_peak()


MON = (2026, 11, 16)
check([peak(*MON, h, m) for h, m in ((0, 59), (1, 0), (3, 59), (4, 0), (5, 30), (6, 0), (9, 59), (10, 0))] ==
      [False, True, True, False, False, True, True, False], "_ds_peak：UTC 01:00–03:59、06:00–09:59 先係繁忙（00:59、04:00、05:30、10:00 唔係）")
check(peak(2026, 11, 13, 2) and not peak(2026, 11, 14, 2) and not peak(2026, 11, 15, 7), "_ds_peak：星期五繁忙；星期六、日全日唔係")
os.environ.pop("DEEPSEEK_PEAK_OK", None)
peak(*MON, 2)
check(llm.peak_now(), "peak_now：繁忙時段 → True")
os.environ["DEEPSEEK_PEAK_OK"] = "1"
check(not llm.peak_now(), "peak_now：用戶自己撳（DEEPSEEK_PEAK_OK=1）→ 當非繁忙")
os.environ.pop("DEEPSEEK_PEAK_OK")
try:
    llm._paid_check("deepseek")
    err = ""
except RuntimeError as e:
    err = str(e)
check("繁忙時段唔用" in err, "_paid_check：繁忙時段唔叫收錢 AI")
peak(*MON, 12)

# ============================================================ 2. _sources
M1 = NS(content=[NS(type="text", text="a", citations=[NS(url="https://u1", title=" T1 "), NS(url="https://u1", title="重複"), NS(url=None, title="冇網址")]),
                 NS(type="web_search_tool_result", content=[NS(type="web_search_result", url="https://u2", title="T2", page_age="1 day"),
                                                            NS(type="web_search_result", url="https://u1", title="又係 u1")])])
M2 = NS(content=[NS(type="text", text="b", citations=[NS(url="https://u3", title="T3")])])
check(llm._sources([M1, M2]) == [dict(title="T1", url="https://u1", age=None), dict(title="T3", url="https://u3", age=None),
                                 dict(title="T2", url="https://u2", age="1 day")], "_sources：網址去重、冇網址唔要、有引用嘅排先")
check([s["url"] for s in llm._sources([M1, M2], cited_only=True)] == ["https://u1", "https://u3"] and len(llm._sources([M1, M2], limit=1)) == 1,
      "_sources：cited_only 淨係要引用過嘅；limit 限數量")


# ============================================================ 3. _claude_ask
class Err(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.status_code = code


CALLS = []


def claude_seq(seq):
    def f(messages, system, timeout, kind, tools=None, max_tokens=None, schema=None):
        CALLS.append(dict(prompt=messages[0]["content"], max_tokens=max_tokens, schema=schema))
        if len(CALLS) > 5:
            raise AssertionError("叫得太多")
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return NS(content=[NS(type="text", text=x)], model=llm.MODEL)
    CALLS.clear()
    llm._claude_call = f


def ask(**kw):
    try:
        return llm._claude_ask("問題", 60, **kw), None
    except Exception as e:  # noqa: BLE001
        return None, e


SCH = {"type": "object", "properties": {"a": {"type": "integer"}}}
claude_seq([Err("output_config.format.schema: unsupported keyword", 400), '{"a": 1}'])
got, err = ask(schema=SCH)
check(got and got[0] == {"a": 1} and len(CALLS) == 2 and CALLS[1]["schema"] is None and "JSON Schema" in CALLS[1]["prompt"],
      "_claude_ask：固定格式被拒（400 schema）→ 將 Schema 寫入提示再試一次")
claude_seq([Err("529 overloaded", 529), '{"a": 2}'])
got, err = ask(schema=SCH)
check(err is not None and "overloaded" in str(err) and len(CALLS) == 1, "_claude_ask：其他錯誤（529）唔改提示重試，照報錯（交俾後備）")
claude_seq([Err("output_config.format: bad", 400), '{"a": 3}'])
got, err = ask()
check(err is not None and len(CALLS) == 1, "_claude_ask：冇用固定格式就唔會因為 400 schema 改提示")
claude_seq([Err("max_tokens: 64000 > 32000, which is the maximum", 400), '{"a": 4}'])
got, err = ask(max_tokens=64000)
check(got[0] == {"a": 4} and [c["max_tokens"] for c in CALLS] == [64000, llm.MAX_TOKENS], "_claude_ask：max_tokens 太大 → 退返預設再試")

# ============================================================ 4. gem_pick
llm._AVAIL = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-3-flash", "gemini-3.1-flash", "gemini-flash-lite-latest",
              "gemini-2.5-flash-lite", "gemini-3-flash-lite", "gemini-embedding-001"]
D_BASE = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-9-pro", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
T_BASE = ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest"]
check(llm.gem_pick("k", D_BASE) == ["gemini-flash-latest", "gemini-2.5-flash", "gemini-3.1-flash", "gemini-3-flash",
                                    "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-3-flash-lite"],
      "gem_pick：Flash 先、Lite 後；原本次序先，再加新版本（3.1 先過 3）；key 冇開放嘅（9-pro）唔用")
check(llm.gem_pick("k", T_BASE) == ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-3-flash-lite",
                                    "gemini-flash-latest", "gemini-3.1-flash", "gemini-3-flash", "gemini-2.5-flash"],
      "gem_pick：翻譯（第一個係 Lite）→ Lite 組先")
llm._AVAIL = []
check(llm.gem_pick("k", D_BASE) == D_BASE, "gem_pick：問唔到型號清單 → 照原本次序")


# ============================================================ 5. 重試
class Resp:
    def __init__(self, d):
        self.b = json.dumps(d).encode()

    def read(self):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http(code, body=b"busy"):
    return urllib.error.HTTPError("https://x.test", code, f"HTTP {code}", {}, io.BytesIO(body))


URLS = []


def serve(seq):
    URLS.clear()
    SLEPT.clear()

    def f(req, timeout=None):
        URLS.append(req.full_url)
        if len(URLS) > 6:
            raise AssertionError("請求太多")
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return Resp(x)
    llm.urllib.request.urlopen = f


REAL = llm.urllib.request.urlopen
os.environ.update(GEMINI_API_KEY="fake-g", MISTRAL_API_KEY="fake-m", DEEPSEEK_API_KEY="fake-d")
GOK = {"candidates": [{"content": {"parts": [{"text": '{"g": 1}'}]}}]}
serve([http(503), GOK])
check(llm._gemini_ask("p", ["m1", "m2"], 300) == ({"g": 1}, "m1") and SLEPT == [10] and all("/m1:" in u for u in URLS),
      "Gemini：503（伺服器忙）、仲有時間 → 等 10 秒同一個型號再試")
serve([http(503), GOK])
check(llm._gemini_ask("p", ["m1", "m2"], 30) == ({"g": 1}, "m2") and SLEPT == [] and "/m2:" in URLS[-1],
      "Gemini：503 但剩唔夠 60 秒 → 唔等，直接試下一個型號")
serve([http(429), GOK])
check(llm._gemini_ask("p", ["m1", "m2"], 300) == ({"g": 1}, "m2") and SLEPT == [], "Gemini：429（額度）唔等，試下一個型號")

MOK = {"choices": [{"message": {"content": '{"m": 1}'}}]}
llm.MIS_MODELS, llm.MIS_GAP = ["mm1", "mm2"], 0.0
serve([http(429), MOK])
check(llm._mistral("p", 300) == ({"m": 1}, "mistral:mm1") and SLEPT == [8] and len(URLS) == 2, "Mistral：429、仲有時間 → 等 8 秒再試同一個型號")
serve([http(429), MOK])
check(llm._mistral("p", 30) == ({"m": 1}, "mistral:mm2") and SLEPT == [], "Mistral：429 但剩唔夠 40 秒 → 唔等，試下一個型號")
serve([http(500), MOK])
check(llm._mistral("p", 300) == ({"m": 1}, "mistral:mm2") and SLEPT == [], "Mistral：其他錯誤唔等，試下一個型號")

llm._paid_check = lambda prov: None
DOK = {"choices": [], "usage": {}}
serve([http(503), DOK])
check(llm._ds_post("/chat/completions", {}, 300) == DOK and SLEPT == [5], "DeepSeek：503、仲有時間 → 等 5 秒再試")
serve([http(429, b"rate limit for api key: sk-SECRET123"), DOK])
try:
    llm._ds_post("/chat/completions", {}, 30)
    err = ""
except RuntimeError as e:
    err = str(e)
check(err.startswith("deepseek：HTTP 429") and "sk-SECRET123" not in err and "****" in err and SLEPT == [] and len(URLS) == 1,
      "DeepSeek：429 但剩唔夠 40 秒 → 唔再試、報錯；錯誤訊息遮走 key")
serve([http(402, b"Insufficient Balance"), DOK])
try:
    llm._ds_post("/chat/completions", {}, 300)
    err = ""
except RuntimeError as e:
    err = str(e)
check(err.startswith("deepseek：HTTP 402") and len(URLS) == 1 and SLEPT == [], "DeepSeek：402 餘額不足唔重試")
llm.urllib.request.urlopen = REAL
print(f"\n全部 {ok} 項通過")
