# -*- coding: utf-8 -*-
"""2026-11-13 scanner/crypto_research.py 細工具行為測試（流程審計 S6：test_crypto_research.py 將 get 換走，重試、單位、解鎖 30／90 日分開、
失敗照記帳都冇測過）。假回覆、唔上網、唔叫 AI、唔改規則。
1. get：404 → None；429 等 25、50 秒再試，最後一次唔再等；斷線等 5 秒再試；其他 HTTP 錯即刻報
2. ratio、money 單位界線
3. unlocks：30 日同 90 日分開計；下次解鎖日、邊個解鎖（90 日）；冇收錄／冇價／出錯 → None
4. main：研究失敗但已經用咗 AI → 照記入每月用量
用法：python tests/test_crypto_small.py"""
import io
import json
import os
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(os.environ.get("TEST_OUT") or T / "_out") / "crypto_small" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(CRYPTO_OUT=str(OUT), CRYPTO_MONTH_USD="10", CRYPTO_EST_USD="0.3")
import crypto_research as C  # noqa: E402

SLEPT = []
C.time.sleep = lambda s: SLEPT.append(s)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. get
class Resp:
    def __init__(self, b):
        self.b = b

    def read(self):
        return self.b


def http(code):
    return urllib.error.HTTPError("https://x.test", code, f"HTTP {code}", {}, io.BytesIO(b""))


URLS = []


def serve(seq):
    def f(req, timeout=None):
        URLS.append(req.full_url)
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return Resp(json.dumps(x).encode())
    C.urllib.request.urlopen = f


def run(seq, tries=3):
    URLS.clear()
    SLEPT.clear()
    serve(seq)
    try:
        return C.get("https://x.test/a", tries=tries), None
    except Exception as e:  # noqa: BLE001
        return None, e


REAL = C.urllib.request.urlopen
got, err = run([http(404), {"never": 1}])
check(got is None and err is None and len(URLS) == 1 and SLEPT == [], "get：404 → None（冇呢個幣），唔重試")
got, err = run([http(429), http(429), {"ok": 1}])
check(got == {"ok": 1} and SLEPT == [25, 50] and len(URLS) == 3, "get：429（每分鐘上限）→ 等 25 秒、50 秒再試")
got, err = run([http(429), http(429), http(429)])
check(isinstance(err, urllib.error.HTTPError) and err.code == 429 and SLEPT == [25, 50], "get：最後一次都 429 → 報錯，唔再等")
got, err = run([urllib.error.URLError("reset"), {"ok": 2}])
check(got == {"ok": 2} and SLEPT == [5], "get：斷線 → 等 5 秒再試")
got, err = run([urllib.error.URLError("a"), TimeoutError("b"), urllib.error.URLError("c")])
check(isinstance(err, urllib.error.URLError) and str(err.reason) == "c" and SLEPT == [5, 5], "get：試夠 3 次都斷線 → 報最後一次嘅錯")
got, err = run([http(500), {"never": 1}])
check(isinstance(err, urllib.error.HTTPError) and err.code == 500 and len(URLS) == 1, "get：其他 HTTP 錯（500）即刻報錯")
C.urllib.request.urlopen = REAL

# ============================================================ 2. ratio、money
check(C.ratio(1, 4) == 0.25 and C.ratio(0, 5) == 0.0 and C.ratio(None, 4) is None and C.ratio(1, 0) is None and C.ratio(1, None) is None
      and C.ratio(2, 3, 2) == 0.67, "ratio：分母係 0 或者冇 → None；分子 0 照計；小數位")
check([C.money(x) for x in (None, 1e12, -2.5e12, 999_999_999_999, 1e8, -5e8, 99_999_999, 1e4, 9999)] ==
      ["—", "1.00 萬億美元", "-2.50 萬億美元", "10,000.0 億美元", "1.0 億美元", "-5.0 億美元", "10,000 萬美元", "1 萬美元", "9,999 美元"],
      "money：≥ 1 萬億寫萬億、≥ 1 億寫億（一個小數）、≥ 1 萬寫萬、其餘寫美元；負數有 -")

