# -*- coding: utf-8 -*-
"""research.py 測試：假 Claude 回覆（唔會真係叫 API、唔使錢）、數據用固定快照 tests/fixtures/research_D_NVDA.json（2026-10-20 Yahoo／SEC）。
用法：python tests/test_research.py"""
import json
import os
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace as NS

T = Path(__file__).resolve().parent
SC = T.parent / "scanner"
OUTD = Path(os.environ.get("TEST_OUT") or T / "_out") / "research" / time.strftime("%Y%m%d-%H%M%S")   # 每次用新 folder
sys.path.insert(0, str(SC))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(ANTHROPIC_API_KEY="test-key-not-real", AI_PROVIDER="claude", RESEARCH_OUT=str(OUTD))   # 2026-10-23：Claude 要明確揀先用
for k in ("GEMINI_API_KEY", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
    os.environ.pop(k, None)
OUTD.mkdir(parents=True, exist_ok=True)

try:                                                      # 真 SDK（淨係用嚟檢查 JSON Schema 格式；scanner/requirements.txt 有）
    from anthropic.lib._parse._transform import transform_schema  # noqa: E402
except ImportError:
    transform_schema = None

CALLS, QUEUE = [], []


def msg(content, stop="end_turn", inp=20000, out=6000, search=0):
    return NS(content=content, stop_reason=stop, model="claude-opus-5-5",
              usage=NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                       server_tool_use=NS(web_search_requests=search, web_fetch_requests=0)))


class BadReq(Exception):
    status_code = 400


class _Stream:
    def __init__(self, kw):
        CALLS.append(kw)
        item = QUEUE.pop(0)
        if callable(item):
            item = item(kw)
        if isinstance(item, Exception):
            raise item
        self.m = item

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.m


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=lambda **kw: NS(beta=NS(messages=NS(stream=lambda **k: _Stream(k)))))
import llm  # noqa: E402
import research as R  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# 0. 固定數據快照（Yahoo + SEC），測試唔使上網
D = json.loads((T / "fixtures" / "research_D_NVDA.json").read_text(encoding="utf-8"))
D["price"], D["ntm_eps"], D["payout"] = 200.0, 10.0, 0.0       # 整數方便手計
R.collect = lambda s: dict(D, sym=s)
R.peer_rows = lambda peers: [dict(sym=p, name=p, price=100, mcap=1e12, fpe=25.0, peg=1.5, rg=0.2, om=0.3, gm=0.5, chg52=0.1) for p in peers]

# 1. JSON Schema 只用 API 支援嘅寫法（SDK 嘅 transform_schema 唔使改任何嘢）
if transform_schema:
    check(transform_schema(R.SCHEMA_A) == R.SCHEMA_A, "分析 JSON Schema 符合 API 支援範圍")
    check(transform_schema(R.SCHEMA_W) == R.SCHEMA_W, "寫作 JSON Schema 符合 API 支援範圍")
else:
    print("⚠ 冇 anthropic SDK（或者佢改咗內部位置）：跳過 JSON Schema 格式檢查")

# 2. 成條流程：搜尋 → 分析（固定格式）→ 寫作（固定格式）
gath = msg([NS(type="server_tool_use"),
            NS(type="web_search_tool_result", content=[NS(type="web_search_result", url="https://ir.example.com/q2", title="Q2 業績", page_age="2 months")]),
            NS(type="text", text="上季收入 467 億美元，按年升 56%。", citations=[NS(url="https://ir.example.com/q2", title="Q2 業績")]),
            NS(type="text", text="大客戶自研晶片增加。", citations=[NS(url="https://news.example.com/asic", title="ASIC 新聞")])], search=4, inp=60000, out=3000)
