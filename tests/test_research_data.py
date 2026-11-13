# -*- coding: utf-8 -*-
"""2026-11-13 scanner/research.py 數據部分行為測試（流程審計 S6：test_research.py 將 collect 換走，SEC 財報、季度、過去市盈率、
collect、到期清單都冇測過）。假數據、唔上網、唔叫 AI、唔改規則。
1. money 單位界線；_get 重試、404 唔重試
2. SEC：sec_facts 本機檔（大過 1000 byte、45 日內）、代號 → CIK；_dur 揀 tag 次序同最新申報、表格類型、拆股用申報日；
   _dur_hist 保留每次申報、_asof 只用嗰日已申報；_annual 日數界線；_quarters 第四季 = 全年 − 頭三季；_ttm 要 4 季連續；split_factor
3. sec_block：財年表（收入增長、EPS、股數拆股調整、自由現金流）、過去 12 個月（YTD 計法）、過去 5 年市盈率（61 個月、最少 12 點）
4. collect：未收市（紐約 16:10 前）剔走今日、未來 12 個月 EPS 加權、預測修訂方向、業績日、每日估值；earn_dates
5. clean_analysis 情境百分比、機率、裁剪；build --dry／--manual 幾時儲存；due_list 到期規則
用法：python tests/test_research_data.py"""
import json
import os
import sys
import time
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "research_data" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["RESEARCH_OUT"] = str(OUT / "research")
import llm  # noqa: E402
import research as R  # noqa: E402

NYT, HKT = ZoneInfo("America/New_York"), ZoneInfo("Asia/Hong_Kong")
SLEPT = []
time.sleep = lambda s: SLEPT.append(s)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


