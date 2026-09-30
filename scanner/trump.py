"""Trump 貼文追蹤（2026-09-30 用戶要求：Trump 嘅貼文好有參考價值；佢以前公開喊過單、提過公司，要追蹤）。[quant-data]

Trump 主要喺 Truth Social 出 post（X 大多只係轉片、冇字），所以用 Truth Social：
  歷史：github.com/stiles/trump-truth-social-archive（2022-02 起，公開存檔，約 3 萬條）
  最近：trumpstruth.org/feed（Truth Social 存檔網站 RSS，可以用 start_date／end_date 揀日子，每次 100 條）
公司：用下面 CO 字典（公司名／$代號 → 股票代號）搵提過邊間上市公司；另外標「股市」＝講股市、叫人買（BUY）。
輸出：
  all    → docs/trump_all.json（全部歷史入面有提公司或者股市嘅貼文）同 docs/trump.json（近 60 日嘅提及，app 標 T·N 用）
  recent → <out>/trump_recent.json（近 3 日全部貼文，feeds 分支，每 5 分鐘；ai.py 翻譯）
用法：python scanner/trump.py all｜recent <out>
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ALL = ROOT / "docs" / "trump_all.json"
RECENT60 = ROOT / "docs" / "trump.json"
ARCHIVE = "https://raw.githubusercontent.com/stiles/trump-truth-social-archive/main/data/truth_archive.json"
FEED = "https://www.trumpstruth.org/feed"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# 公司名 → 代號（大小寫敏感；避開歧義字：Target、Visa、Carrier、X、Meta 單字要大楷開頭）
CO = [
    (r"\bApple\b|Tim Cook", "AAPL"), (r"\bTesla\b", "TSLA"), (r"\bNvidia\b|\bNVIDIA\b|Jensen Huang", "NVDA"), (r"\bMicrosoft\b", "MSFT"),
    (r"\bGoogle\b|\bAlphabet\b|YouTube", "GOOGL"), (r"\bAmazon\b|Jeff Bezos", "AMZN"), (r"\bMeta Platforms\b|\bFacebook\b|\bInstagram\b|\bMeta\b(?!-)", "META"),
    (r"\bIntel\b(?! Politics| [Cc]ommunity| [Cc]ommittee| [Aa]gencies| [Oo]fficials| [Cc]hief| [Rr]eport)", "INTC"), (r"\bAMD\b|Advanced Micro Devices", "AMD"), (r"\bTSMC\b|Taiwan Semiconductor", "TSM"), (r"\bMicron\b", "MU"),
    (r"\bQualcomm\b", "QCOM"), (r"\bBroadcom\b", "AVGO"), (r"\bIBM\b", "IBM"), (r"\bCisco\b", "CSCO"), (r"\bDell\b", "DELL"),
    (r"\bOracle\b|Larry Ellison", "ORCL"), (r"\bSalesforce\b", "CRM"), (r"\bPalantir\b", "PLTR"), (r"\bUber\b", "UBER"), (r"\bNetflix\b", "NFLX"),
    (r"\bDisney\b", "DIS"), (r"\bComcast\b", "CMCSA"), (r"Warner Bros", "WBD"), (r"\bAT&T\b", "T"), (r"\bVerizon\b", "VZ"),
    (r"T-Mobile", "TMUS"), (r"\bBoeing\b", "BA"), (r"\bLockheed\b", "LMT"), (r"\bRaytheon\b|\bRTX\b", "RTX"), (r"\bNorthrop\b", "NOC"),
    (r"General Dynamics", "GD"), (r"\bHoneywell\b", "HON"), (r"General Electric", "GE"), (r"\bCaterpillar\b", "CAT"), (r"\bJohn Deere\b|\bDeere\b", "DE"),
    (r"\bFord\b(?! Foundation)", "F"), (r"General Motors|\bGM\b", "GM"), (r"\bStellantis\b|\bChrysler\b|\bJeep\b", "STLA"), (r"\bToyota\b", "TM"),
    (r"\bHonda\b", "HMC"), (r"\bRivian\b", "RIVN"), (r"Harley-Davidson|\bHarley\b", "HOG"), (r"\bGoodyear\b", "GT"),
    (r"\bExxon\b|ExxonMobil", "XOM"), (r"\bChevron\b", "CVX"), (r"ConocoPhillips", "COP"), (r"\bOccidental\b", "OXY"), (r"\bHalliburton\b", "HAL"),
    (r"\bWalmart\b|\bWal-Mart\b", "WMT"), (r"Home Depot", "HD"), (r"\bMacy'?s\b", "M"), (r"\bNike\b", "NKE"), (r"\bStarbucks\b", "SBUX"),
    (r"McDonald'?s", "MCD"), (r"Coca-Cola|\bCoke\b", "KO"), (r"\bPepsi\b|PepsiCo", "PEP"), (r"Anheuser|Bud Light|Budweiser", "BUD"),
    (r"Cracker Barrel", "CBRL"), (r"\bMattel\b", "MAT"), (r"\bPfizer\b", "PFE"), (r"\bModerna\b", "MRNA"), (r"Johnson & Johnson|Johnson and Johnson", "JNJ"),
    (r"Eli Lilly|\bLilly\b", "LLY"), (r"Novo Nordisk", "NVO"), (r"\bMerck\b", "MRK"), (r"\bAbbVie\b", "ABBV"), (r"UnitedHealth", "UNH"), (r"\bCVS\b", "CVS"),
    (r"JPMorgan|JP Morgan|J\.P\. Morgan|Jamie Dimon", "JPM"), (r"Bank of America", "BAC"), (r"Goldman Sachs|\bGoldman\b", "GS"), (r"Morgan Stanley", "MS"),
    (r"Wells Fargo", "WFC"), (r"\bCitigroup\b|\bCitibank\b", "C"), (r"\bBlackRock\b|Larry Fink", "BLK"), (r"\bBerkshire\b|Warren Buffett", "BRK-B"),
    (r"\bMastercard\b", "MA"), (r"American Express", "AXP"), (r"\bCoinbase\b", "COIN"), (r"Trump Media|\$DJT\b|DJT stock", "DJT"),
    (r"\bNucor\b", "NUE"), (r"Cleveland-Cliffs|Cleveland Cliffs", "CLF"), (r"\bAlcoa\b", "AA"), (r"MP Materials", "MP"), (r"Lithium Americas", "LAC"),
    (r"Trilogy Metals", "TMQ"), (r"\bCameco\b", "CCJ"), (r"Constellation Energy", "CEG"), (r"\bOklo\b", "OKLO"), (r"\bWhirlpool\b", "WHR"), (r"\b3M\b", "MMM"),
]
CO = [(re.compile(p), s) for p, s in CO]
CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
MARKET = re.compile(r"\bBUY\b|[Ss]tock [Mm]arket|\bStocks?\b|\bDow\b|S&P|\bNASDAQ\b|\bNasdaq\b|401\(?k\)?|all-time high|ALL TIME HIGH|record high", re.I)
BUY = re.compile(r"(?i:great time to buy|good time to buy|time to buy|buy (?:the )?stocks?|buy (?:the )?dip)|\bBUY\b(?!\s+AMERICA)")   # 大楷 BUY 先算；BUY AMERICAN 係口號


def fix(t):
    """存檔有啲字係 UTF-8 當 Latin-1 解咗（例如 â\x80\x9c），還原返。"""
    if re.search("[Â-ð][\u0080-¿]", t or ""):
        try:
            return t.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return t or ""


def clean(h):
    t = re.sub(r"<br\s*/?>|</p>", "\n", h or "")
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


def tag(t):
    syms = sorted({s for rx, s in CO if rx.search(t)})          # 唔用 $代號（佢寫 $TRUMP 係講 memecoin）
    kind = "講 BUY" if BUY.search(t) else ("股市" if MARKET.search(t) else "")
    return syms, kind


def get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            print(f"[trump] 重試 {k}：{url[:80]} {e}")
            time.sleep(3 + 5 * k)
    raise RuntimeError(f"攞唔到 {url}")


def feed(a=None, b=None):
    """trumpstruth.org RSS：a／b = 開始／完結日（YYYY-MM-DD），每次最多 100 條（新嘅先）。"""
    q = {k: v for k, v in (("start_date", a), ("end_date", b)) if v}
    x = get(FEED + ("?" + urllib.parse.urlencode(q) if q else "")).decode("utf-8", "ignore")
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        g = lambda k: (re.search(rf"<{k}[^>]*>(.*?)</{k}>", it, re.S) or [None, ""])[1].replace("<![CDATA[", "").replace("]]>", "")
        link = html.unescape(g("link")).strip()
        orig = re.search(r"truthsocial\.com/@realDonaldTrump/(\d+)", it)
        try:
            ts = int(parsedate_to_datetime(g("pubDate")).timestamp())
        except Exception:  # noqa: BLE001
            continue
        out.append(dict(id=orig.group(1) if orig else "tt" + link.rsplit("/", 1)[-1], ts=ts, text=clean(g("description")),
                        url=f"https://truthsocial.com/@realDonaldTrump/{orig.group(1)}" if orig else link))
    return out


def archive():
    a = json.loads(get(ARCHIVE))
    out = []
    for x in a:
        try:
            ts = int(datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")).timestamp())
        except Exception:  # noqa: BLE001
            continue
        out.append(dict(id=str(x["id"]), ts=ts, text=clean(fix(x.get("content") or "")), url=x.get("url") or ""))
    return out


def since(day):
    """由 day（YYYY-MM-DD）到今日：按日子一段段攞 RSS（每段 100 條，唔夠就縮短）。"""
    out, b = {}, datetime.now(timezone.utc).date() + timedelta(days=1)
    a0 = datetime.fromisoformat(day).date()
    while b > a0:
        a = max(a0, b - timedelta(days=4))
        rows = feed(a.isoformat(), b.isoformat())
        if len(rows) >= 100 and (b - a).days > 1:        # 太多：段落縮短
            a = b - timedelta(days=1)
            rows = feed(a.isoformat(), b.isoformat())
        for r in rows:
            out[r["id"]] = r
        b = a
        time.sleep(1.0)
    return list(out.values())


def keep(p):
    syms, kind = tag(p["text"])
    return dict(p, text=p["text"][:600], syms=syms, kind=kind) if (syms or kind) else None


def dedupe(posts):
    seen, out = set(), []
    for p in sorted(posts, key=lambda p: -p["ts"]):
        t = p["text"]
        t = t[len("RT @realDonaldTrump"):] if t.startswith("RT @realDonaldTrump") else re.sub(r"^RT @\w+", "", t)
        k = re.sub(r"\W", "", t)[:80]                                          # 轉發自己舊 post 當同一條
        if k in seen or not p["text"].strip():
            continue
        seen.add(k)
        out.append(p)
    return out


def hk_now():
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "recent"
    if mode == "recent":
        out = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
        now = datetime.now(timezone.utc)
        posts = dedupe(feed((now - timedelta(days=3)).date().isoformat()))
        for p in posts:
            p["syms"], p["kind"] = tag(p["text"])
            p["text"] = p["text"][:1200]
        (out / "trump_recent.json").write_text(json.dumps({"generated": hk_now(), "posts": posts}, ensure_ascii=False, separators=(",", ":")),
                                               encoding="utf-8")
        print(f"[trump] 近 3 日 {len(posts)} 條，提公司 {sum(1 for p in posts if p['syms'])} 條")
        return
    old = json.loads(ALL.read_text(encoding="utf-8"))["posts"] if ALL.exists() else []
    if old:                                                     # 已有歷史：只補最近 10 日
        start = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
        new = since(start)
    else:                                                       # 第一次：存檔 + 存檔之後嘅 RSS
        arc = archive()
        last = max(p["ts"] for p in arc)
        new = arc + since(datetime.fromtimestamp(last - 86400, timezone.utc).date().isoformat())
        print(f"[trump] 存檔 {len(arc)} 條（到 {datetime.fromtimestamp(last, timezone.utc).date()}），加 RSS 共 {len(new)} 條")
    kept = [k for k in (keep(p) for p in new) if k]
    allp = dedupe(old + kept)
    ALL.write_text(json.dumps({"generated": hk_now(), "posts": allp}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cut = datetime.now(timezone.utc).timestamp() - 60 * 86400
    RECENT60.write_text(json.dumps({"generated": hk_now(), "posts": [p for p in allp if p["ts"] >= cut]}, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    n_co = sum(1 for p in allp if p["syms"])
    print(f"[trump] trump_all.json：{len(allp)} 條（提公司 {n_co}、講 BUY {sum(1 for p in allp if p['kind'] == '講 BUY')}），{ALL.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
