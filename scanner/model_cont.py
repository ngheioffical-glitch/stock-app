"""建立延續帳戶 docs/model_cont.json（2026-10-01 用戶要求：回測唔好停喺數據尾；2026-10-09 起係 V2.4）。[quant-backtest]

1. 讀研究嘅 2000 年起 V2.4 帳戶喺數據尾（2026-09-22）收市嘅狀態（stock-strategy/src/v24_hist.py 輸出 results_all/v24_seed.json）：
   三隻腳嘅金額、揸緊咩、聽日要做咩。
2. 買入價換做 Yahoo 調整價（按數據尾嗰日「Yahoo ÷ 研究」比例；金額唔變），QQQ 比較基準都用 Yahoo（app 接駁用）。
3. 用 scanner/model.py 嘅 run() 照 v24 規則逐日行到最新一日。
之後每日 daily-scan.yml 跑「python scanner/model.py cont」繼續。
用法（一次性）：python scanner/model_cont.py ../stock-strategy/results_all/v24_seed.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402
import v24  # noqa: E402


def main(seed_path):
    st = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    end, px0 = st.pop("data_end"), st.pop("px_end")
    F = M.yahoo_frame()
    R = v24.rows(F, M.next_day(F.index[-1]))
    r = next((x for x in R if x["d"] == end), None)
    assert r, f"Yahoo 數據冇 {end}"
    k = {s: r["px"][s] / px0[s] for s in px0 if s in r["px"] and px0.get(s)}
    for leg, sym in (("trend", "TQQQ" if st["trend"]["held"] else "IEF"), ("dip", "TQQQ"), ("xr", st["xr"]["hold"])):
        if st[leg].get("epx") and sym in k:
            st[leg]["epx"] *= k[sym]
    st["hist"][-1]["q"] = round(r["q"], 4)
    for p in st["hist"][-1]["pos"]:
        if p["s"] in k:
            p["e"] = round(p["e"] * k[p["s"]], 2) if p.get("e") else p.get("e")
            p["c"] = round(r["px"][p["s"]], 2)
    st["note"] = f"2000-01-03 起 V2.4 回測帳戶（stock-strategy/src/v24_hist.py）喺 {end} 收市嘅狀態，之後用 Yahoo 數據照 scanner/v24.py 規則繼續行"
    M.CONT.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[cont] {end}：帳戶 {v24.nav(st):,.0f}；價錢比例 {', '.join(f'{s} ×{x:.4f}' for s, x in k.items())}")
    M.run(M.CONT)


if __name__ == "__main__":
    main(sys.argv[1])