class NowDT(datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW


R.datetime = NowDT


def no_ai(*a, **k):
    raise AssertionError("唔應該叫 AI")


llm.ask = llm.gather = no_ai

# ============================================================ 1. money、_get
check([R.money(x) for x in (None, 1e12, -2.5e12, 999_999_999_999, 1e10, 9.99e9, 1e8, 99_990_000, 5e4)] ==
      ["—", "1.00 萬億", "-2.50 萬億", "10,000 億", "100 億", "99.9 億", "1.0 億", "9,999 萬", "5 萬"],
      "money：≥ 1 萬億寫萬億（負數有 -）；≥ 100 億寫整數億；≥ 1 億寫一個小數；其餘寫萬；冇數寫 —")


class Resp:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b


URLS = []


def serve(seq):
    def f(req, timeout=None):
        URLS.append(req.full_url)
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return Resp(x)
    R.urllib.request.urlopen = f


REAL_URLOPEN = R.urllib.request.urlopen
serve([OSError("timed out"), OSError("connection reset"), b"ok"])
check(R._get("https://a.test/x", {}) == b"ok" and SLEPT == [4, 8] and len(URLS) == 3, "_get：出錯重試，等 4 秒、8 秒，第三次得")
URLS.clear()
serve([OSError("HTTP Error 404: Not Found"), b"never"])
try:
    R._get("https://a.test/y", {})
    err = ""
except OSError as e:
    err = str(e)
check("404" in err and len(URLS) == 1, "_get：404（冇呢個檔）唔重試，即刻報錯")
URLS.clear()
serve([OSError("e1"), OSError("e2")])
try:
    R._get("https://a.test/z", {}, tries=2)
    err = ""
except OSError as e:
    err = str(e)
check(err == "e2" and len(URLS) == 2, "_get：試夠次數都唔得 → 報最後一次嘅錯")
R.urllib.request.urlopen = REAL_URLOPEN


# ============================================================ 2. SEC 數據
def fx(start, end, val, form, filed=None):
    x = dict(end=end, val=val, form=form)
    if start:
        x["start"] = start
    if filed:
        x["filed"] = filed
    return x


def facts(tags, unit="USD"):
    return {"facts": {"us-gaap": {t: {"units": {unit: lst} if isinstance(lst, list) else lst} for t, lst in tags.items()}}}


Y24, Y23, Y22, Y21, Y20 = (("2024-01-01", "2024-12-31"), ("2023-01-01", "2023-12-31"), ("2022-01-01", "2022-12-31"),
                           ("2021-01-01", "2021-12-31"), ("2020-01-01", "2020-12-31"))
F1 = facts({"A0": {"USD": [fx(*Y24, 90, "10-K/A", "2025-05-01"),        # 同一期間、同一個 tag：較新申報（重述）→ 用（唔理排位）
                           fx(*Y24, 100, "10-K", "2025-02-01"),
                           fx(*Y23, 80, "8-K", "2024-02-01"),           # 8-K 唔係財報 → 唔算
                           fx(None, "2024-12-31", 5, "10-K", "2025-02-01")],   # 時點數（冇開始日）唔算
                   "EUR": [fx(*Y22, 70, "20-F", "2023-03-01")]},       # 第二個單位一樣睇
            "A1": [fx(*Y24, 999, "10-K", "2026-01-01"),                  # 排後嘅 tag：就算較新都唔用
                   fx(*Y21, 60, "40-F", "2022-03-01"),                   # 排前 tag 冇嘅期間 → 用
                   fx(*Y20, 50, "S-1", "2021-03-01")]})                  # S-1 唔算
check(R._dur(F1, ["A0", "A1"]) == {Y24: 90.0, Y22: 70.0, Y21: 60.0},
      "_dur：同一期間揀排前嘅 tag、同 tag 揀最新申報；只計 10-K／10-Q／20-F／40-F；冇開始日嘅唔算；所有單位都睇")

SPL = {date(2024, 6, 10): 10.0, date(2021, 7, 1): 2.0}
check(R.split_factor(SPL, "2024-06-09") == 10.0 and R.split_factor(SPL, "2024-06-10") == 1.0
      and R.split_factor(SPL, "2021-06-30") == 20.0 and R.split_factor({}, "2020-01-01") == 1.0,
      "split_factor：只乘嗰日之後嘅拆股（同日唔計）；兩次拆股相乘")
F2 = facts({"E": [fx(*Y23, 40.0, "10-K", "2024-02-20"),      # 拆股前申報：舊基準 → ÷ 10
                  fx(*Y22, 3.0, "10-K", "2025-02-20"),       # 拆股後重述舊年（已經係新基準）→ 唔再調整
                  fx(*Y24, 4.0, "10-K", "2025-02-20")]}, unit="USD/shares")
check(R._dur(F2, ["E"], SPL, adj="eps") == {Y23: 4.0, Y22: 3.0, Y24: 4.0}, "_dur 每股盈利：用申報日計拆股（拆股後重述嘅唔會調整兩次）")
check(R._dur(F2, ["E"], SPL, adj="shares") == {Y23: 400.0, Y22: 3.0, Y24: 4.0}, "_dur 股數：拆股前申報 × 10")
check(R._dur(F2, ["E"], SPL) == {Y23: 40.0, Y22: 3.0, Y24: 4.0} and R._dur(F2, ["E"], None, adj="eps") == {Y23: 40.0, Y22: 3.0, Y24: 4.0},
      "_dur：收入等（冇 adj）有拆股都唔調整；冇拆股資料就唔調整")

Q1 = ("2024-01-01", "2024-03-31")
F3 = facts({"E": [fx(*Y23, 40.0, "10-K", "2024-02-20"), fx(*Y23, 4.0, "10-K", "2025-02-20")],
            "E2": [fx(*Q1, 10.0, "10-Q"),                                  # 冇申報日 → 當季尾 45 日後（2024-05-15，拆股前）
                   fx(*Y23, 999.0, "10-K", "2025-06-01")]}, unit="USD/shares")
check(R._dur_hist(F3, ["E", "E2"], SPL, adj="eps") == {Y23: [(0, "2024-02-20", 4.0), (0, "2025-02-20", 4.0), (1, "2025-06-01", 999.0)],
                                                       Q1: [(1, "2024-05-15", 1.0)]},
      "_dur_hist：每次申報都留低；冇申報日當季尾 + 45 日（拆股都用呢日計）")
H3 = R._dur_hist(F3, ["E", "E2"], SPL)
check(H3[Y23][0][2] == 40.0 and H3[Q1][0][2] == 10.0, "_dur_hist：冇 adj 唔調整拆股")
check(R._asof(H3, date(2024, 1, 1)) == {} and R._asof(H3, date(2024, 12, 31)) == {Y23: 40.0, Q1: 10.0}
      and R._asof(H3, date(2025, 2, 20)) == {Y23: 4.0, Q1: 10.0} and R._asof(H3, date(2025, 7, 1))[Y23] == 4.0,
      "_asof：只用嗰日或之前已申報嘅數（重述之前用舊數）；排前 tag 優先，就算排後 tag 較新")


def per(n):
    return ("2025-01-01", (date(2025, 1, 1) + timedelta(days=n)).isoformat())


check(R._annual({per(n): n for n in (349, 350, 364, 380, 381, 91)}) == {per(350)[1]: 350, per(364)[1]: 364, per(380)[1]: 380},
      "_annual：350–380 日先當全年（349、381 唔係）")

Q = {("2023-01-01", "2023-03-31"): 1.1, ("2023-04-01", "2023-06-30"): 1.2, ("2023-07-01", "2023-09-30"): 1.3,
     ("2023-10-01", "2023-12-31"): 7.0, ("2023-01-01", "2023-12-31"): 100.0,      # 已經有第四季 → 唔推算
     ("2024-04-01", "2024-06-30"): 2.0, ("2024-07-01", "2024-09-30"): 2.5, ("2024-01-01", "2024-12-31"): 9.0,   # 得兩季 → 唔推算
     ("2025-01-01", "2025-03-31"): 1.0, ("2025-04-01", "2025-06-30"): 2.0, ("2025-07-01", "2025-09-30"): 3.0,
     ("2025-01-01", "2025-12-31"): 10.0}
QS = R._quarters(Q)
check(QS == [("2023-03-31", 1.1), ("2023-06-30", 1.2), ("2023-09-30", 1.3), ("2023-12-31", 7.0), ("2024-06-30", 2.0), ("2024-09-30", 2.5),
             ("2025-03-31", 1.0), ("2025-06-30", 2.0), ("2025-09-30", 3.0), ("2025-12-31", 4.0)],
      "_quarters：第四季 = 全年 − 頭三季（10 − 6 = 4）；已經有第四季唔推算；年內唔夠三季唔推算")
check(R._ttm(QS) == (10.0, "2025-12-31"), "_ttm：最近 4 季加埋（1+2+3+4）")
check(R._ttm(QS[:-1]) == (None, None), "_ttm：最近 4 季唔連續（中間冇 2024 第四季，相差 365 日）→ 冇")
check(R._ttm(QS[:3]) == (None, None), "_ttm：得 3 季 → 冇")
check(R._ttm(QS, asof=date(2026, 2, 14), avail=45) == (10.0, "2025-12-31") and R._ttm(QS, asof=date(2026, 2, 13), avail=45) == (None, None),
      "_ttm asof：季尾 + 45 日先當知道（2026-02-14 先用到第四季）")

# sec_facts：本機檔 / SEC 下載
R.ROOT = OUT / "app"
LOC = OUT / "stock-strategy" / "data" / "sec" / "facts"
LOC.mkdir(parents=True)
(LOC / "AAA.json").write_text(json.dumps({"cik": 777, "entityName": "Local Co", "pad": "x" * 1200}), encoding="utf-8")
(LOC / "BRK-B.json").write_text(json.dumps({"cik": 1, "entityName": "Too small"}), encoding="utf-8")
GETS = []


def fake_get(url, headers, timeout=60, tries=4):
    GETS.append((url, headers.get("User-Agent")))
    if url.endswith("company_tickers.json"):
        return json.dumps({"0": {"ticker": "AAA", "cik_str": 123}, "1": {"ticker": "BRK.B", "cik_str": 1067983}}).encode()
    return json.dumps({"entityName": "From SEC"}).encode()


R._get = fake_get
d, cik = R.sec_facts("AAA")
check(d["entityName"] == "Local Co" and cik == 777 and GETS == [], "sec_facts：本機檔（大過 1000 byte、45 日內）→ 直接用，唔上 SEC")
t44 = time.time() - 44 * 86400
os.utime(LOC / "AAA.json", (t44, t44))
check(R.sec_facts("AAA")[1] == 777 and GETS == [], "sec_facts：44 日前嘅本機檔照用")
t46 = time.time() - 46 * 86400
os.utime(LOC / "AAA.json", (t46, t46))
d, cik = R.sec_facts("AAA")
check(d["entityName"] == "From SEC" and cik == 123 and [g[0] for g in GETS] == ["https://www.sec.gov/files/company_tickers.json",
      "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json"] and GETS[0][1] == R.UA_SEC["User-Agent"],
      "sec_facts：本機檔超過 45 日 → 喺 SEC 下載（CIK 補夠 10 位）")
GETS.clear()
d, cik = R.sec_facts("BRK-B")
check(d["entityName"] == "From SEC" and cik == 1067983 and len(GETS) == 2, "sec_facts：本機檔太細（壞檔）→ 下載；BRK.B 對到 BRK-B")
GETS.clear()
check(R.sec_facts("NOPE") == (None, None) and len(GETS) == 1, "sec_facts：代號唔喺 SEC 清單 → (None, None)，唔再下載")

# ============================================================ 3. sec_block
SPLIT = date(2024, 6, 10)


def filed30(end):
    return (date.fromisoformat(end) + timedelta(days=30)).isoformat()


def raw(adj_val, f):                                        # SEC 報嘅係當時基準：拆股前申報 = 新基準 × 10
    return adj_val * (10 if date.fromisoformat(f) < SPLIT else 1)


EPS = []
for y in range(2020, 2027):
    for s, e in ((f"{y}-01-01", f"{y}-03-31"), (f"{y}-04-01", f"{y}-06-30"), (f"{y}-07-01", f"{y}-09-30")):
        EPS.append(fx(s, e, raw(1.0, filed30(e)), "10-Q", filed30(e)))
    if y < 2026:
        e = f"{y}-12-31"
        EPS.append(fx(f"{y}-01-01", e, raw(4.0, filed30(e)), "10-K", filed30(e)))     # 第四季要由全年減出嚟
REV = [fx(f"{y}-01-01", f"{y}-12-31", 1000.0 * (y - 2018), "10-K", f"{y + 1}-02-15") for y in range(2019, 2026)]
REV += [fx("2025-01-01", "2025-06-30", 3000.0, "10-Q", "2025-07-30"), fx("2025-01-01", "2025-09-30", 5000.0, "10-Q", "2025-10-30"),
        fx("2026-01-01", "2026-06-30", 4000.0, "10-Q", "2026-07-30"), fx("2026-01-01", "2026-09-30", 6000.0, "10-Q", "2026-10-30")]
SB = {"entityName": "Beta Corp", "facts": {"us-gaap": {
    "Revenues": {"units": {"USD": REV}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": EPS}},
    "NetIncomeLoss": {"units": {"USD": [fx("2025-01-01", "2025-12-31", 700.0, "10-K", "2026-02-15")]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fx("2025-01-01", "2025-12-31", 900.0, "10-K", "2026-02-15")]}},
    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fx("2025-01-01", "2025-12-31", 300.0, "10-K", "2026-02-15")]}},
    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fx("2023-01-01", "2023-12-31", 100.0, "10-K", "2024-01-30"),
                                                                            fx("2025-01-01", "2025-12-31", 1000.0, "10-K", "2026-01-30")]}}}}}
