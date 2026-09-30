"""建立延續帳戶 docs/model_cont.json（2026-10-01 用戶要求：回測唔好停喺 9 月 22 日）。[quant-backtest]

2000 年起嘅 V2.2 回測（stock-strategy，Tiingo 全美股連退市）只去到 Tiingo 數據尾。呢度：
  1. 讀回測最後一日收市嘅帳戶狀態（stock-strategy/src/cont_seed.py 輸出）：持倉、現金、星期五高位、剎車
  2. 價錢換做 Yahoo 拆股調整價（同雲端模型一樣）：入場價、止蝕、R 按「Yahoo 收市 ÷ Tiingo 收市」換算，股數反向換算，帳戶值唔變
  3. 用 Yahoo 數據逐日重播 scan.py（每日收市排名、燈號、候選股）同 model.py（開市賣、buy-stop、止蝕、收市），補到最新一日
之後每日由 daily-scan.yml 跑「python scanner/model.py cont」繼續行（同雲端模型帳戶一樣嘅規則同數據）。
用法（一次性）：python scanner/model_cont.py <cont_seed.json>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402
import scan as SC  # noqa: E402


def main(seed_path):
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    syms, _ = SC.nasdaq_universe()
    syms = sorted(set(syms) | {p["sym"] for p in seed["positions"]})
    full = SC.download(syms, None)                                   # 下載一次（2 年），之後逐日切
    SC.download = lambda s, end=None: {k: v.loc[:end] for k, v in full.items()}
    SC.nasdaq_universe = lambda: (syms, {})
    tmp = Path(tempfile.mkdtemp())
    days = [d for d in full["Close"].index if str(d.date()) >= seed["date"]]

    def scan_at(d):
        SC.OUT = tmp / f"scan_{d}.json"
        SC.scan(d)
        return SC.OUT

    # 1. 數據尾嗰日：建立帳戶（Yahoo 價）
    p0 = scan_at(seed["date"])
    sc = M.load(p0)
    assert sc["date"] == seed["date"], (sc["date"], seed["date"])
    pos = []
    for p in seed["positions"]:
        yc = (sc["stocks"].get(p["sym"]) or {}).get("close")
        k = yc / p["close"] if yc else 1.0
        pos.append(dict(sym=p["sym"], date=p["date"], entry=round(p["entry"] * k, 4), shares=p["shares"] / k, stop=p["stop"] * k,
                        R=round(p["R"] * k, 4), be=p["be"], last_close=yc or p["close"], frac=M.RULE["frac"]))
    st = dict(start=seed["date"], capital=100_000.0, cash=seed["cash"], positions=pos, trades=[], nav=[], peak=seed["peak"],
              braking=seed["braking"], last=seed["date"], ndx0=sc["ndx"], pending={}, slots=0,
              sleeve="bill" if seed["green"] else "ief", last_green=seed["green"],
              note="2000-01-03 起 V2.2 回測帳戶（stock-strategy，Tiingo）喺 " + seed["date"] + " 收市嘅狀態，之後用 Yahoo 數據照規則繼續行")
    nav0 = M.nav_at(st, lambda p: p["last_close"])
    st["nav"].append(dict(date=seed["date"], nav=round(nav0, 2)))
    actions = dict(fills=[], stops=[], warn=[])
    M.snap(st, seed["date"], [], sc["green"])
    M.plan(st, sc, actions)
    M.OUT = M.CONT
    M.save(st, sc, actions)
    print(f"[cont] {seed['date']}：回測帳戶 {seed['nav']:,.0f} → Yahoo 價 {nav0:,.0f}；剎車 {st['braking']}；下一日掛 {len(st['pending']['buys'])} 張、賣 {len(st['pending']['sells'])} 隻")
    # 2. 之後逐日重播
    for d in days[1:]:
        d = str(d.date())
        M.SCAN = scan_at(d)
        M.main()
    print(f"[cont] 完成：{M.CONT}")


if __name__ == "__main__":
    main(sys.argv[1])
