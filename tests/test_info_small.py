# -*- coding: utf-8 -*-
"""2026-11-13 資訊類細模組行為測試（流程審計 S6：hyper、valuation、theme、trump、rates、walert、macro_src、lev2x、earnings、serenity、commod、
airdrop 之前冇測試或者測唔到分支）。假數據、唔上網（換走 urlopen／xfeed.posts／yfinance／AI）、唔改規則；唔 import pandas，跑得快。
1. hyper：揀巨鯨（帳戶 ≥ 100 萬、上月成交 ÷ 帳戶 < 300、歷史盈利頭 25 + 上月頭 10）；持倉變動 → 開／加／減／平／反手，< 25 萬美元唔報。
2. valuation：10 年平均 ± 標準差分五級；multpl 1990 年後百分位分級（< 100 行報錯）；個股 PEG／對 Nasdaq 100 分級；攞唔到沿用舊（標 stale）。
3. theme：升幅、距高位、成交倍數、> 50 日線；百分位；新聞同 Trump 帖只要 48 小時內。
4. trump：兩個來源一個出事照有數據、兩個都出事先報錯；since 4 日一段攞，滿 100 條縮做 1 日。
5. rates：財政部數據 < 30 日唔要；盤中價日子新過收市先用；單日郁 ≥ 10 基點／52 週新高要 alert。
6. walert：48 小時內先要；入／出交易所；24 小時淨流（穩定幣合埋、印發減銷毀）；冇數據唔等於出錯。
7. macro_src：Polymarket 宏觀頭 15、加密頭 12，走去體育／單日價格賭局／唔係「Yes」嘅。
8. lev2x：由 ETF 名抽正股；大發行商排先；< 50 隻唔覆蓋舊檔。
9. earnings：未來 100 日內業績先列；最近 10 日出咗嘅交 AI（持倉優先，每次 3 個）；未夠 2 個鐘唔再做。
10. serenity：淨係要有 cashtag、喺時間範圍內；60 日版冇數據唔覆蓋，近 3 日版照寫。
11. commod：最新價同收市一樣唔加；< 30 日唔要；油／金／銅 alert；銅金比率。
12. airdrop：DefiLlama TVL ≤ 0 當冇；淨係收費 AI（DeepSeek）喺繁忙時段先唔寫。
用法：python tests/test_info_small.py"""
import contextlib
import io
import json
import os
import sys
import time
import types
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import xfeed  # noqa: E402
import hyper  # noqa: E402
import valuation  # noqa: E402
import theme  # noqa: E402
import trump  # noqa: E402
import rates  # noqa: E402
import walert  # noqa: E402
import macro_src  # noqa: E402
import lev2x  # noqa: E402
import earnings  # noqa: E402
import serenity  # noqa: E402
import commod  # noqa: E402
import airdrop  # noqa: E402
import llm  # noqa: E402