ME = []                                                     # 2021-11 至 2026-10 每月 15 號一個收市價，對應月尾
y, m = 2021, 11
while (y, m) <= (2026, 10):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    ME.append((date(y, m, 15), nxt - timedelta(days=1)))
    y, m = nxt.year, nxt.month
CLOSES = [(c, (10 + j) * 4.0) for j, (c, _) in enumerate(ME)] + [(date(2026, 11, 12), 70 * 4.0)]   # 過去 4 季 EPS = 4 → 市盈率 10、11 … 70
R.sec_facts = lambda sym: (SB, 4242)
S = R.sec_block("BETA", {SPLIT: 10.0}, CLOSES)
ys = S["years"]
check(S["cik"] == 4242 and S["name"] == "Beta Corp" and [x["end"] for x in ys] == [f"{y}-12-31" for y in range(2021, 2026)],
      "sec_block：最近 5 個財年")
check(ys[0]["rev"] == 3000.0 and ys[0]["rev_g"] == 0.5 and abs(ys[-1]["rev_g"] - (7000 / 6000 - 1)) < 1e-12,
      "sec_block：收入增長用前一年計（第一年都有，因為攞 6 年先剪）")
check([x["eps"] for x in ys] == [4.0] * 5 and ys[2]["shares"] == 1000.0 and ys[4]["shares"] == 1000.0 and ys[0]["shares"] is None,
      "sec_block：拆股前申報嘅 EPS ÷ 10、股數 × 10（同 Yahoo 調整後股價同一基準）")
