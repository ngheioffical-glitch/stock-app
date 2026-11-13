# -*- coding: utf-8 -*-
"""2026-11-13 scanner/scan.py 行為測試（流程審計 S6：scan.py 之前冇自己嘅測試）。假數據、唔上網、唔改規則。
1. 細工具：swing（已確認 swing 點、向前填）、Wilder ATR、RSI、下一個交易日（週末、紐約假期）、clean（NaN／無限大 → null）。
2. 恐慌買入（fear_info）：VIX ≥ 30 第一日先算新一次（之前 20 個交易日冇先算）、20 日持有期邊界、β 最高 5 隻（收市 ≥ 5、成交額 ≥ 2,000 萬）、
   買入日／賣出日（未到嘅交易日要跳假期）、開市入貨價同回報。
3. 加密相關股（crypto_info）、TQQQ 腳黃燈提示（tq_yellow、tq_info）。
4. 行業（sectors）：Yahoo 查唔到用 Nasdaq；新鮮嘅 Yahoo 快取唔再查；快取有就唔用 Nasdaq 蓋。
5. 成個 scan()：假市場（200 隻股），手砌 4 隻知道答案嘅股：候選、收市高過前高唔追、唔合格、swing low 高過前高要用 20 日低位做止蝕；
   R、2R 保本位；RS 用連派息價；派息；最近 9 日 plans；數據唔齊（排名 < 40 或股票 < 200）唔寫檔；舊日期唔覆蓋新檔。
用法：python tests/test_scan.py"""
import json
import math
import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import scan as S  # noqa: E402
from sector_names import zh  # noqa: E402

OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "scan" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


near = lambda a, b, tol=1e-9: a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))
same = lambda a, b: all((math.isnan(x) and math.isnan(y)) or near(x, y) for x, y in zip(a, b)) and len(a) == len(b)


# ------------------------------------------------------------ 獨立手計（唔用 scan.py 嘅 code）
def swing_or(v, n=3, high=True):
    out, cur = [], math.nan
    for j in range(len(v)):
        i = j - n
        if i - n >= 0:
            w = v[i - n:i + n + 1]
            if v[i] == (max(w) if high else min(w)):
                cur = v[i]
        out.append(cur)
    return out


def atr_or(h, lo, c, n=14):
    out, a = [math.nan], None
    for k in range(1, len(c)):
        tr = max(h[k] - lo[k], abs(h[k] - c[k - 1]), abs(lo[k] - c[k - 1]))
        a = tr if a is None else a + (tr - a) / n
        out.append(a)
    return out


def rsi_or(c, n=14):
    out, up, dn = [math.nan], None, None
    for k in range(1, len(c)):
        d = c[k] - c[k - 1]
        u, w = max(d, 0.0), max(-d, 0.0)
        up = u if up is None else up + (u - up) / n
        dn = w if dn is None else dn + (w - dn) / n
        out.append(math.nan if k < n else (100.0 if dn == 0 else 100 - 100 / (1 + up / dn)))
    return out


# ============================================================ 1. 細工具
v = [1.0, 2.0, 3.0, 5.0, 3.0, 2.0, 1.0, 2.0, 3.0, 4.0, 6.0, 4.0, 3.0, 2.0, 2.5]
sh, sl = S.swing(pd.Series(v), 3, True).tolist(), S.swing(pd.Series(v), 3, False).tolist()
check(same(sh, swing_or(v, 3, True)) and same(sl, swing_or(v, 3, False)), "swing：同手計一樣（高位、低位）")
check(math.isnan(sh[5]) and sh[6] == 5.0 and sh[12] == 5.0 and sh[13] == 6.0,
      "swing 高位 5（第 3 日）要到第 6 日先確認，之前冇；6（第 10 日）第 13 日先確認，之前沿用 5")
check(sl[9] == 1.0 and math.isnan(sl[8]), "swing 低位 1（第 6 日）第 9 日先確認")
df = S.swing(pd.DataFrame({"a": v, "b": v[::-1]}), 3, True)
check(same(df["a"].tolist(), swing_or(v)) and same(df["b"].tolist(), swing_or(v[::-1])), "swing：DataFrame 逐欄計")

