# -*- coding: utf-8 -*-
"""跑晒 tests/ 入面嘅測試（2026-10-24 由 Trading/tmp 搬入嚟；GitHub Actions .github/workflows/tests.yml 每次改 scanner／tests／app 都會跑）。
- 每個 test_*.py 自己一個子程序（佢哋會換走 llm 等模組，唔可以同一個程序跑）
- 唔用真 key、唔使錢、唔上網：清走環境變數入面嘅 key 同 AI 設定，再用 tests/_guard/sitecustomize.py 封鎖上網
- 最後用 check_js.py 檢查 app 嘅 JavaScript 語法（要 node；本機冇 node 就跳過，GitHub 上面一定有）
用法：python tests/run_all.py [llm events ...]（唔寫就全部）；全部過返 0。"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
DROP = ("ANTHROPIC_", "GEMINI_", "MISTRAL_", "DEEPSEEK_", "DDEEPSEEK_", "AI_", "RESEARCH_", "EVENTS_", "AIRDROP_", "GITHUB_", "GH_")


def clean_env():
    env = {k: v for k, v in os.environ.items() if not (k.upper().startswith(DROP) or k.upper().endswith(("_API_KEY", "_TOKEN")))}
    env["PYTHONPATH"] = os.pathsep.join([str(T / "_guard")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PYTHONIOENCODING"] = "utf-8"
    env["TEST_OUT"] = str(Path(os.environ.get("TEST_OUT") or T / "_out"))
    return env


def run(cmd, env):
    t0 = time.time()
    r = subprocess.run(cmd, cwd=T.parent, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, time.time() - t0


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    want = set(argv)
    tests = sorted(p for p in T.glob("test_*.py") if not want or p.stem.removeprefix("test_") in want)
    env, fails, total = clean_env(), [], 0
    for p in tests:
        r, sec = run([sys.executable, str(p)], env)
        m = re.search(r"全部 (\d+) 項通過", r.stdout)
        if r.returncode == 0 and m:
            total += int(m.group(1))
            print(f"✓ {p.name}：{m.group(1)} 項（{sec:.0f} 秒）")
        else:
            fails.append(p.name)
            print(f"✗ {p.name} 失敗（exit {r.returncode}，{sec:.0f} 秒）\n{(r.stdout + r.stderr).strip()[-3000:]}\n")
    summary = f"Python {len(tests) - len(fails)}/{len(tests)} 個檔、{total} 項"
    if not want or "js" in want:
        r, _ = run([sys.executable, str(T / "check_js.py")], env)
        last = (r.stdout.strip().splitlines() or [""])[-1].strip()
        if r.returncode == 2:
            summary += "；冇 node，跳過 JS 語法檢查"
        elif r.returncode:
            fails.append("check_js.py")
            print(f"✗ check_js.py 失敗\n{r.stdout.strip()[-3000:]}\n")
        else:
            summary += "；" + last
            print(f"✓ check_js.py：{last}")
    print(f"\n{'失敗：' + '、'.join(fails) if fails else '全部通過'}（{summary}）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
