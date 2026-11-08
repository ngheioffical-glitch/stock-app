# -*- coding: utf-8 -*-
"""2026-11-09 scanner/crypto_research.py 測試：假 CoinGecko／DefiLlama／Coinbase 回覆 + 假 AI（唔上網、唔使錢）。
用法：python tests/test_crypto_research.py"""
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

T = Path(__file__).resolve().parent
OUTD = Path(os.environ.get("TEST_OUT") or T / "_out") / "crypto" / time.strftime("%Y%m%d-%H%M%S")
OUTD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(CRYPTO_OUT=str(OUTD), GEMINI_API_KEY="fake", CRYPTO_MONTH_USD="1", CRYPTO_EST_USD="0.3")
import crypto_research as C  # noqa: E402
import llm  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
COINS = [dict(id="demo-coin", symbol="dmo", name="Demo Coin", market_cap_rank=30), dict(id="other-dmo", symbol="dmo", name="Other DMO", market_cap_rank=400),
         dict(id="peer-one", symbol="pr1", name="Peer One", market_cap_rank=50), dict(id="tiny-coin", symbol="tny", name="Tiny", market_cap_rank=90)]
calls = []


def price(k):                     # 第 k 日（0 = 365 日前）
    return 2.0 * math.exp(0.002 * k) * (1 + 0.05 * math.sin(k / 9))


