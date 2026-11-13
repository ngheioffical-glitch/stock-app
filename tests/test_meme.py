# -*- coding: utf-8 -*-
"""2026-11-13 scanner/meme.py 行為測試（流程審計 S6：之前冇測試），連 radar.py 嘅解鎖同 X 帖配對。假數據、唔上網、唔改規則。
1. safety（安全分 0–100）：大型 meme（市值 ≥ 3 億）；流動性 5 萬／20 萬、幾耐之前出（3 日、14 日）、全流通 ÷ 流動性 > 100 倍、
   RugCheck 危險／警告／流動性鎖 < 50%；GoPlus 貔貅盤、合約權限、增發、買賣稅 > 10%、頭 10 錢包 > 30%／50%／80%（合約、鎖倉唔計）；檢查攞唔到扣 10。
2. pctl（百分位）。
3. main：熱度（成交 + 交易數百分位）、熱度頭 30 先做安全檢查、分數 = 熱度 × 安全、頭 15；X 帖 $代號；AI 留 48 小時（冇搜尋版 24 小時）、
   每次最多 5 隻、失敗即停；BTC 燈號；導讀。
4. radar.unlocks（之後 30 日解鎖）、radar.x_mentions（個別帳戶出錯唔當系統出錯；名要 5 個字以上先配對）。
用法：python tests/test_meme.py"""
import json
import os
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import meme  # noqa: E402
import radar  # noqa: E402

time.sleep = lambda s: None
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "meme" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. safety
def row(net="solana", liq=3e5, fdv=None, mcap=None, age=None, cid=None, addr="AbC123"):
    return dict(net=net, liq=liq, fdv=fdv, mcap=mcap, cid=cid, addr=addr,
                created=(NOW - timedelta(days=age, hours=1)).isoformat().replace("+00:00", "Z") if age is not None else None)


def rug(risks=(), lp=None):
    meme.get = lambda url, timeout=60: {"risks": [dict(level=lv, name=n) for lv, n in risks], **({"lpLockedPct": lp} if lp is not None else {})}


check(meme.safety(row(net=None, mcap=3e8), NOW) == (80, ["大型 meme：合約同流動性風險低，主要風險係價格大上大落"]), "大型 meme（市值啱啱 3 億）：80 分")
check(meme.safety(row(net=None, mcap=2.99e8), NOW) == (80, ["市值細過 3 億美元"]) and meme.safety(row(net=None), NOW)[1] == ["市值細過 3 億美元"],
      "CoinGecko meme 市值細過 3 億（或者冇市值）：扣 20")
rug()
check(meme.safety(row(liq=2e5, age=14, fdv=1e7), NOW) == (100, []), "流動性啱啱 20 萬、出咗啱啱 14 日、全流通 50 倍：冇扣分")
r = row(liq=4e4, age=2, fdv=4e6)
rug([("warn", "Top holders"), ("info", "x")], lp=50)
sc, fl = meme.safety(r, NOW)
check(sc == 100 - 35 - 25 - 8 and r["age_d"] == 2 and len(fl) == 3 and "好難賣出" in fl[0] and "極新" in fl[1] and "RugCheck 警告：Top holders" in fl[2],
      "流動性 < 5 萬扣 35、出咗 2 日扣 25、RugCheck 警告扣 8；全流通啱啱 100 倍、流動性鎖啱啱 50% 唔扣")
r = row(liq=5e4, age=3, fdv=5.1e6)
rug([("danger", "Mintable")], lp=49)
sc, fl = meme.safety(r, NOW)
check(sc == 100 - 20 - 15 - 15 - 25 - 10 and any("102 倍" in x for x in fl) and "流動性只鎖 49%" in fl[-1],
      "流動性啱啱 5 萬扣 20、出咗 3 日扣 15、全流通 102 倍扣 15、RugCheck 危險扣 25、只鎖 49% 扣 10")
rug()
check(meme.safety(row(age=13), NOW)[0] == 85, "出咗 13 日：扣 15")
rug([("danger", "a"), ("danger", "b"), ("danger", "c"), ("danger", "d"), ("danger", "e")])
check(meme.safety(row(liq=1e4), NOW)[0] == 0, "扣到負數：最低 0 分")