time.sleep = lambda s: None                     # valuation／trump 會等；測試唔使等
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "info_small" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"   # 同一秒跑兩次都唔撞
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def near(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


class Resp:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self.body


REAL_URLOPEN = urllib.request.urlopen


def serve(fn):
    """換走 urlopen：fn(url) → 內容（str／bytes），或者 raise。用完要 urllib.request.urlopen = REAL_URLOPEN。"""
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


# ============================================================ 1. hyper
def lb_row(i, av=2e6, vlm=1e6):
    return dict(ethAddress=f"0x{i:040x}", displayName=None if i % 2 else f"W{i:02d}", accountValue=str(av),
                windowPerformances=[["day", {"pnl": "0", "roi": "0", "vlm": "0"}],
                                    ["month", {"pnl": str(i), "roi": "0.123456", "vlm": str(vlm)}],
                                    ["allTime", {"pnl": str(1000 - i), "roi": "1", "vlm": "0"}]])


LB = [lb_row(i) for i in range(40)]
LB[0] = lb_row(0, av=999_999)                    # 差 1 蚊先夠 100 萬：唔要
LB[1] = lb_row(1, av=1_000_000)                  # 啱啱 100 萬：要
LB[2] = lb_row(2, vlm=300 * 2e6)                 # 上月成交 = 帳戶 300 倍：造市商，唔要
LB[3] = lb_row(3, vlm=299.9 * 2e6)
serve(lambda u: json.dumps({"leaderboardRows": LB}))
W = hyper.pick_whales()
urllib.request.urlopen = REAL_URLOPEN
A = lambda i: f"0x{i:040x}"
check([w["addr"] for w in W] == [A(1)] + [A(i) for i in range(3, 27)] + [A(i) for i in range(39, 29, -1)],
      "hyper 揀巨鯨：< 100 萬、成交 ≥ 300 倍唔要；歷史盈利頭 25（1、3–26），再加上月盈利頭 10 個未入選嘅（39–30）")
check(W[0] == dict(addr=A(1), name=None, value=1_000_000, pnl_all=999, pnl_month=1, roi_month=0.1235) and W[1]["name"] is None and W[2]["name"] == "W04",
      "hyper 巨鯨欄位：帳戶值、歷史／上月盈利（整數）、上月回報（4 位小數）、名")
check(hyper.label(dict(addr="0xabcdef1234567890", name=None)) == "0xabcd…7890" and hyper.label(dict(addr="0x1", name="Bob")) == "Bob",
      "hyper label：有名用名，冇名用地址頭 6 尾 4")
w = dict(addr="0xabcdef1234567890", name=None)
old = [dict(coin="BTC", szi=10.0, entry=50000.0), dict(coin="ETH", szi=-100.0, entry=3000.0), dict(coin="SOL", szi=1000.0, entry=100.0),
       dict(coin="DOGE", szi=1e6, entry=0.2), dict(coin="XRP", szi=500_000.0, entry=2.0), dict(coin="AVAX", szi=5000.0, entry=20.0),
       dict(coin="LINK", szi=10000.0, entry=20.0), dict(coin="ARB", szi=-1_000_000.0, entry=1.0)]
new = [dict(coin="BTC", szi=10.0, entry=50000.0, lev=5), dict(coin="ETH", szi=-200.0, entry=3500.0, lev=10), dict(coin="HYPE", szi=20000.0, entry=38.0, lev=3),
       dict(coin="DOGE", szi=-2e6, entry=0.31, lev=2), dict(coin="XRP", szi=300_000.0, entry=2.5, lev=4), dict(coin="AVAX", szi=5100.0, entry=20.0, lev=1),
       dict(coin="ARB", szi=-400_000.0, entry=1.0, lev=2), dict(coin="SUI", szi=-100_000.0, entry=4.0, lev=5)]
px = dict(BTC=100000.0, ETH=4000.0, SOL=250.0, HYPE=40.0, DOGE=0.3, AVAX=20.0, LINK=24.9999, ARB=0.5, SUI=3.0)
EV = {e["coin"]: e for e in hyper.diff(w, old, new, px, "2026-11-13T00:00:00Z")}
check(set(EV) == {"ETH", "SOL", "HYPE", "DOGE", "XRP", "ARB", "SUI"},
      "hyper diff：冇變（BTC）唔報；變動 < 25 萬美元（AVAX 2,000、LINK 249,999）唔報；啱啱 25 萬（SOL）照報")
check({k: (e["act"], e["usd"]) for k, e in EV.items()} == {"ETH": ("加空", 400000), "SOL": ("平多", 250000), "HYPE": ("開多", 800000), "DOGE": ("反手空", 900000),
                                                          "XRP": ("減多", 500000), "ARB": ("減空", 300000), "SUI": ("開空", 300000)},
      "hyper diff 動作同金額：開（新倉 × 價）、平（舊倉 × 價）、反手（|新 − 舊| × 價）、加、減")
e = EV["ETH"]
check(e["who"] == "0xabcd…7890" and e["px"] == 4000.0 and e["pos_usd"] == 800000 and e["lev"] == 10 and e["entry"] == 3500.0 and e["t"] == "2026-11-13T00:00:00Z",
      "hyper 事件：而家倉位金額、槓桿、入場價用新倉")
check(EV["SOL"]["pos_usd"] == 0 and EV["SOL"]["lev"] is None and EV["XRP"]["px"] == 2.5,
      "hyper：平晒倉位金額 0；冇市價（XRP）用入場價計")

# ============================================================ 2. valuation
B = valuation.band
check([B(p, 20, 5) for p in (30, 29.9, 25, 24.9, 15.1, 15, 10.1, 10)] == ["好貴", "偏貴", "偏貴", "正常", "正常", "偏平", "偏平", "好平"],
      "valuation band：≥ +2 個標準差好貴、≥ +1 偏貴、≤ −1 偏平、≤ −2 好平，其餘正常")
check(B(None, 20, 5) is None and B(25, 20, 0) is None and B(25, None, 5) is None, "valuation band：冇數或者標準差 0 → 唔判斷")
valuation.get = lambda url, timeout=30: ("<html><script>var s='P/E) Ratio for fake is 99 ';</script><p>The Nasdaq 100 Price to Earnings (P/E) Ratio for "
                                         "Nasdaq 100 is 35.20 as of today</p><div>10Y Average: 25.0 · 1 Std Dev range: [20.0 , 30.0]</div>"
                                         "<div>5Y Average: 30.1 · 1 Std Dev range: [27.0 , 33.2]</div></html>")
wp = valuation.worldpe("nasdaq-100", "Nasdaq 100")
check(wp["pe"] == 35.2 and set(wp["avg"]) == {"10", "5"} and wp["avg"]["10"] == dict(mu=25.0, lo=20.0, hi=30.0) and wp["label"] == "好貴",
      "valuation worldpe：唔睇 script 入面嘅字；用 10 年平均 25、標準差 (30 − 20) ÷ 2 = 5 → 35.2 係 +2 個標準差 → 好貴")


def multpl_html(cur, n_post=99, n_pre=20):
    r = [("Nov 1, 2026", cur)] + [(f"Jan {1 + k % 28}, {2000 + k // 28}", float(k + 1)) for k in range(n_post)] + [("Jan 1, 1950", 1000.0)] * n_pre
    pre = ['<abbr title="estimate">†</abbr>', "&#x2002;", ""]
    return "".join(f"<tr><td>{d}</td>\n<td>\n{pre[k % 3]}\n{v}\n</td></tr>" for k, (d, v) in enumerate(r))


def mp(cur, **k):
    valuation.get = lambda url, timeout=30: multpl_html(cur, **k)
    return valuation.multpl("shiller-pe", "CAPE")


m = mp(50.0)
check(m["value"] == 50.0 and m["date"] == "Nov 1, 2026" and m["pct1990"] == 49 and m["med1990"] == 50.0 and m["med_all"] == 59.5 and m["max1990"] == 99.0
      and m["label"] == "中間", "valuation multpl：百分位同中位數淨係計 1990 年後（1950 年嘅 1000 唔計），全期中位數先計")
check([mp(c)["label"] for c in (91, 90, 71, 70, 32, 31, 12, 11)] == ["歷史好高", "偏高", "偏高", "中間", "中間", "偏低", "偏低", "歷史好低"],
      "valuation multpl 分級：≥ 90 百分位歷史好高、≥ 70 偏高、≤ 30 偏低、≤ 10 歷史好低")
check(mp(50.0, n_post=99, n_pre=0)["value"] == 50.0, "valuation multpl：啱啱 100 行照用")
try:
    mp(50.0, n_post=98, n_pre=0)
    msg = ""
except RuntimeError as ex:
    msg = str(ex)
check("歷史得 99 行" in msg, "valuation multpl：唔夠 100 行（網頁改咗格式）→ 報錯，唔好用殘缺數據")
S = valuation.stock_label
check([S(f, 1.0, 30)[0] for f in (None, 0, -5)] == ["冇盈利預測"] * 3, "valuation 個股：冇預期盈利或者 ≤ 0 → 冇盈利預測")
check([S(30, p, 30)[0] for p in (0.99, 1, 1.99, 2, 2.99, 3)] == ["偏平", "合理", "合理", "偏貴", "偏貴", "好貴"], "valuation 個股：PEG < 1 偏平、< 2 合理、< 3 偏貴、≥ 3 好貴")
check([S(f, None, 30)[0] for f in (20.9, 21, 38.9, 39, 59.9, 60)] == ["偏平", "同大市差唔多", "同大市差唔多", "偏貴", "偏貴", "好貴"],
      "valuation 個股：冇 PEG 就同 Nasdaq 100（30 倍）比：< 0.7 倍偏平、< 1.3 差唔多、< 2 偏貴、≥ 2 好貴")
check(S(45, -1, 30)[0] == "偏貴" and S(45, 0, 30)[0] == "偏貴" and S(45, -1, None) == ("未有判斷", ""), "valuation 個股：PEG ≤ 0 唔用 PEG；冇 PEG 又冇大市市盈率 → 未有判斷")


class FakeTicker:
    INFO = {"AAA": dict(forwardPE=30.0, trailingPE=40.123, trailingPegRatio=1.5, priceToSalesTrailing12Months=10.04, earningsGrowth=0.2, revenueGrowth=0.15),
            "BBB": dict(forwardPE=-5.0, trailingPE=None, pegRatio=None)}

    def __init__(self, s):
        self.s = s

    @property
    def info(self):
        if self.s == "BAD":
            raise RuntimeError("boom")
        return self.INFO[self.s]


sys.modules["yfinance"] = types.SimpleNamespace(Ticker=FakeTicker)
st, errs = valuation.stocks(["AAA", "BBB", "BAD"], 30.0)
check(st["AAA"] == dict(fpe=30.0, tpe=40.1, peg=1.5, ps=10.0, eg=0.2, rg=0.15, label="合理", why=st["AAA"]["why"], vs_ndx=1.0) and st["BBB"]["label"] == "冇盈利預測"
      and st["BBB"]["vs_ndx"] is None and "BAD" not in st and errs == ["BAD：boom"], "valuation stocks：Yahoo 欄位四捨五入；試兩次都失敗先記錯")
VR = OUT / "val_root"
(VR / "docs").mkdir(parents=True)
(VR / "docs" / "scan.json").write_text(json.dumps({"ranking": [{"sym": s} for s in ("AAA", "TQQQ", "BBB", "CCC")]}), encoding="utf-8")
(VR / "docs" / "model_cont.json").write_text(json.dumps({"view": {"holdings": [{"sym": "DDD"}, {"sym": "AAA"}, {"sym": "IEF"}]}}), encoding="utf-8")
VJ = VR / "docs" / "valuation.json"
VJ.write_text(json.dumps({"market": {"cape": {"name": "Shiller CAPE", "value": 39.0}},
                          "stocks": {"AAA": {"label": "舊A"}, "CCC": {"label": "舊C"}, "ZZZ": {"label": "舊Z"}}}), encoding="utf-8")
valuation.ROOT, valuation.OUT = VR, VJ
valuation.worldpe = lambda slug, name: dict(name=name, pe=30.0 if slug == "nasdaq-100" else 25.0, avg={}, label=None)
valuation.multpl = lambda path, name: boom()
seen = {}


def fake_stocks(syms, ndx_pe):
    seen.update(syms=syms, ndx=ndx_pe)
    return {"AAA": {"label": "新A"}, "BBB": {"label": "新B"}, "DDD": {"label": "新D"}}, ["CCC：timeout"]


valuation.stocks = fake_stocks
quiet(valuation.main)
V = json.loads(VJ.read_text(encoding="utf-8"))
check(seen == dict(syms=["AAA", "BBB", "CCC", "DDD"], ndx=30.0), "valuation main：排名 + 模型持倉、去重、走 ETF；用 Nasdaq 100 市盈率比較")
check(V["stocks"] == {"AAA": {"label": "新A"}, "BBB": {"label": "新B"}, "DDD": {"label": "新D"}, "CCC": {"label": "舊C", "stale": True}},
      "valuation main：今次攞唔到（CCC）沿用舊（標 stale）；唔再喺名單（ZZZ）唔要；攞到嘅用新")
check(V["market"]["cape"] == {"name": "Shiller CAPE", "value": 39.0, "stale": True} and "spx_hist" not in V["market"] and V["market"]["ndx"]["pe"] == 30.0
      and "CCC：timeout" in V["errs"] and any(x.startswith("cape：") for x in V["errs"]), "valuation main：大市數據攞唔到沿用舊（標 stale）；冇舊就留空；錯誤有記")

# ============================================================ 3. theme
c = [100.0 + i for i in range(70)]
v = [1000.0] * 65 + [3000.0] * 5
m = theme.metrics(c, v)
check(m["px"] == 169.0 and near(m["r1"], 169 / 168 - 1) and near(m["r5"], 169 / 164 - 1) and near(m["r21"], 169 / 148 - 1) and near(m["r63"], 169 / 106 - 1)
      and m["hi"] == 0.0 and near(m["vs"], 2.5) and m["up50"] is True and len(m["spark"]) == 63 and m["spark"][0] == 107.0,
      "theme metrics：1／5／21／63 日升幅、距 52 週高、成交 5 日 ÷ 50 日（3000 ÷ 1200 = 2.5）、高過 50 日線")
m = theme.metrics([200.0 - i for i in range(60)], [0.0] * 60)
check(m["r63"] is None and m["up50"] is False and near(m["hi"], 141 / 200 - 1) and m["vs"] is None, "theme metrics：啱啱 60 日；唔夠 63 日冇 63 日升幅；冇成交量 → 冇倍數")
check(theme.metrics(c[:59], v[:59]) is None, "theme metrics：唔夠 60 日 → 唔計")
check(theme.pctl([1, 2, 3, None, 4], 3) == 75.0 and theme.pctl([1, 2, 3], None) == 0 and theme.pctl([None], 1) == 0, "theme 百分位：≤ 自己嘅比例；冇數 → 0")
now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
NO = OUT / "theme_out"
NO.mkdir()
iso = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
(NO / "news.json").write_text(json.dumps({"items": [dict(t=iso(47), title="Uranium rally", zh="鈾大升", src="R", link="L1"), dict(t=iso(49), title="old"),
                                                     dict(t=iso(1), title="Copper jumps", zh=None, src="B", link="L2")]}), encoding="utf-8")
(NO / "trump_recent.json").write_text(json.dumps({"posts": [dict(ts=(now - timedelta(hours=2)).timestamp(), text="Buy American steel!"),
                                                            dict(ts=(now - timedelta(hours=50)).timestamp(), text="old post")]}), encoding="utf-8")
H = theme.news_hits(NO, now)
check([h["title"] for h in H] == ["鈾大升", "Copper jumps", "Trump：Buy American steel!"] and H[0]["text"] == "Uranium rally 鈾大升" and H[2]["src"] == "Truth Social",
      "theme 新聞：淨係要 48 小時內（49 小時、50 小時嘅唔要）；有中文標題用中文；Trump 帖都計")
NO2 = OUT / "theme_out2"
NO2.mkdir()
(NO2 / "trump_recent.json").write_text((NO / "trump_recent.json").read_text(encoding="utf-8"), encoding="utf-8")
check([h["title"] for h in quiet(theme.news_hits, NO2, now)] == ["Trump：Buy American steel!"], "theme 新聞：冇 news.json 照讀 Trump 帖")

# ============================================================ 4. trump
trump.feed = lambda a, b=None: [dict(id="1", ts=1, text="a")]
trump.xmirror = lambda days: [dict(id="x2", ts=2, text="b", src="x")]
check(trump.recent_posts(3) == ([dict(id="1", ts=1, text="a"), dict(id="x2", ts=2, text="b", src="x")], []), "trump recent_posts：兩個來源合埋（trumpstruth 排先）")
trump.feed = boom
p, e = trump.recent_posts(3)
check(p == [dict(id="x2", ts=2, text="b", src="x")] and e == ["trumpstruth.org：boom"], "trump：trumpstruth 出事、X 有數據 → 照用，記低錯誤")
trump.xmirror = lambda days: (_ for _ in ()).throw(RuntimeError("down"))
try:
    trump.recent_posts(3)
    msg = ""
except RuntimeError as ex:
    msg = str(ex)
check(msg == f"trumpstruth.org：boom；X @{trump.XMIRROR}：down", "trump：兩個來源都出事 → 報錯")
trump.feed, trump.xmirror = (lambda a, b=None: []), (lambda days: [])
check(trump.recent_posts(3) == ([], []), "trump：冇出錯只係冇新帖 → 空，唔報錯")


class TrumpDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 13, 5, 0, tzinfo=timezone.utc)