# ============================================================ 3. unlocks
NOW0 = time.time()
DAY = 86400
EM = {}
GETS = []


def fake_get(u, timeout=60, tries=3):
    GETS.append(u)
    if u.endswith("emissionsProtocolsList"):
        return ["demo", "later", "broken"]
    if u.endswith("/broken"):
        raise RuntimeError("503")
    return EM[u.rsplit("/", 1)[1]]


C.get = fake_get
EM["demo"] = {"documentedData": {"data": [
    {"label": "Investors", "data": [{"timestamp": NOW0 - 10 * DAY, "unlocked": 1e8}, {"timestamp": NOW0 + 20 * DAY, "unlocked": 1.1e8},
                                    {"timestamp": NOW0 + 60 * DAY, "unlocked": 1.3e8}]},
    {"label": "Team", "data": [{"timestamp": NOW0 - 5 * DAY, "unlocked": 0}, {"timestamp": NOW0 + 60 * DAY, "unlocked": 5e7}]},
    {"label": "", "data": [{"timestamp": NOW0 + 70 * DAY, "unlocked": 1e7}, {"timestamp": "壞", "unlocked": 9e9}]},
    {"label": "Past", "data": [{"timestamp": NOW0 - 30 * DAY, "unlocked": 1e9}]}]}}
EM["later"] = {"documentedData": {"data": [{"label": "Team", "data": [{"timestamp": NOW0 + 60 * DAY, "unlocked": 5e7}]}]}}
day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
u = C.unlocks("demo", 4.0, 1e9)
check(u["d30"] == 0.04 and u["d90"] == 0.36, "unlocks：30 日得 Investors 1000 萬（× 4 ÷ 10 億市值 = 4%）；90 日 Investors 3000 萬 + Team 5000 萬 + 冇名 1000 萬 = 36%")
check(u["next"] == day(NOW0 + 20 * DAY) and u["who"] == ["Investors", "Team"], "unlocks：下次解鎖日係最早嗰次；邊個解鎖用 90 日、冇名嘅唔列；已經解鎖晒嘅唔計")
u = C.unlocks("later", 4.0, 1e9)
check(u == {"d30": 0.0, "d90": 0.2, "next": day(NOW0 + 60 * DAY), "who": ["Team"]}, "unlocks：30 日內冇、60 日後先解鎖 → 30 日 0、90 日 20%，下次解鎖日 60 日後")
GETS.clear()
check(C.unlocks("nolist", 4.0, 1e9) is None and len(GETS) == 1, "unlocks：DefiLlama 冇收錄 → None，唔再攞")
check(C.unlocks("broken", 4.0, 1e9) is None, "unlocks：攞唔到 → None（唔 crash）")
GETS.clear()
check(C.unlocks("demo", None, 1e9) is None and C.unlocks("demo", 4.0, None) is None and C.unlocks(None, 4.0, 1e9) is None and GETS == [],
      "unlocks：冇價、冇市值或者唔係協議 → None，唔使攞")

# ============================================================ 4. main：失敗照記帳
(OUT / "coins.json").write_text(json.dumps({"coins": [{"id": "demo", "s": "DMO", "n": "Demo", "r": 1}]}), encoding="utf-8")
C.llm.has_key = lambda p: True
C.llm.start = C.llm.finish = lambda *a, **k: None
COST = {"AAA": 0.25, "BBB": 0.0}


def bad_build(q, dry=False, coins=None):
    C.llm.USAGE.append({"usd": COST[q]})
    raise RuntimeError("AI JSON 壞咗")


C.build = bad_build
mon = datetime.now(C.HKT).strftime("%Y-%m")
check(C.main(["AAA"]) == 1 and json.loads((OUT / "index.json").read_text(encoding="utf-8"))["usage"][mon] == 0.25,
      "main：研究失敗但已經用咗 US$0.25 AI → 返 1、照記入每月用量")
before = (OUT / "index.json").read_text(encoding="utf-8")
check(C.main(["BBB"]) == 1 and (OUT / "index.json").read_text(encoding="utf-8") == before, "main：失敗又冇用 AI → 返 1、唔使改 index")
print(f"\n全部 {ok} 項通過")