def goplus(**g):
    meme.get = lambda url, timeout=60: {"result": {"abc123": g}}


bsc = lambda: row(net="bsc", cid="56", liq=3e5)
goplus(hidden_owner="1", is_mintable="1", buy_tax="0.05", sell_tax="0.1",
       holders=[dict(percent="0.3"), dict(percent="0.5", is_contract=1), dict(percent="0.4", is_locked=1)])
sc, fl = meme.safety(bsc(), NOW)
check(sc == 100 - 20 - 15 and fl == ["GoPlus：隱藏擁有者", "GoPlus：可以增發"], "GoPlus：隱藏擁有者扣 20、可以增發扣 15；稅啱啱 10%、頭 10 錢包啱啱 30%（合約同鎖倉唔計）唔扣")
for top, cut in (("0.31", 20), ("0.5", 20), ("0.51", 35), ("0.8", 35), ("0.81", 50)):
    goplus(holders=[dict(percent=top)])
    check(meme.safety(bsc(), NOW)[0] == 100 - cut, f"頭 10 錢包持 {float(top):.0%}：扣 {cut}")
goplus(sell_tax="0.11")
check(meme.safety(bsc(), NOW) == (75, ["GoPlus：買賣稅 11%"]), "賣出稅 11%（> 10%）：扣 25")
goplus(is_honeypot="1", transfer_pausable="1")
sc, fl = meme.safety(bsc(), NOW)
check(sc == 0 and "貔貅盤" in fl[0] and "可以暫停轉賬" in fl[1], "貔貅盤（買得賣唔得）：0 分")
meme.get = lambda url, timeout=60: (_ for _ in ()).throw(RuntimeError("GoPlus 503"))
check(meme.safety(bsc(), NOW) == (90, ["合約檢查攞唔到（GoPlus 503）"]), "合約檢查攞唔到：扣 10（唔當安全）")
check(meme.safety(row(net="base", cid=None), NOW) == (100, []), "冇鏈 ID（查唔到 GoPlus）：唔扣")

# ============================================================ 2. pctl
check(meme.pctl([1, 2, 3, 4], 2) == 50 and meme.pctl([4, 3, 2, 1], 4) == 100 and meme.pctl([1, 2], 0.5) == 0, "百分位：細過或等於佢嘅比例")
check(meme.pctl([None, 1, 3], 3) == 100 and meme.pctl([], 3) == 0 and meme.pctl([1, 2], None) == 0, "百分位：None 唔計；冇數據 = 0")

# ============================================================ 3. main
DEX = [dict(key=f"solana:A{i}", name=f"Tok{i}", sym=f"T{i}", chain="Solana", net="solana", cid=None, addr=f"A{i}", liq=1e5, fdv=1e6, mcap=None,
            vol=1000.0 * i, chg=0.1, tx=i, created=None, url="u", src="GeckoTerminal 熱門池") for i in range(1, 36)]
DEX.append(dict(DEX[0], vol=999999.0, tx=999))                       # 同一個 key 出兩次：用後面嗰個
BIG = [dict(key=f"cg:b{i}", name=f"Big{i}", sym=f"B{i}", chain="多鏈", net=None, cid=None, addr=None, liq=None, fdv=None, mcap=1e9,
            vol=1e6 * i, chg=0.0, chg7=0.0, tx=None, created=None, rank=i, url="u", src="CoinGecko") for i in range(1, 11)]
meme.pools, meme.big_memes = lambda: [dict(x) for x in DEX], lambda: [dict(x) for x in BIG]
checked = []


def fake_safety(r, now):
    checked.append(r["key"])
    return (10, ["測試：好危險"]) if r["sym"] == "T35" else (100, [])


meme.safety = fake_safety
asked = []


def fake_ai(prompt):
    asked.append(prompt)
    return {"kind": "meme", "verdict": "觀望", "reason": "測試"}, "Claude", True


