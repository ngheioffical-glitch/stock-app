"""個股研究報告（2026-10-20 用戶：「我想我個 app 都好似佢咁」「想複製佢個界面」— 影片入面嗰種 AI 個股研究頁；做法同 Codex 傾好）。

每隻股票嘅流程：
  1. 程式收集數據，每個來源有編號：[S1] Yahoo 報價同公司資料、[S2] Yahoo 分析師預測同目標價、[S3] SEC 財報（XBRL）、
     [S4] 本 app 估值頁（Nasdaq 100 市盈率）。
  2. AI 第一步（上網搜尋）：Claude 原生搜尋寫研究筆記，每句標來源，網上來源接住編號（[S5] 起）。後備 Gemini + Google（標明）。
  3. AI 第二步（固定 JSON 格式）：評級（護城河、不確定性、資本配置）、評分卡、題材、股價圖事件、三個情境嘅「假設」、好淡理由、
     最大盲區、同華爾街唔同嘅地方、商業模式、同業代號、「先搞懂」、名詞表。只可以引用有編號嘅來源；程式剔走唔存在嘅編號。
  4. 程式按公式計估值（AI 只係俾假設，數字全部由程式計）：
       第 1 年每股盈利 = 分析師未來 12 個月預測（本財年同下財年按日子加權）；第 2–5 年、第 6–10 年按情境增長率滾；
       第 10 年股價 = 第 10 年盈利 × 情境市盈率；今日價值 = 10 年股息 + 第 10 年股價，用 RESEARCH_DISCOUNT（預設 9%）折返今日。
       公允價值 = 三個情境今日價值按機率加權。星級 = 現價 ÷ 公允價值，按不確定性用唔同安全邊際（參考晨星公開方法，唔係晨星數據）。
       冇正數盈利預測或者冇情境 → 「未能估值」，唔會亂估。
  5. AI 第三步：拎住程式計好嘅數字寫「30 秒判讀」、結論、同上次比較嘅原因、估值白話、同業比較；唔准自己作新數字。
  6. 輸出 docs/research/<SYM>.json；舊一份搬去 docs/research/hist/<SYM>/<日期>.json；docs/research/index.json 係清單同每月用量。
個人成本、倉位只存喺用戶手機（app 自己計），唔會上傳。今日價值同 10 年後價值分開寫；對成本、對現價都分開。
AI 經 scanner/llm.py：預設 Claude Opus 5.5（effort high），失敗退 Gemini 並標明後備；用咗幾多錢記喺報告同 index.json。

用法：
  python scanner/research.py NVDA [MSFT …]       生成（要 AI key；每月用量超過 RESEARCH_MONTH_USD 就停，--force 照做）
  python scanner/research.py NVDA --dry          唔叫 AI：只收集數據（AI 部分留空、估值寫未能估值），測試用
  python scanner/research.py NVDA --manual DIR   唔叫 API：每步提示寫入 DIR，AI 回覆由 DIR 讀（notes.md + sources.json、
                                                 analysis.json、writing.json），測試提示同人手代入（報告標「樣本」）
  python scanner/research.py NVDA --fresh        當第一次研究（唔同上次比較、唔存舊報告），重做壞咗嘅報告用
  python scanner/research.py --due               排程：清單入面（index.json + scanner/research_list.txt）冇報告、超過
                                                 RESEARCH_MAX_AGE_DAYS（預設 7）日、或者業績公佈咗之後未更新嘅股票，每次最多 RESEARCH_MAX_PER_RUN 隻
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import valuation as appval  # noqa: E402   # app 每日估值（同一條公式，2026-10-21 合併重複）

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("RESEARCH_OUT") or ROOT / "docs" / "research")      # 測試可以改去 tmp
LIST = ROOT / "scanner" / "research_list.txt"
HKT, NYT = ZoneInfo("Asia/Hong_Kong"), ZoneInfo("America/New_York")
STYLE = "用香港廣東話口語、繁體中文。專有名詞（公司、指數、人名、股票代號、產品）保留英文或者通用中譯。"
R = float(os.environ.get("RESEARCH_DISCOUNT", "0.09"))           # 要求回報（折現率）
MAX_SEARCH = int(os.environ.get("RESEARCH_MAX_SEARCH", "8"))
MAX_AGE = int(os.environ.get("RESEARCH_MAX_AGE_DAYS", "7"))
PER_RUN = int(os.environ.get("RESEARCH_MAX_PER_RUN", "2"))
AUTO_TOP = int(os.environ.get("RESEARCH_AUTO_TOP", "5"))     # 2026-10-22 用戶「個股研究得一個，點搞？」：自動加模型持倉 + RS 排名頭幾隻
MONTH_USD = float(os.environ.get("RESEARCH_MONTH_USD", "40"))          # 每月研究用量上限（美元）
EST_USD = float(os.environ.get("RESEARCH_EST_USD", "1.5"))             # 每份估計費用：開始前「已用 + 估計 > 上限」就唔做（2026-10-21 Codex 改卷）
MAX_TOKENS = int(os.environ.get("RESEARCH_MAX_TOKENS", "64000"))         # 分析 JSON 長、effort high 思考都計輸出；API 唔收就自動退返 32000
UA_SEC = {"User-Agent": "stock-app research admin@stock-app.local"}     # SEC 要「名 + 電郵」格式；唔用用戶電郵
EXCH = {"NMS": "那斯達克", "NGM": "那斯達克", "NCM": "那斯達克", "NAS": "那斯達克", "NYQ": "紐約證券交易所", "NYS": "紐約證券交易所",
        "ASE": "NYSE American", "PCX": "NYSE Arca", "BTS": "Cboe"}
REC_ZH = {"strong_buy": "強烈買入", "buy": "買入", "hold": "持有", "underperform": "跑輸", "sell": "賣出", "strong_sell": "強烈賣出", "none": "冇評級"}
# 星級：現價 ÷ 公允價值嘅上限（5 星、4 星、3 星、2 星；再高 = 1 星）。不確定性越高，要越大安全邊際（參考晨星公開方法）
BANDS = {"低": (0.80, 0.95, 1.05, 1.25), "中": (0.70, 0.90, 1.10, 1.35), "高": (0.60, 0.85, 1.20, 1.55),
         "非常高": (0.50, 0.80, 1.30, 1.80), "極高": (0.35, 0.70, 1.50, 2.25)}
SCORES = [("moat", "護城河強度"), ("moat_trend", "護城河趨勢"), ("financial", "財務健康"), ("growth", "成長性"),
          ("valuation", "估值吸引力"), ("management", "管理層同資本配置"), ("strategy", "戰略前瞻"), ("flywheel", "AI／數據飛輪"),
          ("certainty", "確定性")]
GROUPS = [("what", "呢個係乜"), ("why", "點解係佢"), ("how", "零件點運作"), ("now", "現況"), ("me", "同我有乜關係")]
DISCLAIMER = ("AI 生成，可能有錯漏，唔係投資建議。數字（公允價值、情境、星級）由程式按公式計；評級同文字由 AI 寫；"
              "每句事實嘅來源喺「來源」。星級方法參考晨星公開嘅安全邊際做法，唔係晨星評級。")


# ───────────────────────────────────────────── 細工具
def num(x, nd=None):
    """轉 float；NaN／唔係數字 → None。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, nd) if nd is not None else v


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def money(x):
    """美元大數：萬億／億／萬。"""
    if x is None:
        return "—"
    a, s = abs(x), "-" if x < 0 else ""
    if a >= 1e12:
        return f"{s}{a / 1e12:.2f} 萬億"
    if a >= 1e10:
        return f"{s}{a / 1e8:,.0f} 億"
    if a >= 1e8:
        return f"{s}{a / 1e8:.1f} 億"
    return f"{s}{a / 1e4:,.0f} 萬"


def pct(x, nd=1):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def pc(x, nd=1):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _get(url, headers, timeout=60, tries=4):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read()
        except Exception as e:  # noqa: BLE001
            if "404" in str(e) or k == tries - 1:
                raise
            time.sleep(4 * (k + 1))


def _tbl(df):
    """yfinance 表 → {期間: {欄: 數}}（例如 {"0y": {"avg": 9.3, …}}）。"""
    try:
        if df is None or not len(df):
            return {}
        return {str(k): {c: num(v) for c, v in row.items() if c != "currency"} for k, row in df.iterrows()}
    except Exception:  # noqa: BLE001
        return {}


