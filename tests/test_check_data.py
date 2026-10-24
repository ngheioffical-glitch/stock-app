# -*- coding: utf-8 -*-
"""2026-10-24 scanner/check_data.py：發佈前檢查 scan.json、model_cont.json。用而家 docs 入面嘅真檔（應該過），再逐樣整壞（應該唔過）。
唔上網。用法：python tests/test_check_data.py"""
import copy
import json
import os
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
APP = T.parent
sys.path.insert(0, str(APP / "scanner"))
sys.stdout.reconfigure(encoding="utf-8")
import check_data as C  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("✓", what)


S0 = C.strict((APP / "docs" / "scan.json").read_text(encoding="utf-8"))
M0 = C.strict((APP / "docs" / "model_cont.json").read_text(encoding="utf-8"))
check(not C.check_scan(S0) and not C.check_model(M0), "而家發佈緊嘅 scan.json、model_cont.json 檢查過晒")

try:
    C.strict('{"a": NaN}')
    check(False, "NaN 應該唔過")
except ValueError as e:
    check("NaN" in str(e), "JSON 有 NaN（app 讀唔到）：唔過")


def broken_scan(fn):
    s = copy.deepcopy(S0)
    fn(s)
    return C.check_scan(s)


def broken_model(fn):
    m = copy.deepcopy(M0)
    fn(m)
    return C.check_model(m)


check(broken_scan(lambda s: s["ranking"][0].update(status="候選", pivot=100.0, stop=110.0)), "候選股止蝕高過突破價：唔過")
check(broken_scan(lambda s: s.update(ranking=s["ranking"][:3])), "排名得 3 隻：唔過")
check(broken_scan(lambda s: s.update(next_day=s["date"])), "下一個交易日唔係之後：唔過")
check(broken_scan(lambda s: s["ranking"][1].update(rank=s["ranking"][0]["rank"])), "排名重複：唔過")
check(broken_model(lambda m: m.update(last="2000-01-01")), "數據日期同帳戶日期唔一致：唔過")
check(broken_model(lambda m: m["view"]["holdings"][0].update(weight=m["view"]["holdings"][0]["weight"] + 0.3)), "持倉比重加現金 130%：唔過")
check(broken_model(lambda m: m["view"].update(nav=0)), "資產 0：唔過")
if M0.get("positions"):
    check(broken_model(lambda m: m["positions"][0].update(shares=-5)), "持倉股數負數：唔過")
if M0["view"].get("todo"):
    check(broken_model(lambda m: m["view"]["todo"][0].update(frac=1.5)), "要做嘅比例 150%：唔過")

# 成個程式：壞 scan.json → 兩個檔都還原；好嘅 → 返 0
out = Path(os.environ.get("TEST_OUT") or T / "_out") / "check_data" / time.strftime("%Y%m%d-%H%M%S")
out.mkdir(parents=True, exist_ok=True)
(out / "model_cont.json").write_text(json.dumps(M0, ensure_ascii=False), encoding="utf-8")
(out / "scan.json").write_text(json.dumps(dict(S0, ranking=[])), encoding="utf-8")
import contextlib  # noqa: E402
import io  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
    code = C.main(out)
check(code == 1 and buf.getvalue().split() == ["scan.json", "model_cont.json"], f"scan.json 壞：兩個檔都還原（模型讀 scan.json）：{buf.getvalue().split()}")
(out / "scan.json").write_text(json.dumps(S0, ensure_ascii=False), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    check(C.main(out) == 0, "兩個都啱：返 0")
Y = (APP / ".github" / "workflows" / "daily-scan.yml").read_text(encoding="utf-8")
i_chk, i_commit = Y.find("python scanner/check_data.py docs"), Y.find("git commit")
check(0 < i_chk < i_commit and 'git checkout -- "docs/$f"' in Y and "steps.chk.outputs.bad != ''" in Y, "daily-scan：commit 之前檢查、唔過還原、最尾報錯")
print(f"\n全部 {ok} 項通過")
