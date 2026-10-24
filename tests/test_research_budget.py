# -*- coding: utf-8 -*-
"""2026-10-21 Codex 改卷：研究每月上限 + 失敗都記帳（假 build，唔上網、唔使錢）。用法：python tests/test_research_budget.py"""
import json
import os
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
OUTD = Path(os.environ.get("TEST_OUT") or T / "_out") / "research" / ("budget-" + time.strftime("%Y%m%d-%H%M%S"))
OUTD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(ANTHROPIC_API_KEY="test-key-not-real", RESEARCH_OUT=str(OUTD), RESEARCH_MONTH_USD="40", RESEARCH_EST_USD="1.5")
import llm  # noqa: E402
import research as R  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def set_spent(x):
    (OUTD / "index.json").write_text(json.dumps(dict(items=[], usage={time.strftime("%Y-%m"): x})), encoding="utf-8")


ran = []


def fake_build(sym, **kw):
    ran.append(sym)
    llm.USAGE.append(dict(usd=0.25))                       # 用咗錢先失敗
    raise RuntimeError("假失敗")


R.build = fake_build
R.OUT = OUTD

# 1. 三份都失敗：已用嘅錢照記帳（之前月帳仍係 0）
set_spent(0)
R.main(["AAA", "BBB", "CCC"])
check(len(ran) == 3 and abs(R.month_spent() - 0.75) < 1e-9, f"失敗都記帳：月帳 {R.month_spent()}")

# 2. 月帳 38.4：第一份做（38.4 + 1.5 ≤ 40），之後 38.65 + 1.5 > 40 就停
ran.clear()
set_spent(38.4)
R.main(["AAA", "BBB", "CCC"])
check(ran == ["AAA"], f"每份開始前查上限：只做咗 {ran}，月帳 {R.month_spent():.2f}")

# 3. --force 照做
ran.clear()
R.main(["AAA", "--force"])
check(ran == ["AAA"], "--force 照做")
print(f"\n全部 {ok} 項通過")
