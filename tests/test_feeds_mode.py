# -*- coding: utf-8 -*-
"""2026-10-24 老師：「唔建議更新得咁密，淨係新聞密就得，其他全部淨係排程，除非user自己撳refresh」。
測 feeds_gate.py 揀「全部」定「淨係新聞」、feeds.yml 同閘門一致、ai.py 淨係新聞嗰次唔寫其他 AI。假數據，唔上網、唔使錢。
用法：python tests/test_feeds_mode.py"""
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
for k in ("GITHUB_OUTPUT", "GITHUB_EVENT_NAME", "FEEDS_FULL"):
    os.environ.pop(k, None)
import importlib  # noqa: E402

import feeds_gate as G  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


def no_net():
    raise RuntimeError("測試唔上網")


G.bars = no_net

# 1. 邊次做全部
check(all(G.is_full("schedule", c) for c in G.FULL_CRONS), f"全部更新排程：{G.FULL_CRONS}")
check(not G.is_full("schedule", "7,22,37,52 * * * *") and not G.is_full("schedule", "41 10,12 * * 1-5"), "15 分鐘同開市前新聞排程：淨係新聞")
check(G.is_full("workflow_dispatch", "", "") and not G.is_full("workflow_dispatch", "", "1"), "app 撳「重新整理」全部；開 app 自動（relay=1）淨係新聞")
check(G.is_full("push"), "改 workflow push：全部")

# 2. 全部更新一定行（唔理啱啱更新過）；新聞排程照舊 10 分鐘內唔重覆
just = int(time.time()) - 60
o = G.main("schedule", just, "41 11 * * *")
check(o["run"] == 1 and o["full"] == 1, f"全部更新排程：1 分鐘前更新過都照行（{o['why']}）")
o = G.main("schedule", just, "7,22,37,52 * * * *")
check(o["run"] == 0 and o["full"] == 0, f"新聞排程：1 分鐘前更新過就唔行（{o['why']}）")
o = G.main("workflow_dispatch", just, "", "1")
check(o["run"] == 1 and o["full"] == 0, "開 app 自動：一定行，淨係新聞")
old_full = int(time.time()) - 15 * 3600
o = G.main("schedule", just, "7,22,37,52 * * * *", "", old_full)
check(o["run"] == 1 and o["full"] == 1 and "跳咗排程" in o["why"], f"GitHub 跳咗全部更新、上次全部更新 15 個鐘前：新聞排程嗰次升級做全部（{o['why']}）")
o = G.main("schedule", just, "7,22,37,52 * * * *", "", int(time.time()) - 3 * 3600)
check(o["run"] == 0 and o["full"] == 0, "上次全部更新 3 個鐘前：新聞排程照舊（1 分鐘前更新過就唔行）")
o = G.main("workflow_dispatch", just, "", "1", old_full)
check(o["full"] == 0, "開 app 自動嗰種唔會升級做全部（淨係排程或者自己撳重新整理先做全部）")
o = G.main("schedule", just, "7,22,37,52 * * * *", "", 0)
check(o["full"] == 0, "冇全部更新紀錄（攞唔到）：唔升級")

# 3. feeds.yml 同閘門一致
Y = (APP / ".github" / "workflows" / "feeds.yml").read_text(encoding="utf-8")
crons = re.findall(r'cron:\s*"([^"]+)"', Y)
check(set(G.FULL_CRONS) <= set(crons), f"FULL_CRONS 全部喺 feeds.yml 排程入面：{crons}")
pushed = set(re.search(r"git add news\.json econ\.json \$\(ls ([^)]+?) 2>", Y).group(1).split()) - {"ai_usage.json"}
step = re.search(r"淨係新聞：其他檔沿用上一份.*?for f in ([^;]+); do(.*?)done", Y, re.S)
carry = set(step.group(1).split())
check(pushed == carry, f"淨係新聞嗰次：推上去嘅其他檔全部沿用上一份（{sorted(pushed - carry) or '冇漏'}）")
check("prev/$f" in step.group(2) and "curl" not in step.group(2) and "git fetch -q --depth 1 origin feeds" in Y,
      "沿用上一份用 git 攞嘅 feeds 分支（唔經 raw CDN 快取）")
gated = Y.count("if: needs.guard.outputs.full == '1'")
check(gated == len(carry), f"抓其他數據嘅 {gated} 個步驟淨係全部更新先做")
check("FEEDS_FULL: ${{ needs.guard.outputs.full }}" in Y and '"${{ github.event.schedule }}"' in Y, "ai.py 知道係唔係全部更新；閘門收到觸發嘅 cron")
check('feeds/full_at.txt"' in Y and '"$full_at"' in Y and "date -u +%s > full_at.txt" in Y and "cp ../prev/full_at.txt" in Y and "git add full_at.txt" in Y,
      "全部更新寫低時間（full_at.txt），淨係新聞抄返上一份；閘門讀佢")

# 4. ai.py：淨係新聞嗰次唔寫宏觀思考、加密、大額轉帳、商品分析，沿用上一份宏觀思考
import ai  # noqa: E402
import llm  # noqa: E402

out = Path(os.environ.get("TEST_OUT") or T / "_out") / "feeds_mode" / time.strftime("%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)
(out / "news.json").write_text(json.dumps({"items": []}), encoding="utf-8")
(out / "econ.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
P = {"think": {"q": "舊思考"}, "digest": {"hi": []}, "ai_at": recent}
(out / "prev").mkdir()
(out / "prev" / "news.json").write_text(json.dumps(P), encoding="utf-8")
os.environ["FEEDS_PREV"] = str(out / "prev")
check(ai.prev("news.json") == P, "ai.py 上一份優先讀 workflow 用 git 攞咗嘅（FEEDS_PREV）")
os.environ.pop("FEEDS_PREV")
llm.available = lambda: True
llm.start = llm.finish = lambda *a, **k: None
llm.status = lambda: {"provider": "test"}
ai.prev = lambda f: P if f == "news.json" else {}
for fn in ("light_change", "commod_alert", "rates_alert", "tq_alert", "fut_alert", "intraday_move", "premarket"):
    setattr(ai, fn, lambda: None)
ai.context = lambda: ("", "")
ai.hi_titles = lambda N, now, hours=6: []
ai.fresh_econ = lambda E, now: []
ai.translate = lambda *a, **k: "冇新嘢"
ai.econ_ai = ai.fed_ai = lambda *a, **k: "冇新嘢"
ran = []
ai.extras = lambda *a, **k: ran.append(1)
sys.argv = ["ai.py", str(out)]
ai.FULL = False
ai.main()
N = json.loads((out / "news.json").read_text(encoding="utf-8"))
check(not ran and N["think"] == {"q": "舊思考"} and N["digest"] == {"hi": []}, "淨係新聞：唔叫其他 AI，宏觀思考同今日重點沿用上一份")
ai.FULL = True
ai.main()
check(ran == [1], "全部更新：會寫宏觀思考、加密、大額轉帳、商品分析")
check(importlib.reload(ai).FULL, "冇 FEEDS_FULL（本機手動跑）當全部")
print(f"\n全部 {ok} 項通過")
