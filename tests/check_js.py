# -*- coding: utf-8 -*-
"""檢查 app 嘅 JavaScript 語法：docs/index.html 入面嘅 inline <script> 同 docs/sw.js，逐個用 `node --check`。
語法錯就成個 app 白畫面，所以每次改 index.html 都要過。用法：python tests/check_js.py；過返 0，冇 node 返 2。"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
DOCS = T.parent / "docs"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    node = shutil.which("node")
    if not node:
        print("冇 node，檢查唔到 JS 語法")
        return 2
    out = Path(os.environ.get("TEST_OUT") or T / "_out") / "jscheck"
    out.mkdir(parents=True, exist_ok=True)
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    files = []
    for i, s in enumerate(scripts):
        f = out / f"index_{i}.js"
        f.write_text(s, encoding="utf-8")
        files.append(f)
    files.append(DOCS / "sw.js")
    bad = 0
    for f in files:
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            bad += 1
            print(f"✗ {f.name}\n{(r.stderr or r.stdout).strip()[-1500:]}")
        else:
            print(f"✓ {f.name} 語法啱")
    print(f"\nJS 語法：{len(files) - bad}/{len(files)} 個啱（index.html {len(scripts)} 段 + sw.js）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
