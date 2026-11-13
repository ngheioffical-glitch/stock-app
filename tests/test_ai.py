# -*- coding: utf-8 -*-
"""2026-11-13 scanner/ai.py 行為測試（流程審計 S6：之前淨係經 feeds／pause 測試間接行過，好多分支冇測）。假數據、唔上網、唔叫真 AI、唔改規則。
1. ai_to：剩返唔夠 15 秒就唔再叫 AI；timeout 唔可以超過剩返時間。
2. prev：workflow 攞咗上一份（FEEDS_PREV）就讀本機，冇先上網；上網失敗 = 空。
3. translate：沿用舊翻譯；AI 回覆空白／唔係字串嘅唔當翻譯；未夠時間唔譯；冇新嘢唔叫 AI。
4. econ_ai：公佈超過 24 小時唔解讀；解讀過嘅 45 分鐘後（6 個鐘內）再解讀一次（第 2 階段）。
5. fed_ai：全文少過 300 字唔總結；會議紀錄／聲明優先；舊總結留 45 日。
6. digest：事實核對通過就寫一次；唔符合重寫一次（最多 2 次）；新聞冇變沿用。
7. light_change：最近兩日 green10 唔同先算轉燈。
8. intraday_move：淨係美股開市時間（平日 9:30–16:00 紐約）先睇；每 1.5% 一格。
9. season／btc_history：淨係計已經完咗嘅月。
用法：python tests/test_ai.py"""
import contextlib
import io
import json
import os
import sys
import time
import types
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import ai  # noqa: E402

OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "ai" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"   # 同一秒跑兩次都唔撞
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


class Resp:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self.body


REAL_URLOPEN = urllib.request.urlopen


def serve(fn):
    seen = []

    def fake(req, timeout=None):
        url = getattr(req, "full_url", req)
        seen.append(url)
        return Resp(fn(url))
    urllib.request.urlopen = fake
    return seen


def boom(*a, **k):
    raise RuntimeError("boom")


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# ============================================================ 1. ai_to
ai.T0 = time.time()
check(ai.ai_to(300) == 300 and ai.ai_to(5) == 5, "ai_to：時間仲有好多 → 用要求嘅 timeout")
ai.T0 = time.time() - (ai.AI_BUDGET - 40)                 # 剩約 40 − 10 = 30 秒
v = ai.ai_to(300)
check(25 < v <= 30, f"ai_to：剩約 30 秒 → timeout 縮到剩返嘅時間（{v:.1f}）")
ai.T0 = time.time() - (ai.AI_BUDGET - 20)                 # 剩約 10 秒
try:
    ai.ai_to(300)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("AI 時間用晒" in msg, "ai_to：剩唔夠 15 秒 → 唔再叫 AI（沿用上一份）")
ai.T0 = time.time()

# ============================================================ 2. prev
os.environ.pop("FEEDS_PREV", None)
os.environ.pop("GITHUB_REPOSITORY", None)
serve(lambda u: json.dumps({"from": u}))
check(ai.prev("news.json") == {"from": "https://raw.githubusercontent.com/ngheioffical-glitch/stock-app/feeds/news.json"},
      "prev：冇 FEEDS_PREV → 上網攞 feeds 分支上一份")
PD = OUT / "prev"
PD.mkdir()
(PD / "news.json").write_text(json.dumps({"local": True}), encoding="utf-8")
os.environ["FEEDS_PREV"] = str(PD)
seen = serve(boom)
check(ai.prev("news.json") == {"local": True} and seen == [], "prev：workflow 用 git 攞咗（FEEDS_PREV）→ 讀本機，唔上網")
check(ai.prev("econ.json") == {}, "prev：本機冇嗰個檔 → 上網；上網都失敗 → 空")
os.environ.pop("FEEDS_PREV")
urllib.request.urlopen = REAL_URLOPEN

# ============================================================ 3. translate
calls = []


