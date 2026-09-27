"""盤中 5 分鐘掃描（2026-09-28 測試版）：候選股嘅 5 分鐘 K 收市企穩前高就記低。[quant-signals]

「5 分鐘收市企穩」係 LAB_INTRADAY.md 入面未決嘅入場方法，呢個掃描先用嚟觀察，唔改現行 buy-stop 規則。
數據：Yahoo 5 分鐘 K（yfinance，綜合報價）；只用已經完成嘅 K。每次跑都記錄時間同數據延遲，用嚟評估
GitHub 定時同 Yahoo 準唔準。

用法：python scanner/intraday.py 輸出資料夾 [上次 intraday.json 網址或檔案] [--date YYYY-MM-DD 重播]
GitHub Actions 開市期間每 5 分鐘跑，推去 live 分支；app「今日」分頁讀 live/intraday.json。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
HK = ZoneInfo("Asia/Hong_Kong")
MAX_CANDS = 10          # 最多 5 個空位 × 2 張單；手機先按自己持倉揀
BAR = timedelta(minutes=5)


def load_prev(src):
    if not src:
        return None
    try:
        raw = urllib.request.urlopen(src + f"?t={int(time.time())}", timeout=20).read() if src.startswith("http") \
            else Path(src).read_bytes()
        return json.loads(raw)
    except Exception as e:
        print("[intraday] 讀唔到上次結果：", e)
        return None


def bars(syms, day):
    """當日常規時段 5 分鐘 K（美東時間）。day 係今日就攞 1d，重播舊日子就攞 60d 再篩。"""
    import yfinance as yf
    today = datetime.now(NY).date()
    df = yf.download(syms, period="1d" if day == today else "60d", interval="5m", prepost=False,
                     auto_adjust=False, group_by="ticker", progress=False, threads=True)
    out = {}
    for s in syms:
        try:
            d = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            d = d.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
            d.index = d.index.tz_convert(NY)
            d = d[d.index.date == day]
            out[s] = d
        except Exception:
            out[s] = None
    return out


def main():
    argv = sys.argv[1:]
    replay = None
    if "--date" in argv:
        k = argv.index("--date")
        replay = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    args = argv
    out = Path(args[0] if args else ROOT / "live_out")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    now_ny = now.astimezone(NY)
    day = datetime.strptime(replay, "%Y-%m-%d").date() if replay else now_ny.date()
    if replay:
        now_ny = datetime.combine(day, datetime.min.time(), NY).replace(hour=16, minute=5)
    scan = json.loads((ROOT / "docs" / "scan.json").read_text(encoding="utf-8"))
    prev = load_prev(args[1] if len(args) > 1 else None)
    runs = prev.get("runs", []) if prev and prev.get("day") == str(day) else []
    first = {c["sym"]: c for c in prev.get("cands", [])} if prev and prev.get("day") == str(day) else {}

    open_ny = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
    close_ny = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
    in_session = now_ny.weekday() < 5 and open_ny <= now_ny <= close_ny + timedelta(minutes=10)
    stale = scan.get("next_day") != str(day)
    cands = [r for r in scan.get("ranking", []) if r.get("status") == "候選"][:MAX_CANDS]
    res = {"day": str(day), "scan_date": scan.get("date"), "scan_next_day": scan.get("next_day"), "stale_scan": stale,
           "green": scan.get("green"), "in_session": in_session, "cands": [], "runs": runs}
    rec = {"run_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "run_hk": now.astimezone(HK).strftime("%H:%M:%S")}

    if (in_session or replay) and cands:
        t0 = time.time()
        B = bars([c["sym"] for c in cands], day)
        rec["fetch_s"] = round(time.time() - t0, 1)
        last_end = None
        for c in cands:
            b = B.get(c["sym"])
            lv = float(c["pivot"])
            row = {"sym": c["sym"], "rank": c["rank"], "pivot": lv, "stop": c["stop"], "prev_close": c["close"]}
            if b is None or b.empty:
                row["err"] = "冇 5 分鐘數據"
                res["cands"].append(row); continue
            done = b[b.index + BAR <= now_ny]                 # 只用已經完成嘅 K
            if done.empty:
                row["err"] = "未有完成嘅 K"
                res["cands"].append(row); continue
            end = done.index[-1] + BAR
            last_end = max(last_end, end) if last_end else end
            row.update(last=round(float(done.close.iloc[-1]), 4), high=round(float(done.high.max()), 4),
                       bar_end=end.strftime("%H:%M"), dist=round(lv / float(done.close.iloc[-1]) - 1, 5))
            hit = done[done.high >= lv]
            if len(hit):
                k = hit.index[0]
                row["bs"] = {"t": k.strftime("%H:%M"), "px": round(max(float(hit.open.iloc[0]), lv), 4)}
            conf = done[done.close > lv]
            if len(conf):
                k = conf.index[0]
                row["c5"] = {"t": (k + BAR).strftime("%H:%M"), "px": round(float(conf.close.iloc[0]), 4)}
                old = first.get(c["sym"], {}).get("c5")
                if old:                                        # 第一次確認之後唔再改（Yahoo 偶然會改舊 K）
                    row["c5"] = old
                else:
                    row["c5"]["seen_utc"] = rec["run_utc"]   # 第一次喺邊次掃描見到：量度實際通知時間
            res["cands"].append(row)
        if last_end is not None:
            rec["last_bar_end"] = last_end.strftime("%H:%M")
            rec["delay_min"] = round((now_ny - last_end).total_seconds() / 60, 1)
        rec["n_ok"] = sum("last" in c for c in res["cands"])
    else:
        rec["skip"] = "收市時間" if not in_session else "冇候選股"
    if not replay:
        res["runs"] = (runs + [rec])[-120:]
    res["generated"] = now.astimezone(HK).strftime("%Y-%m-%d %H:%M:%S HKT")
    (out / "intraday.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    hits = [f"{c['sym']} {c['c5']['t']}" for c in res["cands"] if "c5" in c]
    print(f"[intraday] {day} 開市中={in_session} 候選 {len(cands)} 隻，數據 {rec.get('n_ok', 0)} 隻，"
          f"延遲 {rec.get('delay_min', '—')} 分鐘；5 分鐘企穩：{', '.join(hits) or '冇'}")


if __name__ == "__main__":
    main()
