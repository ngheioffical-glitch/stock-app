"""模型帳戶（2026-09-29 用戶要求；2026-10-12 起係 V2.7）：雲端每日收市後照規則行虛擬帳戶，新手照抄就得。[quant-risk]

V2.7（stock-strategy/LAB_LOSSMIN.md 第 2 輪：冇偷睇揀法 LM2 2026 年揀中）= 35% 領導股 + 45% 趨勢腳（分 4 份買返）+ 5% 低吸腳 + 15% 輪動腳（安全版）；比重同門檻以 v25.py 為準：
  領導股（V2.2 規則）：scanner/lead.py，讀 docs/scan.json（scan.py 先跑）；三隻 ETF 腳：scanner/v24.py；比重同月尾再平衡：scanner/v25.py。
每日（daily-scan.yml 喺 scan.py 之後跑「python scanner/model.py cont」）：
  1. Yahoo 下載 2 年日線（^NDX、QQQ、TLT、GLD、^IRX、TQQQ、IEF、TMF、UGL；連派息調整價）→ v24.rows() 每日訊號
  2. 由帳戶上次處理嗰日之後，逐個交易日（要 scan.json 都有嗰日）：領導股（開市賣 → buy-stop → 止蝕 → 收市 → 現金）、
     三隻 ETF 腳（開市低吸 → 收市升跌 → 收市執行上一日決定 → 收市決定聽日）、月尾再平衡（領導股只用現金）
  3. 最新一日收市：領導股更新止蝕、決定賣出、掛下一日 buy-stop
  4. 寫 docs/model_cont.json：狀態、hist（每日快照，app 歷史用）、view（持倉、要做同原因、四部分狀態）
  數據唔齊（ETF 價缺）就停喺嗰日之前；scan.json 未更新就唔行（等下次）。
延續帳戶第一次用 scanner/model_cont.py 由研究嘅 2000 年起帳戶（results_all/v25_seed.json）建立。
ai_search()（Gemini + Google 搜尋）俾 lead.py（退市、拆股查證）、earnings.py、radar.py 用。
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
import lead  # noqa: E402
import v24  # noqa: E402
import v25  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONT = ROOT / "docs" / "model_cont.json"
SCAN = ROOT / "docs" / "scan.json"
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


def total(st):
    return lead.value(st) + v25.legs_val(st)


def snap(st, r, fills):
    """每日收市快照（格式同 stock-strategy/src/model_bt.py 嘅 days；pos 有 leg、領導股有止蝕）。"""
    tot = total(st)
    pos = lead.rows(st, tot) + v25.leg_rows(st, r, tot)
    pos.sort(key=lambda x: -x["w"])
    f = [dict(s=x["sym"], side=x["side"], px=x["px"], **({"ret": round(x["ret"], 4)} if x.get("ret") is not None else {}), why=x["reason"])
         for x in fills if x["date"] == r["d"]]
    h = st.setdefault("hist", [])
    h[:] = [x for x in h if x["d"] != r["d"]]
    h.append(dict(d=r["d"], nav=round(tot, 0), cash=round((st["cash"] + v25.leg_cash(st)) / tot, 4), green=r["green"], pos=pos, f=f, q=round(r["q"], 4)))
    nv = [x for x in st.get("nav", []) if x["date"] != r["d"]] + [dict(date=r["d"], nav=round(tot, 2))]
    st["nav"] = nv[-400:]


def recent_fills(st, n=10):
    return [dict(date=h["d"], sym=x["s"], side=x["side"], px=x["px"], ret=x.get("ret"), reason=x["why"])
            for h in st.get("hist", [])[-n:] for x in h.get("f", [])]


def view(st, r, sc, nxt, actions):
    tot = total(st)
    lv = lead.value(st)
    hold, legs, tq = v25.leg_view(st, r, tot)
    hold = lead.holdings(st, sc, tot) + hold
    hold.sort(key=lambda h: -h["weight"])
    todo = lead.todo(st, tot) + v25.leg_todo(st, r, tot)
    legs["lead"] = dict(w=v25.W["lead"], frac=round(lv / tot, 4), n=len(st["positions"]), cap=lead.RULE["cap_brake"] if st["braking"] else lead.RULE["cap"],
                        braking=st["braking"], peak=round(st["peak"], 2) if st.get("peak") else None, cash=round(st["cash"] / tot, 4),
                        slots=st.get("slots", 0), green=r["green"], sleeve="國債（SGOV／BIL）" if r["green"] else "IEF")
    return dict(ver=v25.VER, data_date=r["d"], next_day=nxt, green=r["green"], nav=round(tot, 2), ret=round(tot / st["capital"] - 1, 4),
                cash_frac=round((st["cash"] + v25.leg_cash(st)) / tot, 4), holdings=hold, todo=todo, legs=legs, tq=tq,
                actions=dict(fills=recent_fills(st), stops=actions["stops"], warn=actions["warn"]))


def run(path=CONT, sc=None, F=None):
    """sc、F：重建延續帳戶時傳入（逐日重播）；平時讀 docs/scan.json 同下載 Yahoo。"""
    st = load(path)
    sc = sc or load(SCAN)
    F = yahoo_frame() if F is None else F
    R = v24.rows(F, next_day(F.index[-1]))
    days = [r["d"] for r in R]
    actions = dict(fills=[], stops=[], warn=[])
    if st["last"] not in days:
        raise SystemExit(f"[model] 帳戶最後處理日 {st['last']} 唔喺 Yahoo 數據入面（{days[0]} → {days[-1]}），唔更新")
    i = days.index(st["last"])
    prev = R[i]
    sidx = {d: k for k, d in enumerate(sc["days"])}
    new = [r for r in R[i + 1:] if r["d"] <= sc["date"]]
    if len(R) > i + 1 and not new:
        actions["warn"].append(f"scan.json 仲係 {sc['date']}（ETF 數據去到 {days[-1]}）：等揀股掃描更新先行")
    if new and new[0]["d"] not in sidx:
        actions["warn"].append(f"隔咗超過 10 個交易日先更新，{st['last']} 之後部分日子領導股冇計")
    if new and new[0]["d"] in sidx:
        lead.fix_splits(st, sc, sidx[new[0]["d"]], actions)
    done = 0
    for r in new:
        miss = [s for s in NEED if s not in r["px"]] + ([] if r.get("op") else ["TQQQ 開市價"])
        if miss:
            actions["warn"].append(f"{r['d']} 缺數據（{'、'.join(miss)}）：模型停喺 {prev['d']}，下次掃描再補")
            break
        if r["d"] in sidx:
            lead.step(st, sc, sidx[r["d"]], actions)
        f = []
        if v25.step_legs(st, r, prev, f):
            lv = lead.value(st)
            mv = v25.rebalance(st, lv, st["cash"], r["d"], f)
            st["cash"] += mv
            if st.get("peak") and lv > 0:                # 剎車只計表現：再平衡調入／調出嘅現金唔當升跌（同回測單獨 V2.2 帳戶一樣）
                st["peak"] *= (lv + mv) / lv
        actions["fills"] += f
        snap(st, r, actions["fills"])
        prev = r
        done += 1
    if prev["d"] == sc["date"]:
        lead.plan(st, sc, actions)
        snap(st, prev, actions["fills"])                 # 收市後止蝕上移都計埋
        if actions["stops"]:                             # 同一日重跑：止蝕已經推高咗，提示照留
            st["stop_ups"] = dict(d=prev["d"], list=actions["stops"])
        elif (st.get("stop_ups") or {}).get("d") == prev["d"]:
            actions["stops"] = st["stop_ups"]["list"]
    elif done == 0:
        print(f"[model] 冇新交易日（{st['last']}）")
    nxt = sc["next_day"] if prev["d"] == sc["date"] else next_day(prev["d"])
    st["view"] = view(st, prev, sc, nxt, actions)
    st["view"]["generated"] = __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
    Path(path).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    v = st["view"]
    print(f"[model] {st['last']}：帳戶 {v['nav']:,.0f}；處理 {done} 日；持倉 " +
          "、".join(f"{h['sym']}（{h['leg']} {h['weight']:.0%}）" for h in v["holdings"]) +
          f"；要做 {len(v['todo'])} 樣" + (f"；警告：{actions['warn']}" if actions["warn"] else ""))


# ---------------------------------------------------------------- AI 查證（lead.py、earnings.py、radar.py 用）
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def ai_search(prompt):
    """AI + 上網搜尋（經 llm.py：Claude Opus 5.5 先搜尋再寫 JSON；失敗退 Gemini + Google 搜尋，標籤寫明後備）。
    返 (dict, 來源標籤)；冇真係上網搵到來源就返 (None, 原因)：退市、拆股呢啲會改模型帳戶嘅查證唔可以靠冇來源嘅答案
    （2026-10-20 Codex 搵到：舊版冇來源嘅收購價都會照賣）。lead.py、earnings.py、radar.py 用。"""
    import llm
    if not llm.available():
        return None, "冇 AI key"
    try:
        res, lab, grounded, src = llm.search(prompt + "\n唔肯定就答 unknown。", timeout=300)
    except Exception as e:  # noqa: BLE001
        return None, f"AI 搜尋出錯：{str(e)[:120]}"
    if res is None:
        return None, lab[:200]
    if not grounded:
        return None, f"{lab}：冇上網搜尋來源，唔當查證"
    return res, lab


if __name__ == "__main__":
    if not CONT.exists():
        print("[model] 冇 docs/model_cont.json（要先用 scanner/model_cont.py 建立），跳過")
    else:
        run(CONT)