meme.ai_json = fake_ai
sys.modules["ai"] = types.SimpleNamespace(ask=lambda key, prompt, models, light=False: ({"mood": "熱"}, "gemini"), STYLE="", MODELS_D=[])
now = datetime.now(timezone.utc)
iso = lambda h: (now - timedelta(hours=h)).isoformat(timespec="seconds")
(OUT / "meme.json").write_text(json.dumps({"ai": {"solana:A34": dict(verdict="舊", at=iso(47), grounded=True),
                                                  "solana:A33": dict(verdict="舊冇搜尋", at=iso(25), grounded=False),
                                                  "solana:A2": dict(verdict="唔再上榜", at=iso(1), grounded=True)}}), encoding="utf-8")
(OUT / "radar.json").write_text(json.dumps({"x_posts": [dict(user="u1", text="買咗 $T34 好正"), dict(user="u2", text="$t3 都幾好")]}), encoding="utf-8")
(OUT / "btc.json").write_text(json.dumps({"ma100": {"hold": True}}), encoding="utf-8")
meme.main(OUT)
M = json.loads((OUT / "meme.json").read_text(encoding="utf-8"))
top = {r["sym"]: r for r in M["top"]}
check(M["n"] == 45 and sorted(checked) == sorted([f"solana:A{i}" for i in range(7, 36)] + ["solana:A1"] + [f"cg:b{i}" for i in range(1, 11)]),
      "去重複後 35 + 10 隻；安全檢查只做熱度頭 30 隻新 meme（A1 成交最大）+ 全部大型")
check([r["sym"] for r in M["top"]][:3] == ["T1", "T34", "T33"] and len(M["top"]) == 15 and "T35" not in top and top["T34"]["heat"] == round(100 * 33 / 35) and top["T1"]["heat"] == 100,
      "排名 = 熱度 × 安全：T35 熱度高但安全 10 分 → 跌出頭 15；熱度 = 成交同交易數百分位平均")
check([r["sym"] for r in M["big"]] == [f"B{i}" for i in range(10, 2, -1)] and M["big"][0]["heat"] == 100, "大型 meme 自己一組排熱度，頭 8 隻")
check([t["text"] for t in top["T34"]["x"]] == ["買咗 $T34 好正"] and top["T33"]["x"] == [] and "cid" not in M["top"][0],
      "X 帖：$T34 配到 T34；「$t3」唔會配錯去 T33；唔輸出 cid")
check(M["ai"]["solana:A34"]["verdict"] == "舊" and M["ai"]["solana:A33"]["verdict"] == "觀望" and "solana:A2" not in M["ai"] and len(asked) == 5,
      "AI：47 小時前（有搜尋）沿用；25 小時前冇搜尋版要重做；跌出榜嘅刪；每次最多新做 5 隻")
check(M["btc"] == "綠燈（BTC 高過 100 日線）" and M["guide"]["mood"] == "熱" and M["guide"]["model"] == "gemini" and M["errs"] == [], "BTC 燈號、導讀")
asked.clear()
meme.ai_json = lambda prompt: (asked.append(prompt), (None, "額度用晒", False))[1]
(OUT / "btc.json").write_text("{}", encoding="utf-8")
meme.main(OUT)
M = json.loads((OUT / "meme.json").read_text(encoding="utf-8"))
check(len(asked) == 1 and len(M["errs"]) == 1 and M["errs"][0].endswith("AI：額度用晒") and M["btc"] == "唔知", "AI 失敗：第一隻失敗就停（唔再試其餘）；冇 BTC 數據 = 唔知")

# ============================================================ 4. radar
t0 = NOW.timestamp()
ts = lambda d: t0 + d * 86400
EMI = {"aaa": {"documentedData": {"data": [dict(label="Team", data=[dict(timestamp=ts(-10), unlocked=100), dict(timestamp=ts(5), unlocked=150),
                                                                         dict(timestamp=ts(20), unlocked=200)]),
                                            dict(label="Investors", data=[dict(timestamp=ts(-5), unlocked=50), dict(timestamp=ts(40), unlocked=80)]),
                                            dict(label="Burn", data=[dict(timestamp=ts(-5), unlocked=90), dict(timestamp=ts(10), unlocked=60)])]}},
       "tiny": {"documentedData": {"data": [dict(label="Team", data=[dict(timestamp=ts(-1), unlocked=0), dict(timestamp=ts(3), unlocked=1)])]}}}


