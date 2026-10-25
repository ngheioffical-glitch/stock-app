# -*- coding: utf-8 -*-
"""2026-10-25 scanner/holders.py：上市公司加密幣庫存（CoinGecko 公開 API）+ 加倉／減倉。假網絡，唔上網。
用法：python tests/test_holders.py"""
import json
import os
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import holders as H  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


out = Path(os.environ.get("TEST_OUT") or T / "_out") / "holders" / time.strftime("%Y%m%d-%H%M%S")
H.time.sleep = lambda s: None
BTC = [dict(name="Strategy", symbol="MSTR.US", country="US", total_holdings=800000, total_current_value_usd=8e10, total_entry_value_usd=6e10, percentage_of_total_supply=3.8),
       dict(name="Metaplanet", symbol="3350.T", country="JP", total_holdings=40000, total_current_value_usd=4e9, total_entry_value_usd=0, percentage_of_total_supply=0.19),
       dict(name="Gone Co", symbol="GONE", country="US", total_holdings=100, total_current_value_usd=1e7)]
ETH = [dict(name="BitMine Immersion", symbol="BMNR.US", country="US", total_holdings=6e6, total_current_value_usd=1.4e10)]
fail = set()


def fake(url, tries=3):
    coin = url.rsplit("/", 1)[-1]
    if coin in fail:
        raise RuntimeError("429 too many")
    rows = BTC if coin == "bitcoin" else ETH
    return dict(total_holdings=sum(r["total_holdings"] for r in rows), total_value_usd=sum(r["total_current_value_usd"] for r in rows), companies=rows)


H.get = fake
H.main(out)
o = json.loads((out / "holders.json").read_text(encoding="utf-8"))
check(o["coins"]["BTC"]["top"][0]["name"] == "Strategy" and o["coins"]["BTC"]["n"] == 3 and o["coins"]["ETH"]["top"][0]["hold"] == 6e6, "BTC、ETH 公司持倉按數量排")
check(o["coins"]["BTC"]["top"][1]["entry"] is None, "入貨成本 0（唔知）當冇")
check(o["events"] == [], "第一次行冇比較，唔當加倉")

BTC[0] = dict(BTC[0], total_holdings=810000, total_current_value_usd=8.1e10)    # 加倉 1 萬
BTC[1] = dict(BTC[1], total_holdings=39000)                                      # 減倉
BTC.pop(2)                                                                       # 落榜
BTC.append(dict(name="New Co", symbol="NEW", country="HK", total_holdings=500, total_current_value_usd=5e7))
H.main(out)
o = json.loads((out / "holders.json").read_text(encoding="utf-8"))
ev = {e["name"]: e for e in o["events"]}
check(ev["Strategy"]["kind"] == "加倉" and ev["Strategy"]["delta"] == 10000 and ev["Strategy"]["usd"] == 1e9 and ev["Strategy"]["coin"] == "BTC",
      "加倉：數量差同大約美元（用頭位公司價計）")
check(ev["Metaplanet"]["kind"] == "減倉" and ev["Gone Co"]["kind"] == "落榜" and ev["New Co"]["kind"] == "新上榜" and "BitMine Immersion" not in ev,
      "減倉、落榜、新上榜；冇變唔記")
n = len(o["events"])
fail.add("ethereum")
H.main(out)
o = json.loads((out / "holders.json").read_text(encoding="utf-8"))
check(o["coins"]["ETH"]["top"][0]["name"] == "BitMine Immersion" and o["errs"] and len(o["events"]) == n, "ETH 攞唔到：沿用上一份、記錯誤；BTC 冇變唔加事件")
print(f"\n全部 {ok} 項通過")
