"""新聞排程閘門：.github/workflows/feeds.yml 嘅 guard job 用（2026-10-15）。

用戶：「收盤後追蹤期貨跌幾多先更新一下新聞，方便 user 知道發生咩事，但係又可以平衡唔會搞到 GitHub 用太多被封」。
規則（只管排程觸發；app 撳「重新整理」同開 app 自動更新一定行）：
  1. feeds 分支 10 分鐘內啱啱更新過 → 唔行（避免重覆）。
  2. 美股開市時間（紐約星期一至五 09:30–16:00）→ 行。
  2b. 開市前（紐約平日 04:00–09:30；2026-10-15 用戶：「開市前一定要更新一次」）：今日 04:00 之後未更新過 → 行；否則距離上次夠 60 分鐘 → 行。
      輸出 pre=1，ai.py 會寫「開市前版」今日重點（期貨、今日數據、今日業績）。
  3. 收市後同週末：Nasdaq 100 期貨（NQ=F）由上一個 16:00 收市計，同上次更新嗰陣比再郁 0.75% 或以上 → 行（即刻更新新聞，AI 解釋）；
     （2026-10-15 由 1% 改 0.75%：過去兩年 1% 大約四晚一晚，0.75% 大約五晚兩晚，用戶覺得 1% 太鬆）
     否則距離上次更新夠 4 個鐘先行（底線）。期貨數據攞唔到：夠 2 個鐘就行。
唔理行唔行都計期貨：收市後由收市計郁 0.75% 或以上就輸出提示，ai.py 寫入今日重點同 app 橫額。
全部定淨係新聞（2026-10-24 老師：「唔建議更新得咁密，淨係新聞密就得，其他全部淨係排程，除非user自己撳refresh」）：
  full=1（全部：加密、債息、商品、Trump、Serenity、業績、AI 宏觀思考等）只限 FULL_CRONS 排程、app 撳「重新整理」（workflow_dispatch 冇 relay）、
  改 workflow push；full 一定行（唔理 10 分鐘內更新過）。其他（15 分鐘排程、app 開嗰陣自動 relay=1）full=0，淨係新聞。
輸出（GITHUB_OUTPUT；冇就印出嚟）：run=0／1、why=原因、fut=期貨提示（冇就空）、fut_b=檔位（每 0.75% 一格，向零取整，例如 −1.6% → -2）、fut_d=參考收市日、
  pre=1／0（開市前時段）、fut_now=期貨而家由收市計郁幾多（收市後先有，唔理大細）、full=1／0。
用法：python scanner/feeds_gate.py 事件名 上次更新（Unix 秒） [觸發嘅 cron] [relay]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MOVE = 0.0075          # 期貨再郁 0.75% 先算大郁（每 0.75% 一格）
BASE_H, FAIL_H, DEDUPE_MIN = 4, 2, 10
# 全部更新嘅排程（要同 feeds.yml 嘅 cron 字串一模一樣）：香港 06:29（每日，美股收市後）、19:41（每日，週末加密都更新）、21:11（平日開市前最後一次）
FULL_CRONS = ("29 22 * * *", "41 11 * * *", "11 13 * * 1-5")
UA ={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def us_open(t):
    n = t.astimezone(NY)
    return n.weekday() < 5 and (9, 30) <= (n.hour, n.minute) < (16, 0)


def pre_open(t):
    """開市前時段：紐約平日 04:00–09:30。"""
    n = t.astimezone(NY)
    return n.weekday() < 5 and (4, 0) <= (n.hour, n.minute) < (9, 30)


def last_close(now):
    """最近一個已經過咗嘅紐約 16:00（平日）。"""
    n = now.astimezone(NY)
    d = n.replace(hour=16, minute=0, second=0, microsecond=0)
    if n < d:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def bars():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF?range=5d&interval=5m"
    r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())["chart"]["result"][0]
    cl = r["indicators"]["quote"][0]["close"]
    return [(t, c) for t, c in zip(r["timestamp"], cl) if c]


def futures(now, last_ts):
    """（由收市計而家郁幾多、上次更新嗰陣郁幾多、收市價、而家價）；收市前（開市時間）返 None。"""
    if us_open(now):
        return None
    b = bars()
    cut = last_close(now)
    ref = [c for t, c in b if t < cut.timestamp()]                    # 收市前最後一條 5 分鐘線（15:55 開、16:00 收）
    while not ref and cut > now - timedelta(days=6):                    # 假期冇數據：再向前搵
        cut -= timedelta(days=1)
        ref = [c for t, c in b if t < cut.timestamp()]
    if not ref:
        raise RuntimeError("搵唔到收市價")
    c0, p_now = ref[-1], b[-1][1]
    then = [c for t, c in b if cut.timestamp() <= t <= last_ts]
    p_then = then[-1] if then else c0
    return p_now / c0 - 1, p_then / c0 - 1, c0, p_now, str(cut.date())


def is_full(event, cron="", relay=""):
    """全部更新定淨係新聞：排程表 FULL_CRONS、app 手動撳「重新整理」、改 workflow push 先做全部。"""
    if event == "schedule":
        return cron.strip() in FULL_CRONS
    if event == "workflow_dispatch":
        return relay.strip() != "1"
    return event == "push"


def main(event, last_ts, cron="", relay=""):
    now = datetime.now(NY)
    full = is_full(event, cron, relay)
    age_min = (time.time() - last_ts) / 60 if last_ts else 1e9
    fut, fut_b, fut_d, fut_now, f = "", "", "", "", None
    pre = pre_open(now)
    try:
        f = futures(now, last_ts)
        if f:
            fut_now = f"Nasdaq 100 期貨由 16:00 收市計 {f[0] * 100:+.1f}%（{f[2]:,.0f} → {f[3]:,.0f}）"
        if f and abs(f[0]) >= MOVE:
            fut = f"收市後 Nasdaq 100 期貨{'跌' if f[0] < 0 else '升'} {abs(f[0]) * 100:.1f}%（16:00 收市 {f[2]:,.0f} → 而家 {f[3]:,.0f}）"
            fut_b, fut_d = str(int(f[0] / MOVE)), f[4]
    except Exception as e:  # noqa: BLE001
        f = "err"
        print(f"期貨攞唔到：{e}")
    if event != "schedule":
        run, why = 1, f"{event}：一定行"
    elif full:
        run, why = 1, f"全部更新排程（{cron}）：一定行"
    elif age_min < DEDUPE_MIN:
        run, why = 0, f"{age_min:.0f} 分鐘前啱啱更新"
    elif us_open(now):
        run, why = 1, "開市時間"
    elif pre and last_ts < now.replace(hour=4, minute=0, second=0, microsecond=0).timestamp():
        run, why = 1, "開市前更新（今日第一次）"
    elif pre:
        run, why = int(age_min >= 60), f"開市前，距離上次 {age_min:.0f} 分鐘（夠 60 分鐘先再行）"
    elif f == "err":
        run, why = int(age_min >= FAIL_H * 60), f"期貨攞唔到，距離上次 {age_min / 60:.1f} 個鐘（夠 {FAIL_H} 個鐘先行）"
    elif f and abs(f[0] - f[1]) >= MOVE:
        run, why = 1, f"收市後期貨再郁 {abs(f[0] - f[1]) * 100:.1f}%（由收市計 {f[0] * 100:+.1f}%，上次更新時 {f[1] * 100:+.1f}%）"
    else:
        run, why = int(age_min >= BASE_H * 60), f"收市後期貨冇大郁，距離上次 {age_min / 60:.1f} 個鐘（夠 {BASE_H} 個鐘先行）"
    out = {"run": run, "why": why, "fut": fut, "fut_b": fut_b, "fut_d": fut_d, "pre": int(pre), "fut_now": fut_now, "full": int(full)}
    print(json.dumps(out, ensure_ascii=False))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("".join(f"{k}={v}\n" for k, v in out.items()))
    return out


if __name__ == "__main__":
    a = sys.argv[1:] + ["", "", ""]
    main(a[0], int(a[1] or 0), a[2], a[3])
