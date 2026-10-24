# -*- coding: utf-8 -*-
"""2026-10-24 scanner/airdrop.py 測試：假 AI（llm.search）、假 DefiLlama，唔上網、唔使錢。用法：python tests/test_airdrop.py"""
import json
import os
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
os.environ["GEMINI_API_KEY"] = "fake"
import airdrop as A  # noqa: E402
import llm  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


asked = []


def fake_search(prompt, timeout=None):
    asked.append(prompt)
    if "盤點" in prompt:
        return ({"title": "Perp DEX 盤點", "market": "Perp DEX 30 日交易量約 4,000 億美元（2026-10）",
                 "summary": ["重點一", "重點二"], "platforms": ["Hyperliquid", "Lighter", "Foo"], "risks": ["槓桿風險"]},
                "deepseek:deepseek-flash（上網搜尋 3 次：A）", True, [{"title": "DefiLlama", "url": "https://defillama.com/x"}])
    if "Hyperliquid" in prompt:
        return ({"name": "Hyperliquid", "status": "傳聞", "token": "已發幣（HYPE）", "volume30d": "2,100 億美元（10 月）", "reward": "38.888% 預留社群",
                 "news_date": "2026-10-15", "oi": "unknown"},
                "deepseek:deepseek-flash", True,
                [{"title": "官方", "url": "https://hyperliquid.xyz/blog"}, {"title": "推薦", "url": "https://app.hyperliquid.xyz/join/CHAINLABHK"},
                 {"title": "推薦2", "url": "https://x.com/a?ref=abc"}])
    if "Lighter" in prompt:
        return ({"name": "Lighter", "status": "官方確認"}, "deepseek:deepseek-flash", False, [])     # 冇上網來源
    raise RuntimeError("搜尋失敗")


llm.search = fake_search
llm.available = lambda: True
llm.peak_now = lambda: False
A.llama_tvl = lambda name: 7_100_000_000 if name == "Hyperliquid" else None
out = Path(os.environ.get("TEST_OUT") or T / "_out") / "airdrop" / time.strftime("%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)

A.main(str(out))
o = json.loads((out / "airdrop.json").read_text(encoding="utf-8"))
P = {p["name"]: p for p in o["platforms"]}
check(o["title"] == "Perp DEX 盤點" and o["summary"] == ["重點一", "重點二"] and o["risks"] == ["槓桿風險"], "總覽：標題、重點、風險齊")
check(set(P) == {"Hyperliquid", "Lighter"} and len(o["errs"]) == 1 and "Foo" in o["errs"][0], f"逐個項目查，搵唔到嘅記低錯誤：{o['errs']}")
h = P["Hyperliquid"]
check(h["status"] == "傳聞" and h["tvl_llama"] == 7_100_000_000 and h["oi"] == "", "狀態照 AI（有來源）、TVL 用 DefiLlama、unknown 當空")
check([s["url"] for s in h["src"]] == ["https://hyperliquid.xyz/blog"], f"推薦連結（/join/、?ref=）唔要：{h['src']}")
check(P["Lighter"]["status"] == "未核實", "冇上網來源：一律當「未核實」，唔信 AI 講嘅「官方確認」")
check("ChainLab" in asked[0] and "Hyperliquid" in asked[0], "提示照 ChainLab 寫法、參考五個項目")

n0 = len(asked)
A.main(str(out))
check(len(asked) == n0, "7 日內寫過就唔再寫（慳錢）")

llm.PROVIDER, real_peak = "deepseek", llm.peak_now
llm.peak_now = lambda: True
A.main(str(out), force=True)
check(len(asked) == n0, "DeepSeek 繁忙時段唔寫")
llm.PROVIDER, llm.peak_now = "gemini", real_peak
print(f"\n全部 {ok} 項通過")
