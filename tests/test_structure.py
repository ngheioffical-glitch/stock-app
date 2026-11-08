# -*- coding: utf-8 -*-
"""2026-11-09 scanner/structure.py 測試（老師 Pine 突破規則：BOS／MSS／FVG，只供參考）：人手砌嘅 K 線，唔上網。
用法：python tests/test_structure.py"""
import json
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import structure as S  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# 25 支平盤（高位相同 → 冇轉角位、冇 FVG），之後人手砌：
#  第 1 支轉角高 11 → 第 7 支實體 90% 收穿 11、第 8 支低位 10.0 > 第 6 支高位 9.7（FVG）→ 向上突破（第一次 = BOS）
#  第 4 支實體得 50%：收穿轉角低 9.5 但唔算突破（實體 < 60%）
#  第 11 支轉角低 11.3 → 第 13 支實體收穿、第 14 支高位 11.0 < 第 12 支低位 11.5 → 向下突破，方向相反 = MSS
#  第 15 支低位入咗向上 FVG（9.7–10.0）縮到 9.8（淨返一半以下 → CE 唔畫）；第 16 支穿底 → 刪
flat = [(10, 10.2, 9.9, 10)] * 25
bars = [(10, 10.5, 9.5, 10), (10, 11, 9.8, 10.5), (10.4, 10.6, 9.6, 9.8), (9.8, 10.2, 9.0, 9.2), (9.2, 9.4, 8.8, 9.3),
        (9.3, 9.6, 9.1, 9.5), (9.5, 9.7, 9.4, 9.6), (9.7, 11.6, 9.6, 11.5), (11.5, 12, 10.0, 11.8), (11.8, 12.2, 11.6, 12.0),
        (12.0, 12.1, 11.4, 11.5), (11.5, 11.9, 11.3, 11.7), (11.7, 11.8, 11.5, 11.6), (11.5, 11.55, 10.5, 10.6),
        (10.6, 11.0, 10.2, 10.4), (10.4, 10.5, 9.8, 10.0), (10.0, 10.1, 9.6, 9.7)]
rows = flat + bars
d = [f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}" for k in range(len(rows))]
o, h, l, c = (list(x) for x in zip(*rows))
ta = S.analyze(d, o, h, l, c)
B = 25
check(ta is not None and len(ta["c"]) == len(rows), "夠 30 支就有結果，圖由第一支起（少過 120 支）")
check([(b["k"], b["dir"], b["i"], b["s"], b["lv"]) for b in ta["brk"]] == [("BOS", 1, B + 7, B + 1, 11.0), ("MSS", -1, B + 13, B + 11, 11.3)],
      f"向上突破記喺收穿嗰支（BOS），之後向下突破方向相反 = MSS：{ta['brk']}")
check(not any(b["i"] == B + 3 for b in ta["brk"]), "實體 50% 收穿唔算（要 ≥ 60%）")
# 2026-11-09 老師：「依家暫時先試下BOS／MSS 線先，其他唔好掂住」→ 冇 FVG、轉角線、EMA；三個數字保留
check(not any(k in ta for k in ("fvg", "piv", "e21")), "淨係 BOS／MSS：冇 FVG、轉角線、EMA")
check(set(ta["stat"]) == {"adr", "off52", "atr50"}, "ADR、距 52 週高、距 50 日線 ATR 保留")
check(any("MSS" in f for f in ta["facts"]) and not any("FVG" in f for f in ta["facts"]) and any("ADR" in f for f in ta["facts"]),
      "白話有最近突破同三個數字，冇 FVG")
noFvg = list(rows)
noFvg[B + 8] = (11.5, 12, 9.6, 11.8)                         # 第 3 支低位 9.6 < 第 1 支高位 9.7：冇 FVG
tn = S.analyze(d, *[list(x) for x in zip(*noFvg)])
check(not any(b["i"] == B + 7 for b in tn["brk"]), "收穿但唔係 FVG 中間支：唔算突破")
line = S.facts_line(ta)
check("只係參考" in line and "BOS" in line and "MSS" in line, "俾 AI 嘅一行寫明只係參考")
check(S.facts_line(None) == "", "冇數據就空")
check(S.analyze(d[:20], o[:20], h[:20], l[:20], c[:20]) is None, "少過 30 支返 None")
bad = list(rows)
bad[30] = (float("nan"), 1, 1, 1)
check(S.analyze(d, *[list(x) for x in zip(*bad)]) is not None, "有 NaN 嗰支跳過，唔會死")
# 長數據：圖只留最近 120 支，突破位標返圖入面嘅位置
long = flat * 6 + bars
dl = [f"x{k}" for k in range(len(long))]
tl = S.analyze(dl, *[list(x) for x in zip(*long)])
check(len(tl["c"]) == 120 and tl["d"][-1] == dl[-1], "圖得最近 120 支")
check([b["i"] for b in tl["brk"]] == [120 - 17 + 7, 120 - 17 + 13], "突破位置對返圖入面")
json.dumps(tl)
check(True, "結果可以寫做 JSON")

# events.tech：冇開高低收（測試）就返 None，唔影響事件線
import events as E  # noqa: E402
E.RAW = None
check(E.tech("AAA") is None, "events.tech 冇數據返 None")
check(E.add_ohlc({"d": ["2026-01-02"], "c": [1.0]}, "AAA") == {"d": ["2026-01-02"], "c": [1.0]}, "events.add_ohlc 冇數據就唔加")
import pandas as pd  # noqa: E402
ix = pd.to_datetime(["2026-01-02", "2026-01-05"])
E.RAW = pd.concat({"AAA": pd.DataFrame({"Open": [1.0, 2.0], "High": [1.5, 2.5], "Low": [0.9, 1.9], "Close": [1.2, 2.2]}, index=ix)}, axis=1)
oc = E.add_ohlc({"d": ["2026-01-02", "2026-01-03", "2026-01-05"], "c": [1.2, 1.2, 2.2]}, "AAA")
check(oc["o"] == [1.0, 1.2, 2.0] and oc["h"] == [1.5, 1.2, 2.5] and oc["l"] == [0.9, 1.2, 1.9], "事件線加開高低（對返日子；冇嗰日用收市補）")
E.RAW = None

# research：AI 提示有技術結構；寫作格式有 tech_view
import research as R  # noqa: E402
D = json.loads((T / "fixtures" / "research_D_NVDA.json").read_text(encoding="utf-8"))
check("技術結構" not in R.facts_text(D), "冇 ta 嘅舊數據唔寫技術結構")
D["ta"] = ta
check("技術結構" in R.facts_text(D) and "只係參考" in R.facts_text(D), "有 ta 就加入 AI 數據（寫明只係參考）")
check("tech_view" in R.SCHEMA_W["properties"] and "tech_view" in R.SCHEMA_W["required"], "寫作格式有技術面一段")
check(R.clean_writing({"tech_view": "x" * 900})["tech_view"].endswith("…"), "技術面文字太長會截")

print(f"\n全部 {ok} 項通過")
