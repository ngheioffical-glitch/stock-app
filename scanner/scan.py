"""每日掃描（規則 V2.2），數據源：Nasdaq 公開股票名單 + Yahoo（yfinance）。唔使 Tiingo。[quant-signals]

1. 股票池預選：Nasdaq 名單（全美約 7,000 隻普通股／ADR，唔包 ETF），揀當日成交額頭 300 + 市值頭 300（取合集）。
2. Yahoo 下載預選股 2 年日線（拆股、派息調整）+ ^NDX。
3. 照 RULES_V2.md 計：ADV50 頭 50、RS 排名、合格 ①②③、前高、swing low、ATR、大市燈號。
4. 輸出 JSON：大市燈號、排名表、候選股（buy-stop 價、止蝕、R、2R）、每隻股最近 10 日收市／最低。
   帳戶相關（持倉、空位、剎車）由 app 自己計。

用法：python scanner/scan.py [截止日 YYYY-MM-DD]   → docs/scan.json（GitHub Actions 每個交易日收市後自動跑）
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from sector_names import zh

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "scan.json"
UNI = ROOT / "scanner" / "universe.txt"   # Nasdaq 名單攞唔到時用上次嘅預選股
SECT = ROOT / "scanner" / "sectors.json"  # 行業快取：Yahoo 查過就唔再查（每 180 日更新）

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def nasdaq_universe(n_dv=300, n_cap=300):
    """回傳（預選股、Nasdaq 行業 {股票: (板塊, 行業)}）。"""
    try:
        syms, info = _nasdaq(n_dv, n_cap)
        UNI.write_text("\n".join(syms), encoding="utf-8")
        return syms, info
    except Exception as e:                                      # Nasdaq 網站出事：用上次嘅名單
        print("Nasdaq 名單攞唔到，用上次嘅：", e)
        return UNI.read_text(encoding="utf-8").split(), {}


def _nasdaq(n_dv, n_cap):
    req = urllib.request.Request("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true", headers=UA)
    rows = json.loads(urllib.request.urlopen(req, timeout=60).read())["data"]["rows"]
    df = pd.DataFrame(rows)
    df = df[df.symbol.str.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?")]          # 剔走優先股、認股權證等
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
    df["px"], df["vol"], df["cap"] = num(df.lastsale), num(df.volume), num(df.marketCap)
    df = df[df.px >= 5]
    df["dv"] = df.px * df.vol
    pick = set(df.nlargest(n_dv, "dv").symbol) | set(df.nlargest(n_cap, "cap").symbol)
    df = df.fillna({"sector": "", "industry": ""})
    info = {r.symbol.replace(".", "-"): (r.sector, r.industry) for r in df.itertuples() if r.symbol in pick}
    return sorted(s.replace(".", "-") for s in pick), info


def sectors(syms, nasdaq_info, max_age=180):
    """排名股嘅板塊／行業：Yahoo 優先（分類接近 GICS），查唔到用 Nasdaq。結果存喺 sectors.json。"""
    try:
        cache = json.loads(SECT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    now = pd.Timestamp.now().normalize()
    old = lambda e: e.get("src") != "yahoo" or (now - pd.Timestamp(e["date"])).days > max_age
    need = [s for s in syms if s not in cache or old(cache[s])]
    if need:
        import yfinance as yf
        for s in need:
            try:
                i = yf.Ticker(s).info
                if i.get("sector"):
                    cache[s] = dict(sector=i["sector"], industry=i.get("industry") or "", src="yahoo", date=str(now.date()))
                    continue
            except Exception as e:
                print("Yahoo 行業攞唔到：", s, e)
            if s in nasdaq_info and s not in cache:
                sec, ind = nasdaq_info[s]
                cache[s] = dict(sector=sec, industry=ind, src="nasdaq", date=str(now.date()))
        SECT.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {s: zh(cache[s]["sector"], cache[s]["industry"]) if s in cache else ("", "") for s in syms}


CASH_SYMS = ["IEF", "^IRX", "QQQ", "^VIX", "BTC-USD", "TQQQ"]   # V2.2 現金：紅燈揸 IEF（7–10 年國債）；^IRX 只作記錄；QQQ = 比較基準；
# ^VIX = 恐慌買入訊號；BTC-USD = 加密相關股標示；TQQQ = V2.3 嘅 20% TQQQ 腳（都唔入股票池）
TQ_VOL = 0.35      # V2.3：上一日收市綠燈 + QQQ 20 日波幅（年化）< 35% 先揸 TQQQ，否則 IEF（stock-strategy/src/tq_mix.py）


def download(syms, end=None):
    """Yahoo 日線。auto_adjust=False：開高低收只做拆股調整（同圖表一樣，用嚟定前高、止蝕）；Adj Close 連派息調整（用嚟計 RS）。"""
    import yfinance as yf
    kw = dict(auto_adjust=False, group_by="ticker", threads=True, progress=False)
    if end:
        kw.update(start=(pd.Timestamp(end) - pd.Timedelta(days=740)).strftime("%Y-%m-%d"),
                  end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    else:
        kw.update(period="2y")
    raw = yf.download(syms + ["^NDX"] + CASH_SYMS, **kw)
    f = {k: raw.xs(k, axis=1, level=1) for k in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]}
    return {k: v.dropna(how="all") for k, v in f.items()}


def swing(x, n=3, high=True):
    """已確認 swing 點價位（第 i 日要喺 i−n … i+n 入面最高／最低，第 i+n 日先確認），向前填。x 可以係 DataFrame。"""
    w = 2 * n + 1
    roll = x.rolling(w, min_periods=w)
    ext = roll.max() if high else roll.min()
    return x.shift(n).where(x.shift(n) == ext).ffill()


def wilder_atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = np.maximum(np.maximum(h - l, (h - pc).abs()), (l - pc).abs())
    return tr.ewm(alpha=1 / n, adjust=False).mean()


# 紐約交易所休市日（2026–2027）：用嚟判斷「今日係咪呢個星期最後一個交易日」
NYSE_HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
                 "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
                 "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


def next_trading_day(d):
    d = pd.Timestamp(d) + pd.Timedelta(days=1)
    while d.weekday() >= 5 or str(d.date()) in NYSE_HOLIDAYS:
        d += pd.Timedelta(days=1)
    return d


def bounce_info(ndx, ndx_lo, C, sma50, sma200, hi52, adv, piv, stop, rank, rs_all):
    """牛市回調見底提示（2026-09-30 用戶揀方案 3：只做提示，唔改模型；回測見 stock-strategy/LAB_REBOUND.md）。

    見底訊號（收市確認）：NDX 近 10 日最低曾經去到 200 日線上面 2% 以內（或跌穿）+ 當日升 ≥ 2.5%
                        + 200 日線比 20 日前高（仲向上）+ 50 日線 > 200 日線（牛市回調，唔係熊市）。
    有效：訊號後 10 個交易日內，而 NDX 收市未跌穿訊號前 10 日最低位（跌穿 = 作廢）。
    回調區（zone）：近 20 日 NDX 最低去到 200 日線 2% 以內，而由 60 日高位跌咗 ≥ 5%：列出抗跌領導股。
    領導股（O'Neil：回調時抗跌、之前已經強）：成交額 ≥ 2,000 萬、收市 ≥ 5，RS 喺預選股頭 20%（回調前高位嗰日計），
    回調期間最大跌幅細過 NDX，仲企喺 200 日線上面、50 > 200 日線；按 RS 排。
    """
    s200, s50 = ndx.rolling(200).mean(), ndx.rolling(50).mean()
    e21 = ndx.ewm(span=21, adjust=False).mean()
    green = (ndx > s200) | ((ndx > e21) & (e21 > s50))
    lo = ndx_lo.reindex(ndx.index).fillna(ndx)
    near = (lo / s200 - 1).rolling(10, min_periods=1).min() <= 0.02
    low10 = lo.rolling(10, min_periods=1).min()
    fire = (ndx.pct_change() >= 0.025) & near & (s200 > s200.shift(20)) & (s50 > s200)
    n = len(ndx)
    sig = None
    for k in range(max(0, n - 10), n):
        if fire.iloc[k]:
            sig = k                                               # 最近一次（10 個交易日內）
    out = dict(signal=None, zone=False)
    if sig is not None:
        floor = float(low10.iloc[sig])
        dead = bool((ndx.iloc[sig + 1:] < floor).any())
        out["signal"] = dict(date=str(ndx.index[sig].date()), days=n - 1 - sig, up=round(float(ndx.pct_change().iloc[sig]), 4),
                             floor=round(floor, 2), active=not dead, green_at=bool(green.iloc[sig]),
                             green_now=bool(green.iloc[-1]))
    t = ndx.index[-1]
    lo20 = lo.iloc[-20:]
    trough = lo20.idxmin()
    peak = ndx.loc[:trough].iloc[-60:].idxmax()
    ndx_dd = float(ndx.loc[peak:].min() / ndx.loc[peak] - 1)
    zone = bool((lo20 / s200.iloc[-20:] - 1).min() <= 0.02 and ndx_dd <= -0.05)
    out.update(zone=zone or bool(out["signal"] and out["signal"]["active"]), peak=str(peak.date()), trough=str(trough.date()),
               ndx_dd=round(ndx_dd, 4), ndx_off_low=round(float(ndx.iloc[-1] / ndx.loc[trough:].min() - 1), 4))
    if not out["zone"]:
        return out
    close = C.loc[t]
    ok = (close >= 5) & (adv >= 20e6) & (close > sma200) & (sma50 > sma200)
    rs0 = rs_all.loc[peak][(C.loc[t] >= 5) & (adv >= 20e6)].dropna()
    pct = rs0.rank(pct=True)
    strong = pct[pct >= 0.8].index.intersection(ok[ok].index)
    seg = C.loc[peak:, strong]
    dd = seg.min() / seg.iloc[0] - 1
    lead = dd[dd > ndx_dd].index
    rows = []
    for s in lead:
        h = hi52.get(s, np.nan)
        if not np.isfinite(h) or not np.isfinite(dd[s]):
            continue
        rows.append(dict(sym=s, dd=round(float(dd[s]), 4), off_hi=round(float(close[s] / h - 1), 4),
                         bounce=round(float(close[s] / seg[s].min() - 1), 4), rank=rank.get(s), rs_pct=round(float(pct[s]), 3),
                         pivot=round(float(piv[s]), 4) if np.isfinite(piv[s]) else None,
                         stop=round(float(stop[s]), 4) if np.isfinite(stop[s]) else None,
                         above_piv=bool(np.isfinite(piv[s]) and close[s] >= piv[s])))
    rows.sort(key=lambda r: -r["rs_pct"])
    out["leaders"] = rows[:15]
    out["n_leaders"] = len(rows)
    return out


def fear_info(C, advF, cash_px, nxt):
    """恐慌買入訊號（2026-10-01，stock-strategy/src/lab_fear*.py）：VIX 收市 ≥ 30 嘅第一日（之前 20 個交易日冇 ≥ 30 先算新一次），
    收市揀成交額頭 50 入面 60 日 β（對 QQQ）最高 5 隻；下一日開市用 40% 資金平均買，揸 20 個交易日，第 21 日開市賣。只係訊號。"""
    if "^VIX" not in cash_px or "QQQ" not in cash_px:
        return None
    idx = C.index
    vix = cash_px["^VIX"].reindex(idx).ffill()
    qr = np.log(cash_px["QQQ"].reindex(idx).ffill()).diff()
    R = np.log(C).diff()
    trig, last = [], -10 ** 9
    for i, v in enumerate((vix >= 30).values):
        if v:
            if i - last > 20:
                trig.append(i)
            last = i

    def picks(i):
        a = advF.iloc[i]
        c = C.iloc[i]
        ok = (c >= 5) & (a >= 20e6) & (C.iloc[max(0, i - 60):i + 1].notna().sum() >= 60)
        top = a[ok].sort_values(ascending=False).head(50).index
        x, y = R[top].iloc[i - 59:i + 1], qr.iloc[i - 59:i + 1]
        yy = y - y.mean()
        b = ((x - x.mean()) * yy.values[:, None]).sum() / (yy ** 2).sum()
        return b.dropna().sort_values(ascending=False).head(5)

    n = len(idx) - 1
    out = dict(vix=round(float(vix.iloc[-1]), 2), date=str(idx[-1].date()), fraction=0.4, hold=20,
               history=[str(idx[i].date()) for i in trig[-5:]])
    if trig and n - trig[-1] < 20:                 # 仲喺 20 日持有期內（第 20 日收市後就要賣）
        T = trig[-1]
        b = picks(T)
        bi, si = T + 1, T + 21
        buy_d = str(idx[bi].date()) if bi <= n else str(nxt.date())
        sell_d = str(idx[si].date()) if si <= n else None
        if sell_d is None:                          # 估計：之後嘅交易日
            d, k = nxt, si - n
            while k > 1:
                d, k = next_trading_day(d), k - 1
            sell_d = str(d.date())
        rows = []
        for s_, beta in b.items():
            entry = None
            if bi <= n:
                from_open = cash_px.get("_O")
                entry = float(from_open[s_].iloc[bi]) if from_open is not None and s_ in from_open and np.isfinite(from_open[s_].iloc[bi]) else None
            c = float(C[s_].iloc[-1])
            rows.append(dict(sym=s_, beta=round(float(beta), 2), signal_close=round(float(C[s_].iloc[T]), 4),
                             entry=round(entry, 4) if entry else None, close=round(c, 4),
                             ret=round(c / entry - 1, 4) if entry else None))
        out.update(active=True, trigger=str(idx[T].date()), trigger_vix=round(float(vix.iloc[T]), 2), buy_date=buy_d,
                   sell_date=sell_d, days_held=max(0, n - T), picks=rows)
    else:
        out.update(active=False, preview=[dict(sym=k, beta=round(float(v), 2)) for k, v in picks(n).items()])
    return out


def crypto_info(C, advF, cash_px, extra=()):
    """加密相關股（2026-10-01，src/lab_cryptostk.py）：過去 120 個交易日每日回報同 BTC 相關 ≥ 0.5 嘅股（0.4 喺跌市好多銀行股都過），同 BTC 燈號（> 365 日線）。只係標示。"""
    if "BTC-USD" not in cash_px:
        return None
    btc = cash_px["BTC-USD"].dropna()
    ma = btc.rolling(365).mean()
    br = np.log(btc.reindex(C.index).ffill()).diff()
    top = list(advF.iloc[-1].dropna().sort_values(ascending=False).head(100).index) + [s for s in extra if s in C.columns]
    R = np.log(C[sorted(set(top))]).diff().iloc[-120:]
    cor = R.corrwith(br.iloc[-120:]).dropna()
    return dict(btc=round(float(btc.iloc[-1]), 2), ma365=round(float(ma.iloc[-1]), 2) if np.isfinite(ma.iloc[-1]) else None,
                green=bool(btc.iloc[-1] > ma.iloc[-1]) if np.isfinite(ma.iloc[-1]) else None, date=str(btc.index[-1].date()),
                corr={k: round(float(v), 2) for k, v in cor.sort_values(ascending=False).items() if v >= 0.5})


def tq_info(cash_px, ndx, e21, s50n, s200n, days):
    """V2.3 TQQQ 腳：最近 10 日 TQQQ 收市、QQQ 20 日波幅、訊號（綠燈 + 波幅 < TQ_VOL）。"""
    if "TQQQ" not in cash_px or "QQQ" not in cash_px:
        return None
    q = cash_px["QQQ"].dropna()
    vol = (q.pct_change().rolling(20).std() * (252 ** 0.5)).reindex(days).ffill()
    g = ((ndx > s200n) | ((ndx > e21) & (e21 > s50n))).reindex(days).fillna(False)
    r4 = lambda row: [round(float(x), 4) if x == x else None for x in row]
    return dict(tq10=r4(cash_px["TQQQ"].reindex(days).ffill()), vol10=[round(float(v), 4) if v == v else None for v in vol],
                on10=[bool(a and v == v and v < TQ_VOL) for a, v in zip(g, vol)], vol_max=TQ_VOL)


def must_have():
    """兩個模型帳戶嘅持倉同掛緊嘅 buy-stop：就算跌出成交額／市值頭 300 都要有數據（止蝕、出場、退市判斷靠佢）。"""
    out = set()
    for f in ("model.json", "model_cont.json"):
        try:
            m = json.loads((ROOT / "docs" / f).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out |= {p["sym"] for p in m.get("positions", [])}
        out |= {b["sym"] for b in (m.get("pending") or {}).get("buys", [])}
    return out


def scan(end=None):
    syms, nas_info = nasdaq_universe()
    extra = sorted(must_have() - set(syms))
    if extra:
        print("持倉／掛單唔喺預選名單，照樣下載：", extra)
    syms = syms + extra
    D = download(syms, end)
    O, H, L, C, AC, V = D["Open"], D["High"], D["Low"], D["Close"], D["Adj Close"], D["Volume"]
    ndx = C.pop("^NDX").dropna()
    ndx_lo = L["^NDX"].reindex(ndx.index) if "^NDX" in L.columns else ndx
    cash_px = {k: C.pop(k) for k in CASH_SYMS if k in C.columns}
    for X in (O, H, L, AC, V):
        X.drop(columns=["^NDX"] + CASH_SYMS, inplace=True, errors="ignore")
    C = C.dropna(how="all")
    t = C.index[-1]
    O, H, L, AC, V = O.reindex(C.index), H.reindex(C.index), L.reindex(C.index), AC.reindex(C.index), V.reindex(C.index)
    # 大市
    e21, s50n, s200n = ndx.ewm(span=21, adjust=False).mean(), ndx.rolling(50).mean(), ndx.rolling(200).mean()
    green = bool(ndx[t] > s200n[t] or (ndx[t] > e21[t] and e21[t] > s50n[t]))
    # 指標（全部預選股）
    advF = (C * V).rolling(50, min_periods=50).mean()
    adv = advF.loc[t]
    sma50, sma200 = C.rolling(50).mean().loc[t], C.rolling(200).mean().loc[t]
    hi52 = H.rolling(252, min_periods=252).max().loc[t]
    piv, swl = swing(H, 3, True).loc[t], swing(L, 3, False).loc[t]
    atr = wilder_atr(H, L, C).loc[t]
    low20 = L.rolling(20).min().loc[t]
    q = lambda a, b: AC.shift(a) / AC.shift(b) - 1
    rs_hist = 0.4 * q(0, 63) + 0.2 * q(63, 126) + 0.2 * q(126, 189) + 0.2 * q(189, 252)
    rs_all = rs_hist.loc[t]
    close = C.loc[t]
    # 股票池：收市 ≥ 5、ADV50 ≥ 2,000 萬，ADV50 頭 50；排名：有 253 日歷史先有 RS
    ok = (close >= 5) & (adv >= 20e6)
    pool = adv[ok].sort_values(ascending=False).head(50).index
    rs = rs_all[pool][C[pool].notna().sum() >= 253].dropna().sort_values(ascending=False)
    rank = {s: i + 1 for i, s in enumerate(rs.index)}
    sect = sectors(list(rs.index), nas_info)
    nxt = next_trading_day(t)
    # 最近 10 個交易日：app 幾日冇開，都可以補返 2R 保本、盤中穿止蝕、星期五帳戶值
    days = C.index[-10:]
    after = list(days[1:]) + [nxt]
    days_we = [bool(a.isocalendar()[1] != d.isocalendar()[1]) for d, a in zip(days, after)]
    r4 = lambda row: [round(float(x), 4) for x in row]
    stocks, ranking = {}, []
    for s in C.columns:
        if not np.isfinite(close.get(s, np.nan)):
            continue
        stop = swl[s] - 0.2 * atr[s]
        if not np.isfinite(stop) or stop >= piv[s]:
            stop = low20[s] - 0.2 * atr[s]
        c1, c2, c3 = bool(close[s] > sma200[s]), bool(sma50[s] > sma200[s]), bool(close[s] >= 0.75 * hi52[s])
        rec = dict(close=round(float(close[s]), 4), sma200=round(float(sma200[s]), 4), swing_low=round(float(swl[s]), 4),
                   atr=round(float(atr[s]), 4), rank=rank.get(s), in_pool=s in rank,
                   c10=r4(C[s].loc[days]), l10=r4(L[s].loc[days]),
                   o10=r4(O[s].loc[days]), h10=r4(H[s].loc[days]))       # 開市、最高：模型帳戶判斷 buy-stop 成交
        stocks[s] = rec
        if s in rank:
            status = "唔合格" if not (c1 and c2 and c3) else ("收市高過前高，唔追" if not close[s] < piv[s] else "候選")
            ranking.append(dict(rank=rank[s], sym=s, rs=round(float(rs[s]), 4), close=rec["close"], adv50=float(adv[s]),
                                sma50=round(float(sma50[s]), 4), sma200=rec["sma200"], hi52=round(float(hi52[s]), 4),
                                c1=c1, c2=c2, c3=c3, pivot=round(float(piv[s]), 4), stop=round(float(stop), 4),
                                R=round(float(piv[s] - stop), 4), be_trigger=round(float(piv[s] + 2 * (piv[s] - stop)), 4),
                                sector=sect[s][0], industry=sect[s][1], status=status))
    ranking.sort(key=lambda r: r["rank"])
    stops = pd.Series({s: (swl[s] - 0.2 * atr[s]) if np.isfinite(swl[s] - 0.2 * atr[s]) and swl[s] - 0.2 * atr[s] < piv[s]
                       else low20[s] - 0.2 * atr[s] for s in C.columns})
    try:
        bnc = bounce_info(ndx, ndx_lo, C, sma50, sma200, hi52, adv, piv, stops, rank, rs_hist)
        if bnc.get("leaders"):
            sl = sectors([r["sym"] for r in bnc["leaders"]], nas_info)
            for r in bnc["leaders"]:
                r["industry"] = sl[r["sym"]][1]
    except Exception as e:                                      # 提示出錯唔好影響主掃描
        print("見底提示計唔到：", e)
        bnc = None
    try:
        cash_px["_O"] = O
        fear = fear_info(C, advF, cash_px, nxt)
    except Exception as e:
        print("恐慌訊號計唔到：", e)
        fear = None
    try:
        cry = crypto_info(C, advF, cash_px, extra=list(must_have()) + [r["sym"] for r in ranking])
    except Exception as e:
        print("加密相關計唔到：", e)
        cry = None
    out = dict(date=str(t.date()), next_day=str(nxt.date()), week_end=days_we[-1],
               days=[str(d.date()) for d in days], days_we=days_we,
               generated=pd.Timestamp.now(tz="Asia/Hong_Kong").strftime("%Y-%m-%d %H:%M HKT"),
               ndx=round(float(ndx[t]), 2), ndx_e21=round(float(e21[t]), 2), ndx_s50=round(float(s50n[t]), 2),
               ndx_s200=round(float(s200n[t]), 2), green=green, rank1=ranking[0]["sym"] if ranking else None,
               cash=dict(green10=[bool(g) for g in ((ndx > s200n) | ((ndx > e21) & (e21 > s50n))).reindex(days).fillna(False)],
                         ief10=r4(cash_px["IEF"].reindex(days).ffill()) if "IEF" in cash_px else None,
                         irx10=r4(cash_px["^IRX"].reindex(days).ffill()) if "^IRX" in cash_px else None),
               tq=tq_info(cash_px, ndx, e21, s50n, s200n, days),
               bench=dict(qqq10=r4(cash_px["QQQ"].reindex(days).ffill()) if "QQQ" in cash_px else None),   # 模型帳戶記低 QQQ 收市，app 比較「同期買 QQQ」
               bounce=bnc, fear=fear, crypto=cry, universe_checked=len(syms), ranking=ranking, candidates=[r["sym"] for r in ranking if r["status"] == "候選"],
               stocks=stocks)
    # 安全檢查：數據唔完整就唔覆蓋舊檔，令 app 繼續顯示上一份
    if len(ranking) < 40 or len(stocks) < 200:
        raise SystemExit(f"數據唔完整（排名 {len(ranking)} 隻、股票 {len(stocks)} 隻），唔更新 scan.json")
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8")).get("date", "")
            if out["date"] < prev:
                raise SystemExit(f"新數據日期 {out['date']} 舊過現有 {prev}，唔更新")
        except json.JSONDecodeError:
            pass
    txt = json.dumps(clean(out), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    OUT.write_text(txt, encoding="utf-8")
    return out


def clean(x):
    """NaN／無限大 → null（標準 JSON 冇 NaN，手機瀏覽器讀唔到）。"""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


if __name__ == "__main__":
    o = scan(*(sys.argv[1:] or [None]))
    print(o["date"], "綠燈" if o["green"] else "紅燈", "NDX", round(o["ndx"]), "200 日線", round(o["ndx_s200"]))
    for r in o["ranking"][:25]:
        print(f'{r["rank"]:>2} {r["sym"]:<6} {r["industry"]:<8} RS {r["rs"]:.3f} 收市 {r["close"]:.2f} 前高 {r["pivot"]:.2f} 止蝕 {r["stop"]:.2f} '
              f'{"".join("✅" if x else "❌" for x in (r["c1"], r["c2"], r["c3"]))} {r["status"]}')
    print("候選：", o["candidates"][:10], "｜下一個交易日", o["next_day"], "｜今日係週尾" if o["week_end"] else "")
