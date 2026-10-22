"""事件股價線（2026-10-21 用戶：「影片條 curve 會標邊個時間發生咩大事」「優先要 AI 先，歷史就用翻歷史數據加翻落去」
「唔只係個股，直頭成個大市都可以有」）。[quant-data]

輸出 docs/events/<KEY>.json（KEY = MARKET 即納指 100，或者股票代號）+ docs/events/index.json（有邊啲、幾多個事件）：
  chart:  {d: [...], c: [...]}  前年 1 月 1 日起每日收市（拆股、派息調整）
  events: [{d, i, kind, label, detail, chg, w, ai, src, model}]  i = chart 第幾日；w = 重要程度（app 揀頭幾個寫標籤，其他畫點）
事件：
  數據（唔使 AI）：
    big   大升大跌：個股單日 ≥ max(6%, 3 × 之前 60 日波幅)；大市單日 ≥ 2.5%
    earn  業績：yfinance get_earnings_dates（EPS 實際對預測、驚喜 %、當日／翌日股價反應）
    model 模型買入／賣出（docs/model_cont.json 嘅 trades 同持倉；大市線放趨勢腳、輪動腳嘅 TQQQ）
    light 大市紅綠燈轉燈（V2.2：NDX > 200 日線，或者 > 21 EMA 而且 21 EMA > 50 日線）
    dd    大市由高位跌 10%／20%（每次跌浪第一次）
  AI（優先；2026-10-21 用 Gemini，免費）：大升大跌同股價郁 ≥ 5% 嘅業績用 llm.search 上網搵原因，有來源先用（冇來源唔當真），
    結果存 docs/events/ai_cache.json（每個事件問一次，搵唔到最多再試 2 次）；2026-10-22 起同一條線 EVENTS_BATCH 個日子一次問、
    每次之間停 EVENTS_PAUSE 秒、最多 EVENTS_MAX_CALLS 次；Gemini 429／額度用晒就停（唔當失敗，聽日再問）。大市先，再持倉、排名、研究；新嘅先。
股票：模型持倉（唔計 ETF）+ RS 排名頭 15 + 研究清單。
用法：python scanner/events.py（每日掃描之後；冇 AI key 就淨係數據事件）
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("EVENTS_OUT") or ROOT / "docs" / "events")
HKT, NYT = ZoneInfo("Asia/Hong_Kong"), ZoneInfo("America/New_York")
MAX_CALLS = int(os.environ.get("EVENTS_MAX_CALLS", "6"))    # 每次最多問 AI 幾次（每次一批日子）
BATCH = int(os.environ.get("EVENTS_BATCH", "6"))             # 一次問同一條線最多幾個日子
PAUSE = float(os.environ.get("EVENTS_PAUSE", "15"))          # 每次之間停幾秒（Gemini 免費版每分鐘有上限）
AI_SECS = int(os.environ.get("EVENTS_AI_SECS", "900"))
QUOTA = re.compile(r"429|Too Many|RESOURCE_EXHAUSTED|額度|quota", re.I)
EARN_AI = 0.05                    # 業績股價郁 ≥ 5% 先問 AI（細郁嘅業績，數據標籤 EPS 實際對預測已經夠）
MAX_FAIL = 3
ETF = {"TQQQ", "IEF", "TMF", "UGL", "SGOV", "BIL", "QQQ", "SPY", "QLD", "SQQQ", "GLD"}
MKT, MKT_KEY, MKT_NAME = "^NDX", "MARKET", "納指 100"
LEG = {"lead": "領導股", "dip": "低吸腳", "xr": "輪動腳", "trend": "趨勢腳"}
BASE_W = {"big": 1.0, "earn": 2.0, "dd": 2.2, "light": 1.5, "model": 1.2}


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def targets():
    sc = load(ROOT / "docs" / "scan.json", {})
    md = load(ROOT / "docs" / "model_cont.json", {})
    ri = load(ROOT / "docs" / "research" / "index.json", {})
    held = [p["sym"] for p in md.get("positions", []) if p["sym"] not in ETF]
    top = [r["sym"] for r in (sc.get("ranking") or [])[:15]]
    res = [x["sym"] for x in ri.get("items") or [] if not x.get("dry")]
    ind = {r["sym"]: r.get("industry") for r in sc.get("ranking") or []}
    return list(dict.fromkeys(held + top + res)), set(held), set(top), ind, md


def download(syms, start):
    """Yahoo 每日收市（拆股、派息調整）。大批下載間中會甩股票（2026-10-21 見過），甩咗嘅分細批再攞一次。"""
    import yfinance as yf
    want = syms + [MKT]
    kw = dict(start=start, auto_adjust=True, group_by="ticker", threads=True, progress=False)
    raw = yf.download(want, **kw)
    for _ in range(2):
        c = raw.xs("Close", axis=1, level=1)
        miss = [s for s in want if s not in c.columns or c[s].dropna().empty]
        if not miss:
            break
        print(f"[events] Yahoo 甩咗 {len(miss)} 隻，再攞：{miss[:10]}")
        time.sleep(15)
        more = yf.download(miss, **dict(kw, threads=False))
        mc = more.xs("Close", axis=1, level=1) if len(more.columns) else pd.DataFrame()
        ok = [s for s in miss if s in mc.columns and not mc[s].dropna().empty]
        if not ok:
            break
        raw = pd.concat([raw.drop(columns=ok, level=0, errors="ignore"), more[ok]], axis=1)
    return raw.xs("Close", axis=1, level=1)


def pct(x, n=1):
    return f"{x * 100:+.{n}f}%"


def big_moves(c, index):
    r = c.pct_change()
    vol = r.rolling(60, min_periods=20).std().shift(1)
    out = []
    for d, x in r.items():
        if not np.isfinite(x):
            continue
        thr = 0.025 if index else max(0.06, 3 * vol[d]) if np.isfinite(vol[d]) else 0.06
        if abs(x) >= thr:
            v = f"（之前 60 日一般單日波幅約 {vol[d] * 100:.1f}%）" if np.isfinite(vol[d]) else ""
            out.append(dict(d=str(d.date()), kind="big", chg=round(float(x), 4), label=f"{'大升' if x > 0 else '大跌'} {pct(x)}",
                            detail=f"{'納指 100' if index else '股價'}單日 {pct(x)}{v}。"))
    return out


def earnings(sym, c):
    """過去業績：EPS 實際對預測，同股價反應（開市前公佈睇當日，收市後公佈睇翌日）。同 app「業績」分頁一樣用 get_earnings_dates。"""
    import yfinance as yf
    try:
        df = yf.Ticker(sym).get_earnings_dates(limit=16)
    except Exception as e:  # noqa: BLE001
        print(f"[events] {sym} 業績日期攞唔到：{str(e)[:80]}")
        return []
    if df is None or df.empty:
        return []
    idx, out = c.index, []
    for t, row in df.iterrows():
        tn = t.tz_convert(NYT)
        day = pd.Timestamp(tn.date())
        act, est, sur = row.get("Reported EPS"), row.get("EPS Estimate"), row.get("Surprise(%)")
        if act != act or day < idx[0] or day > idx[-1]:
            continue
        pos = int(idx.searchsorted(day))
        after = tn.hour >= 12
        if after and pos < len(idx) and idx[pos] == day:
            pos += 1
        if pos <= 0 or pos >= len(idx):
            continue
        chg = float(c.iloc[pos] / c.iloc[pos - 1] - 1)
        det = f"{day.date()} {'收市後' if after else '開市前'}公佈：每股盈利 {act:.2f}"
        if est == est:
            det += f"，預測 {est:.2f}"
        if sur == sur:
            det += f"（{'勝' if sur >= 0 else '輸'}預期 {abs(sur):.1f}%）"
        det += f"；{'翌日' if after else '當日'}股價 {pct(chg)}。"
        out.append(dict(d=str(idx[pos].date()), kind="earn", chg=round(chg, 4), label=f"業績 {pct(chg, 0)}", detail=det))
    return out


def model_events(sym, md, market=False):
    """模型帳戶買賣：個股 = 領導股；大市線 = 趨勢腳、輪動腳嘅 TQQQ（低吸腳太密唔放）。"""
    out = []
    for t in md.get("trades", []):
        if market:
            if t["sym"] != "TQQQ" or t["leg"] not in ("trend", "xr"):
                continue
        elif t["sym"] != sym:
            continue
        who = f"模型（{LEG.get(t['leg'], t['leg'])}）"
        out.append(dict(d=t["date"], kind="model", label=f"模型買{'入' if not market else ' TQQQ'}",
                        detail=f"{who}買入{' TQQQ' if market else ''}，約 {t['entry']:.2f}。"))
        if t.get("sell_date"):
            out.append(dict(d=t["sell_date"], kind="model", label=f"模型賣出 {pct(t['ret'], 0)}",
                            detail=f"{who}賣出{' TQQQ' if market else ''}，約 {t['sell']:.2f}，回報 {pct(t['ret'])}。原因：{t.get('reason') or '—'}"))
    if not market:
        for p in md.get("positions", []):
            if p["sym"] == sym:
                out.append(dict(d=p["date"], kind="model", label="模型買入（揸緊）",
                                detail=f"模型（領導股）買入，約 {p['entry']:.2f}；止蝕 {p['stop']:.2f}。"))
    return out


def market_events(full, start):
    """大市：紅綠燈轉燈（V2.2 規則）、由高位跌 10%／20%（新高之後先會再計）。full = 有足夠歷史計 200 日線嘅收市。"""
    e21 = full.ewm(span=21, adjust=False).mean()
    s50, s200 = full.rolling(50).mean(), full.rolling(200).mean()
    green = (full > s200) | ((full > e21) & (e21 > s50))
    out, prev = [], None
    for d in full.index[s200.notna()]:
        g = bool(green[d])
        if prev is not None and g != prev and d >= start:
            out.append(dict(d=str(d.date()), kind="light", label="轉綠燈" if g else "轉紅燈",
                            detail=("大市轉綠燈：NDX 企返 200 日線之上，或者 21 EMA > 50 日線。V2.7：領導股可以買、趨勢腳可以揸 TQQQ。" if g else
                                    "大市轉紅燈：NDX 跌穿 200 日線而且短期均線轉弱。V2.7：領導股賣晒、趨勢腳轉 IEF。")))
        prev = g
    peak = full.cummax()
    hit = set()
    for d in full.index:
        if full[d] >= peak[d]:
            hit.clear()
        dd = full[d] / peak[d] - 1
        for lv in (0.10, 0.20):
            if dd <= -lv and lv not in hit:
                hit.add(lv)
                if d >= start:
                    out.append(dict(d=str(d.date()), kind="dd", label=f"由高位跌 {lv:.0%}",
                                    detail=f"納指 100 由高位 {peak[d]:,.0f} 跌到 {full[d]:,.0f}（{pct(dd)}）。"))
    return out


def merge(evs):
    """同一日有業績同大升大跌：留業績（大升大跌唔重複）；其他同日同類嘅只留一個。"""
    earn_days = {e["d"] for e in evs if e["kind"] == "earn"}
    seen, out = set(), []
    for e in sorted(evs, key=lambda e: (e["d"], e["kind"])):
        if e["kind"] == "big" and e["d"] in earn_days:
            continue
        k = (e["d"], e["kind"], e["label"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def ai_prompt(key, name, evs):
    """一次問一條線嘅幾個日子（2026-10-22：之前一日一個請求，Gemini 免費額度 20 次全部 429）。"""
    who = f"美股指數 {name}" if key == MKT_KEY else f"美股 {name}"
    rows = "\n".join(f"{k + 1}. {e['d']} 收市 {pct(e['chg'])}" + ("（公佈業績之後）" if e["kind"] == "earn" else "") for k, e in enumerate(evs))
    return (f"{who} 喺以下日子（美國時間）大升或者大跌：\n{rows}\n"
            "請上網搜尋每一日（或者前一晚）令佢大升或者大跌嘅主要原因（新聞、公司公告、經濟數據、政策）。"
            "回覆 JSON：{\"items\": [{\"date\": \"YYYY-MM-DD\", \"label\": \"最多 8 個中文字嘅事件名（例如：DeepSeek 衝擊、關稅升級、業績勁過預期）\", "
            "\"detail\": \"一至兩句香港廣東話：發生咩事、點解影響股價，要有具體數字或者名\"}]}，每個日子一項。"
            "搵唔到可靠原因嘅 label 寫 unknown，唔好估。")


def ai_fill(jobs, cache):
    """jobs：[(優先次序, key, name, event)]。按優先次序將同一條線嘅事件 BATCH 個一組問一次；每次之間停 PAUSE 秒；
    Gemini 答 429／額度用晒就即刻停（唔當事件失敗，聽日再問）。返今次問咗幾多個事件。"""
    import llm
    if not llm.available():
        print("[events] 冇 AI key：淨係數據事件")
        return 0
    llm.start()
    groups, order = {}, []
    for pri, key, name, e in sorted(jobs, key=lambda j: j[0]):
        if key not in groups:
            groups[key] = (name, [])
            order.append(key)
        groups[key][1].append(e)
    t0, calls, n = time.time(), 0, 0
    for key in order:
        name, evs = groups[key]
        for b in range(0, len(evs), BATCH):
            if calls >= MAX_CALLS or time.time() - t0 > AI_SECS:
                return n
            if calls:
                time.sleep(PAUSE)
            batch = evs[b:b + BATCH]
            calls += 1
            n += len(batch)
            try:
                res, lab, grounded, src = llm.search(ai_prompt(key, name, batch), timeout=180)
            except Exception as ex:  # noqa: BLE001
                res, lab, grounded, src = None, str(ex), False, []
            if res is None and QUOTA.search(str(lab)):
                print(f"[events] AI 額度／速度上限（{str(lab)[:120]}），今次停，聽日再問")
                return n - len(batch)
            items = {str(x.get("date")): x for x in (res or {}).get("items") or [] if isinstance(x, dict)}
            srcs = [dict(title=s.get("title") or s.get("url"), url=s.get("url")) for s in src[:3] if s.get("url")]
            for e in batch:
                ck, x = f"{key}|{e['d']}", items.get(e["d"]) or {}
                label = str(x.get("label") or "").strip()
                if grounded and label and label.lower() != "unknown":
                    cache[ck] = dict(label=label[:16], detail=str(x.get("detail") or "")[:320], src=srcs,
                                     model=lab.split("（")[0][:60], at=datetime.now(HKT).strftime("%Y-%m-%d"))
                    print(f"[events] AI {ck}：{label}")
                else:
                    old = cache.get(ck) or {}
                    cache[ck] = dict(fail=int(old.get("fail", 0)) + 1, at=datetime.now(HKT).strftime("%Y-%m-%d"),
                                     why=("冇搜尋來源" if res and not grounded else "搵唔到原因" if res else str(lab))[:120])
    return n


def apply_ai(key, evs, cache):
    for e in evs:
        a = cache.get(f"{key}|{e['d']}")
        if e["kind"] in ("big", "earn") and a and a.get("label"):
            e.update(ai=True, label=a["label"], detail=a.get("detail") or e.get("detail"), src=a.get("src") or [], model=a.get("model"))
        w = BASE_W[e["kind"]] + (3 if e.get("ai") else 0)
        if e.get("chg") is not None and e["kind"] in ("big", "earn"):
            w += min(abs(e["chg"]) * 10, 2)
        if e["kind"] == "dd":                            # 跌 20% 比跌 10% 重要（10% 一年可以有幾次，標籤唔好俾佢霸晒）
            w += 0.4 if "20%" in e["label"] else -0.6
        e["w"] = round(w, 3)
    return evs


def pack(key, name, c, evs):
    d = [str(x.date()) for x in c.index]
    pos = {x: i for i, x in enumerate(d)}
    out = []
    for e in evs:
        i = pos.get(e["d"])
        if i is None:                                    # 唔係交易日（例如模型記錄日）：貼去之後第一個交易日
            j = int(np.searchsorted(np.array(d), e["d"]))
            if j >= len(d):
                continue
            i = j
        out.append(dict(e, i=i))
    return dict(key=key, name=name, gen=datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT"),
                chart=dict(d=d, c=[round(float(x), 2) for x in c.values]), events=out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    syms, held, top, ind, md = targets()
    today = datetime.now(NYT).date()
    start = pd.Timestamp(today.year - 2, 1, 1)
    C = download(syms, (start - timedelta(days=420)).strftime("%Y-%m-%d"))
    C.index = pd.to_datetime(C.index).tz_localize(None)
    cache = load(OUT / "ai_cache.json", {})
    cache = {k: v for k, v in cache.items() if not (v.get("fail") and QUOTA.search(v.get("why", "")))}   # 額度問題唔係事件問題：清走再問
    series, jobs = {}, []
    full = C[MKT].dropna()
    mk = merge([e for e in big_moves(full, True) if e["d"] >= str(start.date())] + market_events(full, start) + model_events("", md, market=True))
    series[MKT_KEY] = (MKT_NAME, full[full.index >= start], mk)
    for s in syms:
        if s not in C.columns:
            print(f"[events] {s} 冇數據，跳過")
            continue
        cf = C[s].dropna()                               # 完整歷史計波幅（圖頭幾個月嘅大升大跌都有「之前 60 日」做比較）
        c = cf[cf.index >= start]
        if len(c) < 30:
            continue
        big = [e for e in big_moves(cf, False) if e["d"] >= str(start.date())]
        series[s] = (s, c, merge(big + earnings(s, c) + model_events(s, md)))
    # AI 優先：大市先，再持倉、排名、研究；新嘅先；問過而成功嘅唔再問，失敗最多 MAX_FAIL 次
    for key, (name, c, evs) in series.items():
        tier = 0 if key == MKT_KEY else 1 if key in held else 2 if key in top else 3
        for e in evs:
            if e["kind"] not in ("big", "earn") or (e["kind"] == "earn" and abs(e.get("chg") or 0) < EARN_AI):
                continue
            a = cache.get(f"{key}|{e['d']}") or {}
            if a.get("label") or int(a.get("fail", 0)) >= MAX_FAIL:
                continue
            jobs.append(((tier, -int(e["d"].replace("-", ""))), key, name if key == MKT_KEY else f"{key}{'（' + ind[key] + '）' if ind.get(key) else ''}", e))
    asked = ai_fill(jobs, cache) if jobs else 0
    index = {}
    for key, (name, c, evs) in series.items():
        rep = pack(key, name, c, apply_ai(key, evs, cache))
        (OUT / f"{key}.json").write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index[key] = dict(name=name, n=len(rep["events"]), ai=sum(1 for e in rep["events"] if e.get("ai")),
                          last=rep["chart"]["d"][-1], ind=ind.get(key))
    (OUT / "ai_cache.json").write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "index.json").write_text(json.dumps(dict(generated=datetime.now(HKT).strftime("%Y-%m-%d %H:%M HKT"), items=index,
                                                    ai_pending=max(0, len(jobs) - asked)), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[events] {len(index)} 條線（大市 + {len(index) - 1} 隻股）；事件 {sum(v['n'] for v in index.values())} 個，"
          f"AI 解釋 {sum(v['ai'] for v in index.values())} 個；今次問 AI {asked} 個，仲有 {max(0, len(jobs) - asked)} 個等緊")


if __name__ == "__main__":
    main()
