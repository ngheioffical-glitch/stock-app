"""模型帳戶（2026-09-29 用戶要求，2026-10-09 起係 V2.4）：雲端每日收市後照規則行虛擬帳戶，新手照抄就得。[quant-risk]

V2.4（2026-10-09 用戶揀「最高回報組合」，唔揀股、冇孖展）：規則喺 scanner/v24.py（研究 stock-strategy/src/v24_hist.py 用同一份）：
  80% 趨勢腳（綠燈 + QQQ 波幅 < 35% 揸 TQQQ，否則 IEF）、10% 低吸腳（綠燈 + NDX 2 日 RSI < 25 開市買 TQQQ，RSI > 70 或 10 日賣）、
  10% 輪動腳（月尾揀 TQQQ／TMF／UGL／現金）；每月尾調返 80／10／10。
每日（daily-scan.yml 喺 scan.py 之後跑「python scanner/model.py cont」）：
  1. Yahoo 下載 2 年日線（^NDX、QQQ、TLT、GLD、^IRX、TQQQ、IEF、TMF、UGL；連派息調整價）
  2. 由帳戶上次處理嗰日之後，逐個交易日照 v24.step() 行（開市低吸 → 收市升跌 → 收市執行上一日決定 → 收市決定聽日）
  3. 寫 docs/model_cont.json：狀態、hist（每日快照，app 歷史用）、view（持倉、要做同原因、三隻腳狀態）
  數據唔齊（價錢缺）就停喺嗰日之前，等下次再補，唔會靜靜雞當冇升跌。
延續帳戶第一次用 scanner/model_cont.py 由研究嘅 2000 年起帳戶（results_all/v24_seed.json）建立。
ai_search()（Gemini + Google 搜尋）俾 earnings.py、radar.py 用。
用法：python scanner/model.py cont
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v24  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONT = ROOT / "docs" / "model_cont.json"
SYMS = ["^NDX", "QQQ", "TLT", "GLD", "^IRX", "TQQQ", "IEF", "TMF", "UGL"]
NEED = ("TQQQ", "IEF", "TMF", "UGL")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def yahoo_frame(period="2y"):
    """v24.rows() 要嘅每日數據：調整收市價（連派息）、TQQQ 調整開市價。"""
    import pandas as pd
    import yfinance as yf
    raw = yf.download(SYMS, period=period, auto_adjust=False, group_by="ticker", progress=False, threads=True)
    g = lambda s, k: raw[s][k] if s in raw.columns.get_level_values(0) else pd.Series(dtype=float)
    ndx = g("^NDX", "Close").dropna()
    F = pd.DataFrame(index=ndx.index)
    F["ndx"] = ndx
    F["qqq"], F["tlt"], F["gld"] = g("QQQ", "Adj Close"), g("TLT", "Adj Close"), g("GLD", "Adj Close")
    F["irx"] = g("^IRX", "Close")
    for s in NEED:
        F[s] = g(s, "Adj Close")
    F["tq_open"] = g("TQQQ", "Open") * g("TQQQ", "Adj Close") / g("TQQQ", "Close")
    F.index = pd.to_datetime(F.index).tz_localize(None).normalize()
    F = F[~F.index.duplicated(keep="last")]
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ny = datetime.now(ZoneInfo("America/New_York"))          # 2026-10-09：美股未收市（例如手動喺開市期間跑）嗰日係盤中價，唔可以當收市
    if len(F) and F.index[-1].date() >= ny.date() and (ny.hour, ny.minute) < (16, 20):
        F = F.iloc[:-1]
    return F


def next_day(last):
    import scan as SC
    return str(SC.next_trading_day(last).date())


def recent_fills(st, n=10):
    return [dict(date=h["d"], sym=x["s"], side=x["side"], px=x["px"], ret=x.get("ret"), reason=x["why"])
            for h in st.get("hist", [])[-n:] for x in h.get("f", [])]


def run(path=CONT):
    st = load(path)
    F = yahoo_frame()
    nd = next_day(F.index[-1])
    R = v24.rows(F, nd)
    days = [r["d"] for r in R]
    warn = []
    if st["last"] not in days:
        raise SystemExit(f"[model] 帳戶最後處理日 {st['last']} 唔喺 Yahoo 數據入面（{days[0]} → {days[-1]}），唔更新")
    i = days.index(st["last"])
    prev = R[i]
    done = 0
    for r in R[i + 1:]:
        miss = [s for s in NEED if s not in r["px"]] + ([] if r.get("op") else ["TQQQ 開市價"])
        if miss:
            warn.append(f"{r['d']} 缺數據（{'、'.join(miss)}）：模型停喺 {prev['d']}，下次掃描再補")
            break
        f = []
        v24.step(st, r, prev, f)
        v24.snap(st, r, f)
        prev = r
        done += 1
    if done == 0 and not warn:
        print(f"[model] 冇新交易日（{st['last']}）")
    nxt = next_day(prev["d"]) if prev["d"] != days[-1] else nd
    st["view"] = v24.view(st, prev, nxt, [], warn)
    st["view"]["actions"]["fills"] = recent_fills(st)
    st["view"]["generated"] = __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    Path(path).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    v = st["view"]
    print(f"[model] {st['last']}：帳戶 {v['nav']:,.0f}；處理 {done} 日；持倉 " +
          "、".join(f"{h['sym']}（{h['leg']} {h['weight']:.0%}）" for h in v["holdings"]) +
          f"；要做 {len(v['todo'])} 樣" + (f"；警告：{warn}" if warn else ""))


# ---------------------------------------------------------------- AI 查證（earnings.py、radar.py 用）
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def ai_search(prompt):
    """Gemini + Google 搜尋（grounding）：真係上網查；回傳 dict（JSON）同來源，冇 key／出錯回 (None, 原因)。"""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, "冇 GEMINI_API_KEY"
    body = {"contents": [{"parts": [{"text": prompt + "\n用 Google 搜尋查證，只根據搜尋結果答；唔肯定就答 unknown。最後只回覆一個 JSON object，唔好加其他文字。"}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.1}}
    last = ""
    base = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
    try:                                       # 2026-10-02：舊型號名會 404；同今日重點一樣先問 Google 有邊啲型號（新版本排先）
        import ai as _ai
        base = _ai.pick(key, base) or base
    except Exception as e:  # noqa: BLE001
        print(f"[model] 型號清單攞唔到，用預設：{e}")
    for m in base:
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=120).read())
            c = d["candidates"][0]
            txt = "".join(x.get("text", "") for x in c["content"]["parts"])
            j = re.search(r"\{.*\}", txt, re.S)
            src = [w.get("web", {}).get("title", "") for w in (c.get("groundingMetadata") or {}).get("groundingChunks", [])][:3]
            if j:
                return json.loads(j.group(0)), f"{m}（Google 搜尋：{'、'.join(s for s in src if s) or '冇列出來源'}）"
            last = f"{m} 冇 JSON"
        except Exception as e:  # noqa: BLE001
            last = f"{m}：{str(e)[:80]}"
    return None, last


if __name__ == "__main__":
    if not CONT.exists():
        print("[model] 冇 docs/model_cont.json（要先用 scanner/model_cont.py 建立），跳過")
    else:
        run(CONT)