win = []


def feed_win(a, b=None):
    win.append((a[5:], b[5:]))
    return {("11-10", "11-14"): [dict(id=str(k)) for k in range(100)], ("11-13", "11-14"): [dict(id="a"), dict(id="b")],
            ("11-09", "11-13"): [dict(id=f"c{k}") for k in range(99)], ("11-05", "11-09"): [dict(id="b"), dict(id="d")]}.get((a[5:], b[5:]), [])


trump.datetime, trump.feed = TrumpDT, feed_win
ids = {r["id"] for r in trump.since("2026-11-03")}
trump.datetime = datetime
check(win == [("11-10", "11-14"), ("11-13", "11-14"), ("11-09", "11-13"), ("11-05", "11-09"), ("11-03", "11-05")],
      "trump since：由聽日向前 4 日一段；一段有 100 條（RSS 上限）就縮做 1 日再攞；99 條唔使縮；最後一段到開始日為止")
check(ids == {"a", "b", "d"} | {f"c{k}" for k in range(99)}, "trump since：縮咗嗰段用 1 日嘅結果；同一條（id b）唔重複")

# ============================================================ 5. rates
DAYS = [date(2025, 6, 2) + timedelta(days=k) for k in range(530)]
DAYS = [d for d in DAYS if d.weekday() < 5 and d <= date(2026, 11, 12)]
n = len(DAYS)
TS = {}
for i, d in enumerate(DAYS):
    r = {"3 Mo": 4.0 if i < n - 1 else 3.9, "2 Yr": 3.5 if i < n - 1 else 3.6, "10 Yr": 4.0 if i < n - 1 else 4.45}
    if i >= n - 29:
        r["5 Yr"] = 4.1                                              # 得 29 日：唔要
    if i >= n - 30:
        r["30 Yr"] = 4.8 if i < n - 1 else 4.70                      # 啱啱 30 日：要
    TS[d] = r