c3, h3, l3 = [10.0, 11.0, 9.0], [10.5, 11.5, 10.0], [9.5, 10.5, 8.0]
a3 = S.wilder_atr(pd.Series(h3), pd.Series(l3), pd.Series(c3)).tolist()
check(math.isnan(a3[0]) and near(a3[1], 1.5) and near(a3[2], 1.5 + (3.0 - 1.5) / 14),
      "Wilder ATR：第 2 日真實波幅 1.5（高位減上日收市）；第 3 日 3（上日收市減低位）→ 1.5 + (3 − 1.5) ÷ 14")
rng = np.random.default_rng(3)
cr = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 80))))
hr, lr = [x * 1.012 for x in cr], [x * 0.985 for x in cr]
check(same(S.wilder_atr(pd.Series(hr), pd.Series(lr), pd.Series(cr)).tolist(), atr_or(hr, lr, cr)), "Wilder ATR：亂數 80 日同手計一樣")
check(same(S.rsi14(pd.Series(cr)).tolist(), rsi_or(cr)), "RSI 14：頭 13 日冇數，之後同手計一樣")
check(S.rsi14(pd.Series([float(x) for x in range(1, 30)])).iloc[-1] == 100.0, "RSI：日日升 = 100")

for d, want, what in (("2026-11-13", "2026-11-16", "星期五 → 星期一"), ("2026-11-14", "2026-11-16", "星期六 → 星期一"),
                      ("2026-11-25", "2026-11-27", "感恩節前一日 → 跳過 11-26 假期"), ("2026-07-02", "2026-07-06", "7-03 假期加週末"),
                      ("2026-11-10", "2026-11-11", "平日 → 下一日（退伍軍人節美股照開）"), ("2026-12-24", "2026-12-28", "聖誕節加週末")):
    check(str(S.next_trading_day(d).date()) == want, f"下一個交易日：{d} {what} = {want}")

dirty = {"a": [1.0, float("nan"), "x", float("inf"), -float("inf"), 2, None, {"b": np.float64("nan")}], "c": True, "d": np.float64(1.5)}
check(S.clean(dirty) == {"a": [1.0, None, "x", None, None, 2, None, {"b": None}], "c": True, "d": 1.5}, "clean：NaN、無限大 → null；字串、整數、True 照留")

# ============================================================ 2. 恐慌買入（fear_info）
FI = pd.bdate_range(end="2026-11-24", periods=80)       # 最後一日星期二；下一個交易日 11-25
NF = 79
qr = np.random.default_rng(11).normal(0, 0.01, 80)
qr[0] = 0.0
QC = np.cumsum(qr)
BET = {"B05": 0.5, "B10": 1.0, "B15": 1.5, "B20": 2.0, "B25": 2.5, "B30": 3.0, "B35": 3.5, "B40": 4.0, "EDGEA": 4.2}
NXT = S.next_trading_day(FI[-1])


def fear_case(vix_days, at, has_vix=True):
    """vix_days：VIX 收市 31 嘅日子（其餘 15）；at：EDGE 呢日收市啱啱 5.00（β 4.5）。CHEAP 永遠 < 5（β 6）、THIN 成交額 1,999.9999 萬（β 5）。"""
    C = pd.DataFrame({s: 100 * np.exp(b * QC) for s, b in BET.items()}, index=FI)
    C["EDGE"] = 5.0 * np.exp(4.5 * (QC - QC[at]))
    C["CHEAP"] = 4.0 * np.exp(6.0 * (QC - QC.max()))
    C["THIN"] = 100 * np.exp(5.0 * QC)
    adv = pd.DataFrame(50e6, index=FI, columns=C.columns)
    adv["THIN"] = 20e6 - 1
    adv["EDGEA"] = 20e6
    vix = pd.Series(15.0, index=FI)
    vix.iloc[list(vix_days)] = 31.0
    O = C.shift(1).fillna(C) * 1.003
    px = {"QQQ": pd.Series(400 * np.exp(QC), index=FI), "_O": O}
    if has_vix:
        px["^VIX"] = vix
    return S.fear_info(C, adv, px, NXT), C, O


TOP5 = ["EDGE", "EDGEA", "B40", "B35", "B30"]
f, C, O = fear_case([62, 66], 62)
check(f["active"] and f["trigger"] == str(FI[62].date()) and f["history"] == [str(FI[62].date())] and f["trigger_vix"] == 31.0,
      "VIX 第 62 日 ≥ 30（66 日再 ≥ 30 唔算新一次）：訊號生效")