ANA = {
    "name_zh": "輝達", "one_liner": "賣 AI 晶片同成套系統", "moat": "寬", "moat_why": "CUDA 生態 [S5]", "moat_trend": "穩定",
    "uncertainty": "高", "uncertainty_why": "需求周期 [S6]", "capital": "良好", "capital_why": "回購多 [S3]",
    "scores": [{"key": k, "score": s, "why": "理由", "src": ["S5", "S99"]} for k, s in
               (("moat", 9), ("moat_trend", 6), ("financial", 8), ("growth", 9), ("management", 7), ("strategy", 9), ("flywheel", 8), ("certainty", 3))],
    "themes": [{"name": "AI 算力", "score": 10, "why": "核心"}, {"name": "遊戲", "score": 3, "why": "舊業務"}],
    "events": [{"date": "2025-01-27", "label": "DeepSeek 衝擊", "detail": "一日跌 17%", "src": ["S6"]},
               {"date": "2019-01-01", "label": "太早", "detail": "圖之前，應該剔走", "src": []}],
    "scenarios": [{"key": "bull", "name": "樂觀", "story": "s", "prob": 0.25, "g1": 0.2, "g2": 0.1, "pe": 25, "why": "w", "src": ["S5"]},
                  {"key": "bear", "name": "悲觀", "story": "s", "prob": 0.25, "g1": 0.0, "g2": 0.0, "pe": 10, "why": "w", "src": []},
                  {"key": "base", "name": "基本", "story": "s", "prob": 0.5, "g1": 10, "g2": 5, "pe": 20, "why": "百分比寫錯", "src": ["7"]}],
    "bull": [{"text": "好", "src": ["S5"]}], "bear": [{"text": "淡", "src": ["S6", "S42"]}],
    "blind_spot": {"title": "擔保", "detail": "d", "src": ["S6"]}, "vs_street": [{"topic": "增長", "mine": "慢啲", "street": "快"}],
    "peers": ["amd", "AVGO", "NVDA", "TSM"],
    "business": {"summary": "s", "segments": [{"name": "數據中心", "share": 0.9, "note": "n", "src": ["S3"]}], "how": ["賣晶片"], "customers": "雲端"},
    "primer": {"title": "先搞懂：AI", "subtitle": "大哉問", "plain": "p", "groups": [
        {"key": "how", "items": [{"q": "MoE 係乜？", "a": "專家混合", "detail": "d", "facts": [{"text": "f", "src": ["S5"]}], "myths": [],
                                  "diagram": {"type": "flow", "title": "MoE", "nodes": ["一個字", "路由器", "專家"], "bars": []}}]},
        {"key": "what", "items": [{"q": "Transformer 係乜？", "a": "a", "detail": "d", "facts": [], "myths": ["m"],
                                   "diagram": {"type": "bars", "title": "t", "nodes": [], "bars": [{"label": "x", "value": 1}]}}]}]},
    "glossary": [{"term": "CUDA", "define": "軟件平台"}], "next_check": "第三季業績",
}
WRI = {"verdict_plain": "現價低過公允價值", "verdict_detail": "d", "conclusion": ["c1"], "changes": [], "valuation_plain": "v",
       "direction_up": ["u"], "direction_down": ["d"], "holder_view": "h", "buyer_view": "b", "peers_note": "p"}
QUEUE[:] = [gath, msg([NS(type="text", text=json.dumps(ANA, ensure_ascii=False))]), msg([NS(type="text", text=json.dumps(WRI, ensure_ascii=False))])]
rep = R.build("NVDA")
g, a, w = CALLS[-3:]
check(g["tools"][0]["type"] == "web_search_20260209" and g["tools"][0]["max_uses"] == R.MAX_SEARCH, "第一步：Claude 原生搜尋")
check(a["output_config"]["format"]["type"] == "json_schema" and a["output_config"]["effort"] == "high", "第二步：固定 JSON 格式 + effort high")
check(a["max_tokens"] == R.MAX_TOKENS and "tools" not in a, "第二步：冇搜尋工具（引用同固定格式唔可以一齊用）")
check("[S5]" in a["messages"][0]["content"] and "上季收入 467 億美元" in a["messages"][0]["content"], "筆記帶 [S#] 交俾第二步")
ids = [s["id"] for s in rep["sources"]]
check(ids == ["S1", "S2", "S3", "S4", "S5", "S6"] and rep["sources"][4]["url"] == "https://ir.example.com/q2", "來源：程式 S1–S4、網上 S5 起")
check(all(x["src"] == ["S5"] for x in rep["scores"] if x["key"] == "moat") and rep["bear"][0]["src"] == ["S6"], "唔存在嘅來源編號（S99、S42）剔走")
check([e["label"] for e in rep["chart"]["events"]] == ["DeepSeek 衝擊"], "圖表之前嘅事件剔走")
V = rep["valuation"]
# 手計：EPS 10、payout 0、折現 9%。悲觀：10 年都係 10 × 10 倍 = 100 → 今日 100/1.09^10
bear = 100 / 1.09 ** 10
base_eps10 = 10 * 1.10 ** 4 * 1.05 ** 5
bull_eps10 = 10 * 1.20 ** 4 * 1.10 ** 5
fv = 0.25 * bear + 0.5 * base_eps10 * 20 / 1.09 ** 10 + 0.25 * bull_eps10 * 25 / 1.09 ** 10
check([s["key"] for s in V["scenarios"]] == ["bear", "base", "bull"] and abs(V["scenarios"][0]["today"] - bear) < 0.01, f"悲觀情境今日價值 {bear:.2f}")
check(abs(V["scenarios"][1]["g1"] - 0.10) < 1e-9, "百分比寫錯（10 → 0.10）自動改返")
check(abs(V["fv"] - fv) < 0.02, f"公允價值 = 機率加權 {fv:.2f}")
r = 200 / fv
exp = 5 if r <= 0.6 else 4 if r <= 0.85 else 3 if r <= 1.2 else 2 if r <= 1.55 else 1
check(V["stars"] == exp and V["bands"][1]["max"] == round(fv * 0.85, 2), f"星級（不確定性高）：現價 ÷ 公允價值 {r:.2f} → {exp} 星")
vs = next(x for x in rep["scores"] if x["key"] == "valuation")
check(vs["score"] == int(max(0, min(10, round(10 - (r - 0.5) * 10)))) and [x["key"] for x in rep["scores"]][4] == "valuation", "估值吸引力由程式計、排第 5")
check([p["sym"] for p in rep["peers"]] == ["AMD", "AVGO", "TSM"], "同業：大寫、剔走自己")
check([g_["key"] for g_ in rep["primer"]["groups"]] == ["what", "how"] and rep["primer"]["groups"][0]["items"][0]["diagram"] is None,
      "先搞懂：按次序、得一條棒嘅圖剔走")