check(ys[4]["fcf"] == 600.0 and ys[3]["fcf"] is None, "sec_block：自由現金流 = 經營現金流 − 資本開支；缺一樣就冇")
check(S["ttm"]["rev"] == 8000.0 and S["ttm"]["end"] == "2026-09-30" and S["ttm"]["ni"] == 700.0 and S["ttm"]["fcf"] == 600.0,
      "sec_block 過去 12 個月：今年 9 個月 6000 + 去年全年 7000 − 去年 9 個月 5000 = 8000；冇 YTD 就用全年")
check(S["pe_hist"] == dict(n=61, med=40.0, lo=10.0, hi=70.0, now=70.0, since="2021-11-30"),
      "sec_block 過去市盈率：61 個點（60 個月尾 + 最近收市）、拆股調整後 EPS 一直係 4、中位 40、最低 10、最高 70")
check(R.sec_block("BETA", {SPLIT: 10.0}, CLOSES[-12:])["pe_hist"] == dict(n=12, med=65.0, lo=59.0, hi=70.0, now=70.0, since="2025-12-31"),
      "sec_block：得 12 個點（股價歷史得 12 個月）都計")
check(R.sec_block("BETA", {SPLIT: 10.0}, CLOSES[-11:])["pe_hist"] is None, "sec_block：唔夠 12 個點 → 唔計過去市盈率")
check(R.sec_block("BETA", {SPLIT: 10.0}, [])["pe_hist"] is None, "sec_block：冇股價 → 唔計過去市盈率（唔 crash）")
NEG = json.loads(json.dumps(SB))
for x in NEG["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"]:
    x["val"] = -x["val"]
