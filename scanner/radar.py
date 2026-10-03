"""新項目雷達（2026-10-03 用戶：如果之後出咗類似 HYPE 嘅項目會高度關注）。純資訊，唔係買入信號：
冇偷睇測試（stock-strategy/LAB_RADAR.md）用收入揀幣 2023 起輸 BTC 100 日線，所以 app 只顯示、唔叫買。

來源（全部免費）：DefiLlama 收入總表（近 30 日 vs 前 30 日）、持幣者收入（回購／分派）、母項目資料（代幣、coingecko id）；
CoinGecko 市值／全流通市值／30 日升跌；DefiLlama 代幣解鎖數據集（之後 30 日解鎖）。
三張表：收入增長最快、收入最大（有代幣）、未發幣（可能將來空投，亦可能永遠唔發）；加之後 30 日大解鎖。
每 6 個鐘先做一次（feeds 每 5 分鐘跑，其餘時間沿用上一份）。
用法：python scanner/radar.py out
"""
from __future__ import annotations

import collections
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
EVERY_H = 6
OV = "https://api.llama.fi/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType={}"
SKIP_CAT = {"Stablecoin Issuer", "RWA", "CeDeFi", "Block Builders", "Foundation", "CEX", "Chain"}
MIN_REV30 = 1e6      # 收入榜：近 30 日收入 ≥ 100 萬美元
MIN_PREV30 = 3e5     # 計增長：前 30 日 ≥ 30 萬美元
MIN_NOTOKEN = 5e5    # 未發幣：近 30 日收入 ≥ 50 萬美元
N = 12


def get(u, timeout=60):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read())


def groups():
    """按母項目合併收入：{key: dict(name, cat, rev30, prev30, hold30, gecko, sym, slug)}"""
    rev = get(OV.format("dailyRevenue"))["protocols"]
    hold = {str(o["defillamaId"]): o.get("total30d") or 0 for o in get(OV.format("dailyHoldersRevenue"))["protocols"]}
    pr = {str(p["id"]): p for p in get("https://api.llama.fi/protocols", 90)}
    par = {p["id"]: p for p in get("https://api.llama.fi/lite/protocols2", 90)["parentProtocols"]}
    G = {}
    for o in rev:
        if o.get("protocolType") == "chain" or o.get("category") in SKIP_CAT:
            continue
        p = pr.get(str(o["defillamaId"])) or {}
        pid = p.get("parentProtocol")
        meta = par.get(pid) if pid else p
        key = pid or str(o["defillamaId"])
        g = G.setdefault(key, dict(name=(meta or {}).get("name") or o["name"], cat=o.get("category"), rev30=0.0, prev30=0.0, hold30=0.0,
                                   gecko=(meta or {}).get("gecko_id") or None, sym=((meta or {}).get("symbol") or "").strip(),
                                   slug=(pid or "").replace("parent#", "") or o.get("slug"), top=0.0))
        r30 = o.get("total30d") or 0
        g["rev30"] += r30
        g["prev30"] += o.get("total60dto30d") or 0
        g["hold30"] += hold.get(str(o["defillamaId"]), 0)
        if r30 > g["top"]:
            g["top"], g["cat"] = r30, o.get("category")
    for g in G.values():
        if g["sym"] in ("", "-"):
            g["sym"] = ""
        g.pop("top")
    return G


def markets(ids):
    out = {}
    ids = sorted(set(ids))
    for k in range(0, len(ids), 100):   # CoinGecko 一次最多 100 隻（200 隻會失敗）
        u = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=250&price_change_percentage=30d&ids="
             + ",".join(ids[k:k + 100]))
        for m in get(u):
            out[m["id"]] = dict(px=m.get("current_price"), mcap=m.get("market_cap") or None, fdv=m.get("fully_diluted_valuation") or None,
                                chg30=(m.get("price_change_percentage_30d_in_currency") or 0) / 100, circ=m.get("circulating_supply"))
        time.sleep(2)
    return out