LIVE = {"^TNX": (4.60, datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)), "^IRX": (3.7, datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc))}


def live(sym):
    if sym not in LIVE:
        raise RuntimeError("boom")
    return LIVE[sym]


RO = OUT / "rates_out"
rates.treasury, rates.live = (lambda: TS), live
quiet(rates.main, str(RO))
R = json.loads((RO / "rates.json").read_text(encoding="utf-8"))
by = {r["name"]: r for r in R["rows"]}
check(list(by) == ["3 個月", "2 年", "10 年", "30 年"] and R["errs"] == ["5 年：財政部數據唔夠", "30 年 盤中：boom"],
      "rates：一年內財政部數據唔夠 30 日（5 年得 29 日）唔要；啱啱 30 日（30 年）照用；盤中出錯記低照用收市")
t = by["10 年"]
check(t["y"] == 4.6 and t["src"] == "盤中 11-13 23:00" and t["d"] == 15.0 and t["w"] == 60.0 and t["m"] == 60.0 and t["yr"] == 60.0 and t["hi52"] == 4.6
      and t["lo52"] == 4.0 and t["close_date"] == "2026-11-12", "rates 10 年：Yahoo 盤中日子（紐約 11-13）新過財政部（11-12）→ 用盤中，變動以基點計")
check(by["3 個月"]["y"] == 3.9 and by["3 個月"]["src"] == "財政部收市" and by["2 年"]["src"] == "財政部收市",
      "rates：盤中價同財政部同一日（3 個月）唔用；2 年冇盤中來源")
check(R["curve"] == {"10y_2y": 100.0, "10y_3m": 70.0}, "rates 息差：10 年 − 2 年、10 年 − 3 個月（基點）")
check(R["alert"] == ["10 年債息急升 15 基點至 4.60%", "10 年債息 4.60% 創 52 週新高（一年前大約 4.00%）", "30 年債息急跌 10 基點至 4.70%"],
      "rates alert：單日郁 ≥ 10 基點（30 年啱啱 −10 都計）、創 52 週新高")