check(f["buy_date"] == str(FI[63].date()) and f["sell_date"] == "2026-12-01" and f["days_held"] == 17,
      "買入日 = 訊號後一日；第 21 日賣（數據後 4 日：11-25、跳感恩節 11-27、11-30、12-01）")
check([p["sym"] for p in f["picks"]] == TOP5 and [p["beta"] for p in f["picks"]] == [4.5, 4.2, 4.0, 3.5, 3.0],
      "揀 β 最高 5 隻：收市啱啱 5.00、成交額啱啱 2,000 萬都入選；CHEAP（< 5）、THIN（成交額唔夠）唔揀")
p0 = f["picks"][2]
e0 = float(O["B40"].iloc[63])
check(p0["entry"] == round(e0, 4) and p0["signal_close"] == round(float(C["B40"].iloc[62]), 4)
      and p0["ret"] == round(float(C["B40"].iloc[-1]) / e0 - 1, 4) and p0["close"] == round(float(C["B40"].iloc[-1]), 4),
      "入貨價 = 買入日開市；回報 = 最新收市 ÷ 入貨價 − 1")
check(f["fraction"] == 0.4 and f["hold"] == 20 and f["vix"] == 15.0 and f["date"] == "2026-11-24", "40% 資金、揸 20 日；最新 VIX 15")
f, *_ = fear_case([10, 15, 35], NF)
check(f["history"] == [str(FI[10].date())] and not f["active"], "VIX 10、15、35 日 ≥ 30：35 − 15 = 20 日，唔算新一次")
check([p["sym"] for p in f["preview"]] == TOP5 and f["preview"][0]["beta"] == 4.5 and "picks" not in f, "冇生效：列出今日 β 最高 5 隻（預覽）")
f, *_ = fear_case([10, 15, 36], NF)
check(f["history"] == [str(FI[10].date()), str(FI[36].date())] and not f["active"], "VIX 10、15、36 日：36 − 15 = 21 日 > 20 → 新一次；已經過咗 20 日")
f, *_ = fear_case([60], 60)
check(f["active"] and f["days_held"] == 19 and f["sell_date"] == "2026-11-27", "訊號後第 19 日：仲揸（賣出日 = 下一個交易日之後一日，跳感恩節）")
f, *_ = fear_case([59], NF)
check(not f["active"] and "preview" in f, "訊號後第 20 日收市：持有期完（唔再生效）")
f, *_ = fear_case([NF], NF)
check(f["active"] and f["buy_date"] == "2026-11-25" and all(p["entry"] is None and p["ret"] is None for p in f["picks"])
      and f["sell_date"] == "2026-12-24" and f["days_held"] == 0, "今日先觸發：聽日開市買（未有入貨價），第 21 個交易日賣 = 11-25 之後再數 20 個交易日 12-24")
f, *_ = fear_case([], NF)
check(not f["active"] and f["history"] == [] and len(f["preview"]) == 5, "VIX 一直 < 30：冇訊號，只有預覽")
check(fear_case([62], 62, has_vix=False)[0] is None, "冇 VIX 數據：唔計")

# ============================================================ 3. 加密相關股、TQQQ 提示
CI = pd.bdate_range(end="2026-11-24", periods=150)
rng = np.random.default_rng(5)


def btc_series(days):
    br = rng.normal(0, 0.03, days)
    br[0] = 0.0
    return pd.Series(30000 * np.exp(np.cumsum(br)), index=pd.date_range(end="2026-11-24", periods=days, freq="D"))


btc = btc_series(400)
bc = np.log(btc.reindex(CI).ffill()).diff().fillna(0.0).values
Cc = pd.DataFrame({"MSTR": 50 * np.exp(np.cumsum(bc)), "NEG": 50 * np.exp(-np.cumsum(bc)), "XTRA": 40 * np.exp(np.cumsum(bc)),
                   "INDEP": 50 * np.exp(np.cumsum(rng.normal(0, 0.02, 150)))}, index=CI)
advc = pd.DataFrame(30e6, index=CI, columns=Cc.columns)
advc.loc[CI[-1], "XTRA"] = np.nan
ci = S.crypto_info(Cc, advc, {"BTC-USD": btc})
check(ci["corr"] == {"MSTR": 1.0} and ci["btc"] == round(float(btc.iloc[-1]), 2) and ci["date"] == "2026-11-24",
      "加密相關：同 BTC 一齊郁 = 1.0；反方向、冇關係嘅唔列；今日冇成交額嘅唔列")
