# -*- coding: utf-8 -*-
"""2026-10-24 scanner/intraday.py：排程改每個鐘（:34）之後，收市前最後半個鐘要靠收市後補掃記返（Codex 第二輪質疑「唔會漏記」，Claude 核實有漏洞）。
假 5 分鐘 K、假 scan.json、固定時間，唔上網。用法：python tests/test_intraday.py"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

T = Path(__file__).resolve().parent
APP = T.parent
sys.path.insert(0, str(APP / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import intraday as I  # noqa: E402

NY = ZoneInfo("America/New_York")
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


DAY = "2026-10-23"                       # 星期五（夏令）
out = Path(os.environ.get("TEST_OUT") or T / "_out") / "intraday" / time.strftime("%Y%m%d-%H%M%S")
(out / "docs").mkdir(parents=True, exist_ok=True)
(out / "docs" / "scan.json").write_text(json.dumps({"date": "2026-10-22", "next_day": DAY, "green": True, "ranking": [
    {"sym": "AAA", "status": "候選", "rank": 1, "pivot": 100.0, "stop": 90.0, "close": 98.0}]}), encoding="utf-8")
I.ROOT = out
idx = pd.date_range(f"{DAY} 09:30", f"{DAY} 15:55", freq="5min", tz=NY)
px = pd.Series(99.0, index=idx)
px[pd.Timestamp(f"{DAY} 15:40", tz=NY)] = 101.0           # 收市前 20 分鐘先企穩前高（15:40 開、15:45 收）
BARS = pd.DataFrame({"open": px - 0.5, "high": px + 0.5, "low": px - 1.0, "close": px})
I.bars = lambda syms, day: {s: BARS.copy() for s in syms}
NOW = [None]


class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW[0].astimezone(tz) if tz else NOW[0]


I.datetime = FakeDT


def run(hhmm, prev=None):
    NOW[0] = datetime.fromisoformat(f"{DAY}T{hhmm}:00").replace(tzinfo=NY).astimezone(timezone.utc)
    sys.argv = ["intraday.py", str(out)] + ([str(prev)] if prev else [])
    I.main()
    return json.loads((out / "intraday.json").read_text(encoding="utf-8"))


r1 = run("15:34")
c = r1["cands"][0]
check(r1["in_session"] and "c5" not in c, "15:34（最後一次開市時間排程）：15:40 嗰條 K 仲未出，未記到")
(out / "prev.json").write_text(json.dumps(r1), encoding="utf-8")
r2 = run("16:34", out / "prev.json")
c = r2["cands"][0]
check(not r2["in_session"] and c.get("c5", {}).get("t") == "15:45" and c["c5"].get("seen_utc", "").startswith(f"{DAY}T20:34"),
      f"16:34 收市後補掃：記返 15:45 企穩，發現時間另外記（{c.get('c5')}）")
check(r2["runs"][-1].get("final") is True and len(r2["runs"]) == 2, "補掃標明 final，同日紀錄接落去")
r3 = run("17:34", out / "prev.json")
check(r3["runs"][-1].get("skip") == "收市時間" and not r3["cands"], "收市後超過 1 個鐘：唔再掃")

# 排程本身：夏令同冬令每日都有一次落喺收市後補掃時段（16:10–17:00 紐約時間）
Y = (APP / ".github" / "workflows" / "intraday.yml").read_text(encoding="utf-8")
m, h = re.search(r'cron:\s*"(\S+) (\S+) \* \* 1-5"', Y).groups()
mins = [int(x) for x in m.split(",")]
a, b = (int(x) for x in h.split("-"))
for day in ("2026-07-15", "2026-12-16"):
    runs = [datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+00:00").astimezone(NY) for hh in range(a, b + 1) for mm in mins]
    fin = [t.strftime("%H:%M") for t in runs if (16, 10) < (t.hour, t.minute) <= (17, 0)]
    check(fin, f"{day}：有收市後補掃（紐約 {fin}）")
print(f"\n全部 {ok} 項通過")
