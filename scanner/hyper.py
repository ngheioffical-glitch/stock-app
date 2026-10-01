"""Hyperliquid 巨鯨追蹤（2026-10-01 用戶：邊個巨鯨買賣咩加密貨幣）。輸出 out/hyper.json（feeds 分支）。
全部用 Hyperliquid 公開 API，唔使 key：
- 名單：stats-data 排行榜（每 6 個鐘先更新）：帳戶 ≥ 100 萬美元、上月成交 ÷ 帳戶 < 300（排走造市商），
  歷史盈利頭 25 + 上月盈利頭 10。
- 持倉：/info clearinghouseState（每次 feeds 都抓，約每 5 分鐘）；同上一份比較 → 開倉／加倉／減倉／平倉／反手（變動 ≥ 25 萬美元）。
- 市場：/info metaAndAssetCtxs（價、24 小時升跌、資金費率、未平倉合約）。
用法：python scanner/hyper.py out
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
MIN_EVENT = 250_000
KEEP_EVENTS = 200


def post(body, timeout=25):
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def pick_whales():
    rows = json.loads(urllib.request.urlopen(urllib.request.Request(LB, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())["leaderboardRows"]
    X = []
    for r in rows:
        av = float(r["accountValue"])
        if av < 1e6:
            continue
        w = {a: b for a, b in r["windowPerformances"]}
        turn = float(w["month"]["vlm"]) / av
        if turn >= 300:
            continue
        X.append(dict(addr=r["ethAddress"], name=r.get("displayName"), value=round(av), pnl_all=round(float(w["allTime"]["pnl"])),
                      pnl_month=round(float(w["month"]["pnl"])), roi_month=round(float(w["month"]["roi"]), 4)))
    top = sorted(X, key=lambda x: -x["pnl_all"])[:25]
    seen = {x["addr"] for x in top}
    top += [x for x in sorted(X, key=lambda x: -x["pnl_month"]) if x["addr"] not in seen][:10]
    return top


def label(w):
    a = w["addr"]
    return w.get("name") or f"{a[:6]}…{a[-4:]}"


def positions(addr):
    d = post({"type": "clearinghouseState", "user": addr})
    out = []
    for ap in d.get("assetPositions", []):
        p = ap.get("position") or {}
        szi = float(p.get("szi") or 0)
        if not szi:
            continue
        out.append(dict(coin=p["coin"], szi=szi, entry=float(p.get("entryPx") or 0), value=round(float(p.get("positionValue") or 0)),
                        upnl=round(float(p.get("unrealizedPnl") or 0)), lev=(p.get("leverage") or {}).get("value"),
                        liq=float(p["liquidationPx"]) if p.get("liquidationPx") else None))
    return dict(account=round(float((d.get("marginSummary") or {}).get("accountValue") or 0)), pos=out)


def ctx():
    meta, ctxs = post({"type": "metaAndAssetCtxs"})
    out = {}
    for u, c in zip(meta["universe"], ctxs):
        try:
            px, prev = float(c["markPx"]), float(c["prevDayPx"])
        except (TypeError, ValueError, KeyError):
            continue
        out[u["name"]] = dict(px=px, chg=round(px / prev - 1, 4) if prev else None, fund_ann=round(float(c["funding"]) * 24 * 365, 4),
                              oi=round(float(c["openInterest"]) * px), vol=round(float(c.get("dayNtlVlm") or 0)))
    return out


def diff(w, old, new, px, t):
    ev = []
    o = {p["coin"]: p for p in (old or [])}
    n = {p["coin"]: p for p in (new or [])}
    for coin in set(o) | set(n):
        a, b = (o.get(coin) or {}).get("szi", 0.0), (n.get(coin) or {}).get("szi", 0.0)
        if a == b:
            continue
        p = px.get(coin) or (n.get(coin) or o.get(coin) or {}).get("entry") or 0
        side = lambda s: "多" if s > 0 else "空"
        if a == 0:
            act, usd = f"開{side(b)}", abs(b) * p
        elif b == 0:
            act, usd = f"平{side(a)}", abs(a) * p
        elif (a > 0) != (b > 0):
            act, usd = f"反手{side(b)}", abs(b - a) * p
        elif abs(b) > abs(a):
            act, usd = f"加{side(b)}", abs(b - a) * p
        else:
            act, usd = f"減{side(b)}", abs(b - a) * p
        if usd < MIN_EVENT:
            continue
        nb = n.get(coin) or {}
        ev.append(dict(t=t, addr=w["addr"], who=label(w), coin=coin, act=act, usd=round(usd), px=p,
                       pos_usd=round(abs(b) * p), lev=nb.get("lev"), entry=nb.get("entry")))
    return ev


def main(out):
    path = Path(out, "hyper.json")
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    now = dt.datetime.now(dt.timezone.utc)
    t = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    o = dict(generated=t, err={})
    whales, wat = prev.get("whales"), prev.get("whales_at")
    if not whales or not wat or (now - dt.datetime.fromisoformat(wat.replace("Z", "+00:00"))).total_seconds() > 6 * 3600:
        try:
            whales, wat = pick_whales(), t
        except Exception as e:
            o["err"]["whales"] = f"{type(e).__name__}: {e}"[:200]
    o["whales"], o["whales_at"] = whales or [], wat
    try:
        o["ctx"] = ctx()
    except Exception as e:
        o["err"]["ctx"] = f"{type(e).__name__}: {e}"[:200]
        o["ctx"] = prev.get("ctx") or {}
    px = {k: v["px"] for k, v in o["ctx"].items()}
    P = {}
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda w: (w["addr"], positions(w["addr"])), o["whales"]))  # 出錯會成個 raise
    for a, r in res:
        P[a] = r
    o["positions"] = P
    events = []
    old = prev.get("positions") or {}
    for w in o["whales"]:
        if w["addr"] in old:                          # 新加入名單嘅唔計（冇上一份可以比較）
            events += diff(w, old[w["addr"]]["pos"], P[w["addr"]]["pos"], px, t)
    events.sort(key=lambda e: -e["usd"])
    o["events"] = (events + (prev.get("events") or []))[:KEEP_EVENTS]
    o["new_events"] = len(events)
    agg = {}
    for a, r in P.items():
        for p in r["pos"]:
            g = agg.setdefault(p["coin"], dict(coin=p["coin"], long=0, short=0, n_long=0, n_short=0))
            v = abs(p["szi"]) * px.get(p["coin"], p["entry"])
            if p["szi"] > 0:
                g["long"] += v; g["n_long"] += 1
            else:
                g["short"] += v; g["n_short"] += 1
    o["agg"] = sorted(({**g, "long": round(g["long"]), "short": round(g["short"]), "net": round(g["long"] - g["short"])} for g in agg.values()),
                      key=lambda g: -(g["long"] + g["short"]))[:15]
    path.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"巨鯨 {len(o['whales'])} 個、有倉 {sum(1 for r in P.values() if r['pos'])} 個、新事件 {len(events)}、錯誤 {o['err']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