R.sec_facts = lambda sym: (NEG, 1)
check(R.sec_block("NEG", {SPLIT: 10.0}, CLOSES)["pe_hist"] is None, "sec_block：虧損（EPS ≤ 0）唔計市盈率")
R.sec_facts = lambda sym: (None, None)
check(R.sec_block("X", {}, CLOSES) is None, "sec_block：SEC 冇呢隻 → None")


def boom(sym):
    raise RuntimeError("SEC 503")


R.sec_facts = boom
check(R.sec_block("X", {}, CLOSES) is None, "sec_block：SEC 出錯 → None（唔 crash）")

# ============================================================ 4. collect、earn_dates
TA, SBC = [], []
REAL_STRUCTURE = R.structure
R.structure = types.SimpleNamespace(analyze=lambda d, o, h, lo, c: TA.append(list(d)) or {"trend": "up"})
R.sec_block = lambda sym, splits, closes: SBC.append((splits, closes[-1])) or {"cik": 1, "name": sym}
(R.ROOT / "docs").mkdir(parents=True)
(R.ROOT / "docs" / "valuation.json").write_text(json.dumps({"generated": "2026-11-13 07:00 HKT", "market": {"ndx": {"pe": 30.0}},
                                                            "stocks": {"AAA": {"fpe": 20.0, "label": "偏平"}}}), encoding="utf-8")
IDX = pd.bdate_range("2023-06-01", "2026-11-13")
CL = [100.0 + k * 0.01 for k in range(len(IDX))]
CL[-2], CL[-1] = 150.0, 155.0
HIST = pd.DataFrame({"Open": [c - 1 for c in CL], "High": [c + 2 for c in CL], "Low": [c - 2 for c in CL], "Close": CL}, index=IDX)
FYE = int(datetime(2027, 1, 31, 12, tzinfo=NYT).timestamp())
CFG = {}


def tbl(rows):
    return pd.DataFrame(rows).T if rows else None


class Tk:
    def __init__(self, sym):
        self.sym = sym
        self.info = CFG["info"]
        self.splits = pd.Series({pd.Timestamp("2024-06-10"): 10.0, pd.Timestamp("2020-01-02"): 0.0})
        self.earnings_estimate = tbl(CFG.get("ee"))
        self.revenue_estimate = None
        self.eps_trend = tbl(CFG.get("trend"))
        self.recommendations_summary = pd.DataFrame([{"period": "0m", "strongBuy": 5, "buy": 10, "hold": 3}])
        self.calendar = {"Earnings Date": [date(2026, 11, 10), date(2026, 11, 20)]}

    @property
    def eps_revisions(self):
        raise RuntimeError("Yahoo 404")

    def history(self, **k):
        return CFG.get("hist", HIST)

    def get_earnings_dates(self, limit=8):
        return CFG.get("ed")


sys.modules["yfinance"] = types.SimpleNamespace(Ticker=Tk)


def offline(url, headers, timeout=60, tries=4):
    raise RuntimeError("offline")


R._get = offline
BASE_INFO = dict(currentPrice=154.0, longName="Alpha Co", exchange="NMS", nextFiscalYearEnd=FYE, forwardPE=24.0, trailingPegRatio=1.5,
                 recommendationKey="buy", earningsTimestamp=int(datetime(2026, 8, 21, 16, tzinfo=NYT).timestamp()))
