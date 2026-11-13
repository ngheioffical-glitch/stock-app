# -*- coding: utf-8 -*-
"""2026-11-13 scanner/feeds_gate.py 時間閘門行為測試（流程審計 S6：test_feeds_mode.py 淨係測全部定淨係新聞，冇測 10 分鐘去重、
開市／開市前、收市後期貨再郁 0.75%、期貨攞唔到）。假時間、假期貨 5 分鐘線、唔上網、唔改規則。
用法：python tests/test_feeds_gate.py"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.pop("GITHUB_OUTPUT", None)
import feeds_gate as G  # noqa: E402

NY = ZoneInfo("America/New_York")
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


class NowDT(datetime):
    NOW = None

    @classmethod
    def now(cls, tz=None):
        return cls.NOW.astimezone(tz) if tz else cls.NOW


G.datetime = NowDT
CLOCK = [0.0]
G.time = NS(time=lambda: CLOCK[0])
BARS = []
G.bars = lambda: list(BARS)


def at(*ny):
    NowDT.NOW = datetime(*ny, tzinfo=NY)
    CLOCK[0] = NowDT.NOW.timestamp()


def ago(minutes):
    return int(CLOCK[0] - minutes * 60)


def series(day, until, price_at):
    """紐約 day 09:30 起每 5 分鐘一條線到 until（datetime），價 = price_at(該線時間)。"""
    out, t = [], datetime(*day, 9, 30, tzinfo=NY)
    while t <= until:
        out.append((int(t.timestamp()), price_at(t)))
        t += timedelta(minutes=5)
    return out


NEWS = "7,22,37,52 * * * *"
# 星期二 2026-11-10：收市前 20000，18:00 起 20040（+0.2%），19:30 起 20240（+1.2%）
px = lambda t: 20000.0 if t.hour < 16 else 20040.0 if (t.hour, t.minute) < (19, 30) else 20240.0  # noqa: E731
at(2026, 11, 10, 20, 0)
BARS[:] = series((2026, 11, 10), NowDT.NOW, px)
o = G.main("schedule", ago(5), NEWS)
check(o["run"] == 0 and "啱啱更新" in o["why"] and o["full"] == 0, "排程（淨係新聞）：5 分鐘前啱啱更新 → 唔行")
o = G.main("schedule", ago(120), NEWS)
check(o["run"] == 1 and o["why"].startswith("收市後期貨再郁 1.0%") and o["fut_b"] == "1" and o["fut_d"] == "2026-11-10" and "升 1.2%" in o["fut"],
      "收市後：上次更新（18:00）期貨 +0.2%、而家 +1.2% → 再郁 1% ≥ 0.75% → 即刻行；提示寫升 1.2%、檔位 1")
at(2026, 11, 10, 21, 0)
BARS[:] = series((2026, 11, 10), NowDT.NOW, px)
o = G.main("schedule", ago(60), NEWS)
check(o["run"] == 0 and "冇大郁" in o["why"], "收市後：上次更新（20:00）已經 +1.2%、而家都係 → 冇再郁，1 個鐘 < 4 個鐘 → 唔行")
at(2026, 11, 10, 23, 40)
BARS[:] = series((2026, 11, 10), NowDT.NOW, px)
o = G.main("schedule", ago(239), NEWS)
check(o["run"] == 0 and "冇大郁" in o["why"], "收市後：上次更新（19:41）同而家一樣 +1.2%，3.98 個鐘 → 唔行")
o = G.main("schedule", ago(241), NEWS)
check(o["run"] == 1 and "冇大郁" in o["why"], "收市後冇大郁但距離上次夠 4 個鐘（19:39）→ 行（底線）")
o = G.main("schedule", ago(5), "41 11 * * *")
check(o["run"] == 1 and o["full"] == 1, "全部更新排程：5 分鐘前更新過都照行")
o = G.main("workflow_dispatch", ago(1), "", "1")
check(o["run"] == 1 and o["full"] == 0, "app 開嗰陣自動（relay=1）：一定行、淨係新聞")

at(2026, 11, 10, 11, 0)
o = G.main("schedule", ago(30), NEWS)
check(o["run"] == 1 and o["why"] == "開市時間" and o["fut_now"] == "" and o["pre"] == 0, "開市時間：30 分鐘前更新過照行；開市時間唔計期貨")
o = G.main("schedule", ago(9), NEWS)
check(o["run"] == 0, "開市時間：9 分鐘前更新過 → 唔行（10 分鐘去重）")

at(2026, 11, 10, 5, 0)
BARS[:] = series((2026, 11, 9), datetime(2026, 11, 10, 5, 0, tzinfo=NY), lambda t: 20000.0)
o = G.main("schedule", int(datetime(2026, 11, 10, 3, 50, tzinfo=NY).timestamp()), NEWS)
check(o["run"] == 1 and o["why"] == "開市前更新（今日第一次）" and o["pre"] == 1, "開市前（05:00）：今日 04:00 之後未更新過 → 行")
at(2026, 11, 10, 6, 0)
o = G.main("schedule", ago(30), NEWS)
check(o["run"] == 0 and o["pre"] == 1 and "30 分鐘" in o["why"], "開市前（06:00）：今日 05:30 更新過 → 唔行")
o = G.main("schedule", ago(61), NEWS)
check(o["run"] == 1 and o["pre"] == 1 and "今日第一次" not in o["why"], "開市前（06:00）：今日 04:59 更新過、距離上次 61 分鐘 → 行")


def boom():
    raise OSError("Yahoo 503")


G.bars = boom
at(2026, 11, 10, 22, 0)
o = G.main("schedule", ago(121), NEWS)
check(o["run"] == 1 and "期貨攞唔到" in o["why"] and o["fut"] == "", "收市後期貨攞唔到：距離上次夠 2 個鐘 → 行")
o = G.main("schedule", ago(90), NEWS)
check(o["run"] == 0 and "期貨攞唔到" in o["why"], "收市後期貨攞唔到：1.5 個鐘 → 唔行")
o = G.main("schedule", ago(600), NEWS, "", 0, paused=True)
check(o["paused"] == 1 and o["why"].startswith("暫停中") and o["full"] == 0, "暫停中：淨係新聞，原因寫明暫停")
print(f"\n全部 {ok} 項通過")