def fake_ask(reply):
    def f(key, prompt, models_, light=False):
        calls.append(dict(prompt=prompt, light=light))
        if len(calls) > 5:
            raise RuntimeError("叫 AI 太多次")
        return (reply(len(calls)) if callable(reply) else reply), "gemini:test"
    return f


N = {"items": [dict(title="Fed holds", cat="快訊"), dict(title="Old one", cat="市場"), dict(title="Blank", cat="經濟"), dict(title="NoneReply", cat="加密"),
               dict(title="Sports", cat="體育")]}
P = {"items": [dict(title="Old one", zh="舊譯", zm="m0")]}
S = {"tweets": [dict(id="s1", text="tw1")]}
Tp = {"posts": [dict(id="t1", text="p1"), dict(id="t2", text="p2"), dict(id="t3", text="p3"), dict(id="t4", text="")]}
PT = {"posts": [dict(id="t3", zh="舊T3", zm="m0")]}
ai.ask = fake_ask({"news": ["聯儲局按兵不動", "  ", None], "tweets": ["推文一"], "trump": ["帖一", ""]})
msg = ai.translate(None, N, S, P, {"tweets": []}, Tp, PT)
it = {x["title"]: x for x in N["items"]}
check(msg == "新聞 3／3 條、Serenity 1／1 條、Trump 2／2 條（gemini:test）" and calls[0]["light"] is True, "translate：一次過譯晒新嘢（翻譯用輕量 AI）")
check(it["Fed holds"]["zh"] == "聯儲局按兵不動" and it["Fed holds"]["zm"] == "gemini:test" and "zh" not in it["Blank"] and "zh" not in it["NoneReply"]
      and it["Old one"]["zh"] == "舊譯" and "zh" not in it["Sports"], "translate 新聞：沿用舊翻譯；AI 回空白或者唔係字串 → 唔當譯咗；體育唔譯")
tp = {t["id"]: t for t in Tp["posts"]}
check(tp["t1"]["zh"] == "帖一" and "zh" not in tp["t2"] and tp["t3"]["zh"] == "舊T3" and "zh" not in tp["t4"] and S["tweets"][0]["zh"] == "推文一",
      "translate Trump／Serenity：空白回覆唔要；冇字嘅帖唔譯；舊翻譯沿用")
calls.clear()
N2 = {"items": [dict(title="New", cat="快訊")]}
check(ai.translate(None, N2, None, {"items": []}, {"tweets": []}, allow=False).startswith("未夠 30 分鐘") and calls == [], "translate：未夠時間 → 唔叫 AI，遲啲先譯")
check(ai.translate(None, {"items": [dict(title="Old one", cat="市場")]}, None, P, {"tweets": []}) == "冇新嘢要譯" and calls == [], "translate：全部有舊翻譯 → 唔叫 AI")

# ============================================================ 4. econ_ai
NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)          # 紐約 10:00
ai.reaction = lambda rel: "QQQ +0.10%"
E = {"rows": [dict(t="2026-11-13T08:30:00", name="CPI", actual="3.1%", imp=3),
              dict(t="2026-11-12T09:00:00", name="OLD25", actual="1", imp=3),
              dict(t="2026-11-13T09:00:00", name="NOACT", actual="", imp=3),
              dict(t="2026-11-13T09:00:00", name="LOWIMP", actual="1", imp=0),
              dict(t="2026-11-13", name="DATEONLY", actual="1", imp=3),
              dict(t="2026-11-13T07:00:00", name="STAGED", actual="1", imp=2),
              dict(t="2026-11-13T08:00:00", name="RECENT", actual="1", imp=2),
              dict(t="2026-11-13T02:00:00", name="SIXH", actual="1", imp=2)]}
