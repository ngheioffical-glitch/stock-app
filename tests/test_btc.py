# -*- coding: utf-8 -*-
"""2026-11-13 scanner/btc.py 行為測試（流程審計 S6：之前淨係測咗 ETH 攞唔到時標 stale）。假數據、唔上網、唔改規則。
1. jget：404 = 冇呢個產品（即刻返 None，唔再試）；其他錯再試一次；再錯先報錯。
2. ETH 策略 B（eth_strategy）：逐日手砌一段走勢，逐筆核對：綠燈做多 → 由高位回落 25% 移動止蝕（之後鎖住，要升穿 20 日高位先再買）
   → BTC 轉紅燈平倉 → 紅燈 + ETH 低過 50 日線做空 → 由低位反彈 25% 平倉（即日再空）→ ETH 收市高過 50 日線平倉 → 抄底（MVRV < 0.8）紅燈都做多。
   截斷喺唔同日子：今日做多（止蝕位）、做空（回補位）、現金（鎖住）。
3. 100 日線燈號（ma100_block）：轉燈日子、距離、模型倉每日數據、ETF 價（攞唔到嗰隻唔寫）。
4. main 穩陣版：升穿 365 日線入；跌穿少過 5% 照揸；跌穿 5% 先走。週線燈號用星期一收市。
用法：python tests/test_btc.py"""
import json
import os
import sys
import time
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import btc  # noqa: E402

time.sleep = lambda s: None          # jget 出錯會等 3 秒再試：測試唔使等
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "btc_logic" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. jget
def fake_get(seq):
    calls = []

    def get(url, timeout=60):
        calls.append(url)
        x = seq[min(len(calls), len(seq)) - 1]
        if isinstance(x, Exception):
            raise x
        return x
    return get, calls


http = lambda code: urllib.error.HTTPError("https://x", code, "err", {}, None)
for seq, want, n, what in (([http(404)], None, 1, "404（冇呢個產品）：即刻返 None，唔再試"),
                           ([http(500), b'{"a": 1}'], {"a": 1}, 2, "500 錯一次：再試一次就攞到"),
                           ([ValueError("壞 JSON"), b'{"b": 2}'], {"b": 2}, 2, "其他錯一次：再試一次就攞到"),
                           ([b'[1, 2]'], [1, 2], 1, "第一次攞到：唔使再試")):
    btc.get, calls = fake_get(seq)
    check(btc.jget("https://x") == want and len(calls) == n, f"jget：{what}")
for seq, what in (([http(503), http(503)], "HTTP 錯兩次"), ([ValueError("x"), ValueError("y")], "其他錯兩次")):
    btc.get, calls = fake_get(seq)
    try:
        btc.jget("https://x")
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    check(raised and len(calls) == 2, f"jget：{what} → 報錯（唔會靜靜雞當冇數）")

# ============================================================ 2. ETH 策略 B
btc.rsi_weekly = lambda px, n=14: pd.Series(50.0, index=px.index)     # 週 RSI 固定 50：唔觸發抄底（抄底用 MVRV 測）
IX = pd.date_range("2015-06-01", "2017-03-14", freq="D")
k0 = IX.get_loc(pd.Timestamp("2017-01-01"))
K = np.arange(len(IX)) - k0                                           # k = 0 係 2017-01-01
bpx = np.where(K < 0, 100.0, np.where(K < 60, 120.0, 80.0))          # 2017-03-02（k = 60）起 BTC 跌穿 365 日線 = 紅燈
mvrv = np.where(K == 70, 0.7, 2.0)                                   # k = 70 MVRV 0.7：抄底
E = {0: 10, **{k: 10 + k for k in range(1, 11)}, 11: 17, 12: 14, **{k: 14 for k in range(13, 30)}, **{k: 21 for k in range(30, 61)},
     61: 15, 62: 12, 63: 15.5, **{k: 19 for k in range(64, 71)}, 71: 19.5, 72: 19.5}
