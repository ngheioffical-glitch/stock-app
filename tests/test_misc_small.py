# -*- coding: utf-8 -*-
"""2026-11-13 細模組行為測試（流程審計 S6：fx.chart、feeds.news／econ_nasdaq、people.parse_efd_ptr／senate FMP 錯誤、bars.kline_block、
structure.facts 之前冇直接測）。假回覆、唔上網、唔改規則。
1. fx.chart：最新價同最後一日同日 → 取代；新一日 → 加落尾；冇最新價唔加；冇歷史唔加
2. feeds.news：72 小時內、同類同標題去重；每類最多 80 條、每隻股最多 6 條（新嘅先）
3. feeds.econ_nasdaq：其他日子攞唔到照做；今日攞唔到要報錯；淨係美國、Fed 講話淨係要 Powell、剔走拍賣
4. people.parse_efd_ptr：認表頭、格數唔夠嘅行唔要、代號「--」= 冇；senate：FMP 第一頁答錯誤 dict 記錯（遮 key），之後頁唔當錯
5. bars.kline_block：唔夠 60 日唔畫；structure.facts：有兩次突破先寫「再之前一次」
用法：python tests/test_misc_small.py"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

T = Path(__file__).resolve().parent
sys.path.insert(0, str(T.parent / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import bars  # noqa: E402
import feeds  # noqa: E402
import fx  # noqa: E402
import people  # noqa: E402
import structure  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


# ============================================================ 1. fx.chart
class Resp:
    def __init__(self, d):
        self.b = json.dumps(d).encode()

    def read(self):
        return self.b


def ts(y, m, d, h=14):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def yahoo(closes, meta):
    d = {"chart": {"result": [{"timestamp": [ts(2026, 11, 10), ts(2026, 11, 11), ts(2026, 11, 12)],
                               "indicators": {"quote": [{"close": closes}]}, "meta": meta}]}}
    fx.urllib.request.urlopen = lambda req, timeout=None: Resp(d)
    return fx.chart("JPY=X")


REAL = fx.urllib.request.urlopen
pts, at = yahoo([1.0, None, 3.0], {"regularMarketPrice": 3.5, "regularMarketTime": ts(2026, 11, 12, 20)})
check(pts == [(date(2026, 11, 10), 1.0), (date(2026, 11, 12), 3.5)] and at == "11-13 04:00", "fx.chart：最新價同最後一日同日 → 取代收市；冇收市（None）嗰日唔要；時間轉香港")
pts, at = yahoo([1.0, 2.0, 3.0], {"regularMarketPrice": 3.5, "regularMarketTime": ts(2026, 11, 13, 2)})
check(pts[-2:] == [(date(2026, 11, 12), 3.0), (date(2026, 11, 13), 3.5)] and len(pts) == 4, "fx.chart：最新價係新一日 → 加落尾")
pts, at = yahoo([1.0, 2.0, 3.0], {"regularMarketTime": ts(2026, 11, 13, 2)})
check(pts == [(date(2026, 11, 10), 1.0), (date(2026, 11, 11), 2.0), (date(2026, 11, 12), 3.0)], "fx.chart：冇最新價 → 唔加（唔會加個空價）")
pts, at = yahoo([None, None, None], {"regularMarketPrice": 3.5, "regularMarketTime": ts(2026, 11, 13, 2)})
check(pts == [], "fx.chart：冇歷史 → 唔加最新價（唔 crash）")
fx.urllib.request.urlopen = REAL

# ============================================================ 2. feeds.news
NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
iso = lambda h: (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def fake_rss(url, source, cat, sym=None):
    if sym:
        return [dict(t=iso(k), title=f"AAA news {k}", src="Yahoo", cat=cat, sym=sym) for k in range(8)]
    out = [dict(t=iso(k * 0.5), title=f"Macro story {k}", src=source, cat=cat) for k in range(85)]
    out.append(dict(t=iso(73), title="Too old", src=source, cat=cat))
    out.append(dict(t=iso(1), title="MACRO  story-0!", src="Other", cat=cat))        # 同 Macro story 0 只差大細楷同符號 → 重複
    return out


feeds.FEEDS = {"宏觀": [("SrcA", "https://a.test/rss")]}
feeds.stock_syms = lambda: ["AAA"]
feeds.rss = fake_rss
feeds.ff_news = lambda: [dict(t=iso(2), title="Flash 1", src="FJ", cat="快訊", imp=3), dict(t=iso(3), title="Flash 2", src="FJ", cat="快訊", imp=2)]
got = feeds.news(NOW)
mac = [x for x in got if x["cat"] == "宏觀"]
aaa = [x for x in got if x.get("sym") == "AAA"]
check(len(mac) == 80 and mac[0]["title"] == "Macro story 0" and mac[-1]["title"] == "Macro story 79" and not any(x["title"] in ("Too old", "MACRO  story-0!") for x in got),
      "feeds.news：每類最多 80 條（新嘅先）；超過 72 小時唔要；同類同標題（唔理大細楷、符號）只留一條")
check([x["title"] for x in aaa] == [f"AAA news {k}" for k in range(6)] and [x["title"] for x in got if x["cat"] == "快訊"] == ["Flash 1", "Flash 2"]
      and got == sorted(got, key=lambda x: x["t"], reverse=True), "feeds.news：每隻股最多 6 條；快訊照收；全部按時間新到舊")

# ============================================================ 3. feeds.econ_nasdaq
TODAY = date(2026, 11, 13)
ASKED = []


def fake_get(url, timeout=25):
    d = url.split("date=")[1][:10] if "date=" in url else url
    ASKED.append(d)
    if d == FAIL[0]:
        raise OSError("timed out")
    if d != (TODAY + timedelta(days=1)).isoformat():
        return json.dumps({"data": {"rows": []}}).encode()
    return json.dumps({"data": {"rows": [
        {"country": "United States", "eventName": "CPI (YoY)", "gmt": "08:30", "actual": "3.1%", "consensus": "3.0%", "previous": "&nbsp;"},
        {"country": "Japan", "eventName": "GDP", "gmt": "23:50"},
        {"country": "United States", "eventName": "Fed Waller Speaks", "gmt": "10:00"},
        {"country": "United States", "eventName": "Fed Chair Powell Speaks", "gmt": "Tentative"},
        {"country": "United States", "eventName": "4-Week Bill Auction", "gmt": "11:30"}]}}).encode()


FAIL = [(TODAY - timedelta(days=1)).isoformat()]                 # 即係前兩日嗰次（date 參數 = 日子 + 1）
feeds.get = fake_get
if "date=" not in feeds.NASDAQ_CAL:
    raise SystemExit("NASDAQ_CAL 格式變咗，要改測試")
rows, src = feeds.econ_nasdaq(TODAY)
check(src == "Nasdaq" and [(r["name"], r["t"]) for r in rows] == [("CPI (YoY)", "2026-11-13T08:30"), ("Fed Chair Powell Speaks", "2026-11-13")]
      and rows[0]["actual"] == "3.1%" and rows[0]["previous"] is None and len(ASKED) == 13,
      "econ_nasdaq：其他日子攞唔到照做；淨係美國；Fed 官員講話淨係要 Powell；剔走國庫券拍賣；冇時間就淨係日子；空值 = None")
FAIL[0] = (TODAY + timedelta(days=1)).isoformat()
try:
    feeds.econ_nasdaq(TODAY)
    err = ""
except OSError as e:
    err = str(e)
check(err == "timed out", "econ_nasdaq：今日攞唔到 → 報錯（交俾後備來源）")

# ============================================================ 4. people
PAGE = ("<table><tr><th>Name</th><th>Office</th></tr><tr><td>x</td><td>y</td></tr></table>"
        "<table><tr><th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th><th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th></tr>"
        "<tr><td>1</td><td>10/01/2026</td><td>Spouse</td><td><a href='x'>NVDA</a></td><td>NVIDIA Corp</td><td>Stock</td><td>Purchase</td><td>$1,001 - $15,000</td></tr>"
        "<tr><td>2</td><td>10/02/2026</td><td>Self</td><td>--</td><td>Muni &amp; Bond</td><td>Municipal Security</td><td>Sale (Full)</td><td>$15,001 - $50,000</td></tr>"
        "<tr><td>3</td><td>壞行</td></tr></table>")
check(people.parse_efd_ptr(PAGE) == [
    dict(transactionDate="2026-10-01", owner="Spouse", symbol="NVDA", assetDescription="NVIDIA Corp", assetType="Stock", type="Purchase", amount="$1,001 - $15,000"),
    dict(transactionDate="2026-10-02", owner="Self", symbol="", assetDescription="Muni & Bond", assetType="Municipal Security", type="Sale (Full)", amount="$15,001 - $50,000")],
    "parse_efd_ptr：搵有交易日同金額嘅表；格數唔夠嘅行唔要；代號「--」= 冇；HTML 符號還原")
check(people.parse_efd_ptr("<table><tr><th>Name</th></tr></table>") == [], "parse_efd_ptr：冇交易表 → []")

os.environ["FMP_API_KEY"] = "k123secret"
people.efd_rows = lambda cut, docs: (_ for _ in ()).throw(people.EFDBlocked("HTTP 403"))
PAGES = []


def fmp(seq):
    PAGES[:] = seq
    people.get = lambda url, **k: json.dumps(PAGES.pop(0)).encode()


fmp([{"Error Message": "Invalid API KEY k123secret"}])
errs = []
trades, seen, n_new, status, extra = people.senate({}, "2026-08-15", "2026-11-13T12:00:00", errs)
check(errs == ["參議院（FMP）：Invalid API KEY ***"] and trades == [] and "擋咗程式" in status, "senate：官方擋咗、FMP 第一頁答錯誤 → 記錯（遮走 key），冇交易")
ROW = dict(disclosureDate="2026-11-01", symbol="AMD", assetType="Stock", type="Sale (Partial)", transactionDate="2026-10-20", amount="$1,001 -  $15,000",
           owner="Spouse", firstName="Jane", lastName="Doe", link="https://efdsearch.senate.gov/search/view/ptr/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/")
fmp([[ROW, dict(ROW, symbol="", link="x2"), dict(ROW, assetType="Stock Option", link="x3")], {"Error Message": "limit"}])
errs = []
trades, seen, n_new, status, extra = people.senate({}, "2026-08-15", "2026-11-13T12:00:00", errs)
t = trades[0]
check(errs == [] and status == "ok（FMP）" and len(trades) == 1 and n_new == 1 and (t["sym"], t["type"], t["partial"], t["owner"], t["member"], t["amount"], t["doc"]) ==
      ("AMD", "賣", True, "配偶", "Jane Doe", "$1,001 - $15,000", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
      "senate：FMP 第一頁有交易、第二頁答錯誤 dict → 唔當錯；淨係要有代號嘅股票")

# ============================================================ 5. bars.kline_block、structure.facts
K = [((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(60)]
check(bars.kline_block(K[:59]) is None, "kline_block：唔夠 60 日 → 唔畫")
kb = bars.kline_block(K, keep_days=30)
check(kb and len(kb["d"]) == 30 and kb["d"][-1] == K[-1][0] and kb["c"][-1] == 159.5 and kb["tick"] == sorted(x[4] for x in K[30:])[15] * 1e-5 and "ta" in kb,
      "kline_block：60 日 → 顯示最近 keep_days 日；tick = 顯示嗰段收市中位數 × 0.00001")
DD = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(100)]
two = structure.facts(DD, [dict(i=50, dir=1, k="BOS", lv=100.0), dict(i=90, dir=-1, k="MSS", lv=110.5)], {"adr": None})
check(two == [f"最近一次突破：{DD[90]} 向下 MSS（同之前方向相反，結構轉向），實體收穿轉角位 110.50，距今 9 個交易日",
              f"再之前一次：{DD[50]} 向上 BOS（收穿 100.00）", "近 60 個交易日：向上突破 1 次、向下 1 次"],
      "structure.facts：兩次突破 → 寫最近一次、再之前一次、近 60 日次數")
one = structure.facts(DD, [dict(i=30, dir=1, k="BOS", lv=0.5)], {"adr": 3.2, "off52": -0.1, "atr50": None}, unit="日")
check(len(one) == 3 and not any("再之前一次" in x for x in one) and "近 60 日：向上突破 0 次、向下 0 次" in one and one[-1].startswith("ADR（20 日平均日內波幅）3.2%"),
      "structure.facts：得一次突破唔寫「再之前一次」；60 日前嘅唔計入近 60 日；有 ADR 就加一句")
print(f"\n全部 {ok} 項通過")