ED = pd.DataFrame({"EPS Estimate": [1.0, 1.1]}, index=pd.DatetimeIndex([datetime(2026, 8, 20, 16), datetime(2026, 11, 19, 16)], tz=NYT))


def col(sym="AAA", ny=(2026, 11, 13, 15, 0), **kw):
    CFG.clear()
    CFG.update(info=dict(BASE_INFO), ee={"0y": {"avg": 8.0, "numberOfAnalysts": 30, "growth": 0.2, "currency": "USD"},
                                         "+1y": {"avg": 10.0, "numberOfAnalysts": 28, "growth": 0.25, "currency": "USD"}},
               trend={"+1y": {"current": 10.2, "30daysAgo": 10.0, "90daysAgo": 9.0}}, ed=ED)
    CFG.update(kw)
    NowDT.NOW = datetime(*ny, tzinfo=NYT)
    return R.collect(sym)


D = col()
w = 80 / 365
check(D["price"] == 150.0 and D["price_date"] == "2026-11-12" and TA[-1][-1] == "2026-11-12" and SBC[-1] == ({date(2024, 6, 10): 10.0}, (date(2026, 11, 12), 150.0)),
      "collect：紐約 15:00 今日未收市 → 用上一日收市（技術結構、SEC 市盈率都唔用今日）；拆股表剔走 0")
check(D["ntm_eps"] == round(w * 8 + (1 - w) * 10, 3) and D["ntm_how"] == "分析師預測：本財年 8.00 × 22% + 下財年 10.00 × 78%"
      and D["fpe"] == round(150 / (w * 8 + (1 - w) * 10), 1) and D["n0"] == 30 and D["e1"] == 10.0,
      "collect：未來 12 個月 EPS = 本財年 × 剩低 80 日／365 + 下財年 × 其餘")
check(D["street"]["rev_dir"] == "上修" and D["street"]["rev30"] == 0.02 and D["street"]["counts"] == {"strongBuy": 5, "buy": 10, "hold": 3}
      and D["street"]["rec_zh"] == "買入", "collect：30 日預測升 2% → 上修；評級分佈、中文評級")
check(D["next_earn"] == "2026-11-19" and D["last_earn"] == "2026-08-20", "collect：業績日用 get_earnings_dates（業績分頁讀唔到）")
check(D["app_val"] == {"fpe": 20.0, "label": "偏平", "src": "每日估值", "at": "2026-11-13 07:00 HKT"} and D["ndx_pe"] == 30.0,
      "collect：每日估值名單有呢隻 → 用 app 每日估值")
check(D["chart"]["d"][0] == "2024-01-01" and D["chart"]["d"][-1] == "2026-11-12" and D["chart"]["c"][-1] == 150.0
      and (D["chart"]["o"][-1], D["chart"]["h"][-1], D["chart"]["l"][-1]) == (149.0, 152.0, 148.0) and D["exchange"] == "那斯達克",
      "collect：圖由前兩年 1 月 1 日起、開高低收；交易所中文")
check(col(ny=(2026, 11, 13, 16, 9))["price_date"] == "2026-11-12", "collect：16:09 照當未收市")
check(col(ny=(2026, 11, 13, 16, 10))["price"] == 155.0, "collect：16:10 當收市，用今日價")
D = col("BBB", ee={"+1y": {"avg": 10.0}}, ed=None, trend={"+1y": {"current": 10.05, "30daysAgo": 10.0, "90daysAgo": 9.5}})
check(D["ntm_eps"] == 10.0 and D["ntm_how"] == "分析師預測（下財年）", "collect：得下財年預測 → 直接用")
check(D["street"]["rev_dir"] == "持平偏上修", "collect：30 日變化細（0.5%）但 90 日升超過 3% → 持平偏上修")
check(D["next_earn"] == "2026-11-20" and D["last_earn"] == "2026-08-21", "collect：冇 get_earnings_dates → 下次用 Yahoo calendar（11-10 已過剔走）、上次用 earningsTimestamp")
check(D["app_val"]["src"] == "即場計（同每日估值同一條公式）" and D["app_val"]["vs_ndx"] == 0.8 and D["app_val"]["at"] == "2026-11-12",
      "collect：唔喺每日估值名單 → 即場計，對 Nasdaq 100 市盈率 24 ÷ 30 = 0.8")