rates.treasury = lambda: {d: {"10 Yr": 4.0} for d in DAYS[-10:]}
try:
    quiet(rates.main, str(OUT / "rates_none"))
    msg = ""
except SystemExit as ex:
    msg = str(ex)
check(msg.startswith("[rates] 全部攞唔到"), "rates：全部年期都唔夠數據 → 停低（唔寫空檔）")

# ============================================================ 6. walert
WO = OUT / "walert_out"
WO.mkdir()
(WO / "walert.json").write_text(json.dumps({"ai": {"summary": "舊 AI"}}), encoding="utf-8")
NOW = datetime.now(timezone.utc)
ca = lambda h: (NOW - timedelta(hours=h)).strftime("%a %b %d %H:%M:%S +0000 %Y")
TWEETS = [dict(id=1, created_at=ca(1), text="1,000 #BTC (100,000,000 USD) transferred from unknown wallet to #Coinbase https://whale-alert.io/x1"),
          dict(id=2, created_at=ca(2), text="500 #ETH (2,000,000 USD) transferred from #Binance to unknown new wallet https://whale-alert.io/x2"),
          dict(id=3, created_at=ca(30), text="10 #BTC (1,000,000 USD) transferred from #Kraken to #Binance"),
          dict(id=4, created_at=ca(49), text="9,999 #BTC (900,000,000 USD) transferred from unknown wallet to #Binance"),
          dict(id=5, created_at=ca(3), text="gm everyone")]
xfeed.posts = lambda user, count=40, since_ts=None, pages=1, timeout=30: {"results": TWEETS}
quiet(walert.main, str(WO))
J = json.loads((WO / "walert.json").read_text(encoding="utf-8"))
check([(x["sym"], x["kind"], x["usd"]) for x in J["items"]] == [("BTC", "入交易所", 1e8), ("ETH", "出交易所", 2e6), ("BTC", "交易所之間", 1e6)]
      and J["items"][0]["url"] == "https://x.com/whale_alert/status/1" and J["items"][1]["to"] == "未知新錢包",
      "walert：超過 48 小時（49 小時）唔要；唔係轉帳格式唔要；新到舊排；入／出交易所／交易所之間")
check(J["net24"] == {"BTC": {"in": 1e8, "out": 0.0, "mint": 0.0, "n": 1, "net": 1e8}, "ETH": {"in": 0.0, "out": 2e6, "mint": 0.0, "n": 1, "net": -2e6}}
      and J["ai"] == {"summary": "舊 AI"} and J["errs"] == [], "walert 24 小時淨流：30 小時前嗰條唔計入 24 小時；舊 AI 分析沿用")
real_parse = walert.parse
P = {11: dict(sym="USDT", amt="5", usd=50e6, kind="印發", frm="", to="Tether Treasury", link=None),
     12: dict(sym="USDC", amt="2", usd=20e6, kind="銷毀", frm="", to="USDC Treasury", link=None),
     13: dict(sym="USDC", amt="1", usd=5e6, kind="入交易所", frm="未知錢包", to="Binance", link=None)}
walert.parse = lambda t: dict(P[t["id"]]) if t["id"] in P else None
xfeed.posts = lambda *a, **k: {"results": [dict(id=k, created_at=ca(k - 10), text="") for k in P]}
quiet(walert.main, str(WO))
J = json.loads((WO / "walert.json").read_text(encoding="utf-8"))
walert.parse = real_parse
check(J["net24"] == {"穩定幣": {"in": 5e6, "out": 0.0, "mint": 30e6, "n": 3, "net": 5e6}}, "walert：穩定幣合埋計；印發加、銷毀減")
# 2026-11-13（老師批修正）：真嘅印發／銷毀帖係「minted at …」「burned at …」，之前 PAT 配唔到 → 印發永遠 0
MB = [dict(id=21, created_at=ca(1), text="\U0001F5A8 50,000,000 #USDT (50,012,345 USD) minted at Tether Treasury\n\nhttps://whale-alert.io/transaction/tron/abc"),
      dict(id=22, created_at=ca(2), text="\U0001F525 20,000,000 #USDC (20,000,000 USD) burned at USDC Treasury"),
      dict(id=23, created_at=ca(3), text="1,000 #BTC (100,000,000 USD) transferred from unknown wallet to #Coinbase https://whale-alert.io/x1")]
xfeed.posts = lambda *a, **k: {"results": MB}
quiet(walert.main, str(WO))
J = json.loads((WO / "walert.json").read_text(encoding="utf-8"))
check([(x["sym"], x["kind"], x["usd"], x["to"]) for x in J["items"]] == [("USDT", "印發", 50012345.0, "Tether Treasury"), ("USDC", "銷毀", 2e7, "USDC Treasury"),
                                                                          ("BTC", "入交易所", 1e8, "Coinbase")]
      and J["items"][0]["link"] == "https://whale-alert.io/transaction/tron/abc" and J["items"][1]["link"] is None
      and J["net24"]["穩定幣"]["mint"] == 50012345.0 - 2e7 and J["net24"]["BTC"]["in"] == 1e8,
      "walert：真嘅「minted at／burned at …」帖解析到（印發加、銷毀減）；轉帳照舊")
xfeed.posts = lambda *a, **k: {"results": []}
quiet(walert.main, str(WO))
check(json.loads((WO / "walert.json").read_text(encoding="utf-8"))["items"] == [], "walert：冇出錯只係 48 小時內冇大額轉帳 → 照寫空清單，唔當失敗")
xfeed.posts = boom
try:
    quiet(walert.main, str(WO))
    msg = ""
except SystemExit as ex:
    msg = str(ex)
check(msg.startswith("[walert] 攞唔到") and "boom" in msg, "walert：攞唔到又冇數據 → 停低")

# ============================================================ 7. macro_src
def mk(q, yes="0.4237", oc='["Yes", "No"]', prices=None):
    return dict(question=q, outcomes=oc, outcomePrices=prices if prices is not None else f'["{yes}", "0.5763"]', oneDayPriceChange=0.01,
                volume24hr="1234.6", endDate="2026-12-31T00:00:00Z", slug="s")


