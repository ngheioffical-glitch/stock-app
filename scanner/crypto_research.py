"""加密研究報告（2026-11-09 老師：「建議加密嗰度都可以加類似股票研究咁樣，輸入代號可以出到研究報告，但係報告包含咩就你要幫我設計」）。

同個股研究（research.py）一樣嘅分工：數字全部由程式攞同計，AI 只寫文字同評分，每句事實要標來源編號，程式剔走唔存在嘅編號。
報告內容（我設計，針對加密嘅重點）：
  1. 結論：一句講佢做乜、類別、AI 判斷（值得深入研究／中性觀察／小心，唔係買賣建議）同理由、本檔最大盲區
  2. 數據 [C1 CoinGecko]：價、市值排名、市值、完全攤薄估值（FDV）、市值 ÷ FDV、流通比例、24 小時成交 ÷ 市值、距歷史高位、
     7 日／30 日／1 年升跌、開發活動（GitHub 近 4 週 commit）
  3. 代幣經濟 [C3 DefiLlama 解鎖數據 + AI]：代幣用途、價值捕獲（收入有冇回購／分紅／燒毀返俾持有人）、通脹同解鎖、
     未來 30／90 日解鎖佔市值幾多（程式計）
  4. 基本面 [C2 DefiLlama]：TVL、近 30 日手續費、協議收入、持幣者收入；市值 ÷ 年化手續費（P/F）、÷ 年化收入（P/S）、
     持幣者收益率、市值 ÷ TVL（程式計；唔係協議或者 DefiLlama 冇收錄就寫「冇」）
  5. 技術（只供參考）：日 K（Coinbase 有就用佢嘅開高低收，冇就淨係收市線）+ BOS／MSS（structure.py，同股票同一條規則）
  6. 好淡理由、催化劑（有日子）、風險（監管、被黑、中心化、解鎖壓力）
  7. 同類比較：AI 揀 3–5 個同類，程式攞佢哋嘅市值、FDV、升跌、P/F
  8. 評分卡（AI，0–10）：基本面、代幣經濟、價值捕獲、團隊同治理、安全、社群同敘事
  9. 股價圖事件（AI 搵，有日子同來源）、名詞表、來源
來源：[C1] CoinGecko、[C2] DefiLlama 費用同 TVL、[C3] DefiLlama 解鎖數據、[C4] Coinbase 日 K；網上搜尋 [S1] 起。
輸出 docs/crypto/<id>.json（id = CoinGecko 代號）、docs/crypto/index.json（清單同每月用量）、docs/crypto/coins.json（市值頭 500，app 打字建議用）。
AI 經 scanner/llm.py（跟 app 嘅 AI 次序：DeepSeek 主力、Gemini 後備）；用量記入 docs/ai_usage_research.json（同個股研究同一本帳）。
只係研究參考，唔係投資建議；冇排程自動生成（只有用戶喺 app 撳先做），排程淨係每星期更新 coins.json（唔使 AI）。

用法：
  python scanner/crypto_research.py bitcoin [ETH ...]   代號、CoinGecko id 或者名都得
  python scanner/crypto_research.py --list              淨係更新 coins.json
  python scanner/crypto_research.py ETH --dry           唔叫 AI（測試）
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bars  # noqa: E402
import llm  # noqa: E402
import structure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("CRYPTO_OUT") or ROOT / "docs" / "crypto")
HKT = ZoneInfo("Asia/Hong_Kong")
CG = "https://api.coingecko.com/api/v3"
LL = "https://api.llama.fi"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
STYLE = "用香港廣東話口語、繁體中文。專有名詞（項目、代幣、公司、人名、交易所）保留英文或者通用中譯。"
MONTH_USD = float(os.environ.get("CRYPTO_MONTH_USD", "10"))       # 每月加密研究用量上限（美元）
EST_USD = float(os.environ.get("CRYPTO_EST_USD", "0.3"))
MAX_SEARCH = int(os.environ.get("CRYPTO_MAX_SEARCH", "8"))
MAX_TOKENS = int(os.environ.get("CRYPTO_MAX_TOKENS", "32000"))
N_COINS = 500
SCORES = [("fundamentals", "基本面（用量同收入）"), ("tokenomics", "代幣經濟"), ("capture", "價值捕獲"), ("team", "團隊同治理"),
          ("security", "安全"), ("community", "社群同敘事")]
STANCES = ("值得深入研究", "中性觀察", "小心")
DISCLAIMER = ("AI 生成，可能有錯漏，唔係投資建議。數字（市值、FDV、解鎖、手續費、P/F）由程式按 CoinGecko、DefiLlama、Coinbase 數據計；"
              "評分同文字由 AI 寫，每句事實嘅來源喺「來源」。「值得深入研究／中性觀察／小心」只係研究優先次序，唔係買賣訊號。加密資產波幅好大，可以歸零。")


# ───────────────────────────────────────────── 細工具
def get(u, timeout=60, tries=3):
    """JSON GET；CoinGecko 429（每分鐘上限）就等一陣再試。404 → None。"""
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and k < tries - 1:
                time.sleep(25 * (k + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if k == tries - 1:
                raise
            time.sleep(5)
    return None


def num(x, nd=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd) if nd is not None else v


def ratio(a, b, nd=4):
    return round(a / b, nd) if a is not None and b else None


def money(x):
    if x is None:
        return "—"
    a = abs(x)
    s = "-" if x < 0 else ""
    if a >= 1e12:
        return f"{s}{a / 1e12:.2f} 萬億美元"
    if a >= 1e8:
        return f"{s}{a / 1e8:,.1f} 億美元"
    if a >= 1e4:
        return f"{s}{a / 1e4:,.0f} 萬美元"
    return f"{s}{a:,.0f} 美元"


def px(x):
    return "—" if x is None else f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6g}"


def pct(x, nd=1):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def pc(x, nd=1):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def _cut(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _src(lst, valid):
    out = []
    for x in lst or []:
        m = re.match(r"\s*\[?\s*([CS])\s*(\d+)", str(x), re.I)
        k = f"{m.group(1).upper()}{m.group(2)}" if m else None
        if k in valid and k not in out:
            out.append(k)
    return out


# ───────────────────────────────────────────── 1. 代號清單同搵幣
def coin_list(n=N_COINS):
    """市值頭 n 個：[{id, s, n, r}]（app 打字建議用）。"""
    out = []
    for page in range(1, n // 250 + 1):
        rows = get(f"{CG}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}") or []
        out += [dict(id=m["id"], s=str(m.get("symbol") or "").upper(), n=m.get("name") or m["id"], r=m.get("market_cap_rank"))
                for m in rows if m.get("id")]
        time.sleep(2.5)
    return out


def save_list(coins):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "coins.json").write_text(json.dumps(dict(generated=datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT"), coins=coins),
                                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def load_list():
    try:
        return json.loads((OUT / "coins.json").read_text(encoding="utf-8")).get("coins") or []
    except Exception:  # noqa: BLE001
        return []


def resolve(q, coins):
    """代號（ETH）、CoinGecko id（ethereum）或者名（Ethereum）→ id。同一個代號有幾個幣，揀市值排名最前嗰個。"""
    q0 = str(q or "").strip().lstrip("$")
    if not q0:
        return None
    ql = q0.lower()
    if any(c["id"] == ql for c in coins):
        return ql
    rank = lambda c: c.get("r") or 10 ** 6  # noqa: E731
    hit = sorted([c for c in coins if c["s"].lower() == ql], key=rank) or sorted([c for c in coins if c["n"].lower() == ql], key=rank)
    if hit:
        return hit[0]["id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,60}", ql):
        return None
    d = get(f"{CG}/search?query={urllib.parse.quote(q0)}") or {}
    cs = [c for c in d.get("coins") or [] if c.get("symbol", "").lower() == ql or c.get("id") == ql or c.get("name", "").lower() == ql]
    cs = cs or (d.get("coins") or [])
    return cs[0]["id"] if cs else None


# ───────────────────────────────────────────── 2. 收集數據
LONG_DAYS = 3700                 # 2026-11-09：K 線全螢幕週 K／月 K 要長歷史（大約 10 年；幣上市之前嗰段 Coinbase 返空，跳過）


def coinbase_ohlc(sym, days=365):
    """Coinbase 日 K（{SYM}-USD）：[(日子, 開, 高, 低, 收)]，冇呢個幣就 []。每次最多 300 支（bars.coinbase_daily）。"""
    return bars.coinbase_daily(sym, days, get)


def llama_maps():
    """DefiLlama：gecko_id → 協議（連母項目）同鏈；返 (protocols by id, parents, chains, fees, rev, hold)。"""
    ov = lambda t: get(f"{LL}/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType={t}", 90)  # noqa: E731
    pr = get(f"{LL}/protocols", 90) or []
    par = (get(f"{LL}/lite/protocols2", 90) or {}).get("parentProtocols") or []
    chains = get(f"{LL}/v2/chains", 60) or []
    fees, rev, hold = ((ov(t) or {}).get("protocols") or [] for t in ("dailyFees", "dailyRevenue", "dailyHoldersRevenue"))
    return pr, par, chains, fees, rev, hold


def defi_block(cid, maps):
    """呢個幣喺 DefiLlama 嘅 TVL、手續費、收入（母項目就加埋子項目）。冇收錄返 None。"""
    pr, par, chains, fees, rev, hold = maps

    def block(chain, parent, kids):
        ids = {str(p.get("id")) for p in kids}
        names = {chain["name"]} if chain else set()
        mine = lambda o: str(o.get("defillamaId")) in ids or (o.get("protocolType") == "chain" and o.get("name") in names)  # noqa: E731

        def tot(rows, key):
            hit = [o.get(key) or 0 for o in rows if mine(o)]
            return float(sum(hit)) if hit else None
        tvl = num(chain.get("tvl")) if chain else sum(p.get("tvl") or 0 for p in kids)
        # 類別：收手續費最多嗰個子項目（例如 Hyperliquid 係 Derivatives，唔係佢條橋）
        top = max((o for o in fees if mine(o)), key=lambda o: o.get("total30d") or 0, default=None)
        cat = "Chain" if chain else (top or {}).get("category") or max(kids, key=lambda p: p.get("tvl") or 0).get("category")
        slug = (chain or {}).get("name") or (parent or {}).get("id", "").replace("parent#", "") or kids[0].get("slug")
        return dict(slug=slug, name=(chain or parent or kids[0]).get("name"), kind="chain" if chain else "protocol", category=cat, tvl=num(tvl),
                    fees30=tot(fees, "total30d"), fees1d=tot(fees, "total24h"), rev30=tot(rev, "total30d"), hold30=tot(hold, "total30d"))
    chain = next((c for c in chains if c.get("gecko_id") == cid), None)
    parent = next((p for p in par if p.get("gecko_id") == cid), None)
    kids = [p for p in pr if (parent and p.get("parentProtocol") == parent.get("id")) or (not parent and p.get("gecko_id") == cid)]
    cands = ([block(chain, None, [])] if chain else []) + ([block(None, parent, kids)] if kids else [])
    # 鏈同協議都有（例如 ETH 條鏈 vs「Ethereum Foundation」、HYPE 條鏈 vs Hyperliquid 永續）：揀手續費多嗰個，打和揀鏈
    return max(cands, key=lambda b: (b["fees30"] or 0, b["kind"] == "chain")) if cands else None


def unlocks(slug, price, mcap):
    """未來 30／90 日解鎖（DefiLlama 解鎖數據集，同 radar.py 一樣做法）：{d30, d90, next, who}，佔市值。"""
    if not slug or not price or not mcap:
        return None
    try:
        have = set(get("https://defillama-datasets.llama.fi/emissionsProtocolsList", 60) or [])
        if slug not in have:
            return None
        d = get(f"https://defillama-datasets.llama.fi/emissions/{slug}", 60) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[crypto] 解鎖數據攞唔到：{str(e)[:80]}")
        return None
    now = datetime.now(timezone.utc).timestamp()
    res = {}
    for days in (30, 90):
        t1, tok, first, who = now + days * 86400, 0.0, None, []
        for s in (d.get("documentedData") or {}).get("data") or []:
            pts = [p for p in s.get("data") or [] if isinstance(p.get("timestamp"), (int, float))]
            at = lambda t: max([p.get("unlocked") or 0 for p in pts if p["timestamp"] <= t] or [0])  # noqa: E731
            dl = at(t1) - at(now)
            if dl > 0:
                tok += dl
                who.append(s.get("label") or "")
                nxt = min((p["timestamp"] for p in pts if now < p["timestamp"] <= t1 and (p.get("unlocked") or 0) > at(now)), default=None)
                first = nxt if first is None or (nxt and nxt < first) else first
        res[f"d{days}"] = round(tok * price / mcap, 4)
        if days == 90:
            res["next"] = datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%d") if first else None
            res["who"] = [w for w in who if w][:4]
    return res


def collect(cid, maps=None):
    c = get(f"{CG}/coins/{cid}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=true&sparkline=false")
    if not c or not c.get("market_data"):
        raise RuntimeError(f"{cid}：CoinGecko 冇呢個幣")
    md, sym = c["market_data"], str(c.get("symbol") or "").upper()
    usd = lambda k: num((md.get(k) or {}).get("usd")) if isinstance(md.get(k), dict) else None  # noqa: E731
    price, mcap, fdv = usd("current_price"), usd("market_cap") or None, usd("fully_diluted_valuation") or None
    circ, total, mx = num(md.get("circulating_supply")), num(md.get("total_supply")), num(md.get("max_supply"))
    time.sleep(2)
    mc = get(f"{CG}/coins/{cid}/market_chart?vs_currency=usd&days=365&interval=daily") or {}
    closes = {}
    for ts, p in mc.get("prices") or []:
        d = datetime.fromtimestamp(ts / 1000, timezone.utc).date()
        if d < datetime.now(timezone.utc).date() and p:
            closes[d.isoformat()] = float(p)
    k_all = coinbase_ohlc(sym, LONG_DAYS) if sym else []
    k = k_all[-365:]
    if len(k) >= 60:
        chart = dict(d=[x[0] for x in k], o=[structure._r(x[1]) for x in k], h=[structure._r(x[2]) for x in k],
                     l=[structure._r(x[3]) for x in k], c=[structure._r(x[4]) for x in k], src="C4",
                     long=bars.long_bars(*([x[j] for x in k_all] for j in range(5))))   # 全螢幕 K 線週 K／月 K
        mid = sorted(x[4] for x in k)[len(k) // 2]
        ta = structure.analyze(chart["d"], [x[1] for x in k], [x[2] for x in k], [x[3] for x in k], [x[4] for x in k],
                               tick=max(1e-12, mid * 1e-5), unit="日")
    else:
        ds = sorted(closes)
        chart = dict(d=ds, c=[structure._r(closes[d]) for d in ds], src="C1")
        ta = None
    if len(chart["d"]) < 30:
        raise RuntimeError(f"{cid}：價格歷史太短（{len(chart['d'])} 日）")
    try:
        maps = maps or llama_maps()
        defi = defi_block(cid, maps)
    except Exception as e:  # noqa: BLE001
        print(f"[crypto] DefiLlama 攞唔到：{str(e)[:100]}")
        maps, defi = None, None
    if defi and mcap:
        ann = lambda x: x * 365 / 30 if x else None  # noqa: E731
        defi.update(pf=ratio(mcap, ann(defi["fees30"]), 1), ps=ratio(mcap, ann(defi["rev30"]), 1),
                    hold_yield=ratio(ann(defi["hold30"]), mcap), mc_tvl=ratio(mcap, defi["tvl"], 2))
    unl = unlocks((defi or {}).get("slug"), price, mcap)
    dev = c.get("developer_data") or {}
    links = c.get("links") or {}
    gh = [u for u in ((links.get("repos_url") or {}).get("github") or []) if u][:1]
    mkt = dict(price=price, rank=c.get("market_cap_rank"), mcap=mcap, fdv=fdv, mc_fdv=ratio(mcap, fdv, 3), vol24=usd("total_volume"),
               vol_mcap=ratio(usd("total_volume"), mcap), circ=circ, total=total, max=mx,
               circ_pct=ratio(circ, mx or total, 3), ath=usd("ath"), ath_date=str((md.get("ath_date") or {}).get("usd") or "")[:10] or None,
               off_ath=ratio(price, usd("ath")) - 1 if price and usd("ath") else None,
               chg7=num(md.get("price_change_percentage_7d"), 2), chg30=num(md.get("price_change_percentage_30d"), 2),
               chg1y=num(md.get("price_change_percentage_1y"), 2), commits4w=dev.get("commit_count_4_weeks"), stars=dev.get("stars"))
    for k2 in ("chg7", "chg30", "chg1y"):
        mkt[k2] = mkt[k2] / 100 if mkt[k2] is not None else None
    return dict(id=cid, sym=sym, name=c.get("name") or cid, categories=[x for x in c.get("categories") or [] if x][:6],
                genesis=c.get("genesis_date"), desc=_cut(re.sub(r"<[^>]+>", "", (c.get("description") or {}).get("en") or ""), 1500),
                home=next((u for u in links.get("homepage") or [] if u), None),
                x=("https://x.com/" + links["twitter_screen_name"]) if links.get("twitter_screen_name") else None, github=gh[0] if gh else None,
                price_date=chart["d"][-1], mkt=mkt, defi=defi, unlock=unl, chart=chart, ta=ta, _maps=maps)


def base_sources(D):
    s = [dict(id="C1", kind="data", title=f"CoinGecko：{D['name']}（{D['sym']}）價格、市值、供應、開發活動（{D['price_date']}）",
              url=f"https://www.coingecko.com/en/coins/{D['id']}")]
    if D.get("defi"):
        f = D["defi"]
        s.append(dict(id="C2", kind="data", title=f"DefiLlama：{f['name']} TVL、手續費、收入",
                      url=f"https://defillama.com/{'chain' if f['kind'] == 'chain' else 'protocol'}/{urllib.parse.quote(f['slug'])}"))
    if D.get("unlock"):
        s.append(dict(id="C3", kind="data", title=f"DefiLlama 解鎖數據：{D['defi']['name']}", url=f"https://defillama.com/unlocks/{D['defi']['slug']}"))
    if D["chart"].get("src") == "C4":
        s.append(dict(id="C4", kind="data", title=f"Coinbase：{D['sym']}-USD 日 K", url=f"https://exchange.coinbase.com/trade/{D['sym']}-USD"))
    return s


def facts_text(D):
    m, f, u = D["mkt"], D.get("defi"), D.get("unlock")
    L = [f"項目：{D['name']}（{D['sym']}，CoinGecko id {D['id']}）；類別 {', '.join(D['categories']) or '—'}；開始 {D.get('genesis') or '—'} [C1]",
         f"價：{px(m['price'])} 美元（{D['price_date']}）；市值排名 #{m['rank'] or '—'}；市值 {money(m['mcap'])}；完全攤薄估值 {money(m['fdv'])}；"
         f"市值 ÷ FDV {m['mc_fdv'] if m['mc_fdv'] is not None else '—'}；流通比例 {pc(m['circ_pct'])} [C1]",
         f"升跌：7 日 {pct(m['chg7'])}、30 日 {pct(m['chg30'])}、1 年 {pct(m['chg1y'])}；距歷史高位 {pct(m['off_ath'])}（高位 {px(m['ath'])}，{m['ath_date'] or '—'}）；"
         f"24 小時成交 ÷ 市值 {pc(m['vol_mcap'])} [C1]",
         f"開發活動：GitHub 近 4 週 commit {m['commits4w'] if m['commits4w'] is not None else '—'} [C1]"]
    if f:
        L.append(f"DefiLlama（{f['name']}，{f['category']}）：TVL {money(f['tvl'])}；近 30 日手續費 {money(f['fees30'])}、協議收入 {money(f['rev30'])}、"
                 f"持幣者收入 {money(f['hold30'])}；市值 ÷ 年化手續費 {f.get('pf') or '—'} 倍、÷ 年化收入 {f.get('ps') or '—'} 倍、"
                 f"持幣者收益率 {pc(f.get('hold_yield'))}、市值 ÷ TVL {f.get('mc_tvl') or '—'} [C2]")
    else:
        L.append("DefiLlama 冇收錄呢個項目嘅協議數據（可能唔係 DeFi 協議或者鏈）[C2]")
    if u:
        L.append(f"未來解鎖：30 日內約佔市值 {pc(u['d30'])}、90 日內 {pc(u['d90'])}；下一次 {u.get('next') or '—'}（{'、'.join(u.get('who') or []) or '—'}）[C3]")
    if D.get("ta"):
        L.append(structure.facts_line(D["ta"]) + (" [C4]" if D["chart"].get("src") == "C4" else ""))
    L.append(f"簡介（CoinGecko，英文）：{D['desc'][:900]} [C1]")
    return "\n".join(L)


# ───────────────────────────────────────────── 3. AI
def _s(d):
    return {"type": "string", "description": d}


def _i(d):
    return {"type": "integer", "description": d}


def _e(v, d):
    return {"type": "string", "enum": list(v), "description": d}


def _a(item, d):
    return {"type": "array", "items": item, "description": d}


def _o(props, d=None):
    x = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if d:
        x["description"] = d
    return x


SRC = _a({"type": "string"}, "引用嘅來源編號，例如 [\"C1\", \"S3\"]；只可以用來源清單入面有嘅編號")
PT = _o(dict(text=_s("一點，有數字或者日子，70 字內"), src=SRC))
SCHEMA = _o(dict(
    name_zh=_s("通用中文名；冇就寫英文名"),
    one_liner=_s("呢個項目做乜，一句白話，30 字內"),
    kind=_s("類別，例如 公鏈（L1）、以太坊二層（L2）、DeFi 借貸、去中心化交易所、穩定幣、Meme、AI、遊戲、RWA，10 字內"),
    what=_s("佢點運作、用家係邊個、點賺錢，白話 2–3 句，標來源"),
    token_use=_a(PT, "代幣用途 1–4 點（手續費、質押、治理、抵押、分紅…）"),
    capture=_o(dict(level=_e(["強", "一般", "弱", "冇"], "價值捕獲：協議收入有幾多返到代幣持有人"),
                    why=_s("回購、分紅、燒毀、質押收益定只係投票權；有數字，80 字內"), src=SRC)),
    supply=_o(dict(text=_s("通脹率、發行時間表、團隊同投資者份額、主要解鎖（有日子同數量），100 字內"), src=SRC)),
    team=_o(dict(text=_s("團隊、基金會、主要投資者、治理方式，80 字內"), src=SRC)),
    catalysts=_a(_o(dict(date=_s("YYYY-MM-DD 或者 YYYY-MM；唔知就空"), text=_s("之後可能推動價格嘅事，60 字內"), src=SRC)), "催化劑 2–5 個"),
    risks=_a(PT, "風險 3–5 點：監管、被黑、中心化、解鎖壓力、競爭、依賴單一用途…"),
    bull=_a(PT, "看好理由 3–5 點"),
    bear=_a(PT, "看淡理由 3–5 點"),
    peers=_a({"type": "string"}, "3–5 個最可比嘅加密代幣代號（例如 SOL、AVAX）"),
    peers_note=_s("同類比較一段，用數據講佢貴定平、強定弱，80 字內"),
    scores=_a(_o(dict(key=_e([k for k, _ in SCORES], "評分項目"), score=_i("0 最差 – 10 最好"), why=_s("理由，有數字，標來源"), src=SRC)),
              "評分卡 6 項各一個：fundamentals 基本面（真實用量、收入）、tokenomics 代幣經濟（通脹、解鎖、分配）、capture 價值捕獲、"
              "team 團隊同治理、security 安全（審計、被黑歷史、中心化程度）、community 社群同敘事"),
    stance=_e(STANCES, "研究判斷（唔係買賣建議）：值得深入研究／中性觀察／小心"),
    stance_why=_s("判斷理由，用提示嘅數字，100 字內，唔好用買賣指令語氣"),
    blind_spot=_o(dict(title=_s("最多人忽略嘅風險或者重點，16 字內"), detail=_s("點解、要睇乜，80 字內"), src=SRC)),
    tech_view=_s("技術面（只供參考）一段，80 字內：用提示嘅 BOS／MSS 同 ADR、距 52 週高、距 50 日線；冇技術結構數據就寫空字串"),
    events=_a(_o(dict(date=_s("YYYY-MM-DD"), label=_s("價格圖標籤，8 字內"), detail=_s("發生乜事、對價格點影響，60 字內"), src=SRC)),
              "價格圖要標嘅重要事件 3–6 件（過去一年內，日期要準）"),
    glossary=_a(_o(dict(term=_s("名詞（要喺你嘅文字入面出現過）"), define=_s("白話解釋，50 字內"))), "名詞表 6–15 個"),
    next_check=_s("之後要留意嘅一件事（例如 某日解鎖、主網升級）"),
))
SYS = ("你係一個嚴謹、獨立嘅加密資產研究員，幫新手睇清楚一個項目：做乜、代幣有冇價值捕獲、供應同解鎖、真實用量同收入、風險。" + STYLE +
       "只可以根據提供嘅數據同研究筆記寫；每個事實都要標來源編號（例如 [C1]、[S3]），唔可以用來源清單以外嘅編號，唔可以作數字。"
       "唔肯定就講唔肯定。唔好叫人買賣，唔好講目標價。只回覆一個 JSON object。")


def gather_prompt(D):
    return (f"研究對象：{D['name']}（{D['sym']}）加密項目。今日係 {datetime.now(HKT):%Y-%m-%d}（香港時間）。\n"
            f"下面係程式已經攞到嘅數據（唔使再搜呢啲）：\n{facts_text(D)}\n\n"
            f"請用網上搜尋補充（最多 {MAX_SEARCH} 次），每點寫具體數字同日期，同埋引用搜尋結果：\n"
            "1. 呢個項目做乜、真實用量（用戶數、交易量、收入）最新情況。\n"
            "2. 代幣用途同價值捕獲：有冇回購、分紅、燒毀、質押收益；收入係咪真係返到持有人。\n"
            "3. 供應：通脹率、團隊同投資者份額、之後 6 個月主要解鎖（日期、數量）。\n"
            "4. 團隊、基金會、主要投資者、治理；有冇中心化或者控制權問題。\n"
            "5. 過去一年令價格大升或者大跌嘅事件（每件寫日期）。\n"
            "6. 安全：審計、被黑或者出事紀錄、監管或者訴訟。\n"
            "7. 主要對手同佢嘅分別；之後嘅催化劑（升級、上架、ETF、合作）。\n"
            f"筆記{STYLE}")


def analysis_prompt(D, notes, src):
    return (f"研究對象：{D['name']}（{D['sym']}）。今日 {datetime.now(HKT):%Y-%m-%d}。價格圖由 {D['chart']['d'][0]} 開始。\n\n"
            f"【程式數據】\n{facts_text(D)}\n\n【網上研究筆記】\n{notes or '（今次冇網上筆記）'}\n\n"
            f"【來源清單】\n" + "\n".join(f"[{s['id']}] {s['title']} — {s['url']}" for s in src) + "\n\n"
            "評分要有理由同來源；市值 ÷ FDV 低、解鎖多就要喺代幣經濟同風險講；DefiLlama 冇收入數據就唔好作收入數字。")


def clean(A, src, D):
    valid = {s["id"] for s in src}
    A = dict(A or {})
    pts = lambda k, n, m=7: [dict(text=_cut(x.get("text"), n), src=_src(x.get("src"), valid)) for x in A.get(k) or [] if isinstance(x, dict) and x.get("text")][:m]  # noqa: E731
    for k in ("token_use", "risks", "bull", "bear"):
        A[k] = pts(k, 160)
    for k, n in (("capture", 200), ("supply", 240), ("team", 200)):
        x = A.get(k) if isinstance(A.get(k), dict) else {}
        A[k] = dict({kk: v for kk, v in x.items() if kk != "src"}, src=_src(x.get("src"), valid))
        for kk in ("why", "text"):
            if kk in A[k]:
                A[k][kk] = _cut(A[k][kk], n)
    if A["capture"].get("level") not in ("強", "一般", "弱", "冇"):
        A["capture"]["level"] = None
    A["catalysts"] = [dict(date=_cut(x.get("date"), 10), text=_cut(x.get("text"), 140), src=_src(x.get("src"), valid))
                      for x in A.get("catalysts") or [] if isinstance(x, dict) and x.get("text")][:6]
    seen, sc = set(), []
    for x in A.get("scores") or []:
        if isinstance(x, dict) and x.get("key") in dict(SCORES) and x["key"] not in seen:
            seen.add(x["key"])
            s = num(x.get("score")) or 0
            sc.append(dict(key=x["key"], name=dict(SCORES)[x["key"]], score=int(max(0, min(10, round(s)))), why=_cut(x.get("why"), 200),
                           src=_src(x.get("src"), valid)))
    A["scores"] = sorted(sc, key=lambda x: [k for k, _ in SCORES].index(x["key"]))
    if A.get("stance") not in STANCES:
        A["stance"] = None
    for k, n in (("one_liner", 60), ("kind", 16), ("what", 300), ("stance_why", 240), ("peers_note", 220), ("tech_view", 220),
                 ("next_check", 80), ("name_zh", 30)):
        A[k] = _cut(A.get(k), n)
    if not D.get("ta"):
        A["tech_view"] = ""
    b = A.get("blind_spot") if isinstance(A.get("blind_spot"), dict) else {}
    A["blind_spot"] = dict(title=_cut(b.get("title"), 24), detail=_cut(b.get("detail"), 180), src=_src(b.get("src"), valid))
    c0, c1 = D["chart"]["d"][0], D["chart"]["d"][-1]
    ev = []
    for x in A.get("events") or []:
        if not isinstance(x, dict):
            continue
        d = str(x.get("date") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and c0 <= d <= c1:
            ev.append(dict(date=d, label=_cut(x.get("label"), 16), detail=_cut(x.get("detail"), 140), src=_src(x.get("src"), valid)))
    A["events"] = sorted(ev, key=lambda x: x["date"])[:6]
    A["glossary"] = [dict(term=_cut(x.get("term"), 24), define=_cut(x.get("define"), 100)) for x in A.get("glossary") or []
                     if isinstance(x, dict) and x.get("term")][:15]
    A["peers"] = [p for p in dict.fromkeys(re.sub(r"[^A-Z0-9]", "", str(p).upper()) for p in A.get("peers") or []) if p and p != D["sym"]][:5]
    return A


def peer_rows(peers, coins, maps):
    ids = [resolve(p, coins) for p in peers]
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return []
    try:
        rows = get(f"{CG}/coins/markets?vs_currency=usd&price_change_percentage=30d,1y&ids=" + ",".join(ids)) or []
    except Exception as e:  # noqa: BLE001
        print(f"[crypto] 同類攞唔到：{str(e)[:80]}")
        return []
    out = []
    for m in rows:
        f = defi_block(m["id"], maps) if maps else None
        mc = num(m.get("market_cap")) or None
        out.append(dict(id=m["id"], sym=str(m.get("symbol") or "").upper(), name=m.get("name"), mcap=mc, fdv=num(m.get("fully_diluted_valuation")) or None,
                        mc_fdv=ratio(mc, num(m.get("fully_diluted_valuation")) or None, 3),
                        chg30=(num(m.get("price_change_percentage_30d_in_currency")) or 0) / 100,
                        chg1y=(num(m.get("price_change_percentage_1y_in_currency")) / 100) if m.get("price_change_percentage_1y_in_currency") is not None else None,
                        pf=ratio(mc, f["fees30"] * 365 / 30, 1) if f and f.get("fees30") else None))
    return out


def snap_events(D, events):
    d = D["chart"]["d"]
    pos = {x: i for i, x in enumerate(d)}
    return [dict(e, i=pos.get(e["date"], min(range(len(d)), key=lambda j: abs((date.fromisoformat(d[j]) - date.fromisoformat(e["date"])).days))))
            for e in events]


# ───────────────────────────────────────────── 4. 儲存
def assemble(D, src, A, peers, labels, cost):
    now = datetime.now(HKT)
    A = A or {}
    return dict(v=1, id=D["id"], sym=D["sym"], name=D["name"], name_zh=A.get("name_zh") or D["name"], one_liner=A.get("one_liner"), kind=A.get("kind"),
                categories=D["categories"], links=dict(home=D.get("home"), x=D.get("x"), github=D.get("github")),
                price=D["mkt"]["price"], price_date=D["price_date"], research_date=now.strftime("%Y-%m-%d"), generated=now.strftime("%Y-%m-%d %H:%M HKT"),
                models=labels, cost_usd=round(cost, 3), dry=not A,
                chart=dict(D["chart"], events=snap_events(D, A.get("events") or [])), ta=D.get("ta"),
                mkt=D["mkt"], defi=D.get("defi"), unlock=D.get("unlock"), peers=peers,
                ai={k: A.get(k) for k in ("what", "token_use", "capture", "supply", "team", "catalysts", "risks", "bull", "bear", "peers_note",
                                          "scores", "stance", "stance_why", "blind_spot", "tech_view", "glossary", "next_check")} if A else None,
                sources=src, disclaimer=DISCLAIMER)


def write_index(add_cost=0.0):
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "index.json"
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    items = []
    for p in sorted(OUT.glob("*.json")):
        if p.name in ("index.json", "coins.json"):
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        items.append(dict(id=r["id"], sym=r["sym"], name=r.get("name"), name_zh=r.get("name_zh"), date=r.get("research_date"), price=r.get("price"),
                          rank=(r.get("mkt") or {}).get("rank"), stance=((r.get("ai") or {}).get("stance")), kind=r.get("kind"),
                          one_liner=r.get("one_liner"), dry=r.get("dry"), model=(r.get("models") or {}).get("analysis")))
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    usage = dict(old.get("usage") or {})
    mon = datetime.now(HKT).strftime("%Y-%m")
    usage[mon] = round(usage.get(mon, 0) + add_cost, 3)
    f.write_text(json.dumps(dict(generated=datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT"), items=items, usage=usage, month_budget=MONTH_USD),
                            ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def month_spent():
    try:
        u = json.loads((OUT / "index.json").read_text(encoding="utf-8")).get("usage") or {}
        return float(u.get(datetime.now(HKT).strftime("%Y-%m"), 0))
    except Exception:  # noqa: BLE001
        return 0.0


def build(q, dry=False, coins=None):
    coins = coins if coins is not None else load_list()
    cid = resolve(q, coins)
    if not cid:
        raise RuntimeError(f"搵唔到「{q}」呢個加密幣（試下打代號例如 ETH，或者 CoinGecko id 例如 ethereum）")
    llm.ORDER = [p for p in llm._order() if llm.has_key(p)]
    t0, u0 = time.time(), len(llm.USAGE)
    D = collect(cid)
    maps = D.pop("_maps", None)
    src = base_sources(D)
    labels, A, peers = {}, None, []
    if not dry:
        notes, ws, labels["gather"], n = llm.gather(gather_prompt(D), MAX_SEARCH, timeout=600, first=1)
        src += [dict(id=f"S{k + 1}", kind="web", title=s["title"], url=s["url"], age=s.get("age")) for k, s in enumerate(ws)]
        print(f"[crypto] {cid} 搜尋 {n} 次、{len(ws)} 個來源（{labels['gather']}）")
        raw, labels["analysis"] = llm.ask(analysis_prompt(D, notes, src), schema=SCHEMA, system=SYS, timeout=900, max_tokens=MAX_TOKENS,
                                          kind="crypto-research")
        A = clean(raw, src, D)
        peers = peer_rows(A["peers"], coins, maps)
    cost = sum(u["usd"] for u in llm.USAGE[u0:])
    rep = assemble(D, src, A, peers, labels, cost)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{cid}.json").write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_index(add_cost=cost)
    print(f"[crypto] {cid} 完成（{time.time() - t0:.0f} 秒，約 US${cost:.2f}）：{D['sym']} {px(D['mkt']['price'])}"
          + (f"，判斷 {A.get('stance')}" if A else "（冇 AI，測試）"))
    return rep


def main(argv):
    dry, force = "--dry" in argv, "--force" in argv
    qs = [a for a in argv if not a.startswith("--")]
    coins = load_list()
    if "--list" in argv or not coins:
        try:
            coins = coin_list()
            save_list(coins)
            print(f"[crypto] coins.json：{len(coins)} 個幣")
        except Exception as e:  # noqa: BLE001
            print(f"[crypto] 代號清單更新唔到（用返舊嗰份 {len(coins)} 個）：{str(e)[:120]}")
    if not qs:
        return 0
    if not dry and not any(llm.has_key(p) for p in ("claude", "deepseek", "gemini")):
        print("[crypto] 冇可以上網搜尋嘅 AI key（Claude、DeepSeek 或者 Gemini），今次唔做")
        return 1
    if not dry:
        llm.start(OUT.parent, "ai_usage_research.json")
    bad = 0
    for q in qs:
        if not (dry or force) and month_spent() + EST_USD > MONTH_USD:
            print(f"[crypto] 本月加密研究用量 US${month_spent():.2f} + 估計 US${EST_USD:g} 會超過上限 US${MONTH_USD:g}（CRYPTO_MONTH_USD），{q} 起唔做")
            bad += 1
            break
        u0 = len(llm.USAGE)
        try:
            build(q, dry=dry, coins=coins)
        except Exception as e:  # noqa: BLE001
            bad += 1
            lost = sum(u["usd"] for u in llm.USAGE[u0:])
            if lost > 0:
                write_index(add_cost=lost)
            print(f"[crypto] {q} 失敗（已用約 US${lost:.2f} 照記帳）：{str(e)[:400]}")
    if not dry:
        llm.finish(OUT.parent, "ai_usage_research.json")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