def unlocks(rows, mk, now):
    """之後 30 日解鎖：DefiLlama 數據集 metadata.events。返 [{name, sym, usd, pct, date}]，按佔流通市值排。"""
    try:
        have = set(get("https://defillama-datasets.llama.fi/emissionsProtocolsList"))
    except Exception as e:  # noqa: BLE001
        print(f"[radar] 解鎖清單攞唔到：{e}")
        return []
    t0, t1 = now.timestamp(), (now + timedelta(days=30)).timestamp()
    out = []
    for r in rows:
        cands = [s for s in {r["slug"], r["name"].lower().replace(" ", "-")} if s in have]
        if not cands or not r.get("gecko") or r["gecko"] not in mk:
            continue
        try:
            d = get(f"https://defillama-datasets.llama.fi/emissions/{cands[0]}", 60)
        except Exception as e:  # noqa: BLE001
            print(f"[radar] {cands[0]} 解鎖攞唔到：{e}")
            continue
        # 每個分配類別嘅累計解鎖日線：之後 30 日增加幾多（線性歸屬都計到；metadata.events 只記開始日，唔啱用）
        tok, first, labels = 0.0, None, []
        for s in (d.get("documentedData") or {}).get("data") or []:
            pts = [p for p in s.get("data") or [] if isinstance(p.get("timestamp"), (int, float))]
            at = lambda t: max([p.get("unlocked") or 0 for p in pts if p["timestamp"] <= t] or [0])
            dl = at(t1) - at(t0)
            if dl > 0:
                tok += dl
                labels.append(s.get("label") or "")
                nxt = min((p["timestamp"] for p in pts if t0 < p["timestamp"] <= t1 and (p.get("unlocked") or 0) > at(t0)), default=None)
                first = nxt if first is None or (nxt and nxt < first) else first
        m = mk[r["gecko"]]
        if tok <= 0 or not m.get("px") or not m.get("mcap"):
            continue
        usd = tok * m["px"]
        out.append(dict(name=r["name"], sym=r["sym"], usd=round(usd), pct=round(usd / m["mcap"], 4),
                        date=datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%d") if first else "", who=labels[:3]))
        time.sleep(0.5)
    return sorted([x for x in out if x["pct"] >= 0.001], key=lambda x: -x["pct"])  # 細過流通市值 0.1% 唔顯示


def main(out):
    out = Path(out)
    f = out / "radar.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    if prev.get("at") and "--force" not in sys.argv and now - datetime.fromisoformat(prev["at"]) < timedelta(hours=EVERY_H):
        print("[radar] 未夠 6 個鐘，沿用上一份")
        return
    G = list(groups().values())
    for g in G:
        g["growth"] = g["rev30"] / g["prev30"] - 1 if g["prev30"] >= MIN_PREV30 else None
    tok = [g for g in G if g["gecko"]]
    big = sorted([g for g in tok if g["rev30"] >= MIN_REV30], key=lambda g: -g["rev30"])
    grow = sorted([g for g in G if g["rev30"] >= MIN_REV30 and g["growth"] is not None], key=lambda g: -g["growth"])
    mk = markets([g["gecko"] for g in big[:60] + [g for g in grow[:N] if g["gecko"]]])

    def row(g):
        m = mk.get(g["gecko"] or "", {})
        ann = g["rev30"] * 365 / 30
        return dict(name=g["name"], cat=g["cat"], sym=g["sym"], gecko=g["gecko"], slug=g["slug"], rev30=round(g["rev30"]),
                    growth=None if g["growth"] is None else round(g["growth"], 3), buyback=g["hold30"] > 0, hold30=round(g["hold30"]),
                    mcap=m.get("mcap"), fdv=m.get("fdv"), chg30=None if not m else round(m["chg30"], 3),
                    pe_mc=round(m["mcap"] / ann, 1) if m.get("mcap") and ann else None,
                    pe_fdv=round(m["fdv"] / ann, 1) if m.get("fdv") and ann else None)

    R = dict(at=now.isoformat(timespec="seconds"),
             growth=[row(g) for g in grow[:N]],
             big=[row(g) for g in big[:N]],
             notoken=[row(g) for g in sorted([g for g in G if not g["gecko"] and not g["sym"] and g["rev30"] >= MIN_NOTOKEN],
                                             key=lambda g: -g["rev30"])[:N]],
             n=len(G))
    R["unlocks"] = unlocks([row(g) for g in big[:40]], mk, now)[:8]
    f.write_text(json.dumps(R, ensure_ascii=False), encoding="utf-8")
    print(f"[radar] 增長 {len(R['growth'])}、最大 {len(R['big'])}、未發幣 {len(R['notoken'])}、解鎖 {len(R['unlocks'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
