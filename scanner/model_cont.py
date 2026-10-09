"""建立延續帳戶 docs/model_cont.json（2026-10-01 用戶要求：回測唔好停喺數據尾；2026-10-09 起係 V2.5）。[quant-backtest]

1. 讀研究嘅 2000 年起 V2.5 帳戶喺數據尾（2026-09-22）收市嘅狀態（stock-strategy/src/v25_hist.py → results_all/v25_seed.json）：
   領導股持倉（股數、入場價、止蝕、R、保本）、現金、高位、剎車；三隻 ETF 腳嘅金額、揸緊咩、聽日要做咩。
2. 價錢換做 Yahoo（同雲端一樣）：領導股入場價、止蝕、R 按「Yahoo 收市 ÷ 研究收市」換算，股數反向換算（金額唔變）；ETF 腳買入價同樣換算。
3. 用 Yahoo 數據逐日重播 scan.py（每日收市排名、候選股）同 model.run()，補到最新一日；最後一日嘅掃描寫返 docs/scan.json。
之後每日 daily-scan.yml 跑 scan.py 同「python scanner/model.py cont」繼續。
用法（一次性）：python scanner/model_cont.py ../stock-strategy/results_all/v25_seed.json
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lead  # noqa: E402
import model as M  # noqa: E402
import scan as SC  # noqa: E402
import v24  # noqa: E402
import v25  # noqa: E402


def main(seed_path):
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    d0, L, legs, px0 = seed["date"], seed["lead"], seed["legs"], seed["px_end"]
    F = M.yahoo_frame()
    R = v24.rows(F, M.next_day(F.index[-1]))
    r0 = next((x for x in R if x["d"] == d0), None)
    assert r0, f"Yahoo 數據冇 {d0}"
    # ---- 揀股掃描：下載一次（2 年），之後逐日切
    syms, _ = SC.nasdaq_universe()
    syms = sorted(set(syms) | {p["sym"] for p in L["positions"]})
    full = SC.download(syms, None)
    SC.download = lambda s, end=None: {k: v.loc[:end] for k, v in full.items()}
    SC.nasdaq_universe = lambda: (syms, {})
    tmp = Path(tempfile.mkdtemp())

    def scan_at(d):
        SC.OUT = tmp / f"scan_{d}.json"
        SC.scan(d)
        return M.load(SC.OUT)

    sc0 = scan_at(d0)
    assert sc0["date"] == d0, (sc0["date"], d0)
    pos = []
    for p in L["positions"]:
        yc = (sc0["stocks"].get(p["sym"]) or {}).get("close")
        k = yc / p["close"] if yc else 1.0
        pos.append(dict(sym=p["sym"], date=p["date"], entry=round(p["entry"] * k, 4), shares=p["shares"] / k, stop=p["stop"] * k,
                        R=round(p["R"] * k, 4), be=p["be"], last_close=yc or p["close"], frac=lead.RULE["frac"]))
    kx = {s: r0["px"][s] / px0[s] for s in px0 if s in r0["px"] and px0.get(s)}
    for leg, sym in (("trend", "TQQQ" if legs["trend"]["held"] else "IEF"), ("dip", "TQQQ"), ("xr", legs["xr"]["hold"])):
        if legs[leg].get("epx") and sym in kx:
            legs[leg]["epx"] *= kx[sym]
    st = dict(legs, ver=v25.VER, start=d0, capital=100_000.0, last=d0, trades=legs.get("trades", [])[-100:], hist=[], nav=[],
              cash=L["cash"], positions=pos, peak=L["peak"], braking=L["braking"], pending={}, slots=0,
              sleeve="bill" if L["green"] else "ief", last_green=L["green"],
              note=f"2000-01-03 起 V2.5 回測帳戶（stock-strategy/src/v25_hist.py，Tiingo）喺 {d0} 收市嘅狀態，之後用 Yahoo 數據照規則繼續行")
    actions = dict(fills=[], stops=[], warn=[])
    M.snap(st, r0, [])
    lead.plan(st, sc0, actions)
    st["view"] = M.view(st, r0, sc0, sc0["next_day"], actions)
    M.CONT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[cont] {d0}：研究帳戶 {seed['nav']:,.0f} → Yahoo 價 {M.total(st):,.0f}；領導股 {[p['sym'] for p in pos]}、剎車 {st['braking']}；"
          f"ETF 價錢比例 {', '.join(f'{s} ×{x:.4f}' for s, x in kx.items())}；下一日掛 {len(st['pending']['buys'])} 張、賣 {len(st['pending']['sells'])} 隻", flush=True)
    last = None
    for r in R:
        if r["d"] <= d0:
            continue
        sc = scan_at(r["d"])
        M.run(M.CONT, sc=sc, F=F.loc[:r["d"]])
        last = SC.OUT
    if last:
        cur = M.load(M.SCAN) if M.SCAN.exists() else {}
        if cur.get("date", "") <= r["d"]:
            shutil.copy(last, M.SCAN)
            print(f"[cont] docs/scan.json 更新到 {r['d']}")
    print(f"[cont] 完成：{M.CONT}")


if __name__ == "__main__":
    main(sys.argv[1])
