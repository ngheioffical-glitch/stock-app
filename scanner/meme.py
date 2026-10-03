"""Meme 雷達（2026-10-04 用戶：好似雷達咁研究前景、排名、融合 AI）。純資訊，唔係買入信號：
冇偷睇測試（stock-strategy/LAB_MEME.md）追升幅／熱度揸 meme 年化 −30%、回撤 −90%；meme 同 BTC 每日相關約 0.7、beta 1.5–1.9。
所以排名 = 研究優先次序 × 安全，唔係買入排名。

來源（全部免費）：GeckoTerminal 熱門池（Solana、BNB、Base、Ethereum）+ CoinGecko meme 分類 24 小時成交最大；
安全：RugCheck（Solana）、GoPlus（EVM）合約風險、大戶集中、流動性、幾耐之前出；
X：雷達嗰 10 個研究人士近 7 日帖（radar.json x_posts）提到邊隻；AI：Gemini + Google 搜尋（額度用晒就冇搜尋版）。
.github/workflows/radar.yml 每 6 個鐘跑（喺 radar.py 之後），輸出 <out>/meme.json。
用法：python scanner/meme.py out
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radar import ai_json, get  # noqa: E402

NETS = [("solana", "Solana", None), ("bsc", "BNB 鏈", "56"), ("base", "Base", "8453"), ("eth", "Ethereum", "1")]
SKIP = {"SOL", "WSOL", "USDC", "USDT", "WETH", "ETH", "WBNB", "BNB", "CBBTC", "WBTC", "BTC", "DAI", "USD1", "USDE", "FDUSD"}
AI_MAX, AI_TTL_H = 5, 48

PROMPT = ("Meme 幣「{name}」（{sym}，{chain}）。數據：市值／全流通 {mc}、24 小時成交 {vol}、24 小時升跌 {chg}、流動性 {liq}、出咗 {age}；"
          "安全檢查：{safety}。X 研究人士近 7 日提到：{x}。"
          "用 Google 搜尋查證（X、Telegram、新聞、DexScreener），用香港廣東話口語幫新手判斷，唔好叫人買賣。回覆 JSON："
          "{{\"kind\": \"揀一個：meme／唔係 meme（熱門池入面有代幣化股票、項目代幣等）\", \"story\": \"敘事係乜（例如 AI、政治、動物、名人、某條鏈嘅吉祥物），點解有人炒（一句）\", "
          "\"community\": \"社群同討論係咪真實（真人討論、KOL 收錢叫單、機械人刷量？）（一句）\", "
          "\"outlook\": \"前景：有冇持續嘅催化劑（上大交易所、名人、產品）定只係一陣風（一句）\", "
          "\"rug\": \"有冇「捲款走」或者操控跡象（開發者大量持倉、流動性未鎖、合約權限、短時間暴升暴跌）（一句）\", "
          "\"risks\": [\"風險 1–3 點\"], \"verdict\": \"揀一個：值得研究／觀望／小心\", \"reason\": \"點解（一句）\"}}。搵唔到嘅寫空字串，唔好估。")

GUIDE = ("你係加密研究導師，用香港廣東話口語幫新手睇「Meme 雷達」。背景：我哋冇偷睇測試過，追升幅或者熱度揸 meme 長期大蝕（年化 −30%、回撤 −90%），"
         "meme 同 BTC 每日相關約 0.7（BTC 跌 10%，大 meme 平均跌 15–19%）；而家 BTC 100 日線 {btc}。數據（熱度 × 安全排名、AI 分析）：\n{data}\n"
         "回覆 JSON：{{\"mood\": \"而家 meme 市場熱唔熱、炒緊咩主題（2–3 句，引用具體幣同數字）\", "
         "\"watch\": [\"最值得研究嘅 1–3 隻同點解、要核實咩\"], \"danger\": [\"最危險嘅 1–3 隻同點解\"], "
         "\"how\": [\"教新手玩 meme 嘅 3 條保命規則（結合今次例子，例如注碼、止蝕、避開咩訊號）\"]}}")


def pools():
    out = []
    for net, chain, cid in NETS:
        try:
            d = get(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools?include=base_token", 30)
        except Exception as e:  # noqa: BLE001
            print(f"[meme] {net} 熱門池攞唔到：{e}")
            continue
        inc = {i["id"]: i["attributes"] for i in d.get("included") or []}
        for p in d.get("data") or []:
            a = p["attributes"]
            b = inc.get(p["relationships"]["base_token"]["data"]["id"]) or {}
            sym = (b.get("symbol") or "").upper()
            if not b.get("address") or sym in SKIP:
                continue
            f = lambda k: float(a.get(k) or 0)
            out.append(dict(key=f"{net}:{b['address']}", name=b.get("name") or sym, sym=sym, chain=chain, net=net, cid=cid, addr=b["address"],
                            liq=f("reserve_in_usd"), fdv=f("fdv_usd"), mcap=float(a.get("market_cap_usd") or 0) or None,
                            vol=float((a.get("volume_usd") or {}).get("h24") or 0), chg=float((a.get("price_change_percentage") or {}).get("h24") or 0) / 100,
                            tx=sum(int(v or 0) for v in ((a.get("transactions") or {}).get("h24") or {}).values() if isinstance(v, (int, float))),
                            created=a.get("pool_created_at"), url=f"https://www.geckoterminal.com/{net}/pools/{a.get('address')}", src="GeckoTerminal 熱門池"))
        time.sleep(2.5)                     # GeckoTerminal 免費每分鐘約 30 次
    return out


def big_memes():
    try:
        d = get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=meme-token&order=volume_desc&per_page=20&price_change_percentage=24h,7d", 30)
    except Exception as e:  # noqa: BLE001
        print(f"[meme] CoinGecko meme 攞唔到：{e}")
        return []
    return [dict(key=f"cg:{m['id']}", name=m["name"], sym=(m["symbol"] or "").upper(), chain="多鏈／中心化交易所", net=None, cid=None, addr=None,
                 liq=None, fdv=m.get("fully_diluted_valuation"), mcap=m.get("market_cap"), vol=m.get("total_volume") or 0,
                 chg=(m.get("price_change_percentage_24h") or 0) / 100, chg7=(m.get("price_change_percentage_7d_in_currency") or 0) / 100,
                 tx=None, created=None, rank=m.get("market_cap_rank"), url=f"https://www.coingecko.com/en/coins/{m['id']}", src="CoinGecko meme 成交最大")
            for m in d if (m.get("symbol") or "").upper() not in SKIP]


def safety(r, now):
    """0–100 分＋原因。大型 meme（市值 ≥ 3 億美元，CoinGecko）合約風險低，主要係價格風險。"""
    flags, sc = [], 100
    if r["net"] is None:
        if (r.get("mcap") or 0) >= 3e8:
            return 80, ["大型 meme：合約同流動性風險低，主要風險係價格大上大落"]
        sc -= 20
        flags.append("市值細過 3 億美元")
        return sc, flags
    if r["liq"] < 5e4:
        sc -= 35; flags.append(f"流動性得 ${r['liq'] / 1e3:.0f}K（好難賣出）")
    elif r["liq"] < 2e5:
        sc -= 20; flags.append(f"流動性 ${r['liq'] / 1e3:.0f}K（偏細）")
    if r.get("created"):
        age = (now - datetime.fromisoformat(r["created"].replace("Z", "+00:00"))).days
        r["age_d"] = age
        if age < 3:
            sc -= 25; flags.append(f"出咗 {age} 日（極新，最多捲款走）")
        elif age < 14:
            sc -= 15; flags.append(f"出咗 {age} 日（好新）")
    if r["liq"] and r["fdv"] and r["fdv"] / r["liq"] > 100:
        sc -= 15; flags.append(f"全流通市值係流動性 {r['fdv'] / r['liq']:.0f} 倍（大戶一賣就崩）")
    try:
        if r["net"] == "solana":
            d = get(f"https://api.rugcheck.xyz/v1/tokens/{r['addr']}/report/summary", 20)
            for k in d.get("risks") or []:
                lv = (k.get("level") or "").lower()
                if lv == "danger":
                    sc -= 25; flags.append(f"RugCheck 危險：{k.get('name')}")
                elif lv == "warn":
                    sc -= 8; flags.append(f"RugCheck 警告：{k.get('name')}")
            if d.get("lpLockedPct") is not None and d["lpLockedPct"] < 50:
                sc -= 10; flags.append(f"流動性只鎖 {d['lpLockedPct']:.0f}%")
        elif r["cid"]:
            d = (get(f"https://api.gopluslabs.io/api/v1/token_security/{r['cid']}?contract_addresses={r['addr']}", 20).get("result") or {})
            g = d.get(r["addr"].lower()) or next(iter(d.values()), {}) if d else {}
            one = lambda k: str(g.get(k, "0")) == "1"
            if one("is_honeypot") or one("cannot_sell_all"):
                sc = 0; flags.append("GoPlus：可能買得賣唔得（貔貅盤）")
            for k, t in (("hidden_owner", "隱藏擁有者"), ("can_take_back_ownership", "可以收返擁有權"), ("selfdestruct", "合約可以自毀"),
                         ("transfer_pausable", "可以暫停轉賬"), ("is_blacklisted", "有黑名單功能")):
                if one(k):
                    sc -= 20; flags.append(f"GoPlus：{t}")
            if one("is_mintable"):
                sc -= 15; flags.append("GoPlus：可以增發")
            tax = max(float(g.get("buy_tax") or 0), float(g.get("sell_tax") or 0))
            if tax > 0.1:
                sc -= 25; flags.append(f"GoPlus：買賣稅 {tax * 100:.0f}%")
            top = sum(float(h.get("percent") or 0) for h in (g.get("holders") or [])[:10] if not h.get("is_contract") and not h.get("is_locked"))
            if top > 0.3:                    # 分級：> 30% −20、> 50% −35、> 80% −50（大戶一賣就崩）
                sc -= 50 if top > 0.8 else 35 if top > 0.5 else 20
                flags.append(f"頭 10 個錢包持 {top * 100:.0f}%")
        time.sleep(1)
    except Exception as e:  # noqa: BLE001
        flags.append(f"合約檢查攞唔到（{str(e)[:40]}）")
        sc -= 10
    return max(0, min(100, sc)), flags


def pctl(vals, v):
    vals = sorted(x for x in vals if x is not None)
    return 100 * sum(1 for x in vals if x <= v) / len(vals) if vals and v is not None else 0


def main(out):
    out = Path(out)
    f = out / "meme.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    dex = list({r["key"]: r for r in pools()}.values())
    big = list({r["key"]: r for r in big_memes()}.values())
    rows = dex + big
    # 熱度喺各自組別入面計（大型 meme 成交大太多，混埋計新 meme 永遠排唔上）
    vols, txs = [r["vol"] for r in dex], [r["tx"] for r in dex if r["tx"] is not None]
    for r in dex:
        r["heat"] = round((pctl(vols, r["vol"]) + (pctl(txs, r["tx"]) if r["tx"] is not None else pctl(vols, r["vol"]))) / 2)
    bv = [r["vol"] for r in big]
    for r in big:
        r["heat"] = round(pctl(bv, r["vol"]))
    dex.sort(key=lambda r: -r["heat"])
    cand = dex[:30]                                   # 熱度頭 30 先做安全檢查（慳 API）
    for r in cand + big:
        r["safe"], r["flags"] = safety(r, now)
        r["score"] = round(r["heat"] * r["safe"] / 100)
    cand.sort(key=lambda r: -r["score"])
    big.sort(key=lambda r: -r["heat"])
    top, bigtop = cand[:15], big[:8]
    # X 研究人士帖（radar.py 寫入 radar.json）
    try:
        posts = json.loads((out / "radar.json").read_text(encoding="utf-8")).get("x_posts") or []
    except Exception:  # noqa: BLE001
        posts = []
    for r in top + bigtop:
        pat = re.compile(r"\$" + re.escape(r["sym"]) + r"\b", re.I) if len(r["sym"]) >= 2 else None
        r["x"] = [t for t in posts if pat and pat.search(t["text"])][:3]
    # AI 逐隻（留 48 小時；每次最多 5 隻）
    old = prev.get("ai") or {}
    AI = {k: v for k, v in old.items() if now - datetime.fromisoformat(v["at"]) < timedelta(hours=AI_TTL_H if v.get("grounded", True) else 24)}
    errs = []
    for r in [r for r in top + bigtop if r["key"] not in AI][:AI_MAX]:
        mc = f"${(r['mcap'] or r['fdv'] or 0) / 1e6:.1f}M"
        liq = "—" if r["liq"] is None else f"${r['liq'] / 1e3:.0f}K"
        age = f"{r['age_d']} 日" if r.get("age_d") is not None else "超過一年（大型）" if r["net"] is None else "唔知"
        res, src, gr = ai_json(PROMPT.format(name=r["name"], sym=r["sym"], chain=r["chain"], mc=mc, vol=f"${r['vol'] / 1e6:.1f}M",
                                             chg=f"{r['chg'] * 100:+.0f}%", liq=liq, age=age, safety=f"{r['safe']} 分；" + "；".join(r["flags"]) or "冇明顯問題",
                                             x="；".join(f"@{t['user']}：{t['text'][:160]}" for t in r["x"]) or "冇"))
        if not res:
            errs.append(f"{r['sym']} AI：{src[:80]}")
            continue
        AI[r["key"]] = dict({k: res.get(k) for k in ("kind", "story", "community", "outlook", "rug", "risks", "verdict", "reason")},
                            src=src, grounded=gr, at=now.isoformat(timespec="seconds"))
        print(f"[meme] AI 分析 {r['sym']}")
    keep = {r["key"] for r in top + bigtop}
    AI = {k: v for k, v in AI.items() if k in keep}
    # 導讀（冇搜尋，平）
    try:
        btc = json.loads((out / "btc.json").read_text(encoding="utf-8"))["ma100"]
        bt = "綠燈（BTC 高過 100 日線）" if btc.get("hold") else "紅燈（BTC 低過 100 日線）"
    except Exception:  # noqa: BLE001
        bt = "唔知"
    guide = prev.get("guide")
    try:
        import os
        import ai as A
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        data = "\n".join(f"#{i + 1} {r['name']}（{r['sym']}，{r['chain']}）熱度 {r['heat']}、安全 {r['safe']}、24h {r['chg'] * 100:+.0f}%、成交 ${r['vol'] / 1e6:.1f}M；"
                         f"安全問題：{'、'.join(r['flags'][:3]) or '冇'}；AI：{(AI.get(r['key']) or {}).get('verdict', '')} {(AI.get(r['key']) or {}).get('reason', '')}"
                         for i, r in enumerate(top[:12] + bigtop[:5]))
        g, m = A.gemini(key, A.STYLE + GUIDE.format(btc=bt, data=data), A.MODELS_D)
        guide = dict(g, model=m, at=now.isoformat(timespec="seconds"))
    except Exception as e:  # noqa: BLE001
        errs.append(f"導讀：{str(e)[:80]}")
    for r in top + bigtop:
        r.pop("cid", None)
    res = dict(at=now.isoformat(timespec="seconds"), btc=bt, top=top, big=bigtop, ai=AI, guide=guide, n=len(rows), errs=errs)
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[meme] 候選 {len(rows)}、新 meme {len(top)}、大型 {len(bigtop)}、AI {len(AI)}；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
