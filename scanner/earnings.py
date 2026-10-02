"""業績重點（2026-10-02 用戶：想 app 分析管理層講咩，好似「做得好嘅地方保持到嗎？做得差嘅地方有改善嗎？」）。只係資訊，唔改 V2.3 規則。

股票：模型持倉（docs/model_cont.json，唔計 TQQQ／IEF）+ RS 排名頭 15（docs/scan.json）。
1. 業績日期：yfinance get_earnings_dates（EPS 預測、實際、驚喜 %）→ 下次業績日期（之後 100 日內）。
2. 啱啱出咗業績（最近 10 日、未分析過；失敗下個鐘再試）→ Gemini + Google 搜尋（真係上網查業績新聞同業績會），用廣東話照框架總結；每次最多 3 間（慳免費額度）。
3. 每 55 分鐘先做一次（feeds 每 5 分鐘跑，其餘時間沿用上一份）；分析結果留 60 日。
輸出 <out>/earnings.json：{generated, checked, upcoming: [...], reports: [...], errs}
用法：python scanner/earnings.py out（要 GEMINI_API_KEY 先會做 AI 分析；冇 key 都會更新業績日期）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
HK = ZoneInfo("Asia/Hong_Kong")
MAX_AI, KEEP_DAYS, EVERY_MIN, RECENT_DAYS = 3, 60, 55, 10   # 2026-10-02：Gemini 搜尋額度 429 會失敗，留 10 日畀之後每個鐘再試

PROMPT = ("美股 {sym} 喺 {date}（美國時間）公佈咗最新一季業績（EPS 預測 {est}，實際 {act}）。用 Google 搜尋呢份業績嘅新聞、新聞稿同業績電話會（earnings call）內容，"
          "用香港廣東話口語總結，數字要具體（例如收入幾多億美元、按年 +x%）。重點睇管理層：之前做得好嘅地方今季保持到嗎？之前做得差嘅地方今季有冇改善？"
          "回覆 JSON：{{\"headline\": \"一句總結今季業績好定差、市場點睇\", \"eps\": \"EPS 實際 vs 預期\", \"revenue\": \"收入實際 vs 預期、按年增長\", "
          "\"guidance\": \"下季／全年指引，有冇上調或者下調，同市場預期比較\", \"kept\": [\"做得好嘅地方有冇保持（每點一句，1–3 點）\"], "
          "\"fixed\": [\"做得差嘅地方有冇改善（每點一句，1–3 點）\"], \"mgmt\": [\"管理層喺業績會講嘅重點（2–4 點）\"], "
          "\"risks\": [\"要留意嘅地方（1–2 點）\"], \"reaction\": \"業績後股價反應（如有）\"}}。搵唔到嘅欄位寫「搵唔到」，唔好估。")


def syms():
    sc = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
    md = json.loads((ROOT / "docs" / "model_cont.json").read_text(encoding="utf-8"))
    held = [p["sym"] for p in md.get("positions", [])]
    top = [r["sym"] for r in sc.get("ranking", [])[:15]]
    return list(dict.fromkeys(held + top)), set(held)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "earnings.json"
    prev = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    now = datetime.now(timezone.utc)
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if prev.get("checked") and not manual and now - datetime.fromisoformat(prev["checked"]) < timedelta(minutes=EVERY_MIN):
        print("[earn] 未夠 55 分鐘，沿用上一份")
        return
    import yfinance as yf
    import model as M                                   # ai_search：Gemini + Google 搜尋（同模型帳戶查退市、拆股一樣）
    S, held = syms()
    done = {f"{r['sym']}|{r['date']}" for r in prev.get("reports", [])}
    upcoming, todo, errs = [], [], []
    for s in S:
        try:
            df = yf.Ticker(s).get_earnings_dates(limit=8)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{s}：{str(e)[:60]}")
            continue
        if df is None or df.empty:
            continue
        for t, r in df.iterrows():
            tu = t.tz_convert("UTC").to_pydatetime()
            est, act = r.get("EPS Estimate"), r.get("Reported EPS")
            if tu > now and tu < now + timedelta(days=100):
                upcoming.append(dict(sym=s, date=str(t.date()), when="盤前" if t.hour < 12 else "收市後", est=None if est != est else round(float(est), 2), held=s in held))
            elif tu <= now and tu > now - timedelta(days=RECENT_DAYS) and act == act and f"{s}|{t.date()}" not in done:
                todo.append(dict(sym=s, date=str(t.date()), est=None if est != est else round(float(est), 2), act=round(float(act), 2),
                                 surprise=None if r.get("Surprise(%)") != r.get("Surprise(%)") else round(float(r.get("Surprise(%)")), 1), held=s in held))
    upcoming = sorted({(u["sym"], u["date"]): u for u in upcoming}.values(), key=lambda u: u["date"])
    reports = [r for r in prev.get("reports", []) if r["date"] >= str((now - timedelta(days=KEEP_DAYS)).date())]
    todo.sort(key=lambda x: (not x["held"], x["date"]))
    for x in todo[:MAX_AI]:
        res, src = M.ai_search(PROMPT.format(sym=x["sym"], date=x["date"], est=x["est"], act=x["act"]))
        if not res:
            errs.append(f"{x['sym']} AI：{src}")
            continue
        reports.append(dict(x, **{k: res.get(k) for k in ("headline", "eps", "revenue", "guidance", "kept", "fixed", "mgmt", "risks", "reaction")},
                            src=src, at=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT")))
        print(f"[earn] {x['sym']} {x['date']} 分析完")
    reports.sort(key=lambda r: r["date"], reverse=True)
    res = dict(generated=datetime.now(HK).strftime("%Y-%m-%d %H:%M HKT"), checked=now.isoformat(), syms=S, upcoming=upcoming, reports=reports,
               pending=[x["sym"] for x in todo[MAX_AI:]], errs=errs)
    f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[earn] {len(S)} 隻；未來 100 日業績 {len(upcoming)} 個；新分析 {min(len(todo), MAX_AI)}／待做 {max(0, len(todo) - MAX_AI)}；錯誤 {errs or '冇'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "feeds_out")
