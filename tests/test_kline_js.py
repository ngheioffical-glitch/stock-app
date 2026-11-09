# -*- coding: utf-8 -*-
"""2026-11-09 K 線全螢幕：app（engine.html 嘅 kvBrk、kvAgg）同雲端 Python（structure.py、bars.py）計法要一樣。
老師：「有冇可能可以將K線圖做到好似tradingview咁樣揀timeframe同埋放大縮小？同埋左右回放更遠的K線？」
→ 週 K／月 K 嘅 BOS／MSS 係 app 即場計，所以要證明 JS 版本同 Python 版本出一樣嘅結果。
用 node 跑 engine.html 抽出嚟嘅函數（唔上網）；冇 node 就跳過（check_js.py 都要 node）。
用法：python tests/test_kline_js.py"""
import json
import math
import random
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import bars  # noqa: E402
import structure as S  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


node = shutil.which("node")
if not node:
    print("冇 node，跳過")
    sys.exit(0)

src = (T.parent / "app-src" / "engine.html").read_text(encoding="utf-8")


def fn(name):
    m = re.search(r"^function " + name + r"\(.*?^}\n", src, flags=re.S | re.M)
    assert m, name
    return m.group(0)


js_lib = fn("kvBrk") + fn("kvAgg") + fn("kvDaily")


def run_js(body, data):
    code = js_lib + "\nconst IN = " + json.dumps(data) + ";\n" + body
    r = subprocess.run([node, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)   # 經 stdin：數據大，命令列放唔落
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def walk(n, seed, start=date(2015, 1, 1), p0=100.0):
    """隨機 K 線（有大陽燭、跳空，突破先會多），淨係平日。"""
    rnd, d, out, p, t = random.Random(seed), [], [], p0, start
    while len(out) < n:
        if t.weekday() < 5:
            o = p * (1 + rnd.gauss(0, 0.004) + (rnd.random() < 0.08) * rnd.choice([-1, 1]) * 0.03)
            c = o * (1 + rnd.gauss(0, 0.02) + (rnd.random() < 0.1) * rnd.choice([-1, 1]) * 0.04)
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.004)))
            lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.004)))
            nd = 2 if p0 >= 1 else 9
            d.append(t.isoformat()), out.append((round(o, nd), round(h, nd), round(lo, nd), round(c, nd)))
            p = c
        t += timedelta(days=1)
    return d, out


def py_brk(d, rows, tick):
    ta = S.analyze(d, *[[r[k] for r in rows] for k in range(4)], keep=len(rows), tick=tick)
    return [(b["s"], b["i"], round(b["lv"], 2), b["dir"], b["k"]) for b in ta["brk"]]


total = 0
for seed in range(6):
    d, rows = walk(700, seed)
    O, H, L, C = ([r[k] for r in rows] for k in range(4))
    js = run_js("console.log(JSON.stringify(kvBrk(IN.o, IN.h, IN.l, IN.c, 0.01)))", dict(o=O, h=H, l=L, c=C))
    jb = [(b["s"], b["i"], round(b["lv"], 2), b["dir"], b["k"]) for b in js]
    pb = py_brk(d, rows, 0.01)
    total += len(pb)
    check(jb == pb and len(pb) > 3, f"日 K BOS／MSS：JS 同 Python 一樣（隨機數據 {seed}，{len(pb)} 次突破）")

# 加密細價：tick 用收市中位數 × 0.00001（同 crypto_research.py、btc.py 一樣）
d, rows = walk(500, 42, p0=0.0004)
O, H, L, C = ([r[k] for r in rows] for k in range(4))
tick = sorted(C)[len(C) // 2] * 1e-5
js = run_js(f"console.log(JSON.stringify(kvBrk(IN.o, IN.h, IN.l, IN.c, {tick!r})))", dict(o=O, h=H, l=L, c=C))
ta = S.analyze(d, O, H, L, C, keep=len(rows), tick=tick)
check([(b["s"], b["i"], b["dir"], b["k"]) for b in js] == [(b["s"], b["i"], b["dir"], b["k"]) for b in ta["brk"]] and len(js) > 3,
      f"加密細價（0.0004 美元）tick 一樣計，{len(js)} 次突破")

# 週 K／月 K：JS 合併 = bars.resample（跨年嗰個星期：2024-12-30 星期一同 2025-01-03 同一個星期）
d, rows = walk(2600, 7, start=date(2014, 12, 29))
O, H, L, C = ([r[k] for r in rows] for k in range(4))
for per in ("W", "M"):
    js = run_js(f"console.log(JSON.stringify(kvAgg(kvDaily(IN), '{per}')))", dict(d=d, o=O, h=H, l=L, c=C))
    py = bars.resample(d, O, H, L, C, per)
    same = js["d"] == py["d"] and all(all(abs(a - b) < 0.006 for a, b in zip(js[k], py[k])) for k in "ohlc")
    check(same and len(py["d"]) > (100 if per == "W" else 30), f"{'週' if per == 'W' else '月'} K 合併：JS 同 bars.resample 一樣（{len(py['d'])} 支）")
wk = bars.resample(["2024-12-27", "2024-12-30", "2025-01-03", "2025-01-06"], [1] * 4, [2] * 4, [0.5] * 4, [1.5] * 4, "W")
check(wk["d"] == ["2024-12-27", "2024-12-30", "2025-01-06"], "跨年星期：12-30（一）同 01-03（五）係同一支週 K")

# 週 K 嘅 BOS／MSS：app 用長歷史週 K 計，同 Python 對週 K 跑 analyze 一樣
w = bars.resample(d, O, H, L, C, "W")
js = run_js("console.log(JSON.stringify(kvBrk(IN.o, IN.h, IN.l, IN.c, 0.01)))", w)
ta = S.analyze(w["d"], w["o"], w["h"], w["l"], w["c"], keep=len(w["d"]), tick=0.01)
check([(b["s"], b["i"], b["dir"], b["k"]) for b in js] == [(b["s"], b["i"], b["dir"], b["k"]) for b in ta["brk"]], f"週 K BOS／MSS 一樣（{len(js)} 次）")

# 冇開高低（舊數據淨係收市）：JS 用收市砌（開 = 上一日收市）唔會爛
js = run_js("const S = kvDaily({d: IN.d, c: IN.c}); console.log(JSON.stringify([S.c.length, S.o[1] === IN.c[0], S.h.every((h, i) => h >= S.l[i])]))",
            dict(d=d[:50], c=C[:50]))
check(js == [50, True, True], "淨係收市都砌到 K 線")

# long_bars：股票事件線 + 加密都用
lb = bars.long_bars(d, O, H, L, C)
check(lb["start"] == d[0] and len(lb["m"]["d"]) >= 100 and lb["w"]["c"][-1] == C[-1], "long_bars 有週 K、月 K，最後一支收市 = 最新收市")
check(bars.long_bars(d[:1], O[:1], H[:1], L[:1], C[:1]) is None, "得一日數據就唔出長歷史")
print(f"\n全部 {ok} 項通過（日 K 隨機數據共 {total} 次突破對過）")