iso = lambda m: (NOW - timedelta(minutes=m)).isoformat(timespec="seconds")
PE = {"rows": [dict(t="2026-11-13T07:00:00", name="STAGED", ai="舊解讀1", ai_at=iso(50), ai_stage=1, ai_model="m0"),
               dict(t="2026-11-13T08:00:00", name="RECENT", ai="舊解讀2", ai_at=iso(30), ai_stage=1, ai_model="m0"),
               dict(t="2026-11-13T02:00:00", name="SIXH", ai="舊解讀3", ai_at=iso(120), ai_stage=1, ai_model="m0")]}
calls.clear()
ai.ask = fake_ask({"items": [dict(i=0, text="解讀0"), dict(i=1, text=" 解讀1 "), dict(i=9, text="x"), dict(i="bad", text="y"), dict(i=0, text="")]})
msg = ai.econ_ai(None, {"items": []}, E, PE, NOW, "綠燈", ["NVDA"])
er = {r["name"]: r for r in E["rows"]}
check(msg == "經濟數據解讀 2／2 項（gemini:test）" and "CPI（CPI）" in calls[0]["prompt"] and "QQQ +0.10%" in calls[0]["prompt"],
      "econ_ai：啱啱公佈（90 分鐘前）嘅 CPI 同到期再解讀嘅數據送 AI，連市場反應")
check(er["CPI"]["ai"] == "解讀0" and er["CPI"]["ai_stage"] == 1 and er["CPI"]["ai_at"] == NOW.isoformat(timespec="seconds") and er["CPI"]["ai_model"] == "gemini:test",
      "econ_ai：第一次解讀 = 第 1 階段")
check(er["STAGED"]["ai"] == "解讀1" and er["STAGED"]["ai_stage"] == 2, "econ_ai：解讀咗 50 分鐘（≥ 45）、公佈 3 個鐘（< 6）→ 再解讀一次 = 第 2 階段")
check(er["RECENT"]["ai"] == "舊解讀2" and er["SIXH"]["ai"] == "舊解讀3" and all("ai" not in er[k] for k in ("OLD25", "NOACT", "LOWIMP", "DATEONLY")),
      "econ_ai：解讀咗未夠 45 分鐘、公佈超過 6 個鐘 → 沿用舊解讀；超過 24 小時、未有實際數、低影響、冇時間 → 唔解讀")
calls.clear()
check(ai.econ_ai(None, {"items": []}, {"rows": [E["rows"][1]]}, {"rows": []}, NOW, "綠燈", []) == "冇新數據要解讀" and calls == [],
      "econ_ai：淨係有超過 24 小時嘅數據 → 唔叫 AI")

# ============================================================ 5. fed_ai
fiso = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
RSS = {"press": [dict(title="FOMC statement", link="L1", t=fiso(2), src="聯儲局"),
                 dict(title="Minutes of the Federal Open Market Committee, October", link="L2", t=fiso(1), src="聯儲局"),
                 dict(title="Bank holiday notice", link="L3", t=fiso(0.5), src="聯儲局"),
                 dict(title="FOMC old", link="L5", t=fiso(46), src="聯儲局")],
       "speech": [dict(title="Speech by Governor X", link="L4", t=fiso(0.1), src="聯儲局講話")]}
sys.modules["feeds"] = types.SimpleNamespace(rss=lambda url, src, cat: RSS["press" if "press" in url else "speech"])
TXT = {"L2": "x" * 299, "L1": "y" * 300, "L4": "z" * 5000}
ai.fed_text = lambda url: TXT[url]
calls.clear()
ai.ask = fake_ask({"title": "聯儲局聲明", "tone": "中性", "points": ["p1", " ", 3], "change": "", "impact": "影響"})
Nf = {"items": []}
Pf = {"fed": [dict(link="L9", t=fiso(10), title="舊"), dict(link="L8", t=fiso(50), title="太舊")]}
msg = quiet(ai.fed_ai, None, Nf, Pf, NOW)
check([f["link"] for f in Nf["fed"]] == ["L1", "L9"] and len(calls) == 1 and msg == "聯儲局文件總結 新 1／候選 2，共 2 份",
      "fed_ai：每次最多 2 份（會議紀錄、聲明優先過講話）；會議紀錄全文唔夠 300 字唔總結；舊總結留 45 日（50 日嘅刪走）")