check(rep["models"]["analysis"] == "Claude Opus 5.5（effort high）" and rep["cost_usd"] > 0, f"記低型號同用量（US${rep['cost_usd']}）")
check(rep["n"] == 1 and rep["compare"]["rows"] == [] and rep["checks"][0] == {"label": "護城河寬", "ok": True}, "第一次研究：冇比較、重倉條件清單")
idx = json.loads((OUTD / "index.json").read_text(encoding="utf-8"))
check(idx["items"][0]["sym"] == "NVDA" and idx["usage"][llm.DAY[:7]] == rep["cost_usd"], "index.json：清單同每月用量")

# 3. 第二次：同上次比較、舊報告存檔；Claude 唔收固定格式（400）→ 改用提示要求 JSON
ANA2 = dict(ANA, moat="窄", scores=[dict(x, score=x["score"] - 1) if x["key"] == "moat" else x for x in ANA["scores"]])
WRI2 = dict(WRI, changes=[{"item": "護城河", "why": "對手追近"}])
QUEUE[:] = [gath, BadReq("output_config.format.schema: unsupported"), msg([NS(type="text", text=json.dumps(ANA2, ensure_ascii=False))]),
            msg([NS(type="text", text=json.dumps(WRI2, ensure_ascii=False))])]
D["price"] = 180.0
rep2 = R.build("NVDA")
a2 = CALLS[-2]
check("format" not in a2["output_config"] and "JSON Schema" in a2["messages"][0]["content"], "固定格式被拒 → 將 Schema 寫入提示再試")
rows = {x["item"]: x for x in rep2["compare"]["rows"]}
check(rows["股價"]["prev"] == "200.00" and rows["股價"]["now"] == "180.00" and rows["護城河"]["why"] == "對手追近", "同上次比較：程式比數、AI 寫原因")
check("護城河強度" in rows and rep2["n"] == 2 and len(rep2["history"]) == 2, "評分變化入表、第 2 次研究、歷史 2 條")
check((OUTD / "hist" / "NVDA" / f"{rep['research_date']}.json").exists(), "舊報告存檔 hist/NVDA/日期.json")

# 4. 未能估值：冇正數盈利
D["ntm_eps"], D["ttm_eps"] = -1.0, -2.0
V3 = R.valuation(D, R.clean_analysis(ANA, rep["sources"], D))
check(not V3["ok"] and "盈利" in V3["why"], f"冇正數盈利 → 未能估值：{V3['why']}")

# 5. Claude 全部失敗、冇後備 key → 報告失敗，舊報告保留
QUEUE[:] = [RuntimeError("529 overloaded")]
before = (OUTD / "NVDA.json").read_text(encoding="utf-8")
code = R.main(["NVDA"])
check(code == 1 and (OUTD / "NVDA.json").read_text(encoding="utf-8") == before, "AI 失敗：返 1、舊報告唔郁")
print(f"\n全部 {ok} 項通過")
