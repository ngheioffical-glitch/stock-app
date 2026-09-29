"""每日掃描（規則 v2.1），數據源：Nasdaq 公開股票名單 + Yahoo（yfinance）。唔使 Tiingo。[quant-signals]

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


CASH_SYMS = ["IEF", "^IRX"]     # V2.2 現金：紅燈揸 IEF（7–10 年國債）、綠燈收短期國債息（^IRX = 13 週國債孳息，%）


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


def scan(end=None):
    syms, nas_info = nasdaq_universe()
    D = download(syms, end)
    O, H, L, C, AC, V = D["Open"], D["High"], D["Low"], D["Close"], D["Adj Close"], D["Volume"]
    ndx = C.pop("^NDX").dropna()
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
    adv = (C * V).rolling(50, min_periods=50).mean().loc[t]
    sma50, sma200 = C.rolling(50).mean().loc[t], C.rolling(200).mean().loc[t]
    hi52 = H.rolling(252, min_periods=252).max().loc[t]
    piv, swl = swing(H, 3, True).loc[t], swing(L, 3, False).loc[t]
    atr = wilder_atr(H, L, C).loc[t]
    low20 = L.rolling(20).min().loc[t]
    q = lambda a, b: AC.shift(a) / AC.shift(b) - 1
    rs_all = (0.4 * q(0, 63) + 0.2 * q(63, 126) + 0.2 * q(126, 189) + 0.2 * q(189, 252)).loc[t]
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
    out = dict(date=str(t.date()), next_day=str(nxt.date()), week_end=days_we[-1],
               days=[str(d.date()) for d in days], days_we=days_we,
               generated=pd.Timestamp.now(tz="Asia/Hong_Kong").strftime("%Y-%m-%d %H:%M HKT"),
               ndx=round(float(ndx[t]), 2), ndx_e21=round(float(e21[t]), 2), ndx_s50=round(float(s50n[t]), 2),
               ndx_s200=round(float(s200n[t]), 2), green=green, rank1=ranking[0]["sym"] if ranking else None,
               cash=dict(green10=[bool(g) for g in ((ndx > s200n) | ((ndx > e21) & (e21 > s50n))).reindex(days).fillna(False)],
                         ief10=r4(cash_px["IEF"].reindex(days).ffill()) if "IEF" in cash_px else None,
                         irx10=r4(cash_px["^IRX"].reindex(days).ffill()) if "^IRX" in cash_px else None),
               universe_checked=len(syms), ranking=ranking, candidates=[r["sym"] for r in ranking if r["status"] == "候選"],
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
