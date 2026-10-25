# -*- coding: utf-8 -*-
"""2026-10-25 scanner/people.py：眾議院議員交易（官方 PTR）+ SEC Form 4 內部人。假網絡，唔上網。
PTR 文字樣本係 2026-10 真官方申報嘅格式（公開資料）；Form 4 係格式相同嘅假樣本。
用法：python tests/test_people.py"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import people as P  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


PTR = """ID Owner Asset Transaction
Type
Date Notification
Date
Amount Cap.
Gains >
$200?
NVIDIA Corporation - Common Stock
(NVDA) [ST]
P 10/01/2026 10/01/2026 $1,001 - $15,000
F      S     : New
S          O : Morgan Stanley - E*TRADE #2
SP Alphabet Inc. - Class C Capital Stock
(GOOG) [ST]
S (partial) 10/16/2026 10/16/2026 $50,001 -
$100,000
F      S     : New
JT So Fine Foods LLC [OL] P 09/29/2026 09/29/2026 $50,001 -
$100,000
US Treasury Note 3.375% due
09/15/28 CUSIP 91282CNY3 [GS]
S 10/14/2026 10/15/2026 $5,000,001 -
$25,000,000
* For the complete list of asset type abbreviations"""
rows = P.parse_ptr(PTR)
check(len(rows) == 4, f"拆到 4 筆交易（股票 2、私人公司 1、國債 1）：{len(rows)}")
check(rows[0]["sym"] == "NVDA" and rows[0]["type"] == "買" and rows[0]["traded"] == "2026-10-01" and rows[0]["amount"] == "$1,001 - $15,000" and rows[0]["owner"] == "本人",
      "NVDA：買、日期、金額區間、本人")
check(rows[1]["sym"] == "GOOG" and rows[1]["type"] == "賣" and rows[1]["partial"] and rows[1]["owner"] == "配偶" and rows[1]["amount"] == "$50,001 - $100,000",
      "GOOG：部分賣出、配偶（SP）、跨行金額")
check(rows[2]["sym"] is None and rows[2]["kind"] == "OL" and rows[2]["owner"] == "聯名" and rows[3]["sym"] is None and rows[3]["kind"] == "GS",
      "私人公司（OL，聯名）同國債（GS）冇代號：唔入股票標籤")

F4 = b"""<?xml version="1.0"?><ownershipDocument><documentType>4</documentType>
<issuer><issuerCik>0001</issuerCik><issuerName>DEMO</issuerName><issuerTradingSymbol>demo</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<aff10b5One>1</aff10b5One>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares><transactionPricePerShare><value>100</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-10-21</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>3000</value></transactionShares><transactionPricePerShare><value>110</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-10-21</value></transactionDate><transactionCoding><transactionCode>G</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>500</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-10-21</value></transactionDate><transactionCoding><transactionCode>M</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>9000</value></transactionShares><transactionPricePerShare><value>5</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""
f = P.parse_form4(F4)
check(len(f) == 1 and f[0]["code"] == "S" and f[0]["shares"] == 4000 and f[0]["value"] == 430000 and f[0]["price"] == 107.5 and f[0]["traded"] == "2026-10-20",
      f"Form 4：兩筆公開市場賣出合埋（4,000 股、平均 107.5）；送贈 G、行權 M 唔計（{f}）")
check(f[0]["plan"] and f[0]["role"] == "CEO、董事" and f[0]["sym"] == "DEMO", "記低 10b5-1 預先計劃、職位、代號")

# 成個流程：假網絡
out = Path(os.environ.get("TEST_OUT") or T / "_out") / "people" / time.strftime("%Y%m%d-%H%M%S")
(out / "research").mkdir(parents=True, exist_ok=True)
(out / "scan.json").write_text(json.dumps({"ranking": [{"sym": "DEMO", "status": "候選"}, {"sym": "TQQQ", "status": "唔合格"}]}), encoding="utf-8")
(out / "model_cont.json").write_text(json.dumps({"positions": [{"sym": "DEL"}]}), encoding="utf-8")
(out / "research" / "index.json").write_text(json.dumps({"items": [{"sym": "NVDA"}]}), encoding="utf-8")
check(P.watch_list(out)[:3] == ["DEMO", "DEL", "NVDA"] and "TQQQ" not in P.watch_list(out), "留意清單：排名、持倉、研究；唔要 ETF")
today = date.today()
f1, f_old = (today - timedelta(days=3)).strftime("%m/%d/%Y"), (today - timedelta(days=200)).strftime("%m/%d/%Y")


def idx_zip(docs):
    xml = "<FinancialDisclosure>" + "".join(f"<Member><First>Ann</First><Last>Lee</Last><FilingType>{t}</FilingType><StateDst>CA01</StateDst>"
                                            f"<FilingDate>{d}</FilingDate><DocID>{doc}</DocID></Member>" for doc, t, d in docs) + "</FinancialDisclosure>"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(f"{today.year}FD.xml", xml)
    return b.getvalue()


IDX = [("20000001", "P", f1), ("20000002", "C", f1), ("20000003", "P", f_old)]
calls = []


def fake_get(url, **k):
    calls.append(url)
    if url.endswith("FD.zip"):
        return idx_zip(IDX) if str(today.year) in url else idx_zip([])
    if url.endswith(".pdf"):
        return b"pdf"
    if url == P.SEC_TICK:
        return json.dumps({"0": {"cik_str": 1, "ticker": "DEMO"}}).encode()
    if "submissions" in url:
        return json.dumps({"filings": {"recent": {"form": ["4", "4", "10-K"], "accessionNumber": ["0001-26-1", "0001-26-0", "0001-26-9"],
                                                  "filingDate": [(today - timedelta(days=2)).isoformat(), (today - timedelta(days=400)).isoformat(), today.isoformat()],
                                                  "primaryDocument": ["xslF345X06/f.xml", "xslF345X06/g.xml", "k.htm"]}}}).encode()
    if url.endswith(".xml"):
        return F4
    raise RuntimeError("唔應該攞：" + url)


