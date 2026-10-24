"""名人交易（2026-10-25 老師：「1同2先做，用官方，3第二期」；/codex 兩邊同意：只係資訊，唔改 V2.7 規則，有冇用第二期先研究）。

① 國會議員（眾議院）：官方書記處每年 ZIP 索引（FilingType P = 交易報告 PTR）→ 每份電子申報 PDF 拆出每筆交易：
   議員、州／選區、資產（淨係股票 [ST] 有代號先入標籤；國債、私人公司等只記類型）、買（P）／賣（S、S (partial)）、交易日、通知日、
   金額區間、擁有人（配偶 SP／聯名 JT／子女 DC／本人）、申報日。掃描紙本（冇文字）略過，記數。
   參議院（eFD）要撳同意使用條款先入到，未問老師，暫時唔做。
   唔用 Capitol Trades（佢 robots.txt 禁 AI 爬蟲同程式攞 /_next/data）。
② 公司內部人（SEC Form 4，EDGAR 官方免費，一般 2 個工作日內申報）：留意清單（模型持倉、排名頭 15、候選、研究）每隻嘅 Form 4；
   淨係計公開市場買入（代碼 P）同賣出（S）——授股、行權、送贈、扣稅唔計；記低係咪 10b5-1 預先計劃交易。
「幾時知」：每筆記低 seen（雲端第一次攞到嘅時間）；第一次行（冇舊檔）嘅舊紀錄標 backfill（唔知幾時攞到，研究唔用）。
   第二期研究一律用 seen，唔用交易日、亦唔可以當申報日即刻可用（冇事後孔明）。
輸出 docs/people.json（每日掃描 commit）：近 DAYS 日（按申報日）。數據公開，自己用、唔作商業用途。
用法：python scanner/people.py [docs]
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HK = ZoneInfo("Asia/Hong_Kong")
UA = {"User-Agent": "stock-app research admin@stock-app.local"}   # SEC 要「名 + 電郵」格式；唔用用戶電郵（同 research.py）
DAYS = 90
GAP = 0.25                                                        # 每個請求之間（SEC 上限每秒 10 個）
HOUSE_IDX = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip"
HOUSE_PDF = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{doc}.pdf"
SEC_TICK = "https://www.sec.gov/files/company_tickers.json"
SEC_SUB = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SEC_IDX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
OWNER = {"SP": "配偶", "JT": "聯名", "DC": "子女"}
ETF = {"TQQQ", "IEF", "TMF", "UGL", "SGOV", "BIL", "QQQ", "SPY"}
TX = re.compile(r"(?<![A-Za-z])(P|S \(partial\)|S|E)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(Over \$[\d,]+|\$[\d,]+\s*-\s*\$[\d,]+|\$[\d,]+)")
KIND = re.compile(r"\[([A-Z]{2})\]")
TICK = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,6})\)\s*\[ST\]")
OWN = re.compile(r"(?m)^\s*(SP|JT|DC)\s+\S")


def get(url, tries=3, timeout=40):
    last = None
    for k in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
            time.sleep(GAP)
            return b
        except Exception as e:  # noqa: BLE001
            last = e
            if "404" in str(e):
                break
            time.sleep(2 * (k + 1))
    raise last


def _d(s):
    """MM/DD/YYYY → YYYY-MM-DD。"""
    m, d_, y = s.split("/")
    return f"{y}-{int(m):02d}-{int(d_):02d}"


# ---------------------------------------------------------------- ① 眾議院
def parse_ptr(text):
    """電子 PTR 文字 → 每筆交易 dict。資產（…(代號) [ST]）之後跟「類型 交易日 通知日 金額」；擁有人（SP／JT／DC）喺資產行頭。"""
    out, pos = [], 0
    for m in TX.finditer(text):
        chunk, pos = text[pos:m.start()], m.end()
        kinds = KIND.findall(chunk)
        if not kinds:
            continue
        tk = TICK.findall(chunk)
        own = OWN.findall(chunk)
        typ = m.group(1)
        out.append(dict(sym=tk[-1] if tk and kinds[-1] == "ST" else None, kind=kinds[-1], type="買" if typ == "P" else "交換" if typ == "E" else "賣",
                        partial=typ.startswith("S ("), traded=_d(m.group(2)), notified=_d(m.group(3)),
                        amount=re.sub(r"\s+", " ", m.group(4)), owner=OWNER.get(own[-1], "") if own else "本人"))
    return out


def house_index(years):
    rows = []
    for y in years:
        try:
            z = zipfile.ZipFile(io.BytesIO(get(HOUSE_IDX.format(y=y))))
        except Exception as e:  # noqa: BLE001
            print(f"[people] 眾議院 {y} 索引攞唔到：{e}")
            continue
        for m in ET.fromstring(z.read(f"{y}FD.xml")):
            r = {c.tag: (c.text or "").strip() for c in m}
            if r.get("FilingType") == "P" and r.get("DocID") and r.get("FilingDate"):
                rows.append(dict(doc=r["DocID"], year=y, filed=_d(r["FilingDate"]), state=r.get("StateDst", ""),
                                 member=" ".join(x for x in (r.get("First"), r.get("Last"), r.get("Suffix")) if x)))
    return rows


def pdf_text(b):
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(b)).pages)


def house(prev, cut, now_iso, first, errs):
    """新嘅 PTR 先攞（docs 快取：見過嘅 DocID 唔再下載）。返 (交易, 快取, 新 PTR 數)。"""
    docs = dict(prev.get("house_docs") or {})
    trades = [t for t in prev.get("congress") or [] if t["filed"] >= cut]
    today = date.today()
    idx = [r for r in house_index(sorted({today.year, (today - timedelta(days=DAYS)).year})) if r["filed"] >= cut]
    new = [r for r in idx if r["doc"] not in docs]
    for r in sorted(new, key=lambda r: r["filed"]):
        url = HOUSE_PDF.format(y=r["year"], doc=r["doc"])
        try:
            text = pdf_text(get(url))
        except Exception as e:  # noqa: BLE001
            errs.append(f"眾議院 {r['doc']}：{str(e)[:60]}")
            continue
        rows = parse_ptr(text) if len(text.strip()) > 200 else []
        docs[r["doc"]] = dict(filed=r["filed"], seen=now_iso, n=len(rows), other=sum(1 for t in rows if not t["sym"]), scan=len(text.strip()) <= 200)
        for t in (t for t in rows if t["sym"]):                  # 淨係有代號嘅股票（國債、私人公司、基金等只記數）
            trades.append(dict(t, member=r["member"], state=r["state"], chamber="眾議院", filed=r["filed"], seen=r["filed"] if first else now_iso,
                               backfill=first, doc=r["doc"], url=url))
    docs = {k: v for k, v in docs.items() if v["filed"] >= cut}
    trades.sort(key=lambda t: (t["filed"], t["traded"]), reverse=True)
    return trades, docs, len(new)


# ---------------------------------------------------------------- ② SEC Form 4
def watch_list(docs):
    """模型持倉、排名頭 15、候選、研究清單（唔要 ETF）。"""
    syms = []
    try:
        sc = json.loads((docs / "scan.json").read_text(encoding="utf-8"))
        syms += [r["sym"] for r in sc.get("ranking", [])[:15]] + [r["sym"] for r in sc.get("ranking", []) if r.get("status") == "候選"]
    except Exception:  # noqa: BLE001
        pass
    try:
        m = json.loads((docs / "model_cont.json").read_text(encoding="utf-8"))
        syms += [p["sym"] for p in m.get("positions", [])]
    except Exception:  # noqa: BLE001
        pass
    try:
        syms += [x["sym"] for x in json.loads((docs / "research" / "index.json").read_text(encoding="utf-8")).get("items", [])]
    except Exception:  # noqa: BLE001
        pass
    lst = ROOT / "scanner" / "research_list.txt"
    if lst.exists():
        syms += [s.upper() for ln in lst.read_text(encoding="utf-8").splitlines() for s in ln.split("#", 1)[0].split()]
    return [s for s in dict.fromkeys(syms) if s and s not in ETF]


def _t(el, path):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse_form4(xml):
    """Form 4 XML → 公開市場買入（P）／賣出（S）總結（每份每種代碼一行）；其他代碼唔計。"""
    root = ET.fromstring(xml)
    rel = root.find(".//reportingOwnerRelationship")
    role = []
    if rel is not None:
        if _t(rel, "officerTitle"):
            role.append(_t(rel, "officerTitle"))
        elif _t(rel, "isOfficer") in ("1", "true"):
            role.append("高層")
        if _t(rel, "isDirector") in ("1", "true"):
            role.append("董事")
        if _t(rel, "isTenPercentOwner") in ("1", "true"):
            role.append("10% 大股東")
    base = dict(sym=_t(root, "issuer/issuerTradingSymbol").upper(), name=_t(root, ".//reportingOwner/reportingOwnerId/rptOwnerName"),
                role="、".join(role) or "其他", plan=_t(root, "aff10b5One") in ("1", "true"))
    agg = {}
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        try:
            sh = float(_t(tx, "transactionAmounts/transactionShares/value") or 0)
            px = float(_t(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        a = agg.setdefault(code, dict(shares=0.0, value=0.0, traded=_t(tx, "transactionDate/value")))
        a["shares"] += sh
        a["value"] += sh * px
        a["traded"] = min(a["traded"], _t(tx, "transactionDate/value")) or a["traded"]
    return [dict(base, code=c, type="買" if c == "P" else "賣", shares=round(a["shares"]), value=round(a["value"]),
                 price=round(a["value"] / a["shares"], 2) if a["shares"] else None, traded=a["traded"]) for c, a in agg.items()]


def insider(prev, cut, now_iso, first, docs, errs):
    seen = dict(prev.get("sec_seen") or {})
    trades = [t for t in prev.get("insider") or [] if t["filed"] >= cut]
    watch = watch_list(docs)
    try:
        tick = {v["ticker"].upper(): int(v["cik_str"]) for v in json.loads(get(SEC_TICK)).values()}
    except Exception as e:  # noqa: BLE001
        errs.append(f"SEC 代號表：{str(e)[:60]}")
        return trades, seen, watch, 0
    n_new = 0
    for s in watch:
        cik = tick.get(s) or tick.get(s.replace(".", "-"))
        if not cik:
            continue                                              # 外國公司（例如 TSM 嘅 ADR）唔使交 Form 4
        try:
            rc = json.loads(get(SEC_SUB.format(cik=cik)))["filings"]["recent"]
        except Exception as e:  # noqa: BLE001
            errs.append(f"SEC {s}：{str(e)[:60]}")
            continue
        for i, form in enumerate(rc["form"]):
            acc, filed = rc["accessionNumber"][i], rc["filingDate"][i]
            if form != "4" or filed < cut or acc in seen:
                continue
            path = SEC_DOC.format(cik=cik, acc=acc.replace("-", ""), doc=rc["primaryDocument"][i].split("/")[-1])
            try:
                rows = parse_form4(get(path))
            except Exception as e:  # noqa: BLE001
                errs.append(f"Form 4 {s} {acc}：{str(e)[:60]}")
                continue
            seen[acc] = dict(filed=filed, seen=now_iso)
            n_new += 1
            for t in rows:
                trades.append(dict(t, sym=t["sym"] or s, filed=filed, seen=filed if first else now_iso, backfill=first,
                                   url=SEC_IDX.format(cik=cik, acc=acc.replace("-", ""))))
    seen = {k: v for k, v in seen.items() if v["filed"] >= cut}
    trades.sort(key=lambda t: (t["filed"], t["traded"]), reverse=True)
    return trades, seen, watch, n_new


def main(docs=None):
    docs = Path(docs or ROOT / "docs")
    f = docs / "people.json"
    try:
        prev = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        prev = {}
    first = not prev
    now = datetime.now(timezone.utc)
    now_iso, cut = now.isoformat(timespec="seconds"), (now.date() - timedelta(days=DAYS)).isoformat()
    errs = []
    try:
        cg, hd, n_h = house(prev, cut, now_iso, first, errs)
    except Exception as e:  # noqa: BLE001
        errs.append(f"眾議院：{str(e)[:100]}")
        cg, hd, n_h = prev.get("congress") or [], prev.get("house_docs") or {}, 0
    try:
        ins, ss, watch, n_s = insider(prev, cut, now_iso, first, docs, errs)
    except Exception as e:  # noqa: BLE001
        errs.append(f"SEC：{str(e)[:100]}")
        ins, ss, watch, n_s = prev.get("insider") or [], prev.get("sec_seen") or {}, [], 0
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), days=DAYS, congress=cg, insider=ins, watch=watch,
               house_docs=hd, sec_seen=ss, errs=errs[:20],
               stats=dict(house_new=n_h, house_scan=sum(1 for v in hd.values() if v.get("scan")), sec_new=n_s))
    f.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[people] 議員交易 {len(cg)} 筆（新 PTR {n_h} 份，紙本 {res['stats']['house_scan']} 份略過）；"
          f"內部人 {len(ins)} 筆（新 Form 4 {n_s} 份，留意 {len(watch)} 隻）；錯誤 {errs[:3] or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