epx = np.array([10.0 if k < 0 else float(E[k]) for k in K])
B = pd.DataFrame({"px": bpx, "mvrv": mvrv}, index=IX)
EE = pd.DataFrame({"px": epx}, index=IX)
day = lambda k: str((pd.Timestamp("2017-01-01") + pd.Timedelta(days=k)).date())
s = btc.eth_strategy(B, EE)
tr = [(t["side"], t["entry"], t["entry_date"], t["exit"], t["exit_date"], t["ret"], t["why"]) for t in s["trades"]]
want = [("做多", 10.0, day(0), 14.0, day(12), 0.4, "移動止蝕（由高位 20 回落 25%）"),
        ("做多", 21.0, day(30), 21.0, day(60), 0.0, "BTC 轉紅燈"),
        ("做空", 15.0, day(61), 15.5, day(63), -0.0333, "由低位 12 反彈 25%"),
        ("做空", 15.5, day(63), 19.0, day(64), -0.2258, "ETH 收市高過 50 日線"),
        ("做多", 19.0, day(70), 19.5, day(71), 0.0263, "BTC 轉紅燈")]
for i, what in enumerate(("綠燈第一日做多 10；高位 20 回落到 14（< 15）移動止蝕",
                          "鎖住期間（14、未升穿 20 日高位 20）唔買；1-31 升到 21 > 20 日高位 → 解鎖再買；3-02 BTC 轉紅燈平倉（ETH 21 高過 50 日線 18.4，唔做空）",
                          "紅燈 + ETH 15 低過 50 日線做空；跌到 12 再反彈到 15.5（> 12 × 1.25）平倉",
                          "平倉同日 15.5 仍低過 50 日線：即日再空；ETH 19 高過 50 日線（未到反彈 25%）平倉",
                          "紅燈但 MVRV 0.7（抄底）做多 19；第二日 MVRV 返 2 → 照紅燈平倉")):
    check(len(tr) > i and tr[i] == want[i], f"ETH 策略第 {i + 1} 筆：{what}")
check(len(tr) == 5, "成段走勢一共 5 筆交易（冇多冇少）")
check(s["pos"] == "現金" and s["since"] == day(71) and s["date"] == day(72) and s["px"] == 19.5 and not s["green"] and not s["bottom"]
      and not s["locked"] and s["e50"] == round((14 * 7 + 21 * 31 + 15 + 12 + 15.5 + 19 * 7 + 19.5 * 2) / 50, 2) and s["hi20"] == 21.0
      and "entry" not in s and "stop" not in s, "最後一日：現金（19.5 高過 50 日線，唔做空），由上次平倉日計")
s = btc.eth_strategy(B.iloc[:k0 + 41], EE.iloc[:k0 + 41])
check(s["pos"] == "做多" and s["since"] == day(30) and s["entry"] == 21.0 and s["peak"] == 21.0 and s["stop"] == 15.75 and s["ret"] == 0.0
      and "cover" not in s, "截到 2-10：做多緊，止蝕 = 高位 21 × 0.75 = 15.75")
s = btc.eth_strategy(B.iloc[:k0 + 63], EE.iloc[:k0 + 63])
e50 = (14 * 17 + 21 * 31 + 15 + 12) / 50
check(s["pos"] == "做空" and s["since"] == day(61) and s["entry"] == 15.0 and s["trough"] == 12.0 and s["cover"] == round(min(15.0, e50), 2)
      and s["ret"] == 0.2 and "stop" not in s, "截到 3-03：做空緊，回補位 = min(低位 12 × 1.25, 50 日線) = 15；賺 20%")
s = btc.eth_strategy(B.iloc[:k0 + 20], EE.iloc[:k0 + 20])
check(s["pos"] == "現金" and s["locked"] and s["since"] == day(12) and len(s["trades"]) == 1, "截到 1-20：止蝕後鎖住（現金）")

# ============================================================ 3. 100 日線燈號
DX = pd.date_range("2016-06-01", "2017-06-30", freq="D")
bp = pd.Series(np.where(DX < "2017-03-01", 100.0, np.where(DX < "2017-05-01", 130.0, 70.0)), index=DX)
ep = pd.Series(np.linspace(8, 12, len(DX)), index=DX)
TD = pd.bdate_range("2016-12-01", "2017-06-30")
btc.trading_days = lambda: TD