check(S.crypto_info(Cc, advc, {"BTC-USD": btc}, extra=["XTRA", "NOPE"])["corr"] == {"MSTR": 1.0, "XTRA": 1.0}, "加密相關：持倉（extra）照計")
ma = float(btc.iloc[-365:].mean())
check(ci["ma365"] == round(ma, 2) and ci["green"] == bool(btc.iloc[-1] > ma), "BTC 燈號：收市 vs 365 日線")
short = S.crypto_info(Cc, advc, {"BTC-USD": btc.iloc[-300:]})
check(short["ma365"] is None and short["green"] is None, "BTC 唔夠 365 日：冇燈號（唔估）")
check(S.crypto_info(Cc, advc, {}) is None, "冇 BTC 數據：唔計")

one = lambda x: pd.Series([float(x)])
y = S.tq_yellow(one(110), one(105), one(100), one(120))
check(y == dict(margin=round(110 / 105 - 1, 4), gap21=round(110 / 105 - 1, 4), gap50=0.1),
      "黃燈：NDX 110 < 200 日線 120，但 > 21 日 EMA 105 > 50 日線 100 → 綠燈，再跌 4.76% 轉紅")
y = S.tq_yellow(one(118), one(121), one(119), one(120))
check(y["margin"] == round(max(118 / 120 - 1, min(118 / 121 - 1, 121 / 119 - 1)), 4) and y["margin"] < 0, "黃燈：NDX 低過 200 日線同 21 日 EMA → 紅燈（負數）")
TI = pd.bdate_range(end="2026-11-24", periods=60)
qa = np.r_[np.tile([0.004, -0.004], 25), np.tile([0.045, -0.045], 5)]
q = pd.Series(400 * np.cumprod(1 + qa), index=TI)
ndx = pd.Series(np.linspace(15000, 16000, 60), index=TI)
e21, s50, s200 = ndx - 100, ndx - 200, ndx - 300
tq = S.tq_info({"QQQ": q, "TQQQ": q / 8}, ndx, e21, s50, s200, TI[-10:])
vol = q.pct_change().rolling(20).std() * np.sqrt(252)
check(tq["vol10"] == [round(float(x), 4) for x in vol.iloc[-10:]] and tq["on10"] == [bool(x < 0.35) for x in vol.iloc[-10:]]
      and True in tq["on10"] and False in tq["on10"], "TQQQ 腳：綠燈 + QQQ 20 日波幅 < 35% 先揸（大上大落嗰幾日唔揸）")
check(S.tq_info({"QQQ": q}, ndx, e21, s50, s200, TI[-10:]) is None, "冇 TQQQ 數據：唔計")

# ============================================================ 4. 行業（sectors）
had_yf = sys.modules.get("yfinance")
asked = []


class FakeTicker:
    def __init__(self, s):
        self.s = s

    @property
    def info(self):
        asked.append(self.s)
        if self.s == "BOOM":
            raise RuntimeError("Yahoo 出錯")
        return {"sector": "Technology", "industry": "Semiconductors"} if self.s == "YHO" else {}


sys.modules["yfinance"] = types.SimpleNamespace(Ticker=FakeTicker)
S.SECT = OUT / "sectors.json"
today = str(pd.Timestamp.now().normalize().date())
S.SECT.write_text(json.dumps({"FRESH": dict(sector="Energy", industry="Solar", src="yahoo", date=today),
                              "STALE": dict(sector="Utilities", industry="Solar", src="yahoo", date="2020-01-01"),
                              "NASOLD": dict(sector="Finance", industry="Capital Markets", src="nasdaq", date=today)}), encoding="utf-8")
sec = S.sectors(["FRESH", "STALE", "YHO", "NOINFO", "BOOM", "NASOLD", "NONE"],
                {"NOINFO": ("Technology", "Software - Application"), "BOOM": ("Health Care", "Biotechnology"), "NASOLD": ("X", "Y")})
cache = json.loads(S.SECT.read_text(encoding="utf-8"))
check(sorted(asked) == ["BOOM", "NASOLD", "NOINFO", "NONE", "STALE", "YHO"], "行業：新鮮 Yahoo 快取唔再查；舊過 180 日或者 Nasdaq 嚟嘅要再查")
check(cache["YHO"]["src"] == "yahoo" and sec["YHO"] == zh("Technology", "Semiconductors"), "Yahoo 查到：用 Yahoo（存入快取）")
check(cache["NOINFO"]["src"] == "nasdaq" and sec["NOINFO"] == zh("Technology", "Software - Application")
      and cache["BOOM"]["src"] == "nasdaq" and sec["BOOM"] == zh("Health Care", "Biotechnology"), "Yahoo 冇／出錯：用 Nasdaq 分類")