RAW = [mk("Lakers vs. Celtics: will the Fed chair attend?"), mk("Will the Fed cut rates in December?", oc='["No", "Yes"]'),
       dict(question="Fed rate hike in 2026?", outcomes="[", outcomePrices="["), mk("Will inflation exceed 3%?", prices="[]"),
       mk("Who wins the Super Bowl?")] + [mk(f"Fed decision #{k}?") for k in range(20)]
PM = macro_src.polymarket(RAW)
check(len(PM) == 15 and [x["q"] for x in PM] == [f"Fed decision #{k}?" for k in range(15)] and PM[0] == dict(q="Fed decision #0?", yes=0.424, chg1d=0.01, vol24=1235, end="2026-12-31", slug="s"),
      "macro Polymarket：走去體育（vs.）、唔係 Yes 開頭、壞 JSON、冇價、同宏觀無關；最多 15 個")
RAWC = [mk("Bitcoin up or down on November 13?"), mk("Will the Fed cut?")] + [mk(f"Will Bitcoin hit ${100 + k}k by December 31?") for k in range(15)]
PC = macro_src.polymarket_crypto(RAWC)
check(len(PC) == 12 and PC[0]["q"] == "Will Bitcoin hit $100k by December 31?", "macro 加密 Polymarket：走去單日價格賭局、非加密；最多 12 個")

# ============================================================ 8. lev2x
U = lev2x.underlying
cases = {"GraniteShares 2x Long NVDA Daily ETF": "NVDA", "Direxion Daily AAPL Bull 2X Shares": "AAPL", "Corgi ETF Trust I Corgi LITE 2x Daily ETF": "LITE",
         "Leverage Shares 2X Long SK Hynix Daily ETF": "SKHY", "T-Rex 2X Long Apple Daily Target ETF": "AAPL", "Tradr 2X Long BRKB Daily ETF": "BRK-B",
         "Daily Target 2X Long COIN ETF": "COIN", "Direxion Daily TSLA Bear 2X Shares": None, "Defiance Daily Target 2X Short MSTR ETF": None,
         "Tradr 2X Long SPY Daily ETF": None, "ProShares Ultra NVDA": None}
check({k: U(k) for k in cases} == cases, "lev2x：由 ETF 名抽正股（公司名、SK Hynix、BRKB → BRK-B）；Bear／Short、唔係 2 倍、SPY 唔要")
check(lev2x.rank("Direxion Daily X") == 0 and lev2x.rank("Corgi X") == 8 and lev2x.rank("Unknown") == len(lev2x.ISSUER), "lev2x：發行商排名（大嘅排先）")
TK = [f"Q{chr(65 + k)}" for k in range(26)] + [f"R{chr(65 + k)}" for k in range(23)]
ROWS = ([dict(symbol=f"{t}U", companyName=f"GraniteShares 2x Long {t} Daily ETF") for t in TK]
        + [dict(symbol="NVDT", companyName="Tradr 2X Long NVDA Daily ETF"), dict(symbol="NVDL", companyName="GraniteShares 2x Long NVDA Daily ETF"),
           dict(symbol="NVDU", companyName="Direxion Daily NVDA Bull 2X Shares"), dict(symbol="QAD", companyName="Direxion Daily QA Bear 2X Shares")])
lev2x.OUT = OUT / "lev2x.json"
serve(lambda u: json.dumps({"data": {"data": {"rows": ROWS}}}))
quiet(lev2x.main)
L2 = json.loads(lev2x.OUT.read_text(encoding="utf-8"))
check(len(L2["map"]) == 50 and L2["map"]["NVDA"] == ["NVDU", "NVDL", "NVDT"] and L2["map"]["QA"] == ["QAU"], "lev2x main：啱啱 50 隻照寫；同一隻股按發行商排（Direxion → GraniteShares → Tradr）")
serve(lambda u: json.dumps({"data": {"rows": ROWS[:49]}}))
quiet(lev2x.main)
urllib.request.urlopen = REAL_URLOPEN
check(json.loads(lev2x.OUT.read_text(encoding="utf-8")) == L2, "lev2x main：得 49 隻（名單唔齊）→ 唔覆蓋舊檔")

# ============================================================ 9. earnings
class TSx:
    def __init__(self, u, hour):
        self.u, self.hour = u, hour

    def tz_convert(self, tz):
        return self

    def to_pydatetime(self):
        return self.u

    def date(self):
        return self.u.date()


class DF:
    def __init__(self, rows):
        self.rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self.rows)


NOW = datetime.now(timezone.utc)
dd = lambda days, h=0: NOW + timedelta(days=days, hours=h)
NaN = float("nan")
ER = {"HHH": [(TSx(dd(30), 16), {"EPS Estimate": 2.0, "Reported EPS": NaN}), (TSx(dd(-2), 7), {"EPS Estimate": 1.0, "Reported EPS": 1.2, "Surprise(%)": 20.0})],
      "AAA": [(TSx(dd(10), 8), {"EPS Estimate": NaN, "Reported EPS": NaN}), (TSx(dd(10), 8), {"EPS Estimate": NaN, "Reported EPS": NaN}),
              (TSx(dd(99), 16), {"EPS Estimate": 3.456, "Reported EPS": NaN}), (TSx(dd(100, 1), 16), {"EPS Estimate": 3.0, "Reported EPS": NaN}),
              (TSx(dd(-3), 16), {"EPS Estimate": 1.0, "Reported EPS": 2.0, "Surprise(%)": NaN}),
              (TSx(dd(-20), 16), {"EPS Estimate": 1.0, "Reported EPS": 2.0, "Surprise(%)": NaN})],
      "BBB": [(TSx(dd(-1), 16), {"EPS Estimate": 1.0, "Reported EPS": NaN}), (TSx(dd(-5), 16), {"EPS Estimate": 1.0, "Reported EPS": 0.5, "Surprise(%)": NaN})],
      "FFF": [(TSx(dd(-4), 16), {"EPS Estimate": 1.0, "Reported EPS": 1.1, "Surprise(%)": NaN})],
      "GGG": [(TSx(dd(-6), 16), {"EPS Estimate": 1.0, "Reported EPS": 0.9, "Surprise(%)": NaN})],
      "DDD": None, "EEE": []}


