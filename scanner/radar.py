"""新項目雷達（2026-10-03 用戶：如果之後出咗類似 HYPE 嘅項目會高度關注）。純資訊，唔係買入信號：
冇偷睇測試（stock-strategy/LAB_RADAR.md）用收入揀幣 2023 起輸 BTC 100 日線，所以 app 只顯示、唔叫買。

來源（全部免費）：DefiLlama 收入總表（近 30 日 vs 前 30 日）、持幣者收入（回購／分派）、母項目資料（代幣、coingecko id）；
CoinGecko 市值／全流通市值／30 日升跌；DefiLlama 代幣解鎖數據集（之後 30 日解鎖）。
三張表：收入增長最快、收入最大（有代幣）、未發幣（可能將來空投，亦可能永遠唔發）；加之後 30 日大解鎖。
.github/workflows/radar.yml 每 6 個鐘跑（--force），推去 radar 分支，同 feeds 分開，唔會拖慢新聞。
用法：python scanner/radar.py out
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
EVERY_H = 6
OV = "https://api.llama.fi/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType={}"
SKIP_CAT = {"Stablecoin Issuer", "RWA", "CeDeFi", "Block Builders", "Foundation", "CEX", "Chain"}
MIN_REV30 = 1e6      # 收入榜：近 30 日收入 ≥ 100 萬美元
MIN_PREV30 = 3e5     # 計增長：前 30 日 ≥ 30 萬美元
MIN_NOTOKEN = 5e5    # 未發幣：近 30 日收入 ≥ 50 萬美元
N = 12


def get(u, timeout=60):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read())


def groups():
    """按母項目合併收入：{key: dict(name, cat, rev30, prev30, hold30, gecko, sym, slug)}"""
    rev = get(OV.format("dailyRevenue"))["protocols"]
    hold = {str(o["defillamaId"]): o.get("total30d") or 0 for o in get(OV.format("dailyHoldersRevenue"))["protocols"]}
    pr = {str(p["id"]): p for p in get("https://api.llama.fi/protocols", 90)}
    par = {p["id"]: p for p in get("https://api.llama.fi/lite/protocols2", 90)["parentProtocols"]}
    G = {}
    for o in rev:
        if o.get("protocolType") == "chain" or o.get("category") in SKIP_CAT:
            continue
        p = pr.get(str(o["defillamaId"])) or {}
        pid = p.get("parentProtocol")
        meta = par.get(pid) if pid else p
        key = pid or str(o["defillamaId"])
        g = G.setdefault(key, dict(name=(meta or {}).get("name") or o["name"], cat=o.get("category"), rev30=0.0, prev30=0.0, hold30=0.0,
                                   gecko=(meta or {}).get("gecko_id") or None, sym=((meta or {}).get("symbol") or "").strip(),
                                   slug=(pid or "").replace("parent#", "") or o.get("slug"), top=0.0, listed=None, key=key))
        if p.get("listedAt"):
            g["listed"] = min(g["listed"] or p["listedAt"], p["listedAt"])
        r30 = o.get("total30d") or 0
        g["rev30"] += r30
        g["prev30"] += o.get("total60dto30d") or 0
        g["hold30"] += hold.get(str(o["defillamaId"]), 0)
        if r30 > g["top"]:
            g["top"], g["cat"] = r30, o.get("category")
    for g in G.values():
        if g["sym"] in ("", "-"):
            g["sym"] = ""
        g.pop("top")
    return G


def markets(ids):
    out = {}
    ids = sorted(set(ids))
    for k in range(0, len(ids), 100):   # CoinGecko 一次最多 100 隻（200 隻會失敗）
        u = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=250&price_change_percentage=30d&ids="
             + ",".join(ids[k:k + 100]))
        for m in get(u):
            out[m["id"]] = dict(px=m.get("current_price"), mcap=m.get("market_cap") or None, fdv=m.get("fully_diluted_valuation") or None,
                                chg30=(m.get("price_change_percentage_30d_in_currency") or 0) / 100, circ=m.get("circulating_supply"))
        time.sleep(2)
    return out


def unlocks(rows, mk, now):
    """之後 30 日解鎖：DefiLlama 數據集 metadata.events。返 [{name, sym, usd, pct, date}]，按佔流通市值排。"""
    try:
        have = set(get("https://defillama-datasets.llama.fi/emissionsProtocolsList"))
    except Exception as e:  # noqa: BLE001
        print(f"[radar] 解鎖清單攞唔到：{e}")
        return []
    t0, t1 = now.timestamp(), (now + timedelta(days=30)).timestamp()
    out = []
    for r in rows:
        cands = [s for s in {r["slug"], r["name"].lower().replace(" ", "-")} if s in have]
        if not cands or not r.get("gecko") or r["gecko"] not in mk:
            continue
        try:
            d = get(f"https://defillama-datasets.llama.fi/emissions/{cands[0]}", 60)
        except Exception as e:  # noqa: BLE001
            print(f"[radar] {cands[0]} 解鎖攞唔到：{e}")
            continue
        # 每個分配類別嘅累計解鎖日線：之後 30 日增加幾多（線性歸屬都計到；metadata.events 只記開始日，唔啱用）
        tok, first, labels = 0.0, None, []
        for s in (d.get("documentedData") or {}).get("data") or []:
            pts = [p for p in s.get("data") or [] if isinstance(p.get("timestamp"), (int, float))]
            at = lambda t: max([p.get("unlocked") or 0 for p in pts if p["timestamp"] <= t] or [0])
            dl = at(t1) - at(t0)
            if dl > 0:
                tok += dl
                labels.append(s.get("label") or "")
                nxt = min((p["timestamp"] for p in pts if t0 < p["timestamp"] <= t1 and (p.get("unlocked") or 0) > at(t0)), default=None)
                first = nxt if first is None or (nxt and nxt < first) else first
        m = mk[r["gecko"]]
        if tok <= 0 or not m.get("px") or not m.get("mcap"):
            continue
        usd = tok * m["px"]
        out.append(dict(name=r["name"], sym=r["sym"], usd=round(usd), pct=round(usd / m["mcap"], 4),
                        date=datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%d") if first else "", who=labels[:3]))
        time.sleep(0.5)
    return sorted([x for x in out if x["pct"] >= 0.001], key=lambda x: -x["pct"])  # 細過流通市值 0.1% 唔顯示


# X 加密研究人士（2026-10-03 用戶：結合 X 主流大師、AI 引導判斷）：近 7 日原創帖，對返雷達項目有冇提到
X_ACCOUNTS = [("DefiIgnas", "Ignas（DeFi 研究）"), ("milesdeutscher", "Miles Deutscher"), ("Route2FI", "Route 2 FI（空投／DeFi）"),
              ("0xngmi", "0xngmi（DefiLlama 創辦人）"), ("hosseeb", "Haseeb Qureshi（Dragonfly）"), ("blknoiz06", "Ansem"),
              ("0xMert_", "Mert（Helius／Solana）"), ("MessariCrypto", "Messari"), ("tokenterminal", "Token Terminal"), ("DefiLlama", "DefiLlama")]
X_DAYS = 7
AI_MAX = 6           # 每次最多新分析幾個（Gemini 免費搜尋額度有限；獨立 workflow 每 6 個鐘一次）
AI_TTL_H = 72        # 每個項目分析留 3 日先重做
NEW_DAYS = 180       # 新上榜：DefiLlama 收錄 180 日內
MIN_NEW = 2e5        # 新上榜：近 30 日收入 ≥ 20 萬美元

AI_PROMPT = ("加密項目「{name}」（{sym}，類別 {cat}）。DefiLlama 數據：近 30 日協議收入 {rev}，對上 30 日比較 {growth}；{tok}；{val}。"
             "X 上面研究人士近 7 日提到佢嘅帖：{x}。"
             "用 Google 搜尋查證（官網、文件、新聞、X），用香港廣東話口語幫一個新手判斷呢個項目，唔好叫人買賣。回覆 JSON："
             "{{\"what\": \"做緊乜、用家係邊個（一句）\", \"why\": \"收入點解升／跌（一句，有具體原因）\", "
             "\"token\": \"揀一個：已有代幣／已宣佈會發幣／有積分計劃（可能空投）／公司產品，表明唔發幣／唔清楚\", "
             "\"airdrop\": \"如果未發幣：有冇積分或者空投計劃、點參與（一句）；已有代幣就寫空字串\", "
             "\"value\": \"收入有冇流去代幣持有人（回購、分紅、燒毀）定只係投票權；未發幣寫空字串\", "
             "\"unlock\": \"下一次大額代幣解鎖（日期、數量、佔流通幾多）；冇代幣或者搵唔到寫空字串\", "
             "\"outlook\": \"前景：應用場景、之後嘅催化劑（1–2 句）\", \"strengths\": [\"優勢 1–3 點\"], "
             "\"risks\": [\"風險 1–3 點（競爭、監管、解鎖、靠補貼、中心化等）\"], "
             "\"verdict\": \"揀一個：值得研究／觀望／小心\", \"reason\": \"點解咁判斷（一句）\"}}。搵唔到嘅欄位寫空字串，唔好估。")

GUIDE_PROMPT = ("你係加密研究導師，用香港廣東話口語幫一個新手睇「新項目雷達」。數據（DefiLlama 收入、CoinGecko 市值）同每個項目嘅 AI 分析：\n{data}\n"
                "X 加密研究人士近 7 日提到雷達項目嘅帖：\n{x}\n"
                "背景：我哋冇偷睇測試過，用收入揀山寨幣 2023 年起輸淨係揸 BTC 加 100 日線，所以呢張卡只係觀察同學習，唔可以當買入信號。"
                "回覆 JSON：{{\"themes\": [\"而家資金同用家流緊去邊類項目（2–3 點，引用具體項目同數字）\"], "
                "\"watch\": [\"最值得花時間研究嘅 2–3 個項目，每點「項目：點解（收入、前景、代幣設計）+ 要核實咩」\"], "
                "\"airdrop\": [\"未發幣入面邊個最似會派空投、點參與（1–2 點；冇就空陣列）\"], "
                "\"caution\": [\"要小心嘅 1–3 個（例如收入靠炒作、估值太貴、大解鎖、靠補貼）\"], "
                "\"how\": [\"教新手用呢張卡判斷嘅 2–3 個要點（結合今次例子）\"]}}")


def x_mentions(now, rows):
    """研究人士近 7 日帖，對返雷達項目（名或者 $代號）。返 ({key: [帖]}, 全部有提到項目嘅帖, errs)"""
    posts, errs = [], []
    for u, nm in X_ACCOUNTS:
        try:
            d = get("https://api.fxtwitter.com/2/search?" + urllib.parse.urlencode({"q": f"from:{u}", "feed": "latest", "count": "40"}), 30)
            for t in d.get("results") or []:
                txt = (t.get("text") or "").strip()
                ts = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y")
                if txt.startswith("@") or len(txt) < 40 or now - ts > timedelta(days=X_DAYS) or t.get("replying_to"):
                    continue
                posts.append(dict(user=u, name=nm, text=txt[:500], ts=int(ts.timestamp()), url=f"https://x.com/{u}/status/{t.get('id')}"))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            errs.append(f"X {u}：{str(e)[:60]}")
    M, hit = collections.defaultdict(list), []
    for r in rows:
        pats = [re.compile(r"\$" + re.escape(r["sym"]) + r"\b", re.I)] if len(r["sym"]) >= 2 else []
        first = r["name"].split(" ")[0]
        nm = first if len(first) >= 5 else r["name"]
        if len(nm) >= 5:
            pats.append(re.compile(r"\b" + re.escape(nm) + r"\b", re.I))
        for t in posts:
            if any(p.search(t["text"]) for p in pats):
                if t not in M[r["key"]]:
                    M[r["key"]].append(t)
                if t not in hit:
                    hit.append(t)
    return {k: sorted(v, key=lambda t: -t["ts"])[:4] for k, v in M.items()}, hit, errs


def ai_one(r, xs):
    import model as Mo                       # Gemini + Google 搜尋（同業績分析一樣）
    tok = f"代幣 {r['sym']}" if r["sym"] else "未有代幣"
    val = (f"流通市值 {r['mcap'] / 1e6:.0f} 百萬美元、市值 ÷ 年化收入 {r['pe_mc']} 倍（全流通 {r['pe_fdv']} 倍）、幣價 30 日 {r['chg30'] * 100:+.0f}%"
           if r.get("mcap") and r.get("pe_mc") is not None and r.get("chg30") is not None else "冇市值數據")
    g = "冇比較" if r.get("growth") is None else f"{r['growth'] * 100:+.0f}%"
    xt = "；".join(f"@{t['user']}：{t['text'][:200]}" for t in xs[:3]) or "冇"
    prompt = AI_PROMPT.format(name=r["name"], sym=r["sym"] or "冇代幣", cat=r["cat"], rev=f"{r['rev30'] / 1e6:.1f} 百萬美元",
                              growth=g, tok=tok, val=val, x=xt)
    res, src = Mo.ai_search(prompt)
    if res:
        return res, src, True
    # 2026-10-03：Google 搜尋額度（同業績、宏觀思考共用）用晒會 429 → 改用冇搜尋嘅 Gemini／GitHub Models，標明冇上網查證，24 小時後再試搜尋版
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    try:
        import ai as A
        res2, m = A.gemini(key, A.STYLE + prompt.replace("用 Google 搜尋查證（官網、文件、新聞、X），", "（今次冇得上網，只用你已知嘅資料；唔肯定嘅寫「唔清楚」，唔好估）")
                           + " 只回覆 JSON。", A.MODELS_D)
        return res2, f"{m}（冇上網查證；搜尋版失敗：{str(src)[:60]}）", False
    except Exception as e:  # noqa: BLE001
        return None, f"{src}｜後備：{str(e)[:80]}", False


def brief(r, a):
    g = "—" if r.get("growth") is None else f"{r['growth'] * 100:+.0f}%"
    s = f"{r['name']}（{r['sym'] or '未發幣'}，{r['cat']}）收入 {r['rev30'] / 1e6:.1f}M，增長 {g}"
    if r.get("pe_mc") is not None:
        s += f"，市值÷年收入 {r['pe_mc']} 倍"
    if a:
        s += f"；AI：{a.get('what', '')} 判斷 {a.get('verdict', '')}（{a.get('reason', '')}）代幣狀態 {a.get('token', '')}"
    return s


def ai_guide(R, hit):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, "冇 GEMINI_API_KEY"
    import ai as A
    parts = []
    for k, t in (("growth", "收入增長最快"), ("big", "收入最大"), ("notoken", "未發幣"), ("new", "新上榜")):
        parts.append(f"[{t}] " + "；".join(brief(r, R["ai"].get(r["key"])) for r in R[k][:8]))
    parts.append("[解鎖] " + "；".join(f"{u['name']} {u['date']} {u['pct'] * 100:.1f}%" for u in R["unlocks"]))
    xt = "\n".join(f"@{t['user']}：{t['text'][:250]}" for t in hit[:15]) or "冇"
    try:
        return A.gemini(key, A.STYLE + GUIDE_PROMPT.format(data="\n".join(parts), x=xt), A.MODELS_D)
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:120]


def main(out):
    out = Path(out)
    f = out / "radar.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    if prev.get("at") and "--force" not in sys.argv and now - datetime.fromisoformat(prev["at"]) < timedelta(hours=EVERY_H):
        print("[radar] 未夠 6 個鐘，沿用上一份")
        return
    G = list(groups().values())
    for g in G:
        g["growth"] = g["rev30"] / g["prev30"] - 1 if g["prev30"] >= MIN_PREV30 else None
    tok = [g for g in G if g["gecko"]]
    big = sorted([g for g in tok if g["rev30"] >= MIN_REV30], key=lambda g: -g["rev30"])
    grow = sorted([g for g in G if g["rev30"] >= MIN_REV30 and g["growth"] is not None], key=lambda g: -g["growth"])
    cut = (now - timedelta(days=NEW_DAYS)).timestamp()
    new = sorted([g for g in G if g["listed"] and g["listed"] >= cut and g["rev30"] >= MIN_NEW], key=lambda g: -g["rev30"])
    notok = sorted([g for g in G if not g["gecko"] and not g["sym"] and g["rev30"] >= MIN_NOTOKEN], key=lambda g: -g["rev30"])
    mk = markets([g["gecko"] for g in big[:60] + [g for g in grow[:N] + new[:N * 2] if g["gecko"]]])
    # 舊項目改名或者 DefiLlama 新加統計（例如 Sky）都會有新收錄日：代幣市值 ≥ 10 億美元嘅唔當新
    new = [g for g in new if not (g["gecko"] and (mk.get(g["gecko"]) or {}).get("mcap") and mk[g["gecko"]]["mcap"] >= 1e9)]
    seen = dict(prev.get("seen") or {})          # 第一次出現喺雷達嘅日子（「新」標籤）

    def row(g):
        m = mk.get(g["gecko"] or "", {})
        ann = g["rev30"] * 365 / 30
        seen.setdefault(g["key"], now.strftime("%Y-%m-%d"))
        return dict(key=g["key"], name=g["name"], cat=g["cat"], sym=g["sym"], gecko=g["gecko"], slug=g["slug"], rev30=round(g["rev30"]),
                    growth=None if g["growth"] is None else round(g["growth"], 3), buyback=g["hold30"] > 0, hold30=round(g["hold30"]),
                    mcap=m.get("mcap"), fdv=m.get("fdv"), chg30=None if not m else round(m["chg30"], 3),
                    pe_mc=round(m["mcap"] / ann, 1) if m.get("mcap") and ann else None,
                    pe_fdv=round(m["fdv"] / ann, 1) if m.get("fdv") and ann else None,
                    listed=datetime.fromtimestamp(g["listed"], timezone.utc).strftime("%Y-%m-%d") if g["listed"] else None)

    R = dict(at=now.isoformat(timespec="seconds"), growth=[row(g) for g in grow[:N]], big=[row(g) for g in big[:N]],
             notoken=[row(g) for g in notok[:N + 4]], new=[row(g) for g in new[:N]], n=len(G))
    for k in ("growth", "big", "notoken", "new"):
        for r in R[k]:
            r["first"] = seen[r["key"]]
    R["since"] = prev.get("since") or now.strftime("%Y-%m-%d")     # 雷達開始日：嗰日已經喺榜嘅唔標「新」
    R["seen"] = seen                                                 # 唔刪：刪咗會令舊項目再出現時誤標「新」（每個只係幾十 byte）
    R["unlocks"] = unlocks([row(g) for g in big[:40]], mk, now)[:8]

    allrows = list({r["key"]: r for k in ("notoken", "growth", "new", "big") for r in R[k]}.values())
    XM, hit, errs = x_mentions(now, allrows)
    R["x"], R["x_n"] = XM, len(hit)
    # AI 逐個分析：舊分析未過 3 日就沿用；優先次序 = 未發幣、增長、新上榜、最大
    old = prev.get("ai") or {}
    R["ai"] = {k: v for k, v in old.items()
               if now - datetime.fromisoformat(v["at"]) < timedelta(hours=AI_TTL_H if v.get("grounded", True) else 24)}
    todo = [r for r in allrows if r["key"] not in R["ai"]]
    for r in todo[:AI_MAX]:
        res, src, grounded = ai_one(r, XM.get(r["key"], []))
        if not res:
            errs.append(f"{r['name']} AI：{src}")
            continue
        R["ai"][r["key"]] = dict({k: res.get(k) for k in ("what", "why", "token", "airdrop", "value", "unlock", "outlook", "strengths", "risks", "verdict", "reason")},
                                 src=src, grounded=grounded, at=now.isoformat(timespec="seconds"))
        print(f"[radar] AI 分析 {r['name']}")
    R["ai_pending"] = max(0, len(todo) - AI_MAX)
    keep = {r["key"] for r in allrows}
    R["ai"] = {k: v for k, v in R["ai"].items() if k in keep}
    gd, gm = ai_guide(R, hit)
    R["guide"] = dict(gd, model=gm, at=now.isoformat(timespec="seconds")) if gd else prev.get("guide")
    if not gd:
        errs.append(f"導讀：{gm}")
    R["errs"] = errs
    f.write_text(json.dumps(R, ensure_ascii=False), encoding="utf-8")
    print(f"[radar] 增長 {len(R['growth'])}、最大 {len(R['big'])}、未發幣 {len(R['notoken'])}、新上榜 {len(R['new'])}、解鎖 {len(R['unlocks'])}；"
          f"X 提到 {len(hit)} 帖；AI {len(R['ai'])} 個（待做 {R['ai_pending']}）；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