check(cache["NASOLD"]["industry"] == "Capital Markets" and cache["STALE"]["date"] == "2020-01-01" and sec["FRESH"] == zh("Energy", "Solar"),
      "Yahoo 再查唔到：快取有嘅照用，唔會俾 Nasdaq 蓋")
check(sec["NONE"] == ("", ""), "邊度都冇：空白")
if had_yf is None:
    del sys.modules["yfinance"]
else:
    sys.modules["yfinance"] = had_yf

# ============================================================ 5. 成個 scan()
N = 262
LL = N - 1
IDX = pd.bdate_range(end="2026-11-12", periods=N)        # 最後一日星期四


def kn(xs, ys):
    return np.interp(np.arange(N), xs, ys)


ii = np.arange(N, dtype=float)
fall = 50 + 0.2 * ii - np.maximum(0, 3 - 0.5 * np.abs(ii - (LL - 45)))   # 第 210 日 swing 高 93；第 216 日 swing 低
fall[LL - 30] -= 1.5                                                    # 第 231 日單日急跌：swing low 93.7 高過前高 93
HAND = {"CAND": kn([0, LL - 60, LL - 40, LL - 30, LL], [50, 100, 110, 104, 109]),    # 前高 111（H），swing low 103（L），收市 109
        "BRKO": kn([0, LL - 60, LL - 40, LL - 30, LL], [50, 100, 110, 104, 112]),    # 收市 112 高過前高 111
        "WEAK": kn([0, LL], [100, 60]),                                              # 一路跌：低過 200 日線
        "FALL": fall}
rng = np.random.default_rng(20261113)
GEN = {f"G{k:03d}": 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, N))) for k in range(196)}
MKT = dict(NDX=15000 * np.exp(np.linspace(0, 0.25, N) + rng.normal(0, 0.002, N)), IEF=95 * np.exp(np.linspace(0, 0.02, N)),
           IRX=np.full(N, 4.5), QQQ=400 * np.exp(np.linspace(0, 0.25, N)), VIX=np.full(N, 15.0), BTC=60000 * np.exp(np.cumsum(rng.normal(0, 0.03, N))),
           TQQQ=50 * np.exp(np.linspace(0, 0.7, N)))
CASH = {"^NDX": MKT["NDX"], "IEF": MKT["IEF"], "^IRX": MKT["IRX"], "QQQ": MKT["QQQ"], "^VIX": MKT["VIX"], "BTC-USD": MKT["BTC"], "TQQQ": MKT["TQQQ"]}


def market(drop=(), low=()):
    """手砌股（成交大）+ G000–G035 成交大（入股票池）+ 其餘成交細。low：改做成交細；drop：成隻冇咗。"""
    px = {k: v for k, v in {**HAND, **GEN}.items() if k not in drop}
    big = set(HAND) | {f"G{k:03d}" for k in range(36)}
    C = pd.DataFrame({**px, **CASH}, index=IDX)
    H = pd.DataFrame({k: (v + 1 if k in HAND else v * 1.01) for k, v in px.items()} | CASH, index=IDX)
    Lo = pd.DataFrame({k: (v - 1 if k in HAND else v * 0.99) for k, v in px.items()} | CASH, index=IDX)
    O = C.shift(1).fillna(C)
    AC = C.copy()
    if "G000" in AC:
        AC["G000"] = C["G000"] * np.linspace(0.9, 1.0, N)                   # 連派息調整（RS 用呢個）
    V = pd.DataFrame({k: (5e6 if k in HAND else 1e6 if k in big and k not in low else 1e4) for k in px} | {k: 1e6 for k in CASH}, index=IDX)
    DV = pd.DataFrame(0.0, index=IDX, columns=["CAND", "WEAK"])
    DV.loc[IDX[-3], "CAND"] = 0.25
    return {"Open": O, "High": H, "Low": Lo, "Close": C, "Adj Close": AC, "Volume": V, "Dividends": DV}


