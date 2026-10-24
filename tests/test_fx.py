# -*- coding: utf-8 -*-
"""2026-10-25 外匯（scanner/fx.py）、金價 5 日異動（commod.py）、ai.py 合併外匯同商品。假 Yahoo 數據，唔上網、唔使錢。
異動門檻要同研究（stock-strategy/LAB_FX.md）同一條公式：USDJPY 5 日變化 ≤ −3%、美元指數 20 日 ±3%、黃金 5 日 ≥ +4%。
用法：python tests/test_fx.py"""
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import fx  # noqa: E402
import commod  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "fx" / time.strftime("%Y%m%d-%H%M%S")
OUT.mkdir(parents=True, exist_ok=True)
DAYS = [d for d in (date(2025, 10, 27) + timedelta(i) for i in range(400)) if d.weekday() < 5][:260]


def series(start, step, tail=None):
    """平穩走勢；tail = 最後幾日嘅價（測異動）。"""
    c = [start * (1 + step) ** i for i in range(len(DAYS))]
    if tail:
        c[-len(tail):] = tail
    return list(zip(DAYS, c))


ndx = series(20000, 0.0008)
PX = {"^NDX": ndx, "DX-Y.NYB": series(100, 0.0), "EURUSD=X": series(1.10, 0.0), "CNY=X": series(7.0, 0.0), "CHF=X": series(0.80, 0.0)}


def run(jpy_tail, dxy_tail=None):
    PX["JPY=X"] = series(150, 0.0, jpy_tail)
    if dxy_tail:
        PX["DX-Y.NYB"] = series(100, 0.0, dxy_tail)
    fx.chart = lambda s: (PX[s], "10-24 05:00")
    fx.main(str(OUT))
    return json.loads((OUT / "fx.json").read_text(encoding="utf-8"))


# 1. 日圓 5 日急升：門檻同研究一樣（USDJPY 5 日跌 ≥ 3% 先提示，2.9% 唔提示）
o = run([150, 150, 150, 150, 150, 150 * 0.969])
check(o["alert"] and "日圓 5 日急升" in o["alert"][0] and "可能" in o["alert"][0], f"USDJPY 5 日 −3.1%：提示日圓急升，而且只講「可能」套利平倉（{o['alert']}）")
o = run([150, 150, 150, 150, 150, 150 * 0.971])
check(not o["alert"], "USDJPY 5 日 −2.9%：唔提示")
check([r["sym"] for r in o["rows"]] == ["DX-Y.NYB", "JPY=X", "EURUSD=X", "CNY=X", "CHF=X"], "五樣：美元指數、日圓、歐元、人民幣（在岸 CNY=X）、瑞郎")
# 2. 美元指數 20 日 ±3%
o = run([150], dxy_tail=[100] * 20 + [103.1])
check(o["alert"] and "美元指數 20 日急升 3.1%" in o["alert"][0], f"美元指數 20 日 +3.1%：提示（{o['alert']}）")
o = run([150], dxy_tail=[100] * 20 + [96.9])
check(o["alert"] and "急跌" in o["alert"][0], "美元指數 20 日 −3.1%：提示急跌")
PX["DX-Y.NYB"] = series(100, 0.0)
# 3. 同納指相關：每星期回報；同一走勢 = +1，相反 = −1
PX["EURUSD=X"] = [(d, c / 20000) for d, c in ndx]
PX["CHF=X"] = [(d, 20000 / c) for d, c in ndx]
wob = [(d, c * (1.01 if i % 3 == 0 else 0.995)) for i, (d, c) in enumerate(ndx)]
PX["^NDX"] = wob
PX["EURUSD=X"] = [(d, c / 20000) for d, c in wob]
PX["CHF=X"] = [(d, 20000 / c) for d, c in wob]
o = run([150])
by = {r["sym"]: r for r in o["rows"]}
check(by["EURUSD=X"]["corr"] == 1.0 and by["CHF=X"]["corr"] <= -0.99, f"同納指相關：一齊郁 +1、相反 −1（{by['EURUSD=X']['corr']}, {by['CHF=X']['corr']}）")
check(by["JPY=X"]["pos52"] is None and 0 <= by["EURUSD=X"]["pos52"] <= 1, "52 週位置喺 0–1（成年冇郁就冇位置）")
# 4. 避險跡象：黃金升、日圓升、美債價升（債息跌），納指跌 → 「可能反映避險需求」
PX["CHF=X"], PX["EURUSD=X"] = series(0.80, 0.0), series(1.10, 0.0)
(OUT / "commod.json").write_text(json.dumps({"rows": [{"sym": "GC=F", "name": "黃金", "w": 0.02}]}), encoding="utf-8")
(OUT / "rates.json").write_text(json.dumps({"rows": [{"name": "10 年", "w": -8.0}]}), encoding="utf-8")
PX["^NDX"] = series(20000, 0.0, [20000, 20000, 20000, 20000, 20000, 19400])
o = run([150, 150, 150, 150, 150, 148])
h = o["haven"]
check(h["hit"] and h["n"] == 3 and "可能反映避險需求" in h["text"] and "唔等於資金流向" in h["text"], f"避險跡象 3／4 + 納指跌：寫「可能」（{h['text']}）")
PX["^NDX"] = series(20000, 0.0, [20000, 20000, 20000, 20000, 20000, 20400])
check(not run([150, 150, 150, 150, 150, 148])["haven"]["hit"], "納指升：唔算避險")

# 5. 金價 5 日升 ≥ 4%（commod.py）
G = [100.0] * 255 + [100, 101, 102, 103, 104.1]
commod.chart = lambda s: (G if s == "GC=F" else [50.0] * 260, "10-24 05:00")
cdir = OUT / "commod"
commod.main(str(cdir))
c = json.loads((cdir / "commod.json").read_text(encoding="utf-8"))
check(any("金價 5 日急升 4.1%" in a for a in c["alert"] or []), f"黃金 5 日 +4.1%：提示（{c['alert']}）")
G[-1] = 103.9
commod.main(str(cdir))
check(not any("金價 5 日" in a for a in json.loads((cdir / "commod.json").read_text(encoding="utf-8"))["alert"] or []), "黃金 5 日 +3.9%：唔提示")

# 6. ai.py：商品同外匯異動合併入今日重點；外匯文字俾 AI
import ai  # noqa: E402
ai.OUTDIR = OUT
(OUT / "commod.json").write_text(json.dumps({"rows": [{"sym": "GC=F", "name": "黃金", "px": 2400.0, "d": 0.01, "m": 0.03, "yr": 0.2, "w": 0.05}],
                                             "alert": ["金價 5 日急升 5.0%"]}), encoding="utf-8")
PX["^NDX"] = series(20000, 0.0, [20000, 20000, 20000, 20000, 20000, 19400])
run([150, 150, 150, 150, 150, 150 * 0.969])
ca = ai.commod_alert()
check(ca and "金價 5 日急升 5.0%" in ca["alert"] and any("日圓 5 日急升" in a for a in ca["alert"]) and any("可能反映避險需求" in a for a in ca["alert"])
      and "外匯" not in ca["detail"][:2] and "美元兌日圓" in ca["detail"], f"今日重點異動：商品 + 外匯 + 避險跡象一齊（{len(ca['alert'])} 條）")
t = ai.fx_text()
check("美元兌日圓 145.35" in t and "同納指相關" in t and "日圓升✓" in t, f"AI 睇到外匯價、相關同避險跡象：{t[:120]}…")
print(f"\n全部 {ok} 項通過")
