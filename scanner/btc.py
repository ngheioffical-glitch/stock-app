"""比特幣燈號（2026-10-01 用戶要求；回測見 stock-strategy/LAB_BTC.md）。[quant-signals]

核心（PDF「牛市訊號懶人包」①）：週線收市（香港星期一早上 8 點 = UTC 星期一 00:00）> 365 日線 = 持有，否則空倉。
穩陣版（回測最好）：日線升穿 365 日線就入，跌穿 365 日線 5% 先走（細幅跌穿唔走，少啲假警號）。
參考（唔入規則）：MVRV（市值 ÷ 已實現市值；< 1 = 持有者整體蝕緊、歷史大底）、BitMEX 資金費率（槓桿熱度）、10 年美債孳息、聯邦基金利率、200 週線。
回測（2012–2026）：週線 > 365 日線年化 96%（持有 93%），最大回撤 −72%（持有 −85%）；熊市損失約減半，但牛市少賺。
ETH 策略 B（2026-10-01 用戶揀；回測 stock-strategy/LAB_ETH.md，2017– 年化 149%、最大回撤 −76%）：
  BTC 日線 > 365 日線 = 綠燈 → 做多 ETH；移動止蝕：收市由入場後最高位回落 25% 就走，之後要 ETH 升穿 20 日高位先再買；
  抄底：BTC 跌穿 200 週線／BTC MVRV < 0.8／BTC 週 RSI < 30 → 就算紅燈都做多 ETH（照移動止蝕）；
  做空：BTC 紅燈 + ETH 收市低過 50 日線 → 做空 ETH；平倉：由最低收市反彈 25%、BTC 轉綠燈或者 ETH 收市高過 50 日線。
  全部用每日收市（UTC 00:00）判斷，下一日照做。
輸出 <out>/btc.json（feeds 分支，每 5 分鐘）。用法：python scanner/btc.py <out>
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
EXIT_BAND = 0.05


def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def coinmetrics(asset="btc", since="2016-01-01"):
    url = (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets={asset}&metrics=PriceUSD,CapMVRVCur"
           f"&frequency=1d&page_size=10000&start_time={since}&paging_from=start")
    rows = []
    while url:
        j = json.loads(get(url))
        rows += j["data"]
        url = j.get("next_page_url")
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    return df[["PriceUSD", "CapMVRVCur"]].astype(float).rename(columns={"PriceUSD": "px", "CapMVRVCur": "mvrv"}).sort_index()


def rsi_weekly(px, n=14):
    w = px.resample("W-SUN").last()
    dif = w.diff()
    up, dn = dif.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-dif.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn)).reindex(px.index, method="ffill")


TRAIL, S_TRAIL = 0.25, 0.25


def eth_strategy(b, e):
    """ETH 策略 B：逐日行（同 stock-strategy/src/lab_eth.py sim 一樣）；回傳今日狀態同最近交易。"""
    d = pd.DataFrame({"b": b.px, "bm": b.mvrv, "e": e.px}).dropna()
    d = d[d.e > 0]
    d["b365"], d["b200w"], d["brsiw"] = d.b.rolling(365).mean(), d.b.rolling(1400).mean(), rsi_weekly(d.b)
    d["e50"], d["hi20"] = d.e.rolling(50).mean(), d.e.rolling(20).max().shift(1)
    d = d["2017-01-01":]
    pos, peak, trough, locked, entry, since = 0, 0.0, 0.0, False, None, None
    trades = []
    for t, r in d.iterrows():
        p, green = r.e, bool(r.b > r.b365)
        bot = bool((r.b < r.b200w) if pd.notna(r.b200w) else False) or bool(r.bm < 0.8) or bool(r.brsiw < 30)
        why = None
        if pos == 1:
            peak = max(peak, p)
            if p < peak * (1 - TRAIL):
                why, locked = f"移動止蝕（由高位 {peak:,.0f} 回落 25%）", True
            elif not green and not bot:
                why = "BTC 轉紅燈"
        elif pos == -1:
            trough = min(trough, p)
            why = "BTC 轉綠燈" if green else (f"由低位 {trough:,.0f} 反彈 25%" if p > trough * (1 + S_TRAIL) else ("ETH 收市高過 50 日線" if p > r.e50 else None))
        if why:
            trades.append(dict(side="做多" if pos == 1 else "做空", entry=round(entry[1], 2), entry_date=entry[0], exit=round(p, 2), exit_date=str(t.date()),
                               ret=round((p / entry[1] - 1) * pos, 4), why=why))
            pos = 0
        if pos == 0:
            brk = pd.notna(r.hi20) and p > r.hi20
            if locked and brk:
                locked = False
            if (green or bot) and not locked:
                pos, peak, entry, since = 1, p, (str(t.date()), p), str(t.date())
            elif not green and not bot and p < r.e50:
                pos, trough, entry, since = -1, p, (str(t.date()), p), str(t.date())
    last = d.iloc[-1]
    green, bot = bool(last.b > last.b365), bool((last.b < last.b200w) or (last.bm < 0.8) or (last.brsiw < 30))
    st = dict(pos={1: "做多", -1: "做空", 0: "現金"}[pos], since=since if pos else (trades[-1]["exit_date"] if trades else None),
              date=str(last.name.date()), px=round(last.e, 2), e50=round(last.e50, 2), hi20=round(last.hi20, 2), green=green, bottom=bot, locked=locked,
              btc_rsiw=round(float(last.brsiw), 1), btc_200w=round(float(last.b200w), 0))
    if pos == 1:
        st.update(entry=round(entry[1], 2), peak=round(peak, 2), stop=round(peak * (1 - TRAIL), 2), ret=round(last.e / entry[1] - 1, 4))
    elif pos == -1:
        st.update(entry=round(entry[1], 2), trough=round(trough, 2), cover=round(min(trough * (1 + S_TRAIL), last.e50), 2), ret=round(1 - last.e / entry[1], 4))
    st["trades"] = trades[-10:]
    return st


def fred(sid):
    since = (datetime.now(timezone.utc) - pd.Timedelta(days=400)).date().isoformat()     # FRED 對瀏覽器 User-Agent 會好慢：用預設
    raw = urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={since}", timeout=60).read().decode()
    s = pd.read_csv(io.StringIO(raw), index_col=0, parse_dates=True).iloc[:, 0]
    return pd.to_numeric(s, errors="coerce").dropna()


def live():
    m = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=1d&interval=5m", 20))["chart"]["result"][0]["meta"]
    return float(m["regularMarketPrice"]), datetime.fromtimestamp(m["regularMarketTime"], timezone.utc)


def funding14():
    d = json.loads(get("https://www.bitmex.com/api/v1/funding?symbol=XBTUSD&count=45&reverse=true", 30))
    s = pd.Series([x["fundingRate"] for x in d], index=pd.to_datetime([x["timestamp"] for x in d]))
    s = s[s.index >= s.index.max() - pd.Timedelta(days=14)]
    return float(s.mean() * 3 * 365), str(s.index.max().date())


def main(out):
    hk = ZoneInfo("Asia/Hong_Kong")
    try:                                                   # 上一份（workflow 先 curl 落嚟）：利率一日先變一次，6 個鐘內沿用；攞唔到都沿用
        prev = json.loads(Path(out, "btc.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        prev = {}
    d = coinmetrics("btc")
    try:
        o_eth = eth_strategy(d, coinmetrics("eth"))
    except Exception as ex:  # noqa: BLE001
        print("[btc] ETH 策略計唔到：", ex)
        o_eth = prev.get("eth")
    d["ma365"] = d.px.rolling(365).mean()
    d["wma200"] = d.px.rolling(1400).mean()
    d = d.dropna(subset=["ma365"])
    # 核心：週線收市（UTC 星期一 00:00 嗰一行 = 香港星期一 8 點）
    wk = d[d.index.dayofweek == 0]
    above = wk.px > wk.ma365
    sw = above[above != above.shift(1)]
    w_last = wk.iloc[-1]
    # 穩陣版：日線升穿入、跌穿 5% 先走
    st, since, cur = [], None, False
    for t, r in d.iterrows():
        nxt = (r.px > r.ma365) if not cur else not (r.px < r.ma365 * (1 - EXIT_BAND))
        if nxt != cur:
            since = t
        cur = nxt
        st.append(cur)
    last = d.iloc[-1]
    o = dict(generated=datetime.now(timezone.utc).astimezone(hk).strftime("%Y-%m-%d %H:%M HKT"),
             close=dict(date=str(last.name.date()), px=round(last.px, 2)),
             ma365=round(last.ma365, 2), wma200=round(last.wma200, 2) if pd.notna(last.wma200) else None,
             mvrv=round(last.mvrv, 3) if pd.notna(last.mvrv) else None,
             weekly=dict(date=str(w_last.name.date()), px=round(w_last.px, 2), ma365=round(w_last.ma365, 2), hold=bool(w_last.px > w_last.ma365),
                         since=str(sw.index[-1].date()), switches=[[str(t.date()), bool(v)] for t, v in sw.tail(8).items()]),
             stable=dict(hold=bool(cur), since=str(since.date()) if since is not None else None, exit_line=round(last.ma365 * (1 - EXIT_BAND), 2)),
             chart=[[str(t.date()), round(r.px, 0), round(r.ma365, 0)] for t, r in d.iloc[-730::3].iterrows()])
    if o_eth:
        o["eth"] = o_eth
        try:
            m = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?range=1d&interval=5m", 20))["chart"]["result"][0]["meta"]
            o["eth"]["live"] = dict(px=round(float(m["regularMarketPrice"]), 2), at=datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).astimezone(hk).strftime("%m-%d %H:%M"))
        except Exception as ex:  # noqa: BLE001
            print("[btc] ETH 即時價攞唔到：", ex)
    try:
        px, at = live()
        o["live"] = dict(px=round(px, 2), at=at.astimezone(hk).strftime("%m-%d %H:%M"), dist=round(px / last.ma365 - 1, 4))
    except Exception as e:  # noqa: BLE001
        print("[btc] 即時價攞唔到：", e)
    try:
        f, fd = funding14()
        o["funding14"] = dict(ann=round(f, 4), date=fd)
    except Exception as e:  # noqa: BLE001
        print("[btc] 資金費率攞唔到：", e)
        if prev.get("funding14"):
            o["funding14"] = prev["funding14"]
    pr = prev.get("rates") or {}
    fresh = pr.get("at") and (datetime.now(timezone.utc) - datetime.fromisoformat(pr["at"])).total_seconds() < 6 * 3600
    if fresh:
        o["rates"] = pr
    else:
      try:
        t10, ff = fred("DGS10"), fred("DFF")
        o["rates"] = dict(tnx=round(float(t10.iloc[-1]), 2), tnx_3m=round(float(t10.iloc[-1] - t10[t10.index <= t10.index[-1] - pd.Timedelta(days=91)].iloc[-1]), 2),
                          ff=round(float(ff.iloc[-1]), 2), ff_3m=round(float(ff.iloc[-1] - ff[ff.index <= ff.index[-1] - pd.Timedelta(days=91)].iloc[-1]), 2),
                          date=str(t10.index[-1].date()), at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
      except Exception as e:  # noqa: BLE001
        print("[btc] 利率攞唔到：", e)
        if pr:
            o["rates"] = pr
    Path(out, "btc.json").write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[btc] {o['close']['date']} {o['close']['px']:,.0f} vs 365 日線 {o['ma365']:,.0f}；週線{'持有' if o['weekly']['hold'] else '空倉'}（{o['weekly']['since']} 起）；"
          f"穩陣版{'持有' if o['stable']['hold'] else '空倉'}；MVRV {o['mvrv']}；ETH 策略：{(o.get('eth') or {}).get('pos')}（{(o.get('eth') or {}).get('since')} 起）")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