ORIG = dict(nasdaq_universe=S.nasdaq_universe, download=S.download, sectors=S.sectors, must_have=S.must_have)
S.OUT = OUT / "scan.json"
S.must_have = lambda: set()
S.sectors = lambda syms, info: {s: ("科技", "半導體") for s in syms}


def run_scan(**kw):
    D = market(**kw)
    syms = [s for s in D["Close"].columns if s not in CASH]
    S.nasdaq_universe = lambda: (list(syms), {})
    S.download = lambda syms_, end=None: {k: v.copy() for k, v in D.items()}
    return S.scan()


run_scan()
J = json.loads(S.OUT.read_text(encoding="utf-8"))
rk = {r["sym"]: r for r in J["ranking"]}
st = J["stocks"]
check(J["date"] == "2026-11-12" and J["next_day"] == "2026-11-13" and J["week_end"] is False and J["days"] == [str(d.date()) for d in IDX[-10:]]
      and J["days_we"] == [True, False, False, False, False, True, False, False, False, False],
      "日期：最後一日星期四，下一個交易日星期五（唔係週尾）；最近 10 日入面兩個星期五係週尾")
check(len(J["ranking"]) == 40 and len(st) == 200 and J["universe_checked"] == 200, "邊界：啱啱 40 隻排名、200 隻股：照寫檔")
rs_list = [r["rs"] for r in J["ranking"]]
check([r["rank"] for r in J["ranking"]] == list(range(1, 41)) and rs_list == sorted(rs_list, reverse=True) and J["rank1"] == J["ranking"][0]["sym"],
      "排名跟 RS 由高到低，第 1 名 = rank1")
check(st["CAND"]["in_pool"] and not st["G100"]["in_pool"] and st["G100"]["rank"] is None, "成交額唔夠 2,000 萬（G100）：唔入股票池、冇排名，但照有價（模型帳戶用）")


def rs_or(ac):
    q = lambda a, b: ac[LL - a] / ac[LL - b] - 1
    return 0.4 * q(0, 63) + 0.2 * q(63, 126) + 0.2 * q(126, 189) + 0.2 * q(189, 252)


ac0 = GEN["G000"] * np.linspace(0.9, 1.0, N)
check(near(rk["CAND"]["rs"], round(rs_or(HAND["CAND"]), 4)) and near(rk["G000"]["rs"], round(rs_or(ac0), 4)),
      "RS = 0.4 × 近 3 個月 + 0.2 × 之前每 3 個月回報，用連派息價（G000 Close 同 Adj Close 唔同，跟 Adj Close）")
c = HAND["CAND"]
a = atr_or(c + 1, c - 1, c)[-1]
r = rk["CAND"]
check(near(a, 2.0) and r["pivot"] == 111.0 and st["CAND"]["swing_low"] == 103.0 and r["stop"] == 102.6 and r["R"] == 8.4 and r["be_trigger"] == 127.8,
      "候選股 CAND：前高 111、swing low 103、ATR 2 → 止蝕 103 − 0.2 × 2 = 102.6，R = 8.4，2R 保本位 111 + 16.8 = 127.8")
check(r["status"] == "候選" and r["c1"] and r["c2"] and r["c3"] and r["hi52"] == 111.0 and r["sector"] == "科技" and r["industry"] == "半導體"
      and near(r["sma200"], round(float(np.mean(c[-200:])), 4), 1e-6) and near(r["sma50"], round(float(np.mean(c[-50:])), 4), 1e-6),
      "CAND：收市 109 > 200 日線、50 > 200 日線、≥ 52 週高 × 0.75，收市未過前高 → 候選")
check(st["CAND"]["c10"] == [round(float(x), 4) for x in c[-10:]] and st["CAND"]["l10"] == [round(float(x) - 1, 4) for x in c[-10:]]
      and st["CAND"]["h10"] == [round(float(x) + 1, 4) for x in c[-10:]] and st["CAND"]["o10"] == [round(float(x), 4) for x in c[-11:-1]]
      and st["CAND"]["rsi"] == round(rsi_or(list(c))[-1], 1) and st["CAND"]["atr"] == 2.0, "CAND：最近 10 日開高低收、RSI、ATR")