def etf_get(url, timeout=60):
    if "ETHU" in url:
        raise RuntimeError("Yahoo 冇")
    sym = url.split("/chart/")[1].split("?")[0]
    return json.dumps({"chart": {"result": [{"meta": {"regularMarketPrice": {"IBIT": 50.123, "ETHA": 20.0, "BITX": 40.5}[sym]}}]}}).encode()


btc.get = etf_get
m = btc.ma100_block(pd.DataFrame({"px": bp}), pd.DataFrame({"px": ep}))
m100 = bp.rolling(100).mean()
check(m["hold"] is False and m["since"] == "2017-05-01" and m["flips"] == [["2017-03-01", True], ["2017-05-01", False]]
      and m["dist"] == round(70 / float(m100.iloc[-1]) - 1, 4), "100 日線：3-01 升穿轉綠、5-01 跌穿轉紅；而家紅燈、距離 = 收市 ÷ 100 日線 − 1")
check(m["btc"]["px"] == 70.0 and m["btc"]["ma"]["100"] == round(float(m100.iloc[-1]), 2) and m["eth"]["px"] == 12.0 and m["btc"]["date"] == "2017-06-30",
      "兩隻幣嘅收市同 21／50／100／200 日線")
cm = {r[0]: r for r in m["cm"]}
check(m["cm"][0][0] == "2017-01-03" and "2017-01-02" not in cm and cm["2017-03-01"][3] == 1 and cm["2017-02-28"][3] == 0 and cm["2017-05-01"][3] == 0
      and cm["2017-03-01"][1] == 130.0 and len(m["cm"]) == len(TD[TD >= "2017-01-03"]), "模型倉每日數據：2017-01-03 起美股交易日；燈號 1／0 跟當日")
check(m["etf"] == {"IBIT": 50.12, "ETHA": 20.0, "BITX": 40.5}, "ETF 價：攞唔到嗰隻（ETHU）唔寫")

# ============================================================ 4. main：穩陣版、週線
MX = pd.date_range("2018-01-01", periods=470, freq="D")
mp = np.r_[np.full(400, 100.0), np.full(30, 110.0), np.full(20, 96.0), np.full(20, 90.0)]   # 升穿 → 跌穿約 4%（照揸）→ 跌穿約 10%（走）
FAKE = pd.DataFrame({"px": mp, "mvrv": 1.5}, index=MX)


def fake_cm(asset="btc", since=None):
    if asset == "eth":
        raise RuntimeError("eth 503")
    return FAKE.copy()


def boom(*a, **k):
    raise RuntimeError("唔上網")


btc.coinmetrics, btc.live, btc.funding14, btc.fred, btc.get = fake_cm, boom, boom, boom, boom
btc.main(str(OUT))
o = json.loads((OUT / "btc.json").read_text(encoding="utf-8"))
ma = pd.Series(mp, index=MX).rolling(365).mean()
cut = [t for t in MX[450:] if mp[MX.get_loc(t)] < ma[t] * 0.95][0]
check(o["stable"]["hold"] is False and o["stable"]["since"] == str(cut.date()) and o["stable"]["exit_line"] == round(float(ma.iloc[-1]) * 0.95, 2),
      f"穩陣版：96 跌穿 365 日線但未夠 5% 照揸；90 跌穿 5% 嗰日（{cut.date()}）先走")
FAKE =pd.DataFrame({"px": mp[:450], "mvrv": 1.5}, index=MX[:450])
btc.main(str(OUT))
o2 = json.loads((OUT / "btc.json").read_text(encoding="utf-8"))
check(o2["stable"]["hold"] is True and o2["stable"]["since"] == str(MX[400].date()) and o2["close"]["px"] == 96.0,
      "截到 96 嗰段：仍然持有（由 110 升穿嗰日計）")
mon = [t for t in MX[:450] if t.dayofweek == 0][-1]
check(o2["weekly"]["date"] == str(mon.date()) and o2["weekly"]["hold"] == bool(mp[MX.get_loc(mon)] > ma[mon]) and o2["ma365"] == round(float(ma.iloc[449]), 2)
      and o2["mvrv"] == 1.5 and "ma100" not in o2 and "eth" not in o2, "週線用最近一個星期一收市；ETH 攞唔到又冇舊數據：唔寫 ma100、eth")
print(f"\n全部 {ok} 項通過")
