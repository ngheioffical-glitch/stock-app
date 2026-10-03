"""前瞻敘事（2026-10-04 用戶：要有前瞻性嘅宏觀，例如 RWA、美股代幣化、穩定幣 + AI 代理支付、Robinhood Chain、幣安鏈、Solana 呢類早期佈局位）。
純資訊，唔係買入信號。用數據驗證敘事：穩定幣總量增長、各條鏈資金（TVL）同收入增長、各類項目資金同收入增長；
加 X 研究人士近 7 日帖（radar.json x_posts）；AI（Gemini + Google 搜尋，額度用晒就冇搜尋版）寫 4–6 個敘事。
每日寫一次（留 24 小時），數據每次都更新。.github/workflows/radar.yml 每 6 個鐘跑（喺 radar.py 之後），輸出 <out>/narr.json。
用法：python scanner/narr.py out
"""
from __future__ import annotations

import collections
import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radar import OV, ai_json, get  # noqa: E402

TTL_H = 24
PROMPT = ("你係加密行業研究員，用香港廣東話口語幫一個想「趁市靜增加認知、早期佈局」嘅新手睇前瞻敘事。今日 {date}。\n"
          "數據（DefiLlama）：\n{data}\nX 加密研究人士近 7 日帖：\n{x}\n"
          "用 Google 搜尋查證最新發展（例如 RWA、美股代幣化、穩定幣、AI 代理支付（agentic payment）、Robinhood Chain、幣安鏈、Solana、預測市場等，"
          "但唔好只跟呢個清單，要根據數據同新聞揀真係升溫緊嘅）。揀 4–6 個敘事，回覆 JSON："
          "{{\"summary\": \"而家加密世界最大嘅趨勢（2–3 句）\", "
          "\"narratives\": [{{\"name\": \"敘事名\", \"what\": \"係乜（新手一句明）\", \"why_now\": \"點解係而家（催化劑、政策、大公司入場）\", "
          "\"evidence\": [\"數據證據 1–3 點（引用上面數字或者搜尋到嘅數字）\"], \"stage\": \"揀一個：早期／升溫／主流／過熱\", "
          "\"early\": [\"普通人點早期參與（用產品、儲積分等空投、學習）1–3 點，唔好叫人買幣\"], \"projects\": [\"相關項目或者鏈 2–5 個\"], "
          "\"risks\": [\"風險 1–2 點\"], \"horizon\": \"大概要幾耐先見效\"}}], "
          "\"learn\": [\"趁市靜最值得學嘅 2–3 樣嘢（具體）\"], \"contrarian\": \"反方睇法：呢啲敘事可能點樣落空（一句）\"}}。唔好估數字，搵唔到就唔好寫。")


def chain_growth(names):
    out = []
    for c in names:
        try:
            h = get(f"https://api.llama.fi/v2/historicalChainTvl/{urllib.parse.quote(c)}", 30)
            if len(h) > 31 and h[-31]["tvl"]:
                out.append((c, h[-1]["tvl"], h[-1]["tvl"] / h[-31]["tvl"] - 1, h[-1]["tvl"] / h[-91]["tvl"] - 1 if len(h) > 91 and h[-91]["tvl"] else None))
        except Exception as e:  # noqa: BLE001
            print(f"[narr] {c} TVL 攞唔到：{e}")
        time.sleep(0.3)
    return out


