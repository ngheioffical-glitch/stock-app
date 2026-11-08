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
z = {(x["dir"], x["brk"]): x for x in ta["fvg"]}
check((-1, True) in z and z[(-1, True)]["top"] == 11.5 and z[(-1, True)]["bot"] == 11.0 and z[(-1, True)]["ce"] and z[(-1, True)]["i"] == B + 12,
      "向下突破 FVG（11.0–11.5）由第 1 支起畫，仲有 CE")
check((-1, False) in z and z[(-1, False)]["top"] == 10.2 and z[(-1, False)]["bot"] == 10.1, "普通 FVG 都畫（冇突破嗰種）")
check(not any(x["dir"] > 0 for x in ta["fvg"]), "向上 FVG 穿底之後刪咗")
ta2 = S.analyze(d[:-1], o[:-1], h[:-1], l[:-1], c[:-1])
up = [x for x in ta2["fvg"] if x["dir"] > 0]
check(len(up) == 1 and up[0]["top"] == 9.8 and up[0]["bot"] == 9.7 and up[0]["ot"] == 10.0 and not up[0]["ce"] and up[0]["brk"],
      "影線入咗就縮細（10.0 → 9.8），淨返少過一半 CE 唔畫；佢係向上突破 FVG")
check(ta["piv"]["hi"] and ta["piv"]["lo"], "有最近轉角高同轉角低")
check(any("MSS" in f for f in ta["facts"]) and any("FVG" in f for f in ta["facts"]), "白話有最近突破同未填 FVG")
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

# research：AI 提示有技術結構；寫作格式有 tech_view
import research as R  # noqa: E402
D = json.loads((T / "fixtures" / "research_D_NVDA.json").read_text(encoding="utf-8"))
check("技術結構" not in R.facts_text(D), "冇 ta 嘅舊數據唔寫技術結構")
D["ta"] = ta
check("技術結構" in R.facts_text(D) and "只係參考" in R.facts_text(D), "有 ta 就加入 AI 數據（寫明只係參考）")
check("tech_view" in R.SCHEMA_W["properties"] and "tech_view" in R.SCHEMA_W["required"], "寫作格式有技術面一段")
check(R.clean_writing({"tech_view": "x" * 900})["tech_view"].endswith("…"), "技術面文字太長會截")

print(f"\n全部 {ok} 項通過")
