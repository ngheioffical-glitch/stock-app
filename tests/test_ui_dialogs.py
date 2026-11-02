# -*- coding: utf-8 -*-
"""2026-11-02：Android 外殼（android/.../MainActivity.kt）冇 WebChromeClient，原生 confirm()／alert()／prompt() 唔會彈出
（confirm 即刻當「取消」，老師撳研究「生成」冇反應）。docs/index.html 一律要用 askBox()／noteBox()。
用法：python tests/test_ui_dialogs.py"""
import re
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")
H = (T.parent / "docs" / "index.html").read_text(encoding="utf-8")
code = "\n".join(ln for ln in H.splitlines() if not ln.lstrip().startswith("//"))
bad = [m.group(0) for m in re.finditer(r"(?<![\w.$])(?:window\.)?(confirm|alert|prompt)\(", code)]
assert not bad, f"用咗原生對話框：{bad[:5]}"
print("✓ index.html 冇用原生 confirm／alert／prompt")
assert "function askBox(" in H and "const noteBox" in H
print("✓ 有 app 自己嘅 askBox／noteBox")
print("\n全部 2 項通過")