check(col("CCC", ee={"0y": {"avg": 8.0}})["ntm_how"] == "分析師預測（本財年）", "collect：得本財年預測 → 用本財年")
D = col("DDD", ee=None, trend=None)
check(D["ntm_eps"] is None and D["fpe"] is None and D["street"]["rev_dir"] is None, "collect：冇任何預測 → 冇未來 EPS、冇修訂方向")
CFG_INFO = dict(BASE_INFO, forwardEps=7.0)
check(col("EEE", ee=None, info=CFG_INFO)["ntm_how"] == "Yahoo 預期 EPS", "collect：冇分析師表但有 forwardEps → 用 Yahoo 預期 EPS")
try:
    col("ZZZ", info={"longName": "No price"})
    err = ""
except RuntimeError as e:
    err = str(e)
check("Yahoo 冇報價" in err, "collect：冇報價 → 報錯（代號可能錯）")

FEED = {"syms": ["AAA"], "upcoming": [{"sym": "AAA", "date": "2026-11-10"}, {"sym": "AAA", "date": "2026-11-21"}, {"sym": "BBB", "date": "2026-11-14"}]}
R._get = lambda url, headers, timeout=60, tries=4: json.dumps(dict(FEED, checked="2026-11-12T08:00:00+00:00")).encode()
NowDT.NOW = datetime(2026, 11, 13, 12, tzinfo=ZoneInfo("UTC"))
tk = types.SimpleNamespace(get_earnings_dates=lambda limit=8: ED)
check(R.earn_dates("AAA", tk, date(2026, 11, 12)) == (date(2026, 11, 21), date(2026, 8, 20)),
      "earn_dates：業績分頁 2 日內、有呢隻 → 下次用分頁（剔走已過）；上次用 get_earnings_dates")
check(R.earn_dates("BBB", tk, date(2026, 11, 12)) == (date(2026, 11, 19), date(2026, 8, 20)), "earn_dates：分頁冇呢隻（syms）→ 自己查")
R._get = lambda url, headers, timeout=60, tries=4: json.dumps(dict(FEED, checked="2026-11-10T08:00:00+00:00")).encode()
check(R.earn_dates("AAA", tk, date(2026, 11, 12))[0] == date(2026, 11, 19), "earn_dates：分頁超過 2 日 → 唔用，自己查")

# ============================================================ 5. clean_analysis、build、due_list
D0 = json.loads((T / "fixtures" / "research_D_NVDA.json").read_text(encoding="utf-8"))
SRC = R.base_sources(D0)


def scen(**kw):
    return dict(dict(key="k", name="n", story="s", prob=0.2, g1=0.1, g2=0.05, pe=20, why="w", src=["S3", "S9"]), **kw)


A = R.clean_analysis({"scenarios": [scen(key="bull", g1=25, g2=0.1), scen(key="bear", g1=0.2, g2=8), scen(key="base", g1=-0.5, g2=0.5, pe=60, prob=0.4)]},
                     SRC, D0)
sc = {x["key"]: x for x in A["scenarios"]}
check(abs(sc["bull"]["g1"] - 0.25) < 1e-12 and sc["bull"]["g2"] == 0.1, "clean_analysis：第 2–5 年增長寫咗 25（百分比）→ 0.25；另一個 0.1 唔郁")
check(sc["bear"]["g1"] == 0.2 and abs(sc["bear"]["g2"] - 0.08) < 1e-12, "clean_analysis：第 6–10 年增長寫咗 8 → 0.08")
check((sc["base"]["g1"], sc["base"]["g2"], sc["base"]["pe"]) == (-0.30, 0.40, 45) and sc["base"]["clipped"] and not sc["bull"]["clipped"],
      "clean_analysis：超出範圍收窄（增長 −30%／40%、市盈率 45）並標 clipped")
check([x["prob"] for x in A["scenarios"]] == [0.25, 0.25, 0.5] and sc["bull"]["src"] == ["S3"], "clean_analysis：機率加埋變 1；唔存在嘅來源 S9 剔走")
check(R.clean_analysis({"scenarios": [scen(key="bull"), scen(key="bear"), scen(key="base", pe=None)]}, SRC, D0)["scenarios"] == [],
      "clean_analysis：唔夠三個完整情境 → 冇情境（唔估值）")

R.structure = REAL_STRUCTURE
R.OUT = OUT / "research"
R.collect = lambda s: dict(D0, sym=s)
R.peer_rows = lambda peers: []
NowDT.NOW = datetime(2026, 11, 13, 9, 0, tzinfo=HKT)
rep = R.build("zzz", dry=True)
idx = json.loads((R.OUT / "index.json").read_text(encoding="utf-8"))
check(rep and rep["dry"] and rep["sym"] == "ZZZ" and not rep["valuation"]["ok"] and (R.OUT / "ZZZ.json").exists()
      and [x["sym"] for x in idx["items"]] == ["ZZZ"], "build --dry：唔叫 AI、照樣儲存（標 dry、未能估值）、入 index")