class EarnTicker:
    def __init__(self, s):
        self.s = s

    def get_earnings_dates(self, limit=8):
        if self.s == "CCC":
            raise RuntimeError("boom")
        r = ER.get(self.s, [])
        return None if r is None else DF(r)


asked = []


def ai_search(prompt):
    sym = prompt.split()[1]
    asked.append(sym)
    return (None, "額度用晒") if sym == "GGG" else ({"headline": f"{sym} 好", "eps": "beat"}, "Claude")


sys.modules["yfinance"] = types.SimpleNamespace(Ticker=EarnTicker)
sys.modules["model"] = types.SimpleNamespace(ai_search=ai_search)
os.environ.pop("GITHUB_EVENT_NAME", None)
ER_ROOT = OUT / "earn_root"
(ER_ROOT / "docs").mkdir(parents=True)
(ER_ROOT / "docs" / "scan.json").write_text(json.dumps({"ranking": [{"sym": s} for s in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG")]}), encoding="utf-8")
(ER_ROOT / "docs" / "model_cont.json").write_text(json.dumps({"positions": [{"sym": "HHH"}]}), encoding="utf-8")
earnings.ROOT = ER_ROOT
EO = OUT / "earn_out"
EO.mkdir()
dstr = lambda days: str(dd(days).date())
(EO / "earnings.json").write_text(json.dumps({"reports": [dict(sym="BBB", date=dstr(-5)), dict(sym="OLD", date=dstr(-70))]}), encoding="utf-8")
quiet(earnings.main, str(EO))
E = json.loads((EO / "earnings.json").read_text(encoding="utf-8"))
check([(u["sym"], u["date"], u["when"], u["est"], u["held"]) for u in E["upcoming"]]
      == [("AAA", dstr(10), "盤前", None, False), ("HHH", dstr(30), "收市後", 2.0, True), ("AAA", dstr(99), "收市後", 3.46, False)],
      "earnings 未來業績：100 日內先列（100 日 1 個鐘後唔列）；同一日唔重複；冇預測 = None；按日子排")
check(asked == ["HHH", "GGG", "FFF"] and E["pending"] == ["AAA"], "earnings AI：最近 10 日出咗、有實際 EPS、未分析過；持倉（HHH）優先，之後舊到新；每次最多 3 個，其餘等下次")
check([(r["sym"], r.get("headline")) for r in E["reports"]] == [("HHH", "HHH 好"), ("FFF", "FFF 好"), ("BBB", None)]
      and "GGG AI：額度用晒" in E["errs"] and "CCC：boom" in E["errs"] and E["syms"] == ["HHH", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"],
      "earnings：分析結果新到舊；超過 60 日（OLD）刪走；AI 冇答案、Yahoo 出錯都記低")
check(E["reports"][0]["act"] == 1.2 and E["reports"][0]["surprise"] == 20.0 and E["reports"][0]["src"] == "Claude", "earnings 報告：EPS 實際、驚喜 %、AI 來源")
before = (EO / "earnings.json").read_text(encoding="utf-8")
asked.clear()
quiet(earnings.main, str(EO))
check(asked == [] and (EO / "earnings.json").read_text(encoding="utf-8") == before, "earnings：上次檢查未夠 2 個鐘 → 唔再做、唔覆寫")
del sys.modules["model"]

# ============================================================ 10. serenity
lo = datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp()
hi = datetime(2026, 11, 13, tzinfo=timezone.utc).timestamp()
sym = lambda *s: {"facets": [{"type": "symbol", "original": x} for x in s] + [{"type": "url", "original": "http"}]}
SER = [dict(id="1", created_timestamp=lo, raw_text=sym("nvda", "SPY"), text="$NVDA " + "x" * 300),
       dict(id="2", created_timestamp=hi, raw_text=sym("AMD"), text="too new"), dict(id="3", created_timestamp=lo - 1, raw_text=sym("AMD"), text="too old"),
       dict(id="4", created_timestamp=lo + 60, raw_text=sym("SPY", "BTC"), text="index only"),
       dict(id="5", created_timestamp=lo + 120, raw_text=sym("MU", "AMD"), text="$MU $AMD", replying_to="someone")]
xfeed.posts = lambda user, count=40, since_ts=None, pages=1, timeout=30: {"results": SER}
F = serenity.fetch("2026-11-10", "2026-11-13")
check(set(F) == {"1", "5"} and F["1"]["syms"] == ["NVDA"] and F["5"]["syms"] == ["AMD", "MU"] and F["5"]["reply"] is True and F["1"]["reply"] is False
      and len(F["1"]["text"]) == 160 and F["1"]["full"].startswith("$NVDA x"), "serenity fetch：包開始唔包結束；淨係要有個股 cashtag（SPY、BTC 唔計）；大楷、排序")
real_argv = sys.argv


def ser_main(root, argv, tw):
    serenity.ROOT, serenity.ALL = root, root / "docs" / "serenity_all.json"
    serenity.fetch = tw if callable(tw) else (lambda a, b: tw)
    sys.argv = ["serenity.py"] + argv
    try:
        quiet(serenity.main)
    finally:
        sys.argv = real_argv


SR = OUT / "ser1"
(SR / "docs").mkdir(parents=True)
(SR / "docs" / "serenity_all.json").write_text(json.dumps({"tweets": [dict(id="0", ts=1, syms=["AAPL"], reply=False, text="old")]}), encoding="utf-8")
ser_main(SR, [], F)
J = json.loads((SR / "docs" / "serenity.json").read_text(encoding="utf-8"))
AL = json.loads((SR / "docs" / "serenity_all.json").read_text(encoding="utf-8"))["tweets"]
check(J["days"] == 60 and [t["id"] for t in J["tweets"]] == ["5", "1"] and all("full" not in t for t in J["tweets"]),
      "serenity 60 日版：寫 docs/serenity.json（新到舊、唔要 full）")
check([t["id"] for t in AL] == ["5", "1", "0"] and len(AL[1]["text"]) == 280 and "full" not in AL[1], "serenity：全部歷史併埋舊推文（全文截 280 字）")
SR2 = OUT / "ser2"
(SR2 / "docs").mkdir(parents=True)
ser_main(SR2, [], {})
ser_main(SR2, [], boom)
check(not (SR2 / "docs" / "serenity.json").exists() and not (SR2 / "docs" / "serenity_all.json").exists(), "serenity 60 日版：冇數據或者出錯 → 唔覆蓋舊檔")
ser_main(SR2, ["recent", str(OUT / "ser_recent")], {})
J = json.loads((OUT / "ser_recent" / "serenity_recent.json").read_text(encoding="utf-8"))
check(J["days"] == 3 and J["tweets"] == [] and not (SR2 / "docs" / "serenity_all.json").exists(), "serenity 近 3 日版：冇新推文照寫空（feeds 要知冇）；唔郁全部歷史")

# ============================================================ 11. commod
T0 = 1_794_000_000                             # 2026-11 嘅 Unix 時間（Windows 唔接受 1970 年附近嘅時間）


def chart_json(close, live, mtime, ts=(1000, 2000, 3000, 10_000)):
    return json.dumps({"chart": {"result": [{"indicators": {"quote": [{"close": close}]}, "meta": {"regularMarketPrice": live, "regularMarketTime": T0 + mtime},
                                              "timestamp": [T0 + x for x in ts]}]}})


def ch(close, live, mtime):
    serve(lambda u: chart_json(close, live, mtime))
    try:
        return commod.chart("GC=F")[0]
    finally:
        urllib.request.urlopen = REAL_URLOPEN


check(ch([1.0, None, 2.0, 3.0], 3.0, 20_000) == [1.0, 2.0, 3.0], "commod chart：最新價同最後收市一樣 → 唔加（唔會多咗一日）")
check(ch([1.0, None, 2.0, 3.0], 3.3, 13_601) == [1.0, 2.0, 3.0, 3.3], "commod chart：最新價時間遲過最後一支 K 1 個鐘以上 → 加做新一日")
check(ch([1.0, None, 2.0, 3.0], 3.3, 13_600) == [1.0, 2.0, 3.3], "commod chart：1 個鐘內 → 更新最後一日")
check(ch([1.0, 2.0, 3.0], None, 20_000) == [1.0, 2.0, 3.0], "commod chart：冇最新價 → 照用收市")
CH = {"CL=F": [70.0] * 39 + [73.5], "BZ=F": [80.0] * 29, "GC=F": [2000.0] * 55 + [2000.0, 2010.0, 2020.0, 2050.0, 2100.0], "HG=F": [5.0] * 69 + [4.8]}


def fake_chart(s):
    if s not in CH:
        raise RuntimeError("boom")
    return CH[s], "11-13 10:00"


commod.chart = fake_chart
CO = OUT / "commod_out"
quiet(commod.main, str(CO))
C = json.loads((CO / "commod.json").read_text(encoding="utf-8"))
check([r["sym"] for r in C["rows"]] == ["CL=F", "GC=F", "HG=F"] and C["errs"] == ["布蘭特原油：數據唔夠", "白銀：boom"],
      "commod：唔夠 30 日（布蘭特 29 日）唔要；攞唔到記錯")
g = C["rows"][1]
check(g["px"] == 2100.0 and g["d"] == round(2100 / 2050 - 1, 4) and g["w"] == 0.05 and g["yr"] == 0.05 and g["hi52"] == 2100.0 and g["lo52"] == 2000.0,
      "commod 黃金：當日、5 日、一年升跌、52 週高低")
check(C["cg"] == dict(now=round(4.8 / 2100 * 1000, 3), m3=None, yr=round((4.8 / 2100) / (5.0 / 2000) - 1, 4)), "commod 銅金比率：最近共同日子；唔夠 65 日冇 3 個月變化")
check(C["alert"] is not None and len(C["alert"]) == 4 and C["alert"][0] == "紐約原油單日急升 5.0% 至 73.50" and C["alert"][1].startswith("黃金 2,100.00 創 52 週新高")
      and C["alert"][2].startswith("金價 5 日急升 5.0%") and C["alert"][3] == "銅價單日急跌 4.0%（經濟預期變化）",
      "commod alert：油價單日 ±5%、金價 52 週新高、金價 5 日 ≥ 4%、銅單日 ±4%（啱啱到界都計）")
commod.chart = boom
try:
    quiet(commod.main, str(OUT / "commod_none"))
    msg = ""
except SystemExit as ex:
    msg = str(ex)
check(msg.startswith("[commod] 全部攞唔到"), "commod：全部攞唔到 → 停低")

# ============================================================ 12. airdrop
urls = serve(lambda u: b"7100000000.4")
v1 = airdrop.llama_tvl("Hyper Liquid!")
serve(lambda u: b"0")
v2 = airdrop.llama_tvl("x")
serve(lambda u: b"-5")
v3 = airdrop.llama_tvl("x")
serve(boom)
v4 = airdrop.llama_tvl("x")
urllib.request.urlopen = REAL_URLOPEN
check(v1 == 7_100_000_000 and urls[0] == "https://api.llama.fi/tvl/hyper-liquid" and v2 is None and v3 is None and v4 is None,
      "airdrop DefiLlama TVL：正數先用（四捨五入）；0、負數、出錯 → 冇")
searched = []


def ad_search(prompt, timeout=None):
    searched.append(prompt[:5])
    return None, "冇", False, []


real = (llm.available, llm.peak_now, llm.PROVIDER, llm.search)
llm.available, llm.search = (lambda: True), ad_search
for prov, peak in (("gemini", True), ("deepseek", False), ("deepseek", True)):
    llm.PROVIDER, llm.peak_now = prov, (lambda p=peak: p)
    quiet(airdrop.main, str(OUT / "airdrop_out"), force=True)
llm.available, llm.peak_now, llm.PROVIDER, llm.search = real
check(len(searched) == 2, "airdrop：免費 AI（Gemini）繁忙時段照寫；DeepSeek 非繁忙照寫；淨係 DeepSeek 繁忙時段先唔寫（慳錢）")
print(f"\n全部 {ok} 項通過")