def rget(u, timeout=60):
    if u.endswith("emissionsProtocolsList"):
        return ["aaa", "tiny", "boom", "nomk"]
    k = u.rsplit("/", 1)[1]
    if k == "boom":
        raise RuntimeError("503")
    return EMI[k]


radar.get = rget
rows = [dict(slug="aaa", name="AAA", sym="AAA", gecko="g-aaa"), dict(slug="tiny", name="Tiny", sym="TNY", gecko="g-tiny"),
        dict(slug="boom", name="Boom", sym="BM", gecko="g-boom"), dict(slug="nomk", name="Nomk", sym="NM", gecko="g-nomk")]
mk = {"g-aaa": dict(px=2.0, mcap=10000.0), "g-tiny": dict(px=1.0, mcap=1e6), "g-boom": dict(px=1.0, mcap=1.0)}
U = radar.unlocks(rows, mk, NOW)
check(U == [dict(name="AAA", sym="AAA", usd=200, pct=0.02, date=str((NOW + timedelta(days=5)).date()), who=["Team"])],
      "解鎖：30 日內 Team 多咗 100 粒（× $2 = $200，佔市值 2%），第一次解鎖係 5 日後；30 日後先解鎖、數字減少嘅唔計；佔 < 0.1% 唔顯示")
radar.get = lambda u, timeout=60: (_ for _ in ()).throw(RuntimeError("down"))
check(radar.unlocks(rows, mk, NOW) == [], "解鎖清單攞唔到：空")

fmt = lambda h: (NOW - timedelta(hours=h)).strftime("%a %b %d %H:%M:%S %z %Y")
LONG = " 呢段係足夠長嘅研究筆記，講緊點睇協議收入同代幣解鎖，唔係廣告，純粹分享。"


def feed(fail):
    def posts(u, n, since_ts=None):
        if u in fail:
            raise RuntimeError("帳戶停用")
        if u != "DefiIgnas":
            return {"results": []}
        return {"results": [dict(id=1, text="Ethena 收入創新高" + LONG, created_at=fmt(2)), dict(id=2, text="$ENA 同 abc 都要留意" + LONG, created_at=fmt(5)),
                            dict(id=3, text="@someone Ethena 好" + LONG, created_at=fmt(1)), dict(id=4, text="Ethena 短", created_at=fmt(1)),
                            dict(id=5, text="Ethena 舊帖" + LONG, created_at=fmt(24 * 8)), dict(id=6, text="Ethena 回覆" + LONG, created_at=fmt(1), replying_to="x")]}
    return posts


radar.xfeed.posts = feed(set())
xr = [dict(key="ena", sym="ENA", name="Ethena Labs"), dict(key="abc", sym="X", name="Abc")]
M_, hit, errs, posts = radar.x_mentions(NOW, xr)
check([t["url"].rsplit("/", 1)[1] for t in posts] == ["1", "2"], "X 帖：@ 開頭、太短、超過 7 日、回覆人嘅唔要")
check([t["url"].rsplit("/", 1)[1] for t in M_["ena"]] == ["1", "2"] and "abc" not in M_ and len(hit) == 2,
      "配對：名「Ethena」（≥ 5 字）或 $ENA；名「Abc」太短、代號 1 個字唔配（免亂配）")
acc = [u for u, _ in radar.X_ACCOUNTS]
radar.xfeed.posts = feed(set(acc[1:5]))
check(radar.x_mentions(NOW, xr)[2] == [], "10 個帳戶 4 個攞唔到：唔當系統出錯，照用其餘")
radar.xfeed.posts = feed(set(acc[1:6]))
check(len(radar.x_mentions(NOW, xr)[2]) == 5, "10 個帳戶 5 個攞唔到（一半）：報錯")
print(f"\n全部 {ok} 項通過")
