# -*- coding: utf-8 -*-
"""2026-10-22 研究免費模式：冇 Claude key 用 Gemini 搜尋 + Mistral 分析；自動加持倉同排名頭 5；排程失敗唔當 workflow 失敗。
假 AI、假 build，唔上網、唔使錢。用法：python tests/test_research_free.py"""
import json
import os
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
APP = T.parent
OUTD = Path(os.environ.get("TEST_OUT") or T / "_out") / "research" / ("free-" + time.strftime("%Y%m%d-%H%M%S"))
OUTD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(APP / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("RESEARCH_REQUIRE_CLAUDE", None)
os.environ.update(GEMINI_API_KEY="fake-gem", MISTRAL_API_KEY="fake-mis", RESEARCH_OUT=str(OUTD))
import llm  # noqa: E402
import research as R  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# 1. 冇 Claude：研究次序 = Mistral、Gemini（gather 只有 Gemini 識上網）
def stop(sym):
    raise RuntimeError("stop")


R.collect = stop
try:
    R.build("AAA")
except RuntimeError:
    pass
check(llm.ORDER == ["mistral", "gemini"], f"冇 Claude key：研究用 {llm.ORDER}")
os.environ["ANTHROPIC_API_KEY"] = "fake-claude"
try:
    R.build("AAA")
except RuntimeError:
    pass
check(llm.ORDER == ["mistral", "gemini"], f"有 Claude key 都唔會自動 Claude 起頭（2026-10-23：成個 app 跟同一個次序）：{llm.ORDER}")
import importlib  # noqa: E402
os.environ["DEEPSEEK_API_KEY"] = "fake-ds"
importlib.reload(llm)
try:
    R.build("AAA")
except RuntimeError:
    pass
check(llm.ORDER == ["deepseek", "gemini"], f"有 DeepSeek key：研究 DeepSeek 先、Gemini 後備：{llm.ORDER}")
os.environ["AI_PROVIDER"] = "claude"
importlib.reload(llm)
try:
    R.build("AAA")
except RuntimeError:
    pass
check(llm.ORDER == ["claude", "gemini"], f"AI_PROVIDER=claude 先用 Claude：{llm.ORDER}")
os.environ.pop("AI_PROVIDER")
os.environ.pop("ANTHROPIC_API_KEY")
importlib.reload(llm)                                    # DeepSeek 主力
llm._raw = lambda path: {}
called, real_build, real_due = [], R.build, R.due_list
R.build, R.due_list = (lambda s, **k: called.append(s)), (lambda: [("AAA", "冇正式報告")])
llm.peak_now = lambda: True
check(R.main(["--due"]) == 0 and not called, "繁忙時段：自動研究唔做（留返非繁忙，慳錢）")
llm.peak_now = lambda: False
check(R.main(["--due"]) == 0 and called == ["AAA"], "非繁忙時段照做")
R.build, R.due_list = real_build, real_due
os.environ.pop("DEEPSEEK_API_KEY")
importlib.reload(llm)

# 2. 自動加模型持倉 + 排名頭 5
md = json.loads((APP / "docs" / "model_cont.json").read_text(encoding="utf-8"))
sc = json.loads((APP / "docs" / "scan.json").read_text(encoding="utf-8"))
held = [p["sym"] for p in md["positions"] if p["sym"] not in {"TQQQ", "IEF", "TMF", "UGL"}]
top = [r["sym"] for r in sc["ranking"][:5]]
auto = R.auto_syms()
check(auto[:len(held)] == held and set(top) <= set(auto), f"自動清單：持倉 {held} + 排名頭 5 {top} → {auto}")
due = [s for s, _ in R.due_list()]
check(set(held) <= set(due), f"到期清單包括持倉：{due[:8]}")

# 3. 排程（--due）失敗唔當 workflow 失敗；手動叫嘅照返 1
R.build = lambda s, **k: (_ for _ in ()).throw(RuntimeError("gemini 429"))
R.due_list = lambda: [("AAA", "冇正式報告"), ("BBB", "冇正式報告")]
check(R.main(["--due"]) == 0, "自動排程全部失敗：返 0（唔寄失敗 email）")
check(R.main(["AAA"]) == 1, "app 手動叫失敗：返 1")

# 4. 冇任何搜尋 key 就唔做
os.environ.pop("GEMINI_API_KEY")
check(R.main(["--due"]) == 0 and R.main(["AAA"]) == 1, "冇 Gemini／Claude（識上網）就唔做")
print(f"\n全部 {ok} 項通過")