check(rk["BRKO"]["status"] == "收市高過前高，唔追" and rk["BRKO"]["stop"] == 102.6 and rk["BRKO"]["close"] == 112.0, "BRKO 收市 112 ≥ 前高 111：唔追")
w = HAND["WEAK"]
check(rk["WEAK"]["status"] == "唔合格" and not rk["WEAK"]["c1"] and rk["WEAK"]["pivot"] is None and rk["WEAK"]["R"] is None
      and rk["WEAK"]["stop"] == round(float(w[-1]) - 1 - 0.4, 4), "WEAK 一路跌：唔合格；冇 swing 點 → 止蝕用 20 日低位 − 0.2 × ATR，冇前高就冇 R")
fa = atr_or(fall + 1, fall - 1, fall)
check(st["FALL"]["swing_low"] == 93.7 and rk["FALL"]["pivot"] == 93.0 and rk["FALL"]["stop"] == round(float(fall[LL - 19]) - 1 - 0.2 * fa[-1], 4),
      f"FALL：swing low 93.7 − 0.2 × ATR 仍然 ≥ 前高 93 → 止蝕改用 20 日低位 97.4 − 0.2 × ATR（{rk['FALL']['stop']}）")
check(J["candidates"] == [r["sym"] for r in J["ranking"] if r["status"] == "候選"] and "CAND" in J["candidates"]
      and not {"BRKO", "WEAK", "FALL"} & set(J["candidates"]), "候選名單 = 狀態「候選」嘅股")
check(st["CAND"]["div10"] == [0.0] * 7 + [0.25, 0.0, 0.0] and "div10" not in st["WEAK"] and "div10" not in st["BRKO"],
      "派息：最近 10 日有派息先寫 div10（全部 0 唔寫、冇派息數據唔寫）")
P = J["plans"]
check(list(P) == [str(d.date()) for d in IDX[-10:-1]], "plans：最近 10 日（最後一日除外）每日一份")
p = P[str(IDX[-2].date())]
pr = {x["sym"]: x for x in p["ranking"]}
check(pr["CAND"]["stop"] == 102.6 and pr["CAND"]["pivot"] == 111.0 and pr["CAND"]["status"] == "候選"
      and pr["FALL"]["stop"] == round(float(fall[LL - 20]) - 1 - 0.2 * fa[-2], 4) and pr["WEAK"]["status"] == "唔合格",
      "plans 前一日：CAND 止蝕 102.6；FALL 用嗰日嘅 20 日低位；WEAK 唔合格")
check(p["next_day"] == "2026-11-12" and p["week_end"] is False and p["green"] and p["rank1"] == p["ranking"][0]["sym"]
      and P[str(IDX[-5].date())]["week_end"] is True and P[str(IDX[-5].date())]["next_day"] == "2026-11-09" and p["stocks"]["CAND"]["close"] == round(float(c[-2]), 4), "plans：下一日、週尾、大市燈號")
check(J["green"] and J["ndx"] == round(float(MKT["NDX"][-1]), 2) and J["cash"]["green10"] == [True] * 10
      and J["cash"]["ief10"] == [round(float(x), 4) for x in MKT["IEF"][-10:]] and J["cash"]["irx10"] == [4.5] * 10
      and J["bench"]["qqq10"] == [round(float(x), 4) for x in MKT["QQQ"][-10:]], "大市綠燈、IEF、國債息、QQQ 基準最近 10 日")
check(J["fear"]["active"] is False and J["fear"]["history"] == [] and len(J["tq"]["tq10"]) == 10 and J["crypto"]["date"] == "2026-11-12",
      "VIX 15：冇恐慌訊號；TQQQ、加密資料有寫")
good = S.OUT.read_text(encoding="utf-8")
for kw, what in ((dict(drop=["G195"]), "得 199 隻股"), (dict(low=["G035"]), "得 39 隻排名")):
    try:
        run_scan(**kw)
        raised = ""
    except SystemExit as e:
        raised = str(e)
    check("數據唔完整" in raised and S.OUT.read_text(encoding="utf-8") == good, f"數據唔齊（{what}）：唔覆蓋舊 scan.json")
S.OUT.write_text(json.dumps({"date": "2099-01-01"}), encoding="utf-8")
try:
    run_scan()
    raised = ""
except SystemExit as e:
    raised = str(e)
check("舊過現有" in raised and json.loads(S.OUT.read_text(encoding="utf-8")) == {"date": "2099-01-01"}, "新數據日期舊過現有：唔覆蓋")
for k, fn in ORIG.items():
    setattr(S, k, fn)
print(f"\n全部 {ok} 項通過")
