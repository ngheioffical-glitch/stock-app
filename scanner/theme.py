"""題材雷達（2026-10-05 用戶：想捉核能、稀土呢類題材大升）。純資訊，唔係買入信號：
冇偷睇測試（stock-strategy/LAB_THEME.md）撥 10–30% 每星期追題材 ETF，組合年化反而少 3–10 個百分點（不過仍然贏 QQQ）。

每個題材：題材 ETF + 主要股票（清單 2026-10-05 寫，AI 分析會補充）+ 新聞關鍵字。
數據：Yahoo 日線（1 年）→ 1／5／21／63 日升幅、距 52 週高、成交量（5 日 ÷ 50 日）、> 50 日線；成份股 5／21 日升幅、新高數目。
熱度 = 5 日升幅、21 日升幅、成交急增嘅百分位；「爆發」= ETF 5 日 ≥ +8%，或者 ≥ 3 隻股 5 日 ≥ +15%，或者 ETF 創 52 週新高而成交 ≥ 1.5 倍。
新聞早期訊號：feeds 嘅 news.json（近 48 小時）同 Trump 帖對關鍵字。AI：爆發／熱度頭 4／有新聞嘅題材，每次最多 5 個，留 12 小時。
.github/workflows/radar.yml 每 6 個鐘跑，輸出 <out>/theme.json。
用法：python scanner/theme.py out
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radar import ai_json, get  # noqa: E402

THEMES = [
    ("nuclear", "核能／鈾", ["URA", "NLR"], ["CCJ", "OKLO", "SMR", "LEU", "NNE", "BWXT", "CEG", "UEC"],
     r"nuclear|uranium|reactor|\bSMR\b|核能|核電|鈾"),
    ("rare", "稀土／戰略礦產", ["REMX"], ["MP", "USAR", "UUUU", "NB", "TMC", "ALB"],
     r"rare earth|critical mineral|export control|gallium|germanium|antimony|稀土|關鍵礦產|出口管制"),
    ("quantum", "量子電腦", ["QTUM"], ["IONQ", "RGTI", "QBTS", "QUBT", "IBM"], r"quantum|量子"),
    ("space", "太空", ["UFO", "ARKX"], ["RKLB", "ASTS", "LUNR", "PL", "RDW"], r"\bspace\b|satellite|rocket|SpaceX|太空|衛星|火箭"),
    ("robot", "機械人", ["BOTZ", "ROBO"], ["TSLA", "ISRG", "SYM", "SERV", "TER"], r"robot|humanoid|機械人|人形"),
    ("defense", "國防／無人機", ["ITA", "XAR"], ["LMT", "RTX", "NOC", "AVAV", "KTOS", "PLTR", "RCAT"],
     r"defen[cs]e|drone|Pentagon|military|missile|國防|無人機|軍"),
    ("chips", "半導體／AI 晶片", ["SMH", "SOXX"], ["NVDA", "AMD", "AVGO", "TSM", "MU", "LRCX"], r"semiconductor|\bchips?\b|Nvidia|晶片|半導體"),
    ("power", "AI 電力／數據中心", ["XLU"], ["VST", "CEG", "NRG", "GEV", "ETN", "VRT"], r"data cent(er|re)|power grid|electricity|數據中心|電力|電網"),
    ("gold", "金／銀礦", ["GDX", "SIL"], ["NEM", "AEM", "WPM", "PAAS", "AG"], r"\bgold\b|silver|黃金|白銀"),
    ("copper", "銅礦", ["COPX"], ["FCX", "SCCO", "TECK"], r"copper|銅"),
    ("lithium", "鋰電池", ["LIT"], ["ALB", "SQM", "LAC", "QS"], r"lithium|battery|鋰|電池"),
    ("solar", "太陽能／清潔能源", ["TAN", "ICLN"], ["FSLR", "ENPH", "NXT", "RUN"], r"solar|clean energy|renewable|太陽能|再生能源"),
    ("cyber", "網絡安全", ["CIBR"], ["CRWD", "PANW", "ZS", "FTNT", "NET"], r"cybersecurity|cyber ?attack|hack|ransomware|網絡安全|黑客"),
    ("biotech", "生科／藥", ["XBI"], ["LLY", "NVO", "VRTX", "REGN", "MRNA"], r"\bFDA\b|biotech|drug pric|obesity|GLP-1|生科|藥"),
    ("crypto", "加密股", ["BLOK"], ["COIN", "MSTR", "HOOD", "CRCL", "IREN", "MARA"], r"crypto|bitcoin|stablecoin|加密|比特幣|穩定幣"),
    ("china", "中國科網", ["KWEB"], ["BABA", "PDD", "JD", "BIDU", "TCEHY"], r"China|Chinese|Beijing|中國|北京"),
    ("oil", "石油天然氣", ["XOP"], ["XOM", "CVX", "OXY", "COP"], r"\boil\b|OPEC|crude|natural gas|LNG|石油|原油|天然氣"),
    ("software", "AI 軟件", ["IGV"], ["PLTR", "MSFT", "CRM", "NOW", "APP"], r"software|OpenAI|Anthropic|SaaS|AI model|軟件"),
]
AI_MAX, AI_TTL_H = 5, 12
PROMPT = ("美股題材「{name}」。數據：題材 ETF {etf}：5 日 {r5}、21 日 {r21}、63 日 {r63}、距 52 週高 {hi}、成交 {vs} 倍；"
          "主要股票（5 日／21 日升幅）：{mem}。近 48 小時相關新聞：{news}。"
          "用 Google 搜尋查證最新發展，用香港廣東話口語幫新手判斷，唔好叫人買賣。回覆 JSON："
          "{{\"why\": \"點解升／跌（具體新聞、政策、業績，有日期就寫）\", \"driver\": \"揀一個：政策／業績／行業週期／炒作／未知\", "
          "\"stage\": \"揀一個：早期／升溫／過熱／退潮\", \"leaders\": [\"題材入面最強或者最受關注嘅 2–4 隻股（代號：一句點解）\"], "
          "\"next\": \"之後要留意嘅催化劑（有日期就寫）\", \"how\": \"點樣參與比較穩陣（ETF 定個股、注碼）一句\", "
          "\"risks\": [\"風險 1–2 點\"], \"verdict\": \"揀一個：值得研究／觀望／小心（已過熱）\", \"reason\": \"一句\"}}。搵唔到嘅寫空字串。")
GUIDE = ("你係美股題材研究員，用香港廣東話口語幫新手睇「題材雷達」。背景：冇偷睇測試過，每星期追最熱嘅題材 ETF，長期反而拉低回報，"
         "所以重點係早啲知道、理解點解、控制注碼，唔係見升就追。數據同 AI 分析：\n{data}\n"
         "回覆 JSON：{{\"now\": \"而家資金流緊去邊幾個題材、點解（2–3 句，引用數字）\", \"early\": [\"新聞有訊號但價錢未大升嘅題材（早期）1–2 個，冇就空陣列\"], "
         "\"hot\": [\"已經升好多、要小心追高嘅題材 1–2 個\"], \"how\": [\"點樣用題材雷達嘅 2–3 條規則（結合今次例子，例如注碼、等回調、睇新聞）\"]}}")


def chart(sym):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1y&interval=1d", 30)["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    rows = [(c, v) for c, v in zip(q["close"], q["volume"]) if c is not None]
    return [c for c, _ in rows], [v or 0 for _, v in rows]


def metrics(c, v):
    if len(c) < 60:
        return None
    r = lambda n: c[-1] / c[-1 - n] - 1 if len(c) > n else None
    ma50 = sum(c[-50:]) / 50
    v5, v50 = sum(v[-5:]) / 5, sum(v[-50:]) / 50
    return dict(px=c[-1], r1=r(1), r5=r(5), r21=r(21), r63=r(63), hi=c[-1] / max(c) - 1, vs=v5 / v50 if v50 else None, up50=c[-1] > ma50,
                spark=[round(x, 2) for x in c[-63:]])


def pctl(vals, v):
    vals = sorted(x for x in vals if x is not None)
    return 100 * sum(1 for x in vals if x <= v) / len(vals) if vals and v is not None else 0


def news_hits(out, now):
    items = []
    try:
        N = json.loads((out / "news.json").read_text(encoding="utf-8"))
        for x in N.get("items") or []:
            t = datetime.fromisoformat(x["t"].replace("Z", "+00:00"))
            if t > now - timedelta(hours=48):
                items.append(dict(t=x["t"], text=(x.get("title") or "") + " " + (x.get("zh") or ""), title=x.get("zh") or x.get("title"), src=x.get("src"), link=x.get("link")))
    except Exception as e:  # noqa: BLE001
        print(f"[theme] news.json 讀唔到：{e}")
    try:
        T = json.loads((out / "trump_recent.json").read_text(encoding="utf-8"))
        for p in T.get("posts") or []:
            if p.get("ts", 0) > (now - timedelta(hours=48)).timestamp():
                items.append(dict(t=datetime.fromtimestamp(p["ts"], timezone.utc).isoformat(), text=p.get("text") or "", title="Trump：" + (p.get("text") or "")[:160], src="Truth Social", link=None))
    except Exception:  # noqa: BLE001
        pass
    return items


def main(out):
    out = Path(out)
    f = out / "theme.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    news = news_hits(out, now)
    rows, errs = [], []
    for key, name, etfs, stocks, kw in THEMES:
        E = None
        for e in etfs:
            try:
                E = dict(sym=e, **metrics(*chart(e)))
                break
            except Exception as ex:  # noqa: BLE001
                errs.append(f"{e}：{str(ex)[:40]}")
            time.sleep(0.3)
        mem = []
        for s in stocks:
            try:
                m = metrics(*chart(s))
                if m:
                    m.pop("spark", None)
                    mem.append(dict(sym=s, **m))
            except Exception as ex:  # noqa: BLE001
                errs.append(f"{s}：{str(ex)[:40]}")
            time.sleep(0.3)
        if not E:
            continue
        mem.sort(key=lambda m: -(m["r21"] or -9))
        pat = re.compile(kw, re.I)
        hits = [dict(title=n["title"], src=n["src"], link=n["link"], t=n["t"]) for n in news if pat.search(n["text"])]
        hits.sort(key=lambda h: h["t"], reverse=True)
        big5 = sum(1 for m in mem if (m["r5"] or 0) >= 0.15)
        boom = (E["r5"] or 0) >= 0.08 or big5 >= 3 or (E["hi"] >= -0.005 and (E["vs"] or 0) >= 1.5)
        rows.append(dict(key=key, name=name, etf=E, mem=mem, news=hits[:4], nnews=len(hits), boom=boom, big5=big5,
                         breadth=sum(1 for m in mem if m["up50"]) / len(mem) if mem else None,
                         newhi=sum(1 for m in mem if m["hi"] >= -0.01)))
    r5s, r21s, vss = [r["etf"]["r5"] for r in rows], [r["etf"]["r21"] for r in rows], [r["etf"]["vs"] for r in rows]
    for r in rows:
        e = r["etf"]
        r["heat"] = round(0.4 * pctl(r5s, e["r5"]) + 0.4 * pctl(r21s, e["r21"]) + 0.2 * pctl(vss, e["vs"]))
    rows.sort(key=lambda r: (-r["boom"], -r["heat"]))
    # AI
    old = prev.get("ai") or {}
    AI = {k: v for k, v in old.items() if now - datetime.fromisoformat(v["at"]) < timedelta(hours=AI_TTL_H if v.get("grounded", True) else 6)}
    want = [r for r in rows if r["boom"]] + rows[:4] + [r for r in rows if r["nnews"]]
    seen, todo = set(), []
    for r in want:
        if r["key"] not in seen and r["key"] not in AI:
            seen.add(r["key"]); todo.append(r)
    pc = lambda x: "—" if x is None else f"{x * 100:+.0f}%"
    for r in todo[:AI_MAX]:
        e = r["etf"]
        res, src, gr = ai_json(PROMPT.format(name=r["name"], etf=e["sym"], r5=pc(e["r5"]), r21=pc(e["r21"]), r63=pc(e["r63"]), hi=pc(e["hi"]),
                                             vs=f"{e['vs']:.1f}" if e["vs"] else "—",
                                             mem="、".join(f"{m['sym']} {pc(m['r5'])}／{pc(m['r21'])}" for m in r["mem"][:6]),
                                             news="；".join(h["title"][:120] for h in r["news"][:3]) or "冇"))
        if not res:
            errs.append(f"{r['name']} AI：{src[:400]}")
            break                                  # 額度用晒就停，下次再補
        AI[r["key"]] = dict({k: res.get(k) for k in ("why", "driver", "stage", "leaders", "next", "how", "risks", "verdict", "reason")},
                            src=src, grounded=gr, at=now.isoformat(timespec="seconds"))
        print(f"[theme] AI 分析 {r['name']}")
    guide = prev.get("guide")
    try:
        import ai as A
        key = ""                                    # 用邊個 AI 由 llm.py 決定（2026-10-20）
        data = "\n".join(f"{r['name']}（{r['etf']['sym']}）：5 日 {pc(r['etf']['r5'])}、21 日 {pc(r['etf']['r21'])}、成交 {r['etf']['vs'] or 0:.1f} 倍、熱度 {r['heat']}"
                         f"{'、爆發' if r['boom'] else ''}、新聞 {r['nnews']} 條；AI：{(AI.get(r['key']) or {}).get('stage', '')} {(AI.get(r['key']) or {}).get('why', '')[:120]}"
                         for r in rows)
        g, m = A.ask(key, A.STYLE + GUIDE.format(data=data), A.MODELS_D, light=True)   # 2026-10-24：導讀係輕鬆嘢，先用 Gemini
        guide = dict(g, model=m, at=now.isoformat(timespec="seconds"))
    except Exception as ex:  # noqa: BLE001
        errs.append(f"導讀：{str(ex)[:80]}")
    f.write_text(json.dumps(dict(at=now.isoformat(timespec="seconds"), themes=rows, ai=AI, guide=guide, errs=errs[:20]), ensure_ascii=False), encoding="utf-8")
    print(f"[theme] {len(rows)} 個題材、爆發 {sum(r['boom'] for r in rows)}、AI {len(AI)}；錯誤 {len(errs)}")


if __name__ == "__main__":
    import llm                       # 2026-10-20：記低今日 Claude 用量（同一個 workflow 嘅步驟共用 out/ai_usage.json）
    _out = sys.argv[1] if len(sys.argv) > 1 else "out"
    llm.start(_out)
    try:
        main(_out)
    finally:
        llm.finish(_out)
