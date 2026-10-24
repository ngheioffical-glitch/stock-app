"""發佈前數據檢查（2026-10-24；/codex 檢討：daily-scan.yml 之前直接 commit scan.json、model_cont.json，冇檢查格式）。

檢查 app 會讀嘅兩個檔：
  - JSON 讀得返：冇 NaN／Infinity（Python 會寫出嚟，但 app 嘅 JSON.parse 讀唔到，成頁出錯）
  - scan.json：日期、排名（夠數、代號、排名唔重複、收市價）、候選股突破價同止蝕（止蝕要低過突破價）、燈號
  - model_cont.json：數據日期同帳戶日期一致、資產、比重加現金 ≈ 100%、要做嘅買賣比例、持倉股數同價錢
唔過嘅檔名印喺 stdout（一行一個；scan.json 唔過就連 model_cont.json 一齊，因為模型讀 scan.json），原因印喺 stderr。
.github/workflows/daily-scan.yml 會將唔過嘅檔還原返上一份先 commit，最尾報錯（GitHub 寄 email）。純檢查，唔改任何規則。
用法：python scanner/check_data.py [docs 資料夾]；全部過返 0，有唔過返 1。
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

MIN_RANK = 10            # 排名少過呢個數就當唔完整（scan.py 自己都會擋，呢度再保險）
TOL = 0.02               # 比重 + 現金同 100% 最多差幾多


def strict(text):
    """讀 JSON，見到 NaN／Infinity 就出錯。"""
    def bad(x):
        raise ValueError(f"有 {x}（app 讀唔到）")
    return json.loads(text, parse_constant=bad)


def _day(x):
    try:
        return date.fromisoformat(str(x))
    except ValueError:
        return None


def _pos(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def check_scan(s):
    err = []
    d, nd = _day(s.get("date")), _day(s.get("next_day"))
    if not d or not nd or nd <= d:
        err.append(f"日期唔啱：date={s.get('date')} next_day={s.get('next_day')}")
    if not isinstance(s.get("green"), bool):
        err.append("冇大市燈號（green）")
    R = s.get("ranking")
    if not isinstance(R, list) or len(R) < MIN_RANK:
        err.append(f"排名得 {len(R) if isinstance(R, list) else 0} 隻（少過 {MIN_RANK}）")
        R = R if isinstance(R, list) else []
    ranks = [r.get("rank") for r in R]
    if len(set(ranks)) != len(ranks):
        err.append("排名有重複")
    for r in R:
        sym = r.get("sym")
        if not sym or not isinstance(sym, str):
            err.append(f"排名 {r.get('rank')} 冇代號")
        if not _pos(r.get("close")):
            err.append(f"{sym}：收市價唔啱（{r.get('close')}）")
        if r.get("status") == "候選":
            p, st = r.get("pivot"), r.get("stop")
            if not (_pos(p) and _pos(st) and st < p):
                err.append(f"{sym}：候選股突破價／止蝕唔啱（突破 {p}、止蝕 {st}）")
    return err


def check_model(m):
    err = []
    v = m.get("view") or {}
    dd = _day(v.get("data_date"))
    if not dd or v.get("data_date") != m.get("last"):
        err.append(f"數據日期 {v.get('data_date')} 同帳戶日期 {m.get('last')} 唔一致")
    # 模型日期可以行先過 scan.json（追數嗰陣模型自己用 Yahoo 重播，2026-10-01、10-09 都有），唔當錯；落後由 app 嘅數據警告講
    if not _day(v.get("next_day")) or (dd and _day(v.get("next_day")) <= dd):
        err.append(f"下一個交易日唔啱：{v.get('next_day')}")
    if not _pos(v.get("nav")):
        err.append(f"資產唔啱：{v.get('nav')}")
    cf = v.get("cash_frac")
    if not isinstance(cf, (int, float)) or not 0 <= cf <= 1:
        err.append(f"現金比例唔啱：{cf}")
        cf = 0
    H = v.get("holdings") or []
    if any(not isinstance(h.get("weight"), (int, float)) or h["weight"] < 0 for h in H):
        err.append("持倉比重有負數或者冇數")
    else:
        tot = sum(h["weight"] for h in H) + cf
        if abs(tot - 1) > TOL:
            err.append(f"持倉比重加現金 = {tot:.1%}（應該約 100%）")
    for t in v.get("todo") or []:
        f = t.get("frac")
        if f is not None and not (isinstance(f, (int, float)) and 0 < f <= 1):
            err.append(f"要做 {t.get('sym')}：比例唔啱（{f}）")
        for k in ("trigger", "stop"):
            if t.get(k) is not None and not _pos(t[k]):
                err.append(f"要做 {t.get('sym')}：{k} 唔啱（{t[k]}）")
    for p in m.get("positions") or []:
        if not (_pos(p.get("shares")) and _pos(p.get("entry")) and _pos(p.get("stop"))):
            err.append(f"持倉 {p.get('sym')}：股數／入貨價／止蝕唔啱（{p.get('shares')}／{p.get('entry')}／{p.get('stop')}）")
    for k in ("trades", "nav"):
        if not isinstance(m.get(k), list):
            err.append(f"冇 {k}")
    return err


def main(docs="docs"):
    docs = Path(docs)
    bad = []
    try:
        es = check_scan(strict((docs / "scan.json").read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001
        es = [f"讀唔到：{e}"]
    try:
        em = check_model(strict((docs / "model_cont.json").read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001
        em = [f"讀唔到：{e}"]
    for name, e in (("scan.json", es), ("model_cont.json", em)):
        for x in e[:20]:
            print(f"[check] {name}：{x}", file=sys.stderr)
    if es:
        bad = ["scan.json", "model_cont.json"]               # 模型讀 scan.json，掃描唔啱模型都唔信
    elif em:
        bad = ["model_cont.json"]
    for f in bad:
        print(f)
    if not bad:
        print("[check] scan.json、model_cont.json 檢查過晒", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "docs"))
