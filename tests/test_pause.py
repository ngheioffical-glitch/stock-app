# -*- coding: utf-8 -*-
"""2026-11-02 老師：「新增暫停鍵，冇撳暫停就照依家咁樣排程 有就咩都唔好郁 淨係更新ai今日重點」。
測 scanner/pause.py（閘門、寫狀態）、feeds_gate.py 暫停時淨係新聞、各 workflow 有暫停檢查、ai.py 暫停時淨係寫今日重點。假數據，唔上網。
用法：python tests/test_pause.py"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

T = Path(__file__).resolve().parent
APP = T.parent
sys.path.insert(0, str(APP / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
for k in ("GITHUB_OUTPUT", "GITHUB_EVENT_NAME", "FEEDS_FULL", "FEEDS_PAUSED"):
    os.environ.pop(k, None)
import feeds_gate as G  # noqa: E402
import pause  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


out = Path(os.environ.get("TEST_OUT") or T / "_out") / "pause" / time.strftime("%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)
f = out / "pause.json"

# 1. 閘門
check(pause.gate("schedule", "", f) == (False, False), "冇 pause.json：當冇暫停，照排程")
f.write_text("壞檔", encoding="utf-8")
check(pause.gate("schedule", "", f) == (False, False), "壞檔：當冇暫停")
d = pause.set_state(True, f)
check(d["paused"] is True and "HKT" in d["at"] and pause.paused(f), "set 1：寫 paused=true 同時間")
check(pause.gate("schedule", "", f) == (True, True), "暫停中：排程唔做")
check(pause.gate("push", "", f) == (True, True), "暫停中：push 觸發都唔做")
check(pause.gate("workflow_dispatch", "1", f) == (True, True), "暫停中：app 自動更新（relay=1）唔做")
check(pause.gate("workflow_dispatch", "", f) == (True, False), "暫停中：用戶自己撳照做")
pause.set_state(False, f)
check(pause.gate("schedule", "", f) == (False, False), "set 0：恢復排程")

# 2. feeds 閘門：暫停中全部更新排程都變淨係新聞
just = int(time.time()) - 3600
o = G.main("schedule", just, "41 11 * * *", "", 0, paused=True)
check(o["full"] == 0 and o["paused"] == 1 and "暫停中" in o["why"], "暫停中：全部更新排程都淨係新聞 + AI 今日重點")
o = G.main("schedule", just, "7,22,37,52 * * * *", "", int(time.time()) - 20 * 3600, paused=True)
check(o["full"] == 0, "暫停中：全部更新太耐都唔升級")
o = G.main("schedule", just, "41 11 * * *")
check(o["full"] == 1 and o["paused"] == 0, "冇暫停：照舊全部更新")

# 3. workflow：排程嗰啲一開始檢查暫停
W = APP / ".github" / "workflows"
for n, job in (("daily-scan", "scan"), ("intraday", "scan"), ("radar", "radar"), ("events", "events"), ("research", "research"), ("serenity", "serenity")):
    y = (W / f"{n}.yml").read_text(encoding="utf-8")
    check("scanner/pause.py gate" in y and re.search(rf"\n  {job}:\n    needs: pz\n    if: needs.pz.outputs.skip != '1'", y) and "docs/pause.json" in y,
          f"{n}.yml：先行暫停檢查，暫停中主 job 唔做")
Y = (W / "feeds.yml").read_text(encoding="utf-8")
check("paused: ${{ steps.g.outputs.paused }}" in Y and "FEEDS_PAUSED: ${{ needs.guard.outputs.paused }}" in Y and "scanner/pause.py" in Y,
      "feeds.yml：閘門讀暫停狀態，ai.py 收到 FEEDS_PAUSED")
P = (W / "pause.yml").read_text(encoding="utf-8")
check("workflow_dispatch" in P and "scanner/pause.py set" in P and "git add docs/pause.json" in P and "schedule" not in P, "pause.yml：淨係手動觸發，寫 docs/pause.json")
check(json.loads((APP / "docs" / "pause.json").read_text(encoding="utf-8"))["paused"] is False, "預設 docs/pause.json 係冇暫停")

# 4. ai.py：暫停中淨係寫今日重點
os.environ["FEEDS_PAUSED"] = "1"
import ai  # noqa: E402
import llm  # noqa: E402

check(ai.PAUSED, "FEEDS_PAUSED=1 → ai.PAUSED")
o2 = out / "ai"
o2.mkdir()
(o2 / "news.json").write_text(json.dumps({"items": []}), encoding="utf-8")
(o2 / "econ.json").write_text(json.dumps({"rows": [{"t": "1", "name": "CPI"}]}), encoding="utf-8")
old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
PV = {"think": {"q": "舊"}, "digest": {"hi": [], "points": ["舊重點"]}, "ai_at": old, "fed": {"x": "舊聯儲"}, "tr_at": old}
llm.available = lambda: True
llm.start = llm.finish = lambda *a, **k: None
llm.status = lambda: {"provider": "test"}
ai.prev = lambda n: PV if n == "news.json" else {"rows": [{"t": "1", "name": "CPI", "ai": "舊解讀"}]} if n == "econ.json" else {}
for fn in ("light_change", "commod_alert", "rates_alert", "tq_alert", "fut_alert", "intraday_move", "premarket"):
    setattr(ai, fn, lambda: None)
ai.hi_titles = lambda N, now, hours=6: []
ai.fresh_econ = lambda E, now: []
calls = []
ai.translate = lambda *a, **k: calls.append(("translate", k.get("allow"))) or "沿用"
ai.econ_ai = lambda *a, **k: calls.append("econ") or "x"
ai.fed_ai = lambda *a, **k: calls.append("fed") or "x"
ai.digest = lambda *a, **k: (calls.append("digest") or ({"points": ["新重點"]}, "寫好"))
ai.extras = lambda *a, **k: calls.append("extras")
ai.FULL = True
sys.argv = ["ai.py", str(o2)]
ai.main()
N = json.loads((o2 / "news.json").read_text(encoding="utf-8"))
E = json.loads((o2 / "econ.json").read_text(encoding="utf-8"))
check(("translate", False) in calls and "econ" not in calls and "fed" not in calls and "extras" not in calls,
      f"暫停中：翻譯唔叫 AI、數據解讀／聯儲局／全部更新嗰啲都唔做（{calls}）")
check("digest" in calls and N["digest"] == {"points": ["新重點"]}, "暫停中：AI 今日重點照寫")
check(N["fed"] == {"x": "舊聯儲"} and E["rows"][0].get("ai") == "舊解讀" and not N.get("ai_err"), "暫停中：聯儲局、數據解讀沿用上一份，唔當出錯")
os.environ.pop("FEEDS_PAUSED")
print(f"\n全部 {ok} 項通過")