f1 = Nf["fed"][0]
check(f1["kind"] == "聲明／公佈" and f1["points"] == ["p1"] and f1["tone"] == "中性" and f1["src_title"] == "FOMC statement" and "y" * 300 in calls[0]["prompt"],
      "fed_ai：總結內容（類別、重點只要非空字串、語氣）")
del sys.modules["feeds"]

# ============================================================ 6. digest
for name in ("light_change", "tq_alert", "rates_alert", "commod_alert", "fut_alert", "intraday_move", "premarket"):
    setattr(ai, "_real_" + name, getattr(ai, name))
    setattr(ai, name, lambda: None)
ai.context = lambda: ("綠燈", ["NVDA"])
ai.snapshot = lambda: [dict(s="QQQ", name="QQQ", chg=1.0, unit="%", at="11-13 23:00")]
ai.OUTDIR = None
Nd = {"items": [dict(title="Big news", cat="快訊", t=(NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), imp=3)]}
calls.clear()
ai.ask = fake_ask({"points": ["納指上升，科技股造好"], "econ": ""})
d, msg = ai.digest(None, Nd, {"rows": []}, {}, NOW)
check(d["tries"] == 1 and len(calls) == 1 and d["warn"] == [] and d["points"] == ["納指上升，科技股造好"] and d["checked"] is True and d["hi"] == ["Big news"],
      "digest：事實核對通過（QQQ +1%、AI 寫納指上升）→ 寫一次就得")
calls.clear()
ai.ask = fake_ask(lambda n: {"points": ["納指下跌"] if n == 1 else ["納指上升"], "econ": ""})
d2, msg = quiet(ai.digest, None, Nd, {"rows": []}, {}, NOW)
check(d2["tries"] == 2 and d2["warn"] == [] and d2["points"] == ["納指上升"] and "你上一版有錯" in calls[1]["prompt"] and "實際QQQ +1.00%" in calls[1]["prompt"],
      "digest：寫錯方向（實際升、寫跌）→ 話返 AI 邊度錯，重寫一次")
calls.clear()
ai.ask = fake_ask({"points": ["納指下跌"], "econ": ""})
d3, msg = quiet(ai.digest, None, Nd, {"rows": []}, {}, NOW)
check(d3["tries"] == 2 and len(calls) == 2 and d3["warn"] and "核對有 1 處唔符" in msg, "digest：重寫都仲錯 → 最多寫 2 次，記低唔符合（app 顯示提示）")
calls.clear()
old, msg = ai.digest(None, Nd, {"rows": []}, {"digest": d}, NOW)
check(old is d and msg == "新聞冇變，沿用上一份重點" and calls == [], "digest：新聞同數據冇變 → 沿用，唔叫 AI")
for name in ("light_change", "tq_alert", "rates_alert", "commod_alert", "fut_alert", "intraday_move", "premarket"):
    setattr(ai, name, getattr(ai, "_real_" + name))

# ============================================================ 7. light_change
AR = OUT / "root"
(AR / "docs").mkdir(parents=True)
ai.ROOT = AR


def lc(g):
    (AR / "docs" / "scan.json").write_text(json.dumps({"date": "2026-11-12", "next_day": "2026-11-13", "ndx": 20000, "ndx_s200": 19000, "ndx_e21": 20500,
                                                     "ndx_s50": 20200, "cash": {"green10": g}}), encoding="utf-8")
    return ai.light_change()


check(lc([True] * 9 + [False]) == dict(date="2026-11-12", to="紅燈", frm="綠燈", next_day="2026-11-13",
                                       detail="NDX 收市 20,000；200 日線 19,000；21 日 EMA 20,500；50 日線 20,200"), "light_change：最近一日由綠轉紅 → 轉燈資料")