def data_block():
    L, D = [], {}
    # 穩定幣總量
    s = get("https://stablecoins.llama.fi/stablecoincharts/all", 60)
    v = lambda i: (s[i].get("totalCirculatingUSD") or {}).get("peggedUSD") or 0
    D["stable"] = dict(now=v(-1), d30=v(-1) / v(-31) - 1, d90=v(-1) / v(-91) - 1, d365=v(-1) / v(-366) - 1)
    L.append(f"穩定幣總量 {v(-1) / 1e9:,.0f}B 美元（約 {v(-1) / 1e8:,.0f} 億美元；30 日 {D['stable']['d30'] * 100:+.1f}%、90 日 {D['stable']['d90'] * 100:+.1f}%、1 年 {D['stable']['d365'] * 100:+.0f}%）")
    # 各條鏈：TVL 頭 12 + 指定（Robinhood 等）
    ch = sorted(get("https://api.llama.fi/v2/chains", 60), key=lambda c: -(c.get("tvl") or 0))
    names = [c["name"] for c in ch[:12]]
    for extra in ("Robinhood Chain", "Robinhood", "Plasma", "Hyperliquid L1", "Sui", "Base", "BSC", "Solana"):
        if extra not in names and any(c["name"] == extra for c in ch):
            names.append(extra)
    cg = chain_growth(names)
    D["chains"] = [dict(name=n, tvl=t, d30=a, d90=b) for n, t, a, b in cg]
    L.append("各條鏈 TVL（資金）：" + "；".join(f"{n} {t / 1e9:.1f}B（30 日 {a * 100:+.0f}%{'' if b is None else f'、90 日 {b * 100:+.0f}%'}）" for n, t, a, b in cg))
    # 鏈收入（手續費收入，近 30 日 vs 前 30 日）
    ov = get(OV.format("dailyRevenue"), 60)["protocols"]
    chains_rev = sorted([o for o in ov if o.get("protocolType") == "chain" and (o.get("total30d") or 0) > 1e6], key=lambda o: -o["total30d"])[:10]
    D["chain_rev"] = [dict(name=o["name"], rev30=o["total30d"], g=(o["total30d"] / o["total60dto30d"] - 1) if o.get("total60dto30d") else None) for o in chains_rev]
    L.append("各條鏈近 30 日收入：" + "；".join(f"{x['name']} {x['rev30'] / 1e6:.1f}M" + ("" if x["g"] is None else f"（{x['g'] * 100:+.0f}%）") for x in D["chain_rev"]))
    # 各類項目：收入（30 日 vs 前 30 日）
    cat = collections.defaultdict(lambda: [0.0, 0.0])
    for o in ov:
        if o.get("protocolType") == "chain":
            continue
        c = cat[o.get("category") or "其他"]
        c[0] += o.get("total30d") or 0
        c[1] += o.get("total60dto30d") or 0
    cr = sorted([(k, a, b) for k, (a, b) in cat.items() if a >= 2e6], key=lambda x: -x[1])[:15]
    D["cat_rev"] = [dict(name=k, rev30=a, g=a / b - 1 if b else None) for k, a, b in cr]
    L.append("各類項目近 30 日收入：" + "；".join(f"{k} {a / 1e6:.0f}M" + (f"（{(a / b - 1) * 100:+.0f}%）" if b else "") for k, a, b in cr))
    # 各類項目：TVL（而家 vs 上個月）
    pr = get("https://api.llama.fi/lite/protocols2", 90)["protocols"]
    tv = collections.defaultdict(lambda: [0.0, 0.0])
    for p in pr:
        if p.get("tvl") and p.get("tvlPrevMonth"):
            t = tv[p.get("category") or "其他"]
            t[0] += p["tvl"]
            t[1] += p["tvlPrevMonth"]
    tr = sorted([(k, a, b) for k, (a, b) in tv.items() if a >= 5e8], key=lambda x: -(x[1] / x[2] if x[2] else 0))[:12]
    D["cat_tvl"] = [dict(name=k, tvl=a, d30=a / b - 1) for k, a, b in tr]
    L.append("各類項目 TVL 30 日增長最快：" + "；".join(f"{k} {a / 1e9:.1f}B（{(a / b - 1) * 100:+.0f}%）" for k, a, b in tr))
    return "\n".join(L), D


def main(out):
    out = Path(out)
    f = out / "narr.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    errs = []
    try:
        text, D = data_block()
    except Exception as e:  # noqa: BLE001
        print(f"[narr] 數據攞唔到：{e}")
        return
    ai = prev.get("ai")
    fresh = ai and now - datetime.fromisoformat(ai["at"]) < timedelta(hours=TTL_H if ai.get("grounded", True) else 6)
    if not fresh:
        try:
            posts = json.loads((out / "radar.json").read_text(encoding="utf-8")).get("x_posts") or []
        except Exception:  # noqa: BLE001
            posts = []
        xt = "\n".join(f"@{t['user']}（{t['name']}）：{t['text'][:260]}" for t in posts[:30]) or "冇"
        res, src, gr = ai_json(PROMPT.format(date=now.strftime("%Y-%m-%d"), data=text, x=xt))
        if res:
            ai = dict(res, src=src, grounded=gr, at=now.isoformat(timespec="seconds"))
            print("[narr] AI 寫咗前瞻敘事")
        else:
            errs.append(f"AI：{src[:100]}")
    f.write_text(json.dumps(dict(at=now.isoformat(timespec="seconds"), data=D, ai=ai, errs=errs), ensure_ascii=False), encoding="utf-8")
    print(f"[narr] 數據更新；AI {'有' if ai else '冇'}；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