MD = OUT / "manual"
check(R.build("YYY", manual=str(MD)) is None and (MD / "prompt_gather.txt").exists() and (MD / "prompt_analysis.txt").exists()
      and not (R.OUT / "YYY.json").exists(), "build --manual 未有 analysis.json：寫低提示，唔儲存")
ANA = {"name_zh": "測試", "moat": "窄", "moat_trend": "穩定", "uncertainty": "中", "capital": "普通", "scores": [], "peers": [],
       "scenarios": [scen(key="bull"), scen(key="bear", g1=0.0, g2=0.0, pe=10), scen(key="base", prob=0.6)],
       "bull": [{"text": "好", "src": ["S1"]}], "bear": [{"text": "淡", "src": []}], "blind_spot": {"title": "t", "detail": "d"}, "next_check": "業績"}
(MD / "analysis.json").write_text(json.dumps(ANA, ensure_ascii=False), encoding="utf-8")
check(R.build("YYY", manual=str(MD)) is None and (MD / "prompt_writing.txt").exists() and not (R.OUT / "YYY.json").exists(),
      "build --manual 有分析、未有 writing.json：唔儲存")
(MD / "writing.json").write_text(json.dumps({"verdict_plain": "v", "changes": []}), encoding="utf-8")
(MD / "sources.json").write_text(json.dumps([{"title": "IR", "url": "https://ir.example.com"}]), encoding="utf-8")
rep = R.build("YYY", manual=str(MD))
check(rep["sample"] and not rep["dry"] and rep["valuation"]["ok"] and (R.OUT / "YYY.json").exists() and rep["sources"][-1]["id"] == "S5"
      and rep["models"]["writing"] == "Claude Code（對話入面人手代入，樣本）", "build --manual 回覆齊：儲存（標樣本）、網上來源由 S5 起")

DUE = OUT / "due"
DUE.mkdir()
R.OUT, R.LIST, R.AUTO_TOP, R.MAX_AGE = DUE, OUT / "list.txt", 2, 7
(R.ROOT / "docs" / "model_cont.json").write_text(json.dumps({"positions": [{"sym": "TQQQ"}, {"sym": "FFF"}]}), encoding="utf-8")
(R.ROOT / "docs" / "scan.json").write_text(json.dumps({"ranking": [{"sym": "GGG"}, {"sym": "DDD"}, {"sym": "XXX"}]}), encoding="utf-8")
(DUE / "index.json").write_text(json.dumps({"items": [{"sym": s} for s in ("AAA", "BBB", "CCC", "EEE")]}), encoding="utf-8")
R.LIST.write_text("aaa  # 已經有\nhhh $bad toolongsymbol123\n# ZZZ 成行註解\n", encoding="utf-8")
for s, rd, extra in (("AAA", "2026-11-06", {}), ("BBB", "2026-11-07", {}), ("DDD", "2026-11-12", {"dry": True}),
                     ("EEE", "2026-11-10", {"next_check": {"date": "2026-11-12"}}), ("FFF", "2026-11-12", {"next_check": {"date": "2026-11-11"}}),
                     ("GGG", "2026-11-11", {"next_check": {"date": "2026-11-13"}})):
    (DUE / f"{s}.json").write_text(json.dumps(dict(research_date=rd, **extra)), encoding="utf-8")
NowDT.NOW = datetime(2026, 11, 13, 12, 0, tzinfo=HKT)
check(R.due_list() == [("DDD", "冇正式報告"), ("AAA", "7 日未更新"), ("CCC", "冇正式報告"), ("EEE", "業績（2026-11-12）公佈咗"), ("HHH", "冇正式報告")],
      "due_list：模型持倉（唔計 ETF）+ 排名頭 2 + index + 清單檔；7 日先到期（6 日唔到）；業績過咗未更新要做；dry 當冇報告；"
      "業績前已更新／業績係今日唔使做；註解同壞代號唔要")
R.MAX_AGE = 6
check(("BBB", "6 日未更新") in R.due_list(), "due_list：RESEARCH_MAX_AGE_DAYS 改 6 → 6 日都到期")
print(f"\n全部 {ok} 項通過")