P.get = fake_get
P.pdf_text = lambda b: PTR
P.main(out)
o = json.loads((out / "people.json").read_text(encoding="utf-8"))
check([t["sym"] for t in o["congress"]] == ["GOOG", "NVDA"] and all(t["backfill"] and t["member"] == "Ann Lee" and t["chamber"] == "眾議院" for t in o["congress"]),
      "第一次行：淨係近 90 日嘅交易報告（P），淨係股票；舊紀錄標 backfill（唔知幾時攞到）")
check(len(o["insider"]) == 1 and o["insider"][0]["sym"] == "DEMO" and o["insider"][0]["backfill"] and "edgar/data/1/" in o["insider"][0]["url"],
      "內部人：淨係近 90 日嘅 Form 4；10-K 唔理")
check(not any("20000003" in c for c in calls) and not any("g.xml" in c for c in calls), "超過 90 日嘅申報唔會下載")
calls.clear()
IDX.append(("20000004", "P", f1))
P.main(out)
o = json.loads((out / "people.json").read_text(encoding="utf-8"))
pdfs = [c for c in calls if c.endswith(".pdf")]
new = [t for t in o["congress"] if t["doc"] == "20000004"]
check(pdfs == [P.HOUSE_PDF.format(y=today.year, doc="20000004")] and not any(c.endswith(".xml") for c in calls), "第二次：見過嘅 PTR、Form 4 唔再下載，淨係攞新嗰份")
check(new and not new[0]["backfill"] and new[0]["seen"] > new[0]["filed"] and len(o["congress"]) == 4, "新紀錄記低雲端第一次攞到嘅時間（seen），唔係 backfill")
check(o["stats"]["senate"] == "冇 FMP key" and not any("financialmodelingprep" in c for c in calls), "參議院：冇 FMP key 就唔攞、照行")

# 參議院（FMP 最新申報；官方 eFD 擋程式）
KEY = "TESTKEY123"
os.environ["FMP_API_KEY"] = KEY
d1, d_old = (today - timedelta(days=2)).isoformat(), (today - timedelta(days=200)).isoformat()
SEN = [dict(symbol="NVDA", disclosureDate=d1, transactionDate=d1, firstName="Jane", lastName="Roe", office="Jane Roe", owner="Spouse",
            assetDescription="NVIDIA", assetType="Stock", type="Purchase", amount="$15,001 - $50,000", link="https://efdsearch.senate.gov/search/view/ptr/11111111-2222-3333-4444-555555555555/"),
       dict(symbol="CM", disclosureDate=d1, transactionDate=d1, firstName="Jane", lastName="Roe", owner="Self", assetType="Corporate Bond",
            type="Sale", amount="$1,001 - $15,000", link="x"),
       dict(symbol="AAPL", disclosureDate=d1, transactionDate=d1, firstName="Jane", lastName="Roe", owner="Self", assetType="Stock Option",
            type="Purchase", amount="$1,001 - $15,000", link="y"),
       dict(symbol="MSFT", disclosureDate=d_old, transactionDate=d_old, firstName="Old", lastName="One", owner="Self", assetType="Stock",
            type="Sale (Partial)", amount="$1,001 - $15,000", link="z")]
fmp = []


def fake_get2(url, **k):
    if "financialmodelingprep" in url:
        fmp.append(url)
        return json.dumps(SEN if "page=0" in url else []).encode()
    return fake_get(url, **k)


P.get = fake_get2
P.main(out)
txt = (out / "people.json").read_text(encoding="utf-8")
o = json.loads(txt)
sen = [t for t in o["congress"] if t["chamber"] == "參議院"]
check(len(sen) == 1 and sen[0]["sym"] == "NVDA" and sen[0]["type"] == "買" and sen[0]["owner"] == "配偶" and sen[0]["member"] == "Jane Roe" and sen[0]["backfill"],
      "參議院：淨係股票（債券、期權唔要）、200 日前唔要；第一次攞到標 backfill")
check(len([t for t in o["congress"] if t["chamber"] == "眾議院"]) == 4 and fmp == [P.FMP_SEN.format(p=0, key=KEY)], "眾議院紀錄冇重複；FMP 頭一頁已經舊過 90 日就唔再翻頁")
SEN.append(dict(SEN[0], symbol="AMD", assetDescription="AMD"))
P.main(out)
o = json.loads((out / "people.json").read_text(encoding="utf-8"))
sen = [t for t in o["congress"] if t["chamber"] == "參議院"]
check(len(sen) == 2 and [t for t in sen if t["sym"] == "AMD"][0]["backfill"] is False and o["stats"]["senate_new"] == 1, "參議院第二次：見過嘅唔重複，新嗰筆記 seen、唔係 backfill")
P.get = lambda url, **k: (_ for _ in ()).throw(RuntimeError("boom " + url)) if "financialmodelingprep" in url else fake_get(url, **k)
P.main(out)
txt = (out / "people.json").read_text(encoding="utf-8")
o = json.loads(txt)
check(KEY not in txt and o["stats"]["senate"] == "攞唔到" and len([t for t in o["congress"] if t["chamber"] == "參議院"]) == 2,
      "FMP 出錯：沿用舊紀錄；錯誤訊息唔會寫出 key")
del os.environ["FMP_API_KEY"]
print(f"\n全部 {ok} 項通過")
