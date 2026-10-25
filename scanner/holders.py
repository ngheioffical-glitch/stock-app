"""加密名人持倉（2026-10-25 老師：「加密嗰度都可以做埋呢啲啦，好似有個網叫arkham？可以睇到名人持倉咩幣同埋個量」→「免費版」）。
Arkham API 要錢（月費 US$100 起），網頁有 Cloudflare 防機械人，唔用。改用免費公開數據：
- 上市公司幣庫存：CoinGecko 公開 API `companies/public_treasury/{bitcoin,ethereum}`（唔使 key）：邊間公司揸幾多、市值、佔總供應。
- 同上一份比較 → 加倉／減倉（數量有變先記；第一次行冇比較）。記低雲端第一次見到嘅時間（seen），留近 90 日。
個人知名錢包（例如 Vitalik、孫宇晨）公開地址得好少幣，真正持倉散喺冇標籤嘅錢包，所以唔追。Hyperliquid 巨鯨倉位喺 hyper.py（加密頁）。
只係資訊，唔改 BTC 100 日線規則。輸出 <out>/holders.json（feeds 分支，全部更新先做）。用法：python scanner/holders.py out
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
CG = "https://api.coingecko.com/api/v3/companies/public_treasury/{coin}"
COINS = (("bitcoin", "BTC"), ("ethereum", "ETH"))
TOP = 30                 # 每隻幣列頭 30 間（變動照記晒）
KEEP_DAYS = 90


def get(url, tries=3):
    last = None
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "stock-app research", "Accept": "application/json"}), timeout=30).read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (k + 1))                               # 免費版每分鐘有次數上限
    raise last


def main(out):
    out = Path(out)
    f = out / "holders.json"
    try:
        prev = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        prev = {}
    now = datetime.now(timezone.utc)
    now_iso, cut = now.isoformat(timespec="seconds"), (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    coins, errs = {}, []
    events = [e for e in prev.get("events") or [] if e.get("seen", "") >= cut]
    for cid, sym in COINS:
        try:
            d = get(CG.format(coin=cid))
        except Exception as e:  # noqa: BLE001
            errs.append(f"{sym}：{str(e)[:60]}")
            if (prev.get("coins") or {}).get(sym):
                coins[sym] = prev["coins"][sym]                    # 攞唔到就沿用上一份
            continue
        rows = [dict(name=c.get("name") or "", sym=c.get("symbol") or "", country=c.get("country") or "", hold=float(c.get("total_holdings") or 0),
                     usd=round(float(c.get("total_current_value_usd") or 0)), entry=round(float(c.get("total_entry_value_usd") or 0)) or None,
                     pct=c.get("percentage_of_total_supply")) for c in d.get("companies") or []]
        rows.sort(key=lambda r: -r["hold"])
        old = {r["name"]: r["hold"] for r in ((prev.get("coins") or {}).get(sym) or {}).get("all") or []}
        if old:                                                    # 第一次行冇比較
            px = rows[0]["usd"] / rows[0]["hold"] if rows and rows[0]["hold"] else None
            for r in rows:
                o = old.get(r["name"])
                dh = r["hold"] - (o or 0)
                if (o is None and r["hold"] > 0) or (o is not None and abs(dh) >= max(1e-9, 1e-6 * r["hold"])):
                    events.append(dict(coin=sym, name=r["name"], sym=r["sym"], old=o, new=r["hold"], delta=round(dh, 4),
                                       usd=round(dh * px) if px else None, kind="新上榜" if o is None else "加倉" if dh > 0 else "減倉", seen=now_iso))
            for n, o in old.items():
                if n not in {r["name"] for r in rows}:
                    events.append(dict(coin=sym, name=n, sym="", old=o, new=0, delta=-o, usd=None, kind="落榜", seen=now_iso))
        coins[sym] = dict(total=d.get("total_holdings"), usd=d.get("total_value_usd"), dom=d.get("market_cap_dominance"), n=len(rows),
                          top=rows[:TOP], all=[dict(name=r["name"], hold=r["hold"]) for r in rows], at=now_iso)
        time.sleep(3)
    if not coins:
        raise SystemExit(f"[holders] 全部攞唔到：{errs}")
    events.sort(key=lambda e: e["seen"], reverse=True)
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), coins=coins, events=events[:300], errs=errs)
    out.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[holders] " + "；".join(f"{k} {v['n']} 間、合共 {v['total']:,.0f}" for k, v in coins.items())
          + f"；今次變動 {sum(1 for e in events if e['seen'] == now_iso)} 個；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