# ───────────────────────────────────────────── 1. 數據
TAGS = dict(
    rev=["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
         "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    gp=["GrossProfit"], op=["OperatingIncomeLoss"], ni=["NetIncomeLoss", "ProfitLoss"],
    eps=["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"],
    cfo=["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    capex=["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    sbc=["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    buyback=["PaymentsForRepurchaseOfCommonStock"], div=["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    shares=["WeightedAverageNumberOfDilutedSharesOutstanding"],
)


def sec_facts(sym):
    """SEC companyfacts（XBRL）：本機回測資料夾有 45 日內嘅就用（Actions 冇呢個資料夾），否則喺 SEC 下載。返 (dict, cik)。"""
    loc = ROOT.parent / "stock-strategy" / "data" / "sec" / "facts" / f"{sym}.json"
    if loc.exists() and loc.stat().st_size > 1000 and time.time() - loc.stat().st_mtime < 45 * 86400:
        d = json.loads(loc.read_text(encoding="utf-8"))
        return d, d.get("cik")
    tick = json.loads(_get("https://www.sec.gov/files/company_tickers.json", UA_SEC))
    cik = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in tick.values()}.get(sym)
    if not cik:
        return None, None
    time.sleep(0.3)
    return json.loads(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", UA_SEC)), cik


def _dur(facts, tags, splits=None, adj=None):
    """期間數（收入、盈利…）：{(開始, 結束): 數}。同一期間揀排前嘅 tag、最新嘅申報（即係重述之後嘅數）。
    adj="eps"／"shares"：每股數 ÷、股數 × 「申報日之後」嘅拆股倍數。要用申報日唔係期末日：拆股之後嘅報告會用新基準重述舊年
    （例如 NVDA 2024 年 10 拆 1 之後，年報將 2023 財年 EPS 1.74 重述做 0.17），用期末日會調整兩次。"""
    g = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    best = {}
    for pri, tg in enumerate(tags):
        for lst in (g.get(tg) or {}).get("units", {}).values():
            for x in lst:
                if "start" not in x or x.get("form", "")[:4] not in ("10-K", "10-Q", "20-F", "40-F"):
                    continue
                k, cand = (x["start"], x["end"]), (pri, x.get("filed") or x["end"], float(x["val"]))
                cur = best.get(k)
                if cur is None or cand[0] < cur[0] or (cand[0] == cur[0] and cand[1] > cur[1]):
                    best[k] = cand
    out = {}
    for k, (pri, filed, v) in best.items():
        if adj and splits:
            f = split_factor(splits, filed)
            v = v / f if adj == "eps" else v * f
        out[k] = v
    return out


def _dur_hist(facts, tags, splits=None, adj=None):
    """同 _dur，但保留每一次申報：{(開始, 結束): [(tag 次序, 申報日, 數)]}。計歷史市盈率用：每個月只用嗰日已經申報咗嘅數，
    唔用之後重述嘅數（2026-10-21 Codex 改卷：之前用最新重述 + 季尾 45 日，含事後資訊）。冇申報日就當季尾 45 日後先知道。"""
    g = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    out = {}
    for pri, tg in enumerate(tags):
        for lst in (g.get(tg) or {}).get("units", {}).values():
            for x in lst:
                if "start" not in x or x.get("form", "")[:4] not in ("10-K", "10-Q", "20-F", "40-F"):
                    continue
                filed = x.get("filed") or (date.fromisoformat(x["end"]) + timedelta(days=45)).isoformat()
                v = float(x["val"])
                if adj and splits:
                    f = split_factor(splits, filed)
                    v = v / f if adj == "eps" else v * f
                out.setdefault((x["start"], x["end"]), []).append((pri, filed, v))
    return out


def _asof(h, d):
    """_dur_hist → d 嗰日已知嘅期間數：每個期間揀 d 或之前申報、tag 次序最前、最新嗰次。"""
    ds, out = d.isoformat(), {}
    for k, lst in h.items():
        c = [x for x in lst if x[1] <= ds]
        if c:
            pri = min(x[0] for x in c)
            out[k] = max((x for x in c if x[0] == pri), key=lambda x: x[1])[2]
    return out


def _annual(d):
    return {e: v for (s, e), v in d.items() if 350 <= _days(s, e) <= 380}


def _ttm_ytd(d):
    """過去 12 個月 = 今個財年至今（YTD）+ 上個財年全年 − 上個財年同期 YTD。現金流表只報 YTD（6 個月、9 個月），
    唔可以直接加 4 個季度。冇 YTD 就用最近全年。返 (數, 截至)。"""
    ann = sorted((k for k in d if 350 <= _days(*k) <= 380), key=lambda k: k[1])
    if not ann:
        return None, None
    s_a, e_a = ann[-1]
    ytd = [k for k in d if 0 < _days(e_a, k[0]) <= 7 and _days(*k) < 340]
    if not ytd:
        return d[(s_a, e_a)], e_a
    s_y, e_y = max(ytd, key=lambda k: k[1])
    prior = [k for k in d if abs(_days(s_a, k[0])) <= 7 and abs(_days(k[1], e_y) - 364) <= 10 and abs(_days(*k) - _days(s_y, e_y)) <= 10]
    if not prior:
        return d[(s_a, e_a)], e_a
    return d[(s_y, e_y)] + d[(s_a, e_a)] - d[prior[0]], e_y


def _quarters(d):
    """季度數 [(季尾, 數)]；第四季 = 全年 − 頭三季（年報通常唔會獨立報第四季）。"""
    q = {e: (s, v) for (s, e), v in d.items() if 80 <= _days(s, e) <= 100}
    for (s, e), v in d.items():
        if 350 <= _days(s, e) <= 380 and not any(abs(_days(e, qe)) <= 5 for qe in q):
            ins = [(qe, qv) for qe, (qs, qv) in q.items() if _days(s, qs) >= -5 and _days(qe, e) >= -5]
            if len(ins) == 3:
                q[e] = (max(x[0] for x in ins), v - sum(x[1] for x in ins))
    return sorted((e, v) for e, (s, v) in q.items())


def _ttm(qs, asof=None, avail=0):
    """最近 4 季加埋（要連續，最舊同最新相差 ≤ 300 日）；asof：只用 季尾 + avail 日 ≤ asof 嘅季度（計歷史市盈率用）。"""
    if asof:
        qs = [x for x in qs if date.fromisoformat(x[0]) + timedelta(days=avail) <= asof]
    k = qs[-4:]
    if len(k) < 4 or _days(k[0][0], k[-1][0]) > 300:
        return None, None
    return sum(v for _, v in k), k[-1][0]


def split_factor(splits, end):
    """季尾之後嘅拆股倍數（SEC 嘅每股數係當時未拆股嘅，Yahoo 股價已經調整）。"""
    f = 1.0
    for d, r in splits.items():
        if d > date.fromisoformat(end):
            f *= r
    return f


def sec_block(sym, splits, closes):
    """SEC 財年數據（最近 5 年）、過去 12 個月、過去 5 年市盈率（按月）。"""
    try:
        facts, cik = sec_facts(sym)
    except Exception as e:  # noqa: BLE001
        print(f"[research] {sym} SEC 數據攞唔到：{str(e)[:120]}")
        return None
    if not facts:
        return None
    F = {k: _dur(facts, t, splits, adj="eps" if k == "eps" else "shares" if k == "shares" else None) for k, t in TAGS.items()}
    A = {k: _annual(v) for k, v in F.items()}
    ends = sorted(A["rev"])[-6:]
    years = []
    for e in ends:
        g = lambda k: A[k].get(e)
        cfo, capex = g("cfo"), g("capex")
        years.append(dict(end=e, rev=g("rev"), gp=g("gp"), op=g("op"), ni=g("ni"), eps=num(g("eps"), 3),
                          fcf=cfo - capex if cfo is not None and capex is not None else None, cfo=cfo, capex=capex,
                          sbc=g("sbc"), buyback=g("buyback"), div=g("div"), shares=g("shares")))
    for a, b in zip(years, years[1:]):
        b["rev_g"] = b["rev"] / a["rev"] - 1 if a.get("rev") and b.get("rev") else None
    years = years[-5:]
    ttm = {}
    for k in ("rev", "gp", "op", "ni", "cfo", "capex", "sbc", "buyback", "div"):
        ttm[k], e = _ttm_ytd(F[k])
        if k == "rev":
            ttm["end"] = e
    if ttm.get("cfo") is not None and ttm.get("capex") is not None:
        ttm["fcf"] = ttm["cfo"] - ttm["capex"]
    # 過去 5 年市盈率（每月）：調整後股價 ÷ 過去 4 季 EPS（已按拆股調整；只用嗰日已經申報咗嘅數，唔用之後重述）
    H = _dur_hist(facts, TAGS["eps"], splits, adj="eps")
    pes = []
    if H and closes:
        days = [closes[-1][0]]
        while len(days) < 61:                            # 過去 60 個月尾 + 最近收市日
            days.append(date(days[-1].year, days[-1].month, 1) - timedelta(days=1))
        for d in reversed(days):
            eps, _e = _ttm(_quarters(_asof(H, d)))
            px = next((c for dd, c in reversed(closes) if dd <= d), None)
            if eps and eps > 0 and px:
                pes.append((d.isoformat(), px / eps))
    pe_hist = None
    if len(pes) >= 12:
        v = sorted(x[1] for x in pes)
        pe_hist = dict(n=len(v), med=num(v[len(v) // 2], 1), lo=num(v[0], 1), hi=num(v[-1], 1), now=num(pes[-1][1], 1), since=pes[0][0])
    return dict(cik=cik, name=facts.get("entityName"), years=years, ttm=ttm, pe_hist=pe_hist)


FEED_EARN = "https://raw.githubusercontent.com/{repo}/feeds/earnings.json"


def earn_dates(sym, t, pdate):
    """下次同上次業績日期，同 app「業績」分頁一樣：先讀 feeds 分支 earnings.json（earnings.py；只有持倉 + 排名頭 15，要 2 日內），
    冇呢隻股或者過期，就用同一個方法（yfinance get_earnings_dates）自己查。都唔得返 (None, None)，由調用者用 Yahoo calendar。"""
    nxt = None
    try:
        repo = os.environ.get("GITHUB_REPOSITORY") or "ngheioffical-glitch/stock-app"
        e = json.loads(_get(FEED_EARN.format(repo=repo), {"User-Agent": "Mozilla/5.0"}, timeout=20, tries=2))
        chk = datetime.fromisoformat(e["checked"])
        if datetime.now(chk.tzinfo) - chk < timedelta(days=2) and sym in (e.get("syms") or []):
            up = sorted(u["date"] for u in e.get("upcoming") or [] if u.get("sym") == sym and u["date"] >= pdate.isoformat())
            nxt = date.fromisoformat(up[0]) if up else None
    except Exception as ex:  # noqa: BLE001
        print(f"[research] 讀唔到業績分頁數據（{str(ex)[:80]}），自己查")
    last = None
    try:
        df = t.get_earnings_dates(limit=8)
        if df is not None and not df.empty:
            ds = sorted(ts.tz_convert(NYT).date() for ts in df.index)
            past = [d for d in ds if d <= pdate]
            fut = [d for d in ds if d > pdate]
            last = past[-1] if past else None
            nxt = nxt or (fut[0] if fut else None)
    except Exception as ex:  # noqa: BLE001
        print(f"[research] {sym} get_earnings_dates 失敗（{str(ex)[:80]}），用 Yahoo calendar")
    return nxt, last


def collect(sym):
    """收集一隻股票嘅全部程式數據。"""
    import yfinance as yf
    t = yf.Ticker(sym)
    i = t.info or {}
    h = t.history(period="6y", interval="1d", auto_adjust=True)
    if h is None or not len(h) or not (i.get("currentPrice") or i.get("regularMarketPrice")):
        raise RuntimeError(f"{sym}：Yahoo 冇報價（代號啱唔啱？）")
    closes = [(ts.date(), float(c)) for ts, c in zip(h.index, h["Close"]) if c == c]
    now = datetime.now(NYT)
    if closes[-1][0] == now.date() and (now.hour, now.minute) < (16, 10):
        closes = closes[:-1]                             # 今日未收市：用上一個收市價（報告寫「收市」）
    price, pdate = closes[-1][1], closes[-1][0]
    try:
        splits = {ts.date(): float(v) for ts, v in t.splits.items() if v and v > 0}
    except Exception:  # noqa: BLE001
        splits = {}
    est = {}
    for n in ("earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions"):
        try:
            est[n] = _tbl(getattr(t, n))
        except Exception:  # noqa: BLE001
            est[n] = {}
    try:
        rs = t.recommendations_summary
        rec = {k: int(v) for k, v in rs.iloc[0].items() if k != "period"} if rs is not None and len(rs) else {}
    except Exception:  # noqa: BLE001
        rec = {}
    try:
        cal = t.calendar or {}
    except Exception:  # noqa: BLE001
        cal = {}
    # 未來 12 個月 EPS = 本財年 × 本財年剩低比例 + 下財年 × 其餘（分析師平均）
    ee = est["earnings_estimate"]
    e0, e1 = (ee.get("0y") or {}).get("avg"), (ee.get("+1y") or {}).get("avg")
    fye = i.get("nextFiscalYearEnd")
    w = clip(((datetime.fromtimestamp(fye, NYT).date() - pdate).days / 365) if fye else 0.5, 0, 1)
    if e0 and e1:
        ntm, ntm_how = w * e0 + (1 - w) * e1, f"分析師預測：本財年 {e0:.2f} × {w:.0%} + 下財年 {e1:.2f} × {1 - w:.0%}"
    elif e1 or e0 or i.get("forwardEps"):
        ntm = e1 or e0 or i.get("forwardEps")
        ntm_how = "分析師預測（下財年）" if e1 else "分析師預測（本財年）" if e0 else "Yahoo 預期 EPS"
    else:
        ntm, ntm_how = None, None
    tr = (est["eps_trend"].get("+1y") or est["eps_trend"].get("0y") or {})
    r30 = tr["current"] / tr["30daysAgo"] - 1 if tr.get("current") and tr.get("30daysAgo") else None
    r90 = tr["current"] / tr["90daysAgo"] - 1 if tr.get("current") and tr.get("90daysAgo") else None
    if r30 is None:
        rdir = None
    else:
        rdir = "上修" if r30 > 0.01 else "下修" if r30 < -0.01 else "持平"
        if rdir == "持平" and r90 is not None and abs(r90) > 0.03:
            rdir = "持平偏上修" if r90 > 0 else "持平偏下修"
    nxt_e, last_e = earn_dates(sym, t, pdate)            # 2026-10-21 合併重複：同「業績」分頁同一個來源
    edates = [nxt_e] if nxt_e else [d for d in (cal.get("Earnings Date") or []) if isinstance(d, date) and d >= pdate]
    if not edates and i.get("earningsTimestamp"):
        d = datetime.fromtimestamp(i["earningsTimestamp"], NYT).date()
        edates = [d] if d >= pdate else []
    last_earn = last_e or (datetime.fromtimestamp(i["earningsTimestamp"], NYT).date() if i.get("earningsTimestamp") else None)
    start = date(pdate.year - 2, 1, 1)
    ch = [(d, c) for d, c in closes if d >= start]
    S = sec_block(sym, splits, closes)
    val = {}
    try:
        val = json.loads((ROOT / "docs" / "valuation.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    vs = dict((val.get("stocks") or {}).get(sym) or {})
    ndx = ((val.get("market") or {}).get("ndx") or {})
    # 2026-10-21 合併重複：報告顯示同排名／持倉頁一樣嘅「每日估值」（Yahoo 預期市盈率 + PEG）。唔喺每日估值名單（只有排名同持倉）
    # 就用同一條公式（valuation.stock_label）即場計，口徑一樣
    if vs:
        vs["src"], vs["at"] = "每日估值", val.get("generated")
    else:
        fpe_y, peg_y = i.get("forwardPE"), i.get("trailingPegRatio") or i.get("pegRatio")
        lab, why = appval.stock_label(fpe_y, peg_y, ndx.get("pe"))
        vs = dict(fpe=num(fpe_y, 1), tpe=num(i.get("trailingPE"), 1), peg=num(peg_y, 2), ps=num(i.get("priceToSalesTrailing12Months"), 1),
                  label=lab, why=why, vs_ndx=num(fpe_y / ndx["pe"], 2) if fpe_y and fpe_y > 0 and ndx.get("pe") else None,
                  src="即場計（同每日估值同一條公式）", at=pdate.isoformat())
    return dict(
        sym=sym, name=i.get("longName") or i.get("shortName") or sym, exchange=EXCH.get(i.get("exchange"), i.get("fullExchangeName") or ""),
        currency=i.get("currency") or "USD", sector=i.get("sector"), industry=i.get("industry"), country=i.get("country"),
        website=i.get("website"), summary=(i.get("longBusinessSummary") or "")[:1500], employees=i.get("fullTimeEmployees"),
        price=round(price, 2), price_date=pdate.isoformat(), hi52=num(i.get("fiftyTwoWeekHigh"), 2), lo52=num(i.get("fiftyTwoWeekLow"), 2),
        chg52=num(i.get("52WeekChange"), 4), mcap=num(i.get("marketCap")), shares=num(i.get("sharesOutstanding")),
        ttm_eps=num(i.get("trailingEps"), 3), ntm_eps=num(ntm, 3), ntm_how=ntm_how, e0=num(e0, 3), e1=num(e1, 3),
        n0=int((ee.get("0y") or {}).get("numberOfAnalysts") or 0) or None, n1=int((ee.get("+1y") or {}).get("numberOfAnalysts") or 0) or None,
        g0=(ee.get("0y") or {}).get("growth"), g1=(ee.get("+1y") or {}).get("growth"),
        rev0=(est["revenue_estimate"].get("0y") or {}).get("avg"), rev1=(est["revenue_estimate"].get("+1y") or {}).get("avg"),
        rg0=(est["revenue_estimate"].get("0y") or {}).get("growth"), rg1=(est["revenue_estimate"].get("+1y") or {}).get("growth"),
        tpe=num(i.get("trailingPE"), 1), fpe=num(price / ntm, 1) if ntm and ntm > 0 else None, peg=num(i.get("trailingPegRatio"), 2),
        ps=num(i.get("priceToSalesTrailing12Months"), 1), gm=num(i.get("grossMargins"), 4), om=num(i.get("operatingMargins"), 4),
        pm=num(i.get("profitMargins"), 4), roe=num(i.get("returnOnEquity"), 4), cash=num(i.get("totalCash")), debt=num(i.get("totalDebt")),
        payout=num(i.get("payoutRatio"), 4), dy=num(i.get("dividendYield"), 2), beta=num(i.get("beta"), 2),
        street=dict(mean=num(i.get("targetMeanPrice"), 2), median=num(i.get("targetMedianPrice"), 2), high=num(i.get("targetHighPrice"), 2),
                    low=num(i.get("targetLowPrice"), 2), n=i.get("numberOfAnalystOpinions"), rec=i.get("recommendationKey"),
                    rec_zh=REC_ZH.get(i.get("recommendationKey") or "none", i.get("recommendationKey")), rec_mean=num(i.get("recommendationMean"), 2),
                    counts=rec, rev_dir=rdir, rev30=num(r30, 4), rev90=num(r90, 4)),
        next_earn=edates[0].isoformat() if edates else None, last_earn=last_earn.isoformat() if last_earn and last_earn <= pdate else None,
        chart=dict(d=[d.isoformat() for d, _ in ch], c=[round(c, 2) for _, c in ch]),
        sec=S, ndx_pe=ndx.get("pe"), app_val=vs or None,
    )


def base_sources(D):
    s, sec = D["sym"], D.get("sec") or {}
    out = [dict(id="S1", kind="data", title=f"Yahoo Finance：{s} 報價、公司資料、股價歷史（{D['price_date']} 收市）",
                url=f"https://finance.yahoo.com/quote/{s}/"),
           dict(id="S2", kind="data", title=f"Yahoo Finance：{s} 分析師盈利同收入預測、目標價、評級",
                url=f"https://finance.yahoo.com/quote/{s}/analysis/"),
           dict(id="S3", kind="data", title=f"SEC EDGAR：{sec.get('name') or s} 財務報表（XBRL）" if sec else "SEC EDGAR（今次攞唔到）",
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(sec['cik']):010d}&type=10-K" if sec.get("cik") else "https://www.sec.gov/edgar/search/"),
           dict(id="S4", kind="data", title="Nasdaq 100 市盈率（worldperatio.com，經本 app 估值頁）", url="https://worldperatio.com/index/nasdaq-100/")]
    return out


def facts_text(D):
    """俾 AI 睇嘅數據（每行標來源）。"""
    st, S = D["street"], D.get("sec") or {}
    L = [f"公司：{D['name']}（{D['sym']}，{D['exchange']}）；行業：{D['sector']}／{D['industry']}；國家：{D['country']}；員工 {D['employees']} [S1]",
         f"股價：{D['price']} {D['currency']}（{D['price_date']} 收市）；52 週 {D['lo52']}–{D['hi52']}、一年升跌 {pct(D['chg52'])}；市值 {money(D['mcap'])} [S1]",
         f"每股盈利（已按拆股調整）：過去 12 個月 {D['ttm_eps']} [S1]；分析師平均預測：本財年 {D['e0']}（{D['n0'] or '—'} 位，增長 {pct(D['g0'])}）、"
         f"下財年 {D['e1']}（{D['n1'] or '—'} 位，增長 {pct(D['g1'])}）；未來 12 個月約 {D['ntm_eps']}（{D['ntm_how']}）[S2]",
         f"收入預測：本財年 {money(D['rev0'])}（增長 {pct(D['rg0'])}）、下財年 {money(D['rev1'])}（增長 {pct(D['rg1'])}）[S2]",
         f"盈利預測變化（下財年 EPS）：30 日 {pct(st['rev30'])}、90 日 {pct(st['rev90'])} → {st['rev_dir']} [S2]",
         f"分析師目標價：平均 {st['mean']}、中位 {st['median']}、最高 {st['high']}、最低 {st['low']}（{st['n']} 位）；評級 {st['rec_zh']}"
         f"（1 = 強烈買入、5 = 強烈賣出：平均 {st['rec_mean']}）；分佈 {st['counts']} [S2]",
         f"利潤率：毛利率 {pc(D['gm'])}、經營利潤率 {pc(D['om'])}、淨利潤率 {pc(D['pm'])}；股本回報率 {pc(D['roe'])} [S1]",
         f"資產負債：現金同短期投資 {money(D['cash'])}、債務 {money(D['debt'])}；派息率 {pc(D['payout'])}、息率 {D['dy']}%；beta {D['beta']} [S1]",
         f"市盈率：過去 12 個月 {D['tpe']} 倍、未來 12 個月 {D['fpe']} 倍、PEG {D['peg']}、市銷率 {D['ps']} 倍 [S1][S2]；Nasdaq 100 市盈率 {D['ndx_pe']} 倍 [S4]"]
    ph = S.get("pe_hist")
    if ph:
        L.append(f"過去 5 年市盈率（過去 12 個月盈利計，每月）：中位數 {ph['med']}、最低 {ph['lo']}、最高 {ph['hi']}、而家 {ph['now']} [S1][S3]")
    if S.get("years"):
        L.append("財年數據（SEC 財報；每股數已按拆股調整）[S3]：")
        for y in S["years"]:
            L.append(f"  財年至 {y['end']}：收入 {money(y['rev'])}（增長 {pct(y.get('rev_g'))}）、毛利 {money(y['gp'])}、經營利潤 {money(y['op'])}、"
                     f"淨利潤 {money(y['ni'])}、攤薄 EPS {y['eps']}、自由現金流 {money(y['fcf'])}、股權獎勵 {money(y['sbc'])}、"
                     f"回購 {money(y['buyback'])}、派息 {money(y['div'])}、攤薄股數 {money(y['shares']).replace('億', '億股').replace('萬', '萬股') if y['shares'] else '—'}")
        t = S.get("ttm") or {}
        L.append(f"  過去 4 季（至 {t.get('end')}）：收入 {money(t.get('rev'))}、經營利潤 {money(t.get('op'))}、淨利潤 {money(t.get('ni'))}、"
                 f"自由現金流 {money(t.get('fcf'))}、股權獎勵 {money(t.get('sbc'))}、回購 {money(t.get('buyback'))} [S3]")
    L.append(f"下次業績（預計）：{D['next_earn'] or '未知'}；上次業績：{D['last_earn'] or '未知'} [S1]")
    L.append(f"公司簡介（Yahoo，英文）：{D['summary'][:900]} [S1]")
    return "\n".join(L)


def peer_rows(peers):
    import yfinance as yf
    rows = []
    for p in peers[:5]:
        try:
            i = yf.Ticker(p).info or {}
            px = i.get("currentPrice") or i.get("regularMarketPrice")
            if not px:
                continue
            rows.append(dict(sym=p, name=i.get("shortName") or p, price=num(px, 2), mcap=num(i.get("marketCap")), fpe=num(i.get("forwardPE"), 1),
                             peg=num(i.get("trailingPegRatio"), 2), rg=num(i.get("revenueGrowth"), 4), om=num(i.get("operatingMargins"), 4),
                             gm=num(i.get("grossMargins"), 4), chg52=num(i.get("52WeekChange"), 4)))
        except Exception as e:  # noqa: BLE001
            print(f"[research] 同業 {p} 攞唔到：{str(e)[:80]}")
        time.sleep(0.3)
    return rows


# ───────────────────────────────────────────── 2–3. AI 提示同固定格式
def _s(desc):
    return {"type": "string", "description": desc}


def _n(desc):
    return {"type": "number", "description": desc}


def _i(desc):
    return {"type": "integer", "description": desc}


def _e(vals, desc):
    return {"type": "string", "enum": list(vals), "description": desc}


def _a(item, desc):
    return {"type": "array", "items": item, "description": desc}


def _o(props, desc=None):
    d = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if desc:
        d["description"] = desc
    return d


SRC = _a({"type": "string"}, "引用嘅來源編號，例如 [\"S3\", \"S7\"]；只可以用來源清單入面有嘅編號")
DIAGRAM = _o(dict(type=_e(["none", "flow", "bars"], "none 冇圖；flow 流程（方格加箭咀）；bars 橫棒比較"),
                  title=_s("圖標題（冇圖就空）"), nodes=_a({"type": "string"}, "flow 用：2–6 個方格，每個 8 字內"),
                  bars=_a(_o(dict(label=_s("名"), value=_n("數值"))), "bars 用：2–6 條")), "簡單示意圖；真係有幫助先畫")
QA = _o(dict(q=_s("問題"), a=_s("第一行答案，40 字內"), detail=_s("深入少少，120 字內"),
             facts=_a(_o(dict(text=_s("一個事實，有數字或者年份"), src=SRC)), "事實 0–3 個"),
             myths=_a({"type": "string"}, "常見誤解 0–2 個"), diagram=DIAGRAM))
GROUP = _o(dict(key=_e([k for k, _ in GROUPS], "what 呢個係乜、why 點解係佢、how 零件點運作、now 現況、me 同我有乜關係（同持有呢隻股有乜關係）"),
                items=_a(QA, "1–3 條問答")))
PRIMER = _o(dict(title=_s("「先搞懂」主題，例如 先搞懂：AI 模型架構（Transformer、注意力、MoE）"), subtitle=_s("一句副題，例如 產業嘅大哉問"),
                 plain=_s("白話：點解要先搞懂呢樣嘢，40 字內"), groups=_a(GROUP, "5 組，次序 what、why、how、now、me")),
            "先搞懂：睇呢間公司之前要識嘅產業概念")
SCHEMA_A = _o(dict(
    name_zh=_s("公司通用中文名（例如 輝達、微軟）；冇通用中文名就寫英文名"),
    one_liner=_s("呢間公司做乜，一句白話，30 字內"),
    moat=_e(["寬", "窄", "無"], "經濟護城河：寬 = 好大機會 20 年以上保持超額回報；窄 = 10 年左右；無"),
    moat_why=_s("護城河嘅來源同證據，60 字內，句尾標來源例如 [S7]"),
    moat_trend=_e(["擴闊", "穩定", "收窄"], "護城河趨勢"),
    uncertainty=_e(["低", "中", "高", "非常高", "極高"], "公允價值嘅不確定性（將來盈利可能範圍有幾闊）"),
    uncertainty_why=_s("點解係呢個不確定性，60 字內，標來源"),
    capital=_e(["典範", "良好", "普通", "差"], "管理層資本配置（投資、收購、回購、派息、股權攤薄）"),
    capital_why=_s("資本配置評級理由，60 字內，標來源"),
    scores=_a(_o(dict(key=_e([k for k, _ in SCORES if k != "valuation"], "評分項目"), score=_i("0 最差 – 10 最好"),
                      why=_s("一兩句理由，要有具體數字，標來源"), src=SRC)),
              "評分卡：8 項各一個（估值吸引力由程式計，唔使寫）。moat 護城河強度、moat_trend 護城河趨勢、financial 財務健康、"
              "growth 成長性、management 管理層同資本配置、strategy 戰略前瞻、flywheel AI／數據飛輪（有冇用 AI 或數據令產品越用越好、"
              "成本越低；冇就低分）、certainty 確定性（10 = 盈利好容易預測）"),
    themes=_a(_o(dict(name=_s("題材，例如 AI 算力、資料中心，6 字內"), score=_i("同呢個題材嘅相關程度 0–10"), why=_s("一句理由"))),
              "投資題材 4–8 個，相關程度由高到低"),
    events=_a(_o(dict(date=_s("YYYY-MM-DD"), label=_s("股價圖上嘅標籤，8 字內"), detail=_s("發生乜事、對股價點影響，60 字內"), src=SRC)),
              "股價圖要標嘅重要事件 4–7 件（圖由提示講嘅開始日起），日期要準"),
    scenarios=_a(_o(dict(key=_e(["bear", "base", "bull"], "悲觀／基本／樂觀"), name=_s("情境名，10 字內，例如 客製化晶片主導"),
                         story=_s("呢個情境講緊乜，80 字內"), prob=_n("機率（0–1，三個加埋 = 1）"),
                         g1=_n("第 2–5 年每年每股盈利增長（小數，0.25 = 25%）"), g2=_n("第 6–10 年每年每股盈利增長（小數）"),
                         pe=_n("第 10 年嘅市盈率（倍）"), why=_s("假設嘅依據，標來源"), src=SRC)),
                 "三個情境（bear、base、bull 各一）。程式會用提示講嘅第 1 年 EPS 起計，你只俾假設，唔使自己計價值"),
    bull=_a(_o(dict(text=_s("看好理由一點，有數字，60 字內"), src=SRC)), "看好理由 3–5 點"),
    bear=_a(_o(dict(text=_s("看淡理由一點，有數字，60 字內"), src=SRC)), "看淡理由 3–5 點"),
    blind_spot=_o(dict(title=_s("本檔最大盲區，16 字內"), detail=_s("點解係盲區、要睇乜，80 字內"), src=SRC), "最多人忽略、但最影響結論嘅風險"),
    vs_street=_a(_o(dict(topic=_s("議題"), mine=_s("你嘅睇法，40 字內"), street=_s("華爾街共識（根據提示嘅分析師數據或者來源），40 字內"))),
                 "你同華爾街睇法唔同嘅地方 0–5 點（冇就空）"),
    peers=_a({"type": "string"}, "3–5 個最可比嘅美股代號（例如 AMD、AVGO）"),
    business=_o(dict(
        summary=_s("佢點賺錢，白話 2–3 句"),
        segments=_a(_o(dict(name=_s("業務分部"), share=_n("佔收入比例（0–1）"), note=_s("一句：增長、利潤率或者趨勢"), src=SRC)), "業務分部 2–5 個"),
        how=_a({"type": "string"}, "賺錢方式重點 2–4 點"),
        customers=_s("主要客戶同集中程度，60 字內，標來源")), "商業模式"),
    primer=PRIMER,
    glossary=_a(_o(dict(term=_s("名詞（要喺你嘅文字入面出現過）"), define=_s("白話解釋，50 字內"))), "名詞表 8–25 個"),
    next_check=_s("下次要睇嘅事件，例如 2027 財年第三季業績"),
))
SCHEMA_W = _o(dict(
    verdict_plain=_s("30 秒判讀（白話）：現價對公允價值、星級，加一句結論，70 字內；只用提示俾你嘅數字"),
    verdict_detail=_s("「看懂呢一節」：3–6 句解釋點樣得出呢個判讀"),
    conclusion=_a({"type": "string"}, "結論 1–3 段，每段 150 字內，要用提示嘅數字；最後一段講最要盯嘅一件事"),
    changes=_a(_o(dict(item=_s("同上次比較表入面嘅項目名（照抄）"), why=_s("點解變，40 字內"))), "同上次比較每行嘅原因；第一次研究就空"),
    valuation_plain=_s("估值白話：點計、關鍵假設、最大嘅不確定，120 字內"),
    direction_up=_a({"type": "string"}, "令公允價值向上修嘅 2–3 樣嘢"),
    direction_down=_a({"type": "string"}, "令公允價值向下修嘅 2–3 樣嘢"),
    holder_view=_s("已經持有嘅人點睇（唔好講具體倉位或者買賣指令），100 字內"),
    buyer_view=_s("未持有、考慮買嘅人點睇（唔好講具體倉位或者買賣指令），100 字內"),
    peers_note=_s("同業比較一段，100 字內，用提示嘅同業數字"),
))
SYS_A = ("你係一個嚴謹、獨立嘅股票研究員，做法似晨星：睇護城河、不確定性、資本配置，再用情境估值。" + STYLE +
         "只可以根據提供嘅數據同研究筆記寫；每個事實都要標來源編號（例如 [S3]），唔可以用來源清單以外嘅編號，唔可以作數字。"
         "唔肯定就講唔肯定。只回覆一個 JSON object。")
SYS_W = ("你係股票研究報告嘅編輯，將程式計好嘅數字寫成清楚、易明嘅中文。" + STYLE +
         "只可以用提示入面嘅數字，唔可以自己計新數字或者改數字。唔好用買賣指令或者具體倉位建議嘅語氣。只回覆一個 JSON object。")


def gather_prompt(D):
    return (f"研究對象：{D['name']}（{D['sym']}）。今日係 {datetime.now(HKT):%Y-%m-%d}（香港時間）。\n"
            f"下面係程式已經攞到嘅數據（唔使再搜呢啲）：\n{facts_text(D)}\n\n"
            f"請用網上搜尋補充以下資料（最多 {MAX_SEARCH} 次），每點寫具體數字同日期，同埋引用搜尋結果：\n"
            "1. 最近一季業績同管理層指引（收入、利潤率、下季指引），市場點反應。\n"
            f"2. {D['chart']['d'][0][:4]} 年至今令股價大升或者大跌嘅重要事件（每件寫日期）。\n"
            "3. 主要競爭對手同威脅（新技術、客戶自己研發、價格戰）。\n"
            "4. 管理層同資本配置：回購、派息、收購、股權攤薄、重大投資或者擔保。\n"
            "5. 主要風險：客戶集中、監管、出口管制、訴訟、供應鏈、會計。\n"
            "6. 最近 3 個月分析師評級或者目標價變化，同市場最大嘅爭論點。\n"
            "7. 理解呢間公司一定要識嘅一個產業概念（例如 AI 晶片公司：AI 模型架構點樣決定晶片需求），同相關事實。\n"
            f"筆記{STYLE}")


def sources_text(src):
    return "\n".join(f"[{s['id']}] {s['title']} — {s['url']}" for s in src)


def prev_text(old):
    if not old:
        return "（第一次研究呢隻股票）"
    v = old.get("valuation") or {}
    rt = old.get("ratings") or {}
    sc = "、".join(f"{x['name']} {x['score']}" for x in old.get("scores") or [])
    return (f"上次研究 {old.get('research_date')}：股價 {old.get('price')}、公允價值 {num(v.get('fv'), 2)}、{v.get('stars')} 星；"
            f"護城河 {rt.get('moat')}、不確定性 {rt.get('uncertainty')}、資本配置 {rt.get('capital')}；評分：{sc}。"
            f"上次情境：" + "；".join(f"{s.get('name')}（機率 {s.get('prob')}、增長 {s.get('g1')}／{s.get('g2')}、市盈率 {s.get('pe')}）"
                                    for s in v.get("scenarios") or []))


def analysis_prompt(D, notes, src, old):
    return (f"研究對象：{D['name']}（{D['sym']}）。今日 {datetime.now(HKT):%Y-%m-%d}。股價圖由 {D['chart']['d'][0]} 開始。\n\n"
            f"【程式數據】\n{facts_text(D)}\n\n【網上研究筆記】\n{notes or '（今次冇網上筆記）'}\n\n【來源清單】\n{sources_text(src)}\n\n"
            f"【上次報告】\n{prev_text(old)}\n\n"
            "【估值點計（程式做，你只俾假設）】\n"
            f"第 1 年每股盈利 = {D['ntm_eps']}（{D['ntm_how']}）；第 2–5 年每年增長 g1、第 6–10 年每年增長 g2；"
            f"第 10 年股價 = 第 10 年盈利 × 市盈率 pe；用 {R:.0%} 折現返今日（加埋派息率 {pc(D['payout'])} 嘅股息）。"
            "三個情境機率加埋要 = 1。大型成熟公司第 10 年市盈率一般 12–25 倍；第 6–10 年增長通常要慢落嚟。"
            "假設要同上面嘅歷史增長、分析師預測同研究筆記對得上；同分析師差好遠就要喺 why 講點解。\n"
            "評分要有理由同來源；題材、事件、先搞懂都要同呢間公司有關。")


def writing_prompt(D, A, V, cmp_rows, peers, old):
    st = D["street"]
    lines = [f"公司：{D['name']}（{D['sym']}），股價 {D['price']}（{D['price_date']} 收市）。"]
    if V.get("ok"):
        b = V["bands"]
        lines += [f"Claude 公允價值 {V['fv']:.2f}（三個情境今日價值按機率加權；折現率 {R:.0%}）；現價係公允價值嘅 {V['p_fv']:.0%}"
                  f"（{'低' if V['p_fv'] < 1 else '高'} {abs(1 - V['p_fv']):.0%}）→ {V['stars']} 星（不確定性 {A['uncertainty']}）。",
                  f"星級價：5 星 ≤ {b[0]['max']:.2f}、4 星 ≤ {b[1]['max']:.2f}、3 星 ≤ {b[2]['max']:.2f}、2 星 ≤ {b[3]['max']:.2f}、再高 = 1 星。",
                  f"第 1 年每股盈利 {V['eps0']:.2f}（{V['eps0_how']}）。"]
        for s in V["scenarios"]:
            lines.append(f"情境「{s['name']}」（{s['key']}，機率 {s['prob']:.0%}）：第 2–5 年增長 {s['g1']:.0%}、第 6–10 年 {s['g2']:.0%}、"
                         f"第 10 年市盈率 {s['pe']:.0f} 倍 → 第 10 年股價 {s['p10']:.2f}、今日價值 {s['today']:.2f}（對現價 {pct(s['vs_price'])}）。")
        lines.append(f"10 年後股價（機率加權）{V['p10w']:.2f}，係現價嘅 {V['x10w']:.1f} 倍，即係每年約 {V['cagr10']:.1%}（未計股息）。")
    else:
        lines.append(f"未能估值：{V.get('why')}。")
    lines.append(f"華爾街：目標價平均 {st['mean']}（{st['n']} 位，最低 {st['low']}、最高 {st['high']}）、評級 {st['rec_zh']}、"
                 f"盈利預測方向 {st['rev_dir']}（30 日 {pct(st['rev30'])}、90 日 {pct(st['rev90'])}）。")
    lines.append(f"評級：護城河 {A['moat']}（{A['moat_trend']}）、不確定性 {A['uncertainty']}、資本配置 {A['capital']}。")
    lines.append("評分：" + "、".join(f"{x['name']} {x['score']}" for x in A["scores"]))
    lines.append("看好：" + "；".join(x["text"] for x in A["bull"]))
    lines.append("看淡：" + "；".join(x["text"] for x in A["bear"]))
    lines.append(f"最大盲區：{A['blind_spot']['title']}：{A['blind_spot']['detail']}")
    if peers:
        lines.append("同業：" + "；".join(f"{p['sym']} 預期市盈率 {p['fpe']}、收入增長 {pc(p['rg'])}、經營利潤率 {pc(p['om'])}、一年 {pct(p['chg52'])}"
                                          for p in peers))
        lines.append(f"{D['sym']} 自己：預期市盈率 {D['fpe']}、收入增長（本財年預測）{pct(D['rg0'])}、經營利潤率 {pc(D['om'])}、一年 {pct(D['chg52'])}")
    if cmp_rows:
        lines.append(f"同上次（{old.get('research_date')}）比較表：" + "；".join(f"{r['item']}：{r['prev']} → {r['now']}" for r in cmp_rows))
    else:
        lines.append("第一次研究（changes 留空）。")
    return "【程式計好嘅數字同研究重點】\n" + "\n".join(lines)


# ───────────────────────────────────────────── 清理 AI 回覆（剔走假來源、數字收窄到合理範圍）
def _src(lst, valid):
    out = []
    for x in lst or []:
        m = re.search(r"(\d+)", str(x))
        k = f"S{m.group(1)}" if m else None
        if k in valid and k not in out:
            out.append(k)
    return out


def _cut(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def clean_analysis(A, src, D):
    valid = {s["id"] for s in src}
    fx = lambda lst: [dict(x, src=_src(x.get("src"), valid)) for x in lst or [] if isinstance(x, dict)]
    A = dict(A)
    for k in ("bull", "bear", "events"):
        A[k] = fx(A.get(k))[:7]
    raw, A["scores"] = A.get("scores"), []
    seen = set()
    for x in fx(raw if isinstance(raw, list) else []):
        if x.get("key") in dict(SCORES) and x["key"] not in seen and x["key"] != "valuation":
            seen.add(x["key"])
            A["scores"].append(dict(key=x["key"], name=dict(SCORES)[x["key"]], score=int(clip(round(num(x.get("score")) or 0), 0, 10)),
                                    why=_cut(x.get("why"), 200), src=x["src"]))
    A["themes"] = sorted([dict(name=_cut(x.get("name"), 12), score=int(clip(round(num(x.get("score")) or 0), 0, 10)), why=_cut(x.get("why"), 120))
                          for x in A.get("themes") or [] if isinstance(x, dict)], key=lambda x: -x["score"])[:8]
    c0 = date.fromisoformat(D["chart"]["d"][0])
    ev = []
    for x in A["events"]:
        try:
            d = date.fromisoformat(str(x.get("date"))[:10])
        except ValueError:
            continue
        if c0 <= d <= date.fromisoformat(D["price_date"]):
            ev.append(dict(date=d.isoformat(), label=_cut(x.get("label"), 16), detail=_cut(x.get("detail"), 140), src=x["src"]))
    A["events"] = sorted(ev, key=lambda x: x["date"])[:7]
    sc = []
    for x in fx(A.get("scenarios")):
        p, g1, g2, pe = num(x.get("prob")), num(x.get("g1")), num(x.get("g2")), num(x.get("pe"))
        if None in (p, g1, g2, pe):
            continue
        if g1 > 3 or g2 > 3:                             # 寫咗百分比（25）而唔係小數（0.25）
            g1, g2 = g1 / 100 if g1 > 3 else g1, g2 / 100 if g2 > 3 else g2
        sc.append(dict(key=x.get("key"), name=_cut(x.get("name"), 20), story=_cut(x.get("story"), 160), prob=clip(p, 0.02, 0.9),
                       g1=clip(g1, -0.30, 0.80), g2=clip(g2, -0.20, 0.40), pe=clip(pe, 5, 45), why=_cut(x.get("why"), 240), src=x["src"],
                       clipped=(g1, g2, pe) != (clip(g1, -0.30, 0.80), clip(g2, -0.20, 0.40), clip(pe, 5, 45))))
    tot = sum(x["prob"] for x in sc)
    for x in sc:
        x["prob"] = x["prob"] / tot if tot else 0
    A["scenarios"] = sc if len(sc) == 3 else []
    A["blind_spot"] = dict(A.get("blind_spot") or {}, src=_src((A.get("blind_spot") or {}).get("src"), valid))
    A["peers"] = [re.sub(r"[^A-Z0-9.\-]", "", str(p).upper()).replace(".", "-") for p in A.get("peers") or []]
    A["peers"] = [p for p in dict.fromkeys(A["peers"]) if p and p != D["sym"]][:5]
    b = A.get("business") or {}
    b["segments"] = [dict(x, share=clip(num(x.get("share")) or 0, 0, 1), src=_src(x.get("src"), valid)) for x in b.get("segments") or [] if isinstance(x, dict)][:6]
    A["business"] = b
    pr = A.get("primer") or {}
    order = [k for k, _ in GROUPS]
    gs = {}
    for g in pr.get("groups") or []:
        if isinstance(g, dict) and g.get("key") in order and g["key"] not in gs:
            items = []
            for it in (g.get("items") or [])[:3]:
                dg = it.get("diagram") or {}
                if dg.get("type") == "flow" and not (2 <= len(dg.get("nodes") or []) <= 8):
                    dg = dict(type="none")
                if dg.get("type") == "bars":
                    dg["bars"] = [dict(label=_cut(x.get("label"), 14), value=num(x.get("value")) or 0) for x in dg.get("bars") or [] if isinstance(x, dict)][:8]
                    if len(dg["bars"]) < 2:
                        dg = dict(type="none")
                items.append(dict(q=_cut(it.get("q"), 80), a=_cut(it.get("a"), 90), detail=_cut(it.get("detail"), 260),
                                  facts=[dict(text=_cut(f.get("text"), 160), src=_src(f.get("src"), valid)) for f in it.get("facts") or [] if isinstance(f, dict)][:4],
                                  myths=[_cut(m, 120) for m in it.get("myths") or []][:3], diagram=dg if dg.get("type") in ("flow", "bars") else None))
            gs[g["key"]] = items
    pr["groups"] = [dict(key=k, name=dict(GROUPS)[k], items=gs[k]) for k in order if gs.get(k)]
    A["primer"] = pr
    A["glossary"] = [dict(term=_cut(x.get("term"), 24), define=_cut(x.get("define"), 120)) for x in A.get("glossary") or [] if isinstance(x, dict) and x.get("term")][:30]
    A["vs_street"] = [x for x in A.get("vs_street") or [] if isinstance(x, dict)][:6]
    for k in ("moat", "moat_trend", "uncertainty", "capital"):
        A[k] = A.get(k) if A.get(k) in {"moat": ("寬", "窄", "無"), "moat_trend": ("擴闊", "穩定", "收窄"),
                                         "uncertainty": tuple(BANDS), "capital": ("典範", "良好", "普通", "差")}[k] else None
    return A


def clean_writing(W):
    W = dict(W or {})
    for k in ("verdict_plain", "verdict_detail", "valuation_plain", "holder_view", "buyer_view", "peers_note"):
        W[k] = _cut(W.get(k), 600)
    W["conclusion"] = [_cut(x, 500) for x in W.get("conclusion") or []][:4]
    for k in ("direction_up", "direction_down"):
        W[k] = [_cut(x, 160) for x in W.get(k) or []][:4]
    W["changes"] = [dict(item=_cut(x.get("item"), 30), why=_cut(x.get("why"), 120)) for x in W.get("changes") or [] if isinstance(x, dict)]
    return W


# ───────────────────────────────────────────── 4. 程式計估值
def valuation(D, A):
    if not A or not A.get("scenarios"):
        return dict(ok=False, why="未有 AI 情境假設")
    eps0, how = D["ntm_eps"], D["ntm_how"]
    if eps0 is not None and eps0 <= 0:                   # 2026-10-21 Codex 改卷：分析師預測虧損 ≠ 冇預測，唔可以跳去用過去 EPS
        return dict(ok=False, why=f"分析師預測未來 12 個月虧損（每股 {eps0:.2f}），用盈利計唔到公允價值")
    if not eps0:
        if D["ttm_eps"] and D["ttm_eps"] > 0:
            eps0, how = D["ttm_eps"], "過去 12 個月 EPS（冇分析師預測）"
        else:
            return dict(ok=False, why="未有正數嘅盈利或者盈利預測，用盈利計唔到公允價值")
    if not A.get("uncertainty"):
        return dict(ok=False, why="AI 冇俾不確定性評級")
    price, payout = D["price"], clip(D["payout"] or 0, 0, 0.9)
    rows = []
    for sc in sorted(A["scenarios"], key=lambda s: {"bear": 0, "base": 1, "bull": 2}.get(s["key"], 1)):
        e, pv, path = eps0, 0.0, []
        for t in range(1, 11):
            if t > 1:
                e *= 1 + (sc["g1"] if t <= 5 else sc["g2"])
            path.append(round(e, 3))
            pv += e * payout / (1 + R) ** t
        p10 = e * sc["pe"]
        pv += p10 / (1 + R) ** 10
        rows.append(dict(sc, eps=path, p10=round(p10, 2), today=round(pv, 2), vs_price=round(pv / price - 1, 4), x10=round(p10 / price, 3)))
    rows.sort(key=lambda r: r["today"])                    # 悲觀 → 樂觀（AI 標錯都照價值排）
    for r, k in zip(rows, ("bear", "base", "bull")):
        r["key"] = k
    fv = sum(r["prob"] * r["today"] for r in rows)
    p10w = sum(r["prob"] * r["p10"] for r in rows)
    b = BANDS[A["uncertainty"]]
    ratio = price / fv
    stars = 5 if ratio <= b[0] else 4 if ratio <= b[1] else 3 if ratio <= b[2] else 2 if ratio <= b[3] else 1
    return dict(ok=True, fv=round(fv, 2), p_fv=round(ratio, 4), stars=stars, uncertainty=A["uncertainty"],
                bands=[dict(stars=5 - k, max=round(fv * x, 2)) for k, x in enumerate(b)] + [dict(stars=1, max=None)],
                eps0=round(eps0, 3), eps0_how=how, payout=payout, discount=R, scenarios=rows, p10w=round(p10w, 2),
                x10w=round(p10w / price, 3), cagr10=round((p10w / price) ** 0.1 - 1, 4))


def val_score(V):
    if not V.get("ok"):
        return None
    r = V["p_fv"]
    return dict(key="valuation", name="估值吸引力", score=int(clip(round(10 - (r - 0.5) * 10), 0, 10)),
                why=f"現價係 Claude 公允價值嘅 {r:.0%}（{V['stars']} 星）；由程式按「現價 ÷ 公允價值」計，0.5 倍或以下 = 10 分、1.5 倍或以上 = 0 分", src=["S1"])


def checks(D, A, scores):
    """重倉條件（參考影片作者嘅做法；只係清單，唔係指令）：全部由程式按評級同財報判斷。"""
    sc = {x["key"]: x["score"] for x in scores}
    S = D.get("sec") or {}
    ys = [y for y in S.get("years") or [] if y.get("shares")]
    fcf = (S.get("ttm") or {}).get("fcf")
    dil = (ys[-1]["shares"] / ys[-4]["shares"]) ** (1 / 3) - 1 if len(ys) >= 4 else None
    self_funded = None if fcf is None else bool(fcf > 0 and (dil is None or dil < 0.02))
    return [dict(label="護城河寬", ok=A.get("moat") == "寬"),
            dict(label="護城河強度 ≥ 8", ok=sc.get("moat", 0) >= 8),
            dict(label="確定性 ≥ 7", ok=sc.get("certainty", 0) >= 7),
            dict(label="財務健康 ≥ 7", ok=sc.get("financial", 0) >= 7),
            dict(label="唔靠集資生存", ok=self_funded,
                 why=f"過去 4 季自由現金流 {money(fcf)}；攤薄股數 3 年每年 {pct(dil)}" if fcf is not None else "財報數據唔齊")]


def compare(old, D, V, A, scores):
    """同上次報告比較（程式比；原因由 AI 第三步寫）。"""
    if not old:
        return []
    ov, ort = old.get("valuation") or {}, old.get("ratings") or {}
    f2 = lambda x: "—" if x is None else f"{x:,.2f}"
    rows = [dict(item="股價", prev=f2(old.get("price")), now=f2(D["price"])),
            dict(item="Claude 公允價值", prev=f"{f2(ov.get('fv'))}（{ov.get('stars', '—')} 星）" if ov.get("ok") else "未能估值",
                 now=f"{f2(V.get('fv'))}（{V.get('stars', '—')} 星）" if V.get("ok") else "未能估值")]
    for k, n in (("moat", "護城河"), ("uncertainty", "不確定性"), ("capital", "資本配置")):
        if ort.get(k) != A.get(k):
            rows.append(dict(item=n, prev=ort.get(k) or "—", now=A.get(k) or "—"))
    osc = {x["key"]: x["score"] for x in old.get("scores") or []}
    for x in scores:
        if x["key"] in osc and osc[x["key"]] != x["score"]:
            rows.append(dict(item=x["name"], prev=str(osc[x["key"]]), now=str(x["score"])))
    return rows


# ───────────────────────────────────────────── 5. 組合同儲存
def load_report(sym):
    f = OUT / f"{sym}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:  # noqa: BLE001
        return None


def snap_events(D, events):
    d = D["chart"]["d"]
    out = []
    for e in events:
        k = min(range(len(d)), key=lambda j: abs(_days(d[j], e["date"])))
        out.append(dict(e, i=k))
    return out


def assemble(D, src, A, V, W, peers, cmp_rows, old, labels, cost, sample=False):
    scores = list(A["scores"]) if A else []
    vs = val_score(V)
    if vs:
        scores.insert(4 if len(scores) >= 4 else len(scores), vs)
    order = [k for k, _ in SCORES]
    scores.sort(key=lambda x: order.index(x["key"]))
    W = W or {}
    wmap = {x["item"]: x["why"] for x in W.get("changes") or []}
    for r in cmp_rows:
        r["why"] = wmap.get(r["item"], "")
    hist = list((old or {}).get("history") or [])
    now = datetime.now(HKT)
    rep = dict(
        v=1, sym=D["sym"], name=D["name"], name_zh=(A or {}).get("name_zh") or D["name"], one_liner=(A or {}).get("one_liner"),
        exchange=D["exchange"], currency=D["currency"], sector=D["sector"], industry=D["industry"], website=D["website"],
        price=D["price"], price_date=D["price_date"], research_date=now.strftime("%Y-%m-%d"), generated=now.strftime("%Y-%m-%d %H:%M HKT"),
        n=len(hist) + 1, prev_date=(old or {}).get("research_date"),
        next_check=dict(text=(A or {}).get("next_check"), date=D["next_earn"]),
        models=labels, cost_usd=round(cost, 3), sample=sample, dry=A is None,
        chart=dict(D["chart"], events=snap_events(D, (A or {}).get("events") or [])),
        ratings=dict(moat=(A or {}).get("moat"), moat_why=(A or {}).get("moat_why"), moat_trend=(A or {}).get("moat_trend"),
                     uncertainty=(A or {}).get("uncertainty"), uncertainty_why=(A or {}).get("uncertainty_why"),
                     capital=(A or {}).get("capital"), capital_why=(A or {}).get("capital_why")),
        street=D["street"], valuation=V, scores=scores, themes=(A or {}).get("themes") or [],
        bull=(A or {}).get("bull") or [], bear=(A or {}).get("bear") or [], blind_spot=(A or {}).get("blind_spot"),
        vs_street=(A or {}).get("vs_street") or [], business=(A or {}).get("business"), primer=(A or {}).get("primer"),
        glossary=(A or {}).get("glossary") or [], peers=peers,
        me=dict(sym=D["sym"], fpe=D["fpe"], rg=D["rg0"], om=D["om"], chg52=D["chg52"], mcap=D["mcap"]),
        key=dict(mcap=D["mcap"], ttm_eps=D["ttm_eps"], ntm_eps=D["ntm_eps"], tpe=D["tpe"], fpe=D["fpe"], peg=D["peg"], ps=D["ps"],
                 gm=D["gm"], om=D["om"], pm=D["pm"], roe=D["roe"], cash=D["cash"], debt=D["debt"], dy=D["dy"], beta=D["beta"],
                 hi52=D["hi52"], lo52=D["lo52"], chg52=D["chg52"], ndx_pe=D["ndx_pe"], e0=D["e0"], e1=D["e1"], g0=D["g0"], g1=D["g1"],
                 rev0=D["rev0"], rev1=D["rev1"], rg0=D["rg0"], rg1=D["rg1"]),
        app_val=D.get("app_val"),                         # 2026-10-21：同排名／持倉頁一樣嘅每日估值（Yahoo 預期市盈率、PEG → 偏平／偏貴）
        fin=(D.get("sec") or {}).get("years"), ttm=(D.get("sec") or {}).get("ttm"), pe_hist=(D.get("sec") or {}).get("pe_hist"),
        checks=checks(D, A or {}, scores) if A else [], writing=W, compare=dict(prev=(old or {}).get("research_date"), rows=cmp_rows),
        sources=src, disclaimer=DISCLAIMER,
    )
    rep["history"] = (hist + [dict(date=rep["research_date"], price=D["price"], fv=V.get("fv"), stars=V.get("stars"),
                                   moat=rep["ratings"]["moat"], uncertainty=rep["ratings"]["uncertainty"])])[-52:]
    return rep


def save(rep, old):
    OUT.mkdir(parents=True, exist_ok=True)
    if old and old.get("research_date") and not old.get("dry"):
        h = OUT / "hist" / rep["sym"]
        h.mkdir(parents=True, exist_ok=True)
        (h / f"{old['research_date']}.json").write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / f"{rep['sym']}.json").write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_index(add_cost=rep["cost_usd"])


def write_index(add_cost=0.0):
    f = OUT / "index.json"
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    items = []
    for p in sorted(OUT.glob("*.json")):
        if p.name in ("index.json", "ai_usage.json"):
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        v = r.get("valuation") or {}
        items.append(dict(sym=r["sym"], name=r.get("name"), name_zh=r.get("name_zh"), date=r.get("research_date"), price=r.get("price"),
                          price_date=r.get("price_date"), fv=v.get("fv"), p_fv=v.get("p_fv"), stars=v.get("stars"),
                          moat=(r.get("ratings") or {}).get("moat"), uncertainty=(r.get("ratings") or {}).get("uncertainty"),
                          one_liner=r.get("one_liner"), sample=r.get("sample"), dry=r.get("dry"), next_check=(r.get("next_check") or {}).get("date"),
                          model=(r.get("models") or {}).get("analysis")))
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    usage = dict(old.get("usage") or {})
    mon = datetime.now(HKT).strftime("%Y-%m")
    usage[mon] = round(usage.get(mon, 0) + add_cost, 3)
    f.write_text(json.dumps(dict(generated=datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT"), items=items, usage=usage,
                                 month_budget=MONTH_USD), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def month_spent():
    try:
        u = json.loads((OUT / "index.json").read_text(encoding="utf-8")).get("usage") or {}
        return float(u.get(datetime.now(HKT).strftime("%Y-%m"), 0))
    except Exception:  # noqa: BLE001
        return 0.0


# ───────────────────────────────────────────── 主流程
def _manual(dirp, name, prompt):
    """--manual：寫低提示；有回覆檔就讀返（測試提示、人手代入）。"""
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / f"prompt_{name}.txt").write_text(prompt, encoding="utf-8")
    return dirp


def build(sym, dry=False, manual=None, fresh=False):
    sym = sym.upper().strip().lstrip("$")
    # 2026-10-23 用戶：「成個app deepseek行先，然後gemini做後備」→ 研究同其他功能一樣跟 llm.py 次序（AI_PROVIDER + AI_FALLBACK）；
    # 之前係「有 Claude key 就 Claude 起頭」，而家 Claude 要設 AI_PROVIDER=claude 先用
    llm.ORDER = [p for p in llm._order() if llm.has_key(p)]
    t0, u0 = time.time(), len(llm.USAGE)
    old = None if fresh else load_report(sym)          # --fresh：當第一次研究（唔同上次比較、唔存舊檔）
    D = collect(sym)
    src = base_sources(D)
    labels, A, W, peers = {}, None, None, []
    if manual:
        md = Path(manual)
        _manual(md, "gather", gather_prompt(D))
        notes = (md / "notes.md").read_text(encoding="utf-8") if (md / "notes.md").exists() else ""
        ws = json.loads((md / "sources.json").read_text(encoding="utf-8")) if (md / "sources.json").exists() else []
        src += [dict(id=f"S{len(src) + k + 1}", kind="web", title=s["title"], url=s["url"], age=s.get("age")) for k, s in enumerate(ws)]
        labels["gather"] = "Claude Code（對話入面人手代入，樣本）"
        _manual(md, "analysis", SYS_A + "\n\n" + analysis_prompt(D, notes, src, old))
        if (md / "analysis.json").exists():
            A = clean_analysis(json.loads((md / "analysis.json").read_text(encoding="utf-8")), src, D)
            labels["analysis"] = labels["gather"]
    elif not dry:
        notes, ws, labels["gather"], n = llm.gather(gather_prompt(D), MAX_SEARCH, timeout=600, first=len(src) + 1)
        src += [dict(id=f"S{len(src) + k + 1}", kind="web", title=s["title"], url=s["url"], age=s.get("age")) for k, s in enumerate(ws)]
        print(f"[research] {sym} 搜尋 {n} 次、{len(ws)} 個來源（{labels['gather']}）")
        raw, labels["analysis"] = llm.ask(analysis_prompt(D, notes, src, old), schema=SCHEMA_A, system=SYS_A, timeout=900,
                                          max_tokens=MAX_TOKENS, kind="research-a")
        A = clean_analysis(raw, src, D)
    V = valuation(D, A) if A else dict(ok=False, why="未有 AI 分析（測試模式）")
    if A:
        peers = peer_rows(A["peers"])
    scores = list(A["scores"]) if A else []
    vs = val_score(V)
    cmp_rows = compare(old, D, V, A or {}, scores + ([vs] if vs else []))
    if A and manual:
        md = Path(manual)
        _manual(md, "writing", SYS_W + "\n\n" + writing_prompt(D, A, V, cmp_rows, peers, old))
        if (md / "writing.json").exists():
            W = clean_writing(json.loads((md / "writing.json").read_text(encoding="utf-8")))
            labels["writing"] = labels["gather"]
    elif A:
        raw, labels["writing"] = llm.ask(writing_prompt(D, A, V, cmp_rows, peers, old), schema=SCHEMA_W, system=SYS_W, timeout=600,
                                         max_tokens=MAX_TOKENS, kind="research-w")
        W = clean_writing(raw)
    cost = sum(u["usd"] for u in llm.USAGE[u0:])
    rep = assemble(D, src, A, V, W, peers, cmp_rows, old, labels, cost, sample=bool(manual))
    if manual and not (A and W):
        print(f"[research] {sym}：--manual 未齊回覆（{'analysis.json' if not A else 'writing.json'}），提示已寫入 {manual}；今次唔儲存")
        return None
    save(rep, old)
    v = rep["valuation"]
    print(f"[research] {sym} 完成（{time.time() - t0:.0f} 秒，約 US${cost:.2f}）：股價 {D['price']}、"
          + (f"公允價值 {v['fv']}（{v['stars']} 星，現價係 {v['p_fv']:.0%}）" if v.get("ok") else f"未能估值（{v.get('why')}）"))
    return rep


def auto_syms():
    """模型持倉（唔計 ETF）+ RS 排名頭 AUTO_TOP 隻（2026-10-22）。"""
    try:
        md = json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8"))
        sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    etf = {"TQQQ", "IEF", "TMF", "UGL", "SGOV", "BIL", "QQQ", "SPY", "QLD", "SQQQ", "GLD"}
    held = [p["sym"] for p in md.get("positions", []) if p["sym"] not in etf]
    return list(dict.fromkeys(held + [r["sym"] for r in (sc.get("ranking") or [])[:AUTO_TOP]]))


def due_list():
    idx = {}
    try:
        idx = {x["sym"]: x for x in json.loads((OUT / "index.json").read_text(encoding="utf-8")).get("items", [])}
    except Exception:  # noqa: BLE001
        pass
    want = auto_syms() + list(idx)
    if LIST.exists():
        for ln in LIST.read_text(encoding="utf-8").splitlines():
            want += [s.upper() for s in ln.split("#", 1)[0].split() if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", s)]
    out = []
    today = datetime.now(HKT).date()
    for s in dict.fromkeys(want):
        r = load_report(s)
        if not r or r.get("dry") or r.get("sample"):
            out.append((s, "冇正式報告"))
            continue
        age = (today - date.fromisoformat(r["research_date"])).days
        nxt = (r.get("next_check") or {}).get("date")
        if nxt and date.fromisoformat(nxt) < today and r["research_date"] <= nxt:
            out.append((s, f"業績（{nxt}）公佈咗"))
        elif age >= MAX_AGE:
            out.append((s, f"{age} 日未更新"))
    return out


def main(argv):
    dry, force, fresh = "--dry" in argv, "--force" in argv, "--fresh" in argv
    manual = argv[argv.index("--manual") + 1] if "--manual" in argv else None
    syms = [a for a in argv if not a.startswith("--") and a != manual]
    if "--due" in argv:
        todo = due_list()
        print(f"[research] 到期：{todo or '冇'}")
        syms = [s for s, _ in todo][:PER_RUN]
    if not syms:
        return 0
    if not (dry or manual):
        # 2026-10-22：預設唔再一定要 Claude（老師暫時唔用 Opus）；設 RESEARCH_REQUIRE_CLAUDE=1 就變返舊做法
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip() and os.environ.get("RESEARCH_REQUIRE_CLAUDE", "0") == "1":
            print("[research] 冇 ANTHROPIC_API_KEY：研究報告要用 Claude 起頭（RESEARCH_REQUIRE_CLAUDE=1），今次唔做")
            return 0 if "--due" in argv else 1
        if not any(llm.has_key(p) for p in ("claude", "deepseek", "gemini")):
            print("[research] 冇可以上網搜尋嘅 AI key（Claude、DeepSeek 或者 Gemini），今次唔做")
            return 0 if "--due" in argv else 1
    if "--due" in argv and not force and llm.PROVIDER in llm.PAID and llm.peak_now():
        print("[research] 而家係 DeepSeek 繁忙時段（香港平日 09–12、14–18 時），自動研究留返下次非繁忙先做（慳錢）")
        return 0                                         # 2026-10-23 用戶：「set死排程一定要非繁忙時段做」
    if not (dry or manual):
        llm.start(OUT.parent, "ai_usage_research.json")  # 讀今日用量同各流程收錢 AI 帳本（上限要跨流程計）
    bad, done = 0, 0
    for s in syms:
        # 2026-10-21 Codex 改卷：每份開始前都查上限（之前成批只查一次）；失敗嗰份已經用咗嘅錢都要記帳
        if not (dry or manual or force) and month_spent() + EST_USD > MONTH_USD:
            print(f"[research] 本月研究用量 US${month_spent():.2f} + 估計 US${EST_USD:g} 會超過上限 US${MONTH_USD:g}（RESEARCH_MONTH_USD），"
                  f"{s} 起唔做；--force 照做")
            return 1 if not done else 0
        u0 = len(llm.USAGE)
        try:
            build(s, dry=dry, manual=manual, fresh=fresh)
            done += 1
        except Exception as e:  # noqa: BLE001
            bad += 1
            lost = sum(u["usd"] for u in llm.USAGE[u0:])
            if lost > 0:
                write_index(add_cost=lost)
            print(f"[research] {s} 失敗（舊報告保留；已用約 US${lost:.2f} 照記帳）：{str(e)[:400]}")
    # 自動排程（--due）失敗唔當 workflow 失敗（免費 AI 額度間中爆，聽日再試，唔好日日寄失敗 email）；app 手動叫嘅照返 1
    if not (dry or manual):
        llm.finish(OUT.parent, "ai_usage_research.json")  # 研究嘅 AI 用量帳本（唔放 docs/research，嗰度淨係報告）
    return 1 if bad == len(syms) and "--due" not in argv else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