def fake_get(u, timeout=60, tries=3):
    calls.append(u)
    p, q = urlparse(u), parse_qs(urlparse(u).query)
    if "coinbase.com" in u:
        if "/TNY-USD/" in p.path:
            return None                                   # Coinbase 冇呢個幣
        s = datetime.strptime(q["start"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        e = datetime.strptime(q["end"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        out, t = [], e
        while t >= s:
            k = 365 - (today - t).days
            c = price(k)
            out.append([int(t.timestamp()), c * 0.97, c * 1.03, c * 0.99, c, 1000])
            t -= timedelta(days=1)
        return out                                        # 新到舊（同 Coinbase 一樣）
    if p.path.endswith("/coins/markets"):
        if "ids" in q:
            return [dict(id="peer-one", symbol="pr1", name="Peer One", market_cap=5e8, fully_diluted_valuation=1e9,
                         price_change_percentage_30d_in_currency=-12.0, price_change_percentage_1y_in_currency=40.0)]
        return [dict(id=c["id"], symbol=c["symbol"], name=c["name"], market_cap_rank=c["market_cap_rank"]) for c in COINS] if q.get("page") == ["1"] else []
    if p.path.endswith("/search"):
        return dict(coins=[dict(id="tiny-coin", symbol="TNY", name="Tiny")]) if q["query"][0].lower() in ("tiny", "tny") else dict(coins=[])
    m = re.search(r"/coins/([a-z\-]+)$", p.path)
    if m:
        cid = m.group(1)
        if cid not in ("demo-coin", "tiny-coin"):
            return None
        return dict(id=cid, symbol="dmo" if cid == "demo-coin" else "tny", name="Demo Coin" if cid == "demo-coin" else "Tiny", market_cap_rank=30,
                    categories=["DeFi", "Dexs", None], genesis_date="2021-05-01",
                    description=dict(en="<p>Demo Coin is a <b>decentralized exchange</b> token.</p>"),
                    links=dict(homepage=["https://demo.example", ""], twitter_screen_name="demo", repos_url=dict(github=["https://github.com/demo/demo"])),
                    developer_data=dict(commit_count_4_weeks=42, stars=900),
                    market_data=dict(current_price=dict(usd=4.0), market_cap=dict(usd=1e9), fully_diluted_valuation=dict(usd=4e9), total_volume=dict(usd=5e7),
                                     circulating_supply=2.5e8, total_supply=1e9, max_supply=1e9, ath=dict(usd=10.0), ath_date=dict(usd="2024-03-01T00:00:00Z"),
                                     price_change_percentage_7d=-3.0, price_change_percentage_30d=12.5, price_change_percentage_1y=80.0))
    if p.path.endswith("/market_chart"):
        return dict(prices=[[int((today - timedelta(days=365 - k)).timestamp() * 1000), price(k)] for k in range(366)])
    if u.startswith(C.LL + "/protocols"):
        return [dict(id="11", name="Demo DEX v2", slug="demo-dex-v2", parentProtocol="parent#demo", tvl=3e8, category="Dexs"),
                dict(id="12", name="Demo DEX v3", slug="demo-dex-v3", parentProtocol="parent#demo", tvl=2e8, category="Dexs"),
                dict(id="21", name="Peer One", slug="peer-one", gecko_id="peer-one", tvl=1e8, category="Lending")]
    if "lite/protocols2" in u:
        return dict(parentProtocols=[dict(id="parent#demo", name="Demo", gecko_id="demo-coin")])
    if "v2/chains" in u:
        return [dict(name="DemoChain", gecko_id="some-chain", tvl=5e9)]
    if "overview/fees" in u:
        t = q["dataType"][0]
        f = {"dailyFees": (6e6, 4e6, 1e6), "dailyRevenue": (1e6, 5e5, 2e5), "dailyHoldersRevenue": (5e5, 0, 0)}[t]
        return dict(protocols=[dict(defillamaId="11", name="Demo DEX v2", total30d=f[0], total24h=f[0] / 30, category="Dexs"),
                               dict(defillamaId="12", name="Demo DEX v3", total30d=f[1], total24h=f[1] / 30, category="Dexs"),
                               dict(defillamaId="21", name="Peer One", total30d=f[2], total24h=f[2] / 30, category="Lending")])
    if u.endswith("emissionsProtocolsList"):
        return ["demo"]
    if "emissions/demo" in u:
        now = datetime.now(timezone.utc).timestamp()
        return dict(documentedData=dict(data=[dict(label="Investors", data=[dict(timestamp=now - 86400 * 10, unlocked=1e8),
                                                                             dict(timestamp=now + 86400 * 20, unlocked=1.1e8),
                                                                             dict(timestamp=now + 86400 * 60, unlocked=1.3e8)])]))
    raise AssertionError("唔應該攞：" + u)


C.get = fake_get
C.time.sleep = lambda s: None
asked = []


def fake_gather(prompt, max_search=None, timeout=None, first=1):
    asked.append(("gather", prompt))
    return ("Demo 係去中心化交易所 [S1]，有回購 [S2]。", [dict(title="Demo 官網", url="https://demo.example/docs"),
                                                        dict(title="新聞", url="https://news.example/demo")], "Gemini（後備測試）", 3)


def fake_ask(prompt, schema=None, system=None, timeout=None, max_tokens=None, kind="ask", **k):
    asked.append(("ask", prompt, schema, system))
    d0 = (today - timedelta(days=100)).date().isoformat()
    return (dict(name_zh="示範幣", one_liner="一個去中心化交易所嘅代幣", kind="去中心化交易所", what="用家喺度換幣，收手續費 [S1]",
                 token_use=[dict(text="治理投票", src=["S1"]), dict(text="冇來源都照收", src=["S99"]), "唔係 dict"],
                 capture=dict(level="一般", why="每月回購 [S2]", src=["S2", "X1"]), supply=dict(text="團隊 20%", src=["C3"]), team=dict(text="基金會", src=[]),
                 catalysts=[dict(date="2027-01", text="V4 升級", src=["S2"])], risks=[dict(text="監管", src=["S1"])],
                 bull=[dict(text="收入升 [S1]", src=["S1"])], bear=[dict(text="解鎖壓力", src=["C3"])], peers=["PR1", "DMO", "pr1", "zzz"],
                 peers_note="比 PR1 平", scores=[dict(key="fundamentals", score=12, why="收入高", src=["C2"]), dict(key="security", score=6.6, why="有審計", src=["S1"]),
                                                dict(key="fundamentals", score=1, why="重複", src=[]), dict(key="bogus", score=5, why="", src=[])],
                 stance="強烈買入", stance_why="收入同用量都升", blind_spot=dict(title="解鎖", detail="之後 90 日解鎖", src=["C3"]),
                 tech_view="最近向上 BOS，只供參考。", events=[dict(date=d0, label="上主網", detail="主網上線", src=["S1"]),
                                                          dict(date="2019-01-01", label="太舊", detail="圖之前", src=[])],
                 glossary=[dict(term="FDV", define="完全攤薄估值")], next_check="2027 年 1 月升級"), "Gemini（測試）")


C.llm.gather = fake_gather
C.llm.ask = fake_ask
C.llm.USAGE.clear()

# ───── 代號清單同搵幣
check(C.main(["--list"]) == 0 and (OUTD / "coins.json").exists(), "--list 寫 coins.json（唔使 AI）")
coins = C.load_list()
check([c["s"] for c in coins][:2] == ["DMO", "DMO"] and coins[0]["id"] == "demo-coin", "代號清單：代號轉大楷、有排名")
check(C.resolve("dmo", coins) == "demo-coin", "同一個代號有幾個幣：揀市值排名最前")
check(C.resolve("$DMO", coins) == "demo-coin" and C.resolve("other-dmo", coins) == "other-dmo" and C.resolve("Peer One", coins) == "peer-one",
      "代號、id、名都搵到；$ 開頭都得")
check(C.resolve("tiny", coins) == "tiny-coin", "清單冇就問 CoinGecko 搜尋")
check(C.resolve("<script>", coins) is None and C.resolve("", coins) is None, "亂打唔會搵")

# ───── 數據
D = C.collect("demo-coin")
maps = D.pop("_maps")
m = D["mkt"]
check(m["mc_fdv"] == 0.25 and m["circ_pct"] == 0.25 and abs(m["off_ath"] + 0.6) < 1e-9, "市值 ÷ FDV、流通比例、距歷史高位由程式計")
check(m["chg30"] == 0.125 and m["chg1y"] == 0.8 and m["vol_mcap"] == 0.05, "升跌轉做小數；成交 ÷ 市值")
f = D["defi"]
check(f["name"] == "Demo" and f["kind"] == "protocol" and f["tvl"] == 5e8 and f["fees30"] == 1e7 and f["rev30"] == 1.5e6 and f["category"] == "Dexs",
      "DefiLlama：母項目加埋子項目（TVL、手續費、收入）")
check(f["pf"] == round(1e9 / (1e7 * 365 / 30), 1) and f["hold_yield"] == round(5e5 * 365 / 30 / 1e9, 4) and f["mc_tvl"] == 2.0, "P/F、持幣者收益率、市值 ÷ TVL")
u = D["unlock"]
check(u["d30"] == round(1e7 * 4 / 1e9, 4) and u["d90"] == round(3e7 * 4 / 1e9, 4) and u["who"] == ["Investors"], "未來 30／90 日解鎖佔市值")
ch = D["chart"]
check(ch["src"] == "C4" and all(k in ch for k in "ohlc") and ch["d"][-1] < today.date().isoformat(), "Coinbase 有日 K：圖有開高低收，今日未完嗰支唔要")
check(D["ta"] and "brk" in D["ta"] and not any(k in D["ta"] for k in ("fvg", "piv")) and "日" in " ".join(D["ta"]["facts"]), "加密都有 BOS／MSS（用「日」唔係「交易日」）")
D2 = C.collect("tiny-coin")
check(D2["chart"]["src"] == "C1" and "o" not in D2["chart"] and D2["ta"] is None, "Coinbase 冇：淨係 CoinGecko 收市線，冇 BOS／MSS")
src = C.base_sources(D)
check([s["id"] for s in src] == ["C1", "C2", "C3", "C4"], "數據來源 C1–C4")
ft = C.facts_text(D)
check("[C2]" in ft and "市值 ÷ 年化手續費" in ft and "Demo Coin is a decentralized exchange token." in ft, "俾 AI 嘅數據每行標來源、簡介去 HTML")

# ───── 成份報告
calls.clear()
rep = C.build("DMO", coins=coins)
a = rep["ai"]
check(rep["id"] == "demo-coin" and (OUTD / "demo-coin.json").exists(), "寫 docs/crypto/<id>.json")
check([x["src"] for x in a["token_use"]] == [["S1"], []] and a["capture"]["src"] == ["S2"], "剔走唔存在嘅來源（S99、X1）；唔係 dict 嘅點唔要")
check(a["stance"] is None, "判斷唔喺三個選擇（例如「強烈買入」）就唔顯示")
check([(x["key"], x["score"]) for x in a["scores"]] == [("fundamentals", 10), ("security", 7)], "評分收窄 0–10、去重複、唔認識嘅唔要")
check(len(rep["chart"]["events"]) == 1 and rep["chart"]["events"][0]["label"] == "上主網" and rep["chart"]["d"][rep["chart"]["events"][0]["i"]] == rep["chart"]["events"][0]["date"],
      "圖事件：圖之前嘅唔要；對返圖嘅位置")
check([p["sym"] for p in rep["peers"]] == ["PR1"] and rep["peers"][0]["pf"] == round(5e8 / (1e6 * 365 / 30), 1), "同類：去重複、唔要自己、搵唔到嘅唔要；程式計 P/F")
g = [x for x in asked if x[0] == "ask"][-1]
check("唔好叫人買賣" in g[3] and "[C1]" in g[1] and "Demo 係去中心化交易所" in g[1] and g[2] is C.SCHEMA, "AI 提示有數據、筆記、固定格式；系統提示講明唔叫人買賣")
check(rep["sources"][-1]["id"] == "S2" and rep["sources"][-1]["url"] == "https://news.example/demo", "網上來源接住 S1、S2")
idx = json.loads((OUTD / "index.json").read_text(encoding="utf-8"))
check(idx["items"][0]["id"] == "demo-coin" and idx["items"][0]["kind"] == "去中心化交易所" and idx["month_budget"] == 1.0, "index.json 有清單同每月上限")
check(not any("coins.json" in json.dumps(x) for x in idx["items"]), "coins.json 唔會當報告")
check("唔係投資建議" in rep["disclaimer"] and "唔係買賣訊號" in rep["disclaimer"], "免責聲明")

# ───── 用量上限、測試模式
mon = datetime.now(C.HKT).strftime("%Y-%m")
idx["usage"] = {mon: 0.9}
(OUTD / "index.json").write_text(json.dumps(idx), encoding="utf-8")
n0 = len(asked)
check(C.main(["DMO"]) == 1 and len(asked) == n0, "本月用量 + 估計超過上限就唔叫 AI")
r = C.build("tiny", dry=True, coins=coins)
check(r["dry"] and r["ai"] is None and len(asked) == n0, "--dry 唔叫 AI")
check("--dry" in C.__doc__ and "唔係投資建議" in C.DISCLAIMER, "用法同免責有寫")

print(f"\n全部 {ok} 項通過")
