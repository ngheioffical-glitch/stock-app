"""暫停鍵（2026-11-02 老師：「新增暫停鍵，冇撳暫停就照依家咁樣排程 有就咩都唔好郁 淨係更新ai今日重點」）。
狀態放 docs/pause.json（{"paused": true/false, "at": ...}），app 撳掣 → .github/workflows/pause.yml 寫入。
- 暫停中：排程同 app 自動更新（feeds relay=1）一律唔做；淨係 feeds.yml 照攞新聞 + 寫 AI 今日重點（ai.py FEEDS_PAUSED=1）。
- 用戶自己撳嘅（workflow_dispatch，唔係 relay）照做：老師自己要嘅。
用法：
  python scanner/pause.py gate <github.event_name> [relay]   → 印 paused=0|1、skip=0|1（寫入 $GITHUB_OUTPUT 用）
  python scanner/pause.py set 1|0                             → 寫 docs/pause.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FILE = Path(__file__).resolve().parents[1] / "docs" / "pause.json"


def paused(f=FILE):
    try:
        return bool(json.loads(Path(f).read_text(encoding="utf-8")).get("paused"))
    except Exception:  # noqa: BLE001  冇檔或者壞檔 = 冇暫停（照舊排程）
        return False


def gate(event, relay="", f=FILE):
    """返 (paused, skip)：暫停中而且唔係用戶自己撳 → skip。"""
    p = paused(f)
    user = event == "workflow_dispatch" and str(relay).strip() != "1"
    return p, p and not user


def set_state(on, f=FILE):
    d = dict(paused=bool(on), at=datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT"))
    Path(f).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "gate":
        p, s = gate(a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
        print(f"paused={int(p)}")
        print(f"skip={int(s)}")
    elif a and a[0] == "set":
        print(set_state(a[1].strip() in ("1", "true", "on") if len(a) > 1 else True))
    else:
        raise SystemExit(__doc__)
