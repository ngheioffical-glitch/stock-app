# -*- coding: utf-8 -*-
"""2026-10-21 scanner/events.py 測試：假 Yahoo 數據 + 假 AI（唔上網、唔使錢）。用法：python tests/test_events.py"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

T = Path(__file__).resolve().parent
OUTD = Path(os.environ.get("TEST_OUT") or T / "_out") / "events" / time.strftime("%Y%m%d-%H%M%S")
OUTD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(EVENTS_OUT=str(OUTD), GEMINI_API_KEY="fake", EVENTS_MAX_CALLS="1", EVENTS_PAUSE="0", EVENTS_BATCH="6")
os.environ.pop("ANTHROPIC_API_KEY", None)
import events as E  # noqa: E402
import llm  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# 假數據：大市 2 年半，2025-04-09 +12%、之前跌 25%；AAA 一日 -20%
idx = pd.bdate_range("2023-06-01", "2026-10-20")
rng = np.random.default_rng(1)
mk = pd.Series(np.exp(np.cumsum(rng.normal(0.0004, 0.006, len(idx)))) * 20000, index=idx)
crash = idx.get_loc(pd.Timestamp("2025-03-03"))
mk.iloc[crash:crash + 25] *= np.linspace(1, 0.74, 25)
mk.iloc[crash + 25:] *= 0.74
j = idx.get_loc(pd.Timestamp("2025-04-09"))
mk.iloc[j:] *= 1.12
aaa = pd.Series(np.exp(np.cumsum(rng.normal(0.0005, 0.01, len(idx)))) * 100, index=idx)
k = idx.get_loc(pd.Timestamp("2026-02-10"))
aaa.iloc[k:] *= 0.80
E.download = lambda syms, start: pd.DataFrame({"^NDX": mk, "AAA": aaa})
E.targets = lambda: (["AAA"], {"AAA"}, {"AAA"}, {"AAA": "半導體"},
                     {"trades": [dict(sym="AAA", leg="lead", date="2026-01-05", entry=100.0, sell_date="2026-02-11", sell=80.0, ret=-0.2, reason="跌穿止蝕")],
                      "positions": []})
# 2026-10-23：業績後大跌嗰日同大升跌合做一個點；細郁嘅業績唔再標
E.earnings = lambda s, c: [dict(d="2026-02-10", kind="earn", chg=-0.2, label="業績 -20%", detail="2026-02-09 收市後公佈：每股盈利 1.00，預測 1.50（輸預期 33.3%）；翌日股價 -20.0%。"),
                           dict(d="2025-11-03", kind="earn", chg=0.01, label="業績 +1%", detail="2025-11-03 開市前公佈：每股盈利 1.10；當日股價 +1.0%。")]

asked = []


QUOTA_NOW = [False]


def fake_search(prompt, timeout=None):
    asked.append(prompt)
    if QUOTA_NOW[0]:
        return None, "gemini：搜尋失敗（gemini-x：HTTP Error 429: Too Many Requests）", False, []
    if "2025-04-09" in prompt:
        return {"items": [{"date": "2025-04-09", "label": "關稅暫停 90 日", "detail": "白宮宣佈暫停對等關稅 90 日，納指一日升 12%。", "src": ["S2"]}]},             "gemini-x（Google 搜尋：Reuters）", True, [{"title": "無關", "url": "https://x.com/other"}, {"title": "Reuters", "url": "https://r.com/a"}]
    if "AAA" in prompt:
        return {"items": [{"date": "2026-02-10", "label": "unknown"}]}, "gemini-x", True, []
    return {"items": []}, "gemini-x", False, []


llm.search = fake_search
llm.available = lambda: True
llm.start = lambda *a, **k: None

E.main()
idxj = json.loads((OUTD / "index.json").read_text(encoding="utf-8"))
M = json.loads((OUTD / "MARKET.json").read_text(encoding="utf-8"))
A = json.loads((OUTD / "AAA.json").read_text(encoding="utf-8"))
cache = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))
kinds = {e["kind"] for e in M["events"]}
check(kinds == {"big", "light"}, f"大市淨係大升跌同轉燈（冇回撤、模型買賣）：{sorted(kinds)}")
e9 = next(e for e in M["events"] if e["d"] == "2025-04-09")
check(e9.get("ai") and e9["label"] == "關稅暫停 90 日" and e9["chg"] > 0.1 and e9["src"][0]["url"].startswith("https://"), f"大升跌同原因合做一個點：{e9['label']}")
check(len(asked) == 1 and "納指 100" in asked[0], f"每次最多 EVENTS_MAX_CALLS 次，大市優先（問咗 {len(asked)} 次）")
check(asked[0].count("收市") >= 1 and "items" in asked[0], "一次問一批日子，要 items 逐日答")
check(e9["src"] == [{"title": "Reuters", "url": "https://r.com/a"}] and '"src"' in asked[0], f"來源逐項對應（AI 話用第 2 個就只掛第 2 個）：{e9['src']}")
check(idxj["ai_pending"] == 1, "未問嘅數目記低咗")
ab = [e for e in A["events"] if e["kind"] == "big"]
check(ab and ab[0]["d"] == "2026-02-10" and ab[0]["label"] == f"業績大跌 {E.pct(ab[0]['chg'])}" and ab[0].get("earn") and "每股盈利 1.00" in ab[0]["detail"],
      f"業績後大跌合做一個點：{[(e['d'], e['label']) for e in ab]}")
check({e["kind"] for e in A["events"]} == {"big"} and not any(e["d"] == "2025-11-03" for e in A["events"]), "個股淨係大升跌（冇模型買賣、細郁業績）")
check(all(0 <= e["i"] < len(A["chart"]["d"]) for e in A["events"]), "每個事件都對到圖上面嘅日子")
check(A["chart"]["d"][0] >= "2024-01-01", f"圖由前年 1 月起：{A['chart']['d'][0]}")
check(idxj["items"]["AAA"]["n"] == len(A["events"]), "index.json 有每條線嘅事件數")
w_ai = e9["w"]
check(w_ai > max(e["w"] for e in M["events"] if not e.get("ai")), "AI 解釋咗嘅事件最重要（app 會先寫標籤）")

# 第二次跑：成功嘅唔再問，失敗嘅再試
asked.clear()
E.main()
check(len(asked) == 1 and "AAA" in asked[0] and "（公佈業績之後）" in asked[0], "已經解釋咗嘅唔再問，輪到個股（話埋 AI 係業績後）")
cache = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))
check(any(v.get("fail") == 1 for k, v in cache.items() if k.startswith("AAA|")), "搵唔到原因（unknown）唔用，記低失敗次數")
A2 = json.loads((OUTD / "AAA.json").read_text(encoding="utf-8"))
check(not any(e.get("ai") for e in A2["events"]), "失敗嘅事件保留數據標籤")

# 第三次：Gemini 429 → 即刻停，唔當事件失敗（之前 20 個 429 全部記咗失敗）
asked.clear(); QUOTA_NOW[0] = True
before = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))
E.main()
after = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))
check(len(asked) == 1, "429 之後唔再問")
check({k: v.get("fail") for k, v in after.items()} == {k: v.get("fail") for k, v in before.items()}, "429 唔加失敗次數")
after["X|2026-01-01"] = {"fail": 2, "why": "gemini：HTTP Error 429: Too Many Requests"}
(OUTD / "ai_cache.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
QUOTA_NOW[0] = False; E.main()
check("X|2026-01-01" not in json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8")), "舊嘅 429 失敗記錄會清走，聽日再問")
# 舊原因（冇 sv，來源未逐項對應）：排最後再問一次，換正確來源
c = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))
c["MARKET|2025-04-09"] = {"label": "舊原因", "detail": "舊", "src": [{"title": "無關", "url": "https://x.com/other"}]}
(OUTD / "ai_cache.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
asked.clear()
E.MAX_CALLS = 5
E.main()
E.MAX_CALLS = 1
c = json.loads((OUTD / "ai_cache.json").read_text(encoding="utf-8"))["MARKET|2025-04-09"]
check(c.get("sv") == 2 and c["label"] == "關稅暫停 90 日" and c["src"][0]["url"] == "https://r.com/a" and "AAA" in asked[0] and "2025-04-09" in asked[-1],
      "舊原因排最後（先做未有原因嘅）再問一次，換正確來源")
# 繁忙時段（DeepSeek 主力）：唔問 AI，留返非繁忙
asked.clear()
real_prov, real_peak = llm.PROVIDER, llm.peak_now
llm.PROVIDER, llm.peak_now = "deepseek", (lambda: True)
E.main()
check(not asked, "DeepSeek 繁忙時段：唔問 AI（慳錢）")
llm.PROVIDER, llm.peak_now = real_prov, real_peak
import importlib  # noqa: E402
for k in ("EVENTS_MAX_CALLS", "EVENTS_BATCH", "EVENTS_PAUSE", "AI_PROVIDER"):
    os.environ.pop(k, None)
os.environ["DEEPSEEK_API_KEY"] = "fake-ds"
E2 = importlib.reload(E)
check((E2.MAX_CALLS, E2.BATCH, E2.PAUSE) == (25, 3, 2.0), f"用 DeepSeek：每日問多啲、每批 3 個日子（{E2.MAX_CALLS}, {E2.BATCH}, {E2.PAUSE}）")
os.environ.pop("DEEPSEEK_API_KEY")
E3 = importlib.reload(E)
check((E3.MAX_CALLS, E3.BATCH, E3.PAUSE) == (6, 6, 15.0), "冇 DeepSeek（Gemini 免費）：照舊慢慢問")
print(f"\n全部 {ok} 項通過")