check(lc([False] * 9 + [True])["to"] == "綠燈" and lc([True] * 10) is None and lc([False, True, True]) is None and lc([True]) is None,
      "light_change：最後兩日一樣（早啲轉過唔計）或者唔夠兩日 → 冇轉燈")

# ============================================================ 8. intraday_move
NY = ZoneInfo("America/New_York")


class AiDT(datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW


def move(ny, px=98.4):
    AiDT.NOW = datetime(*ny, tzinfo=NY)
    ai._MV.clear()
    seen = serve(lambda u: json.dumps({"chart": {"result": [{"meta": {"chartPreviousClose": 100.0, "regularMarketPrice": px}}]}}))
    ai.datetime = AiDT
    try:
        return quiet(ai.intraday_move), seen
    finally:
        ai.datetime = datetime
        urllib.request.urlopen = REAL_URLOPEN


v, seen = move((2026, 11, 12, 10, 0))
check(v == dict(text="盤中 QQQ 大跌 1.6%（由上日收市計；TQQQ 大約 -4.8%）", b=-1, chg=-1.6, key="2026-11-12|-1") and len(seen) == 1,
      "intraday_move：平日開市時間 QQQ −1.6%（≥ 1 格 1.5%）→ 盤中大跌提示")
check(move((2026, 11, 12, 15, 59))[0]["key"] == "2026-11-12|-1" and move((2026, 11, 12, 9, 30))[0] is not None, "intraday_move：9:30 同 15:59 都計")
check(all(move(t) == (None, []) for t in ((2026, 11, 12, 9, 29), (2026, 11, 12, 16, 0), (2026, 11, 14, 10, 0))),
      "intraday_move：開市前、16:00 收市後、星期六 → 唔睇（唔上網）")
check(move((2026, 11, 12, 10, 0), px=101.4)[0] is None and move((2026, 11, 12, 10, 0), px=103.1)[0]["b"] == 2, "intraday_move：唔夠 1.5% 冇；+3.1% = 2 格")
ai._MV.clear()

# ============================================================ 9. season／btc_history
def monthly(y1=2026, m1=11):
    ts, cl, c, y, m = [], [], 100.0, 2000, 1
    while (y, m) <= (y1, m1):
        if (y, m) != (2000, 1):
            c *= 0.98 if m == 11 else 1.01                       # 每年 11 月跌 2%，其他月升 1%
        ts.append(int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp()))
        cl.append(1e9 if (y, m) == (y1, m1) else c)               # 今個月未完：古怪數字，唔可以計
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": cl}]}}]}})


MON = monthly()
serve(lambda u: MON)
S2 = quiet(ai.season, datetime(2026, 11, 13, tzinfo=timezone.utc))
check(len(S2) == 2 and S2[0] == "S&P 500（2000 起）：11 月 0/26 年升、平均 -2.0%；11–12 月 0/26 年升、平均 -1.0%；中期選舉年（2010, 2014, 2018, 2022 等）"
      "11–12 月 0/6 年升、平均 -1.0%；中期選舉年 11 月起之後 12 個月 6/6 年升、平均 +9.3%" and S2[1].startswith("納指 100（2000 起）：11 月 0/26 年升"),
      "season：今個月（未完）唔計；11 月、11–12 月、中期選舉年同期、之後 12 個月嘅升跌年數同平均")
serve(lambda u: MON if "yahoo" in u else boom())
B = quiet(ai.btc_history, datetime(2026, 11, 13, tzinfo=timezone.utc))
urllib.request.urlopen = REAL_URLOPEN
check(B == ["BTC 季節性（2000 起）：11 月 0/26 年升、平均 -2.0%、中位 -2.0%；11–12 月 0/26 年升、平均 -1.0%、中位 -1.0%"],
      "btc_history：今個月唔計；減半週期數據攞唔到 → 淨係寫季節性，唔 crash")
print(f"\n全部 {ok} 項通過")
