# -*- coding: utf-8 -*-
"""2026-11-07：docs/index.html 係 app-src/build.py 砌出嚟。直接改嗰個檔，下次 build 就冇咗，所以檢查佢同 build 出嚟一樣；
同時檢查測試版嘅嘢冇漏上正式 app：KEY 用錯就睇唔到老師嘅本金、跟單同 token；?data= 可以由網址改數據來源。
用法：python tests/test_app_build.py"""
import re
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
ROOT = T.parent
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT / "app-src"))
from build import build_html  # noqa: E402

H = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
n = 0


def ok(name, cond, info=""):
    global n
    assert cond, f"{name} {info}"
    n += 1
    print("✓", name)


ok("docs/index.html 同 build 出嚟一樣（改 app-src，再行 python app-src/build.py）", H == build_html())
ok("用真設定", 'const KEY = "signals-app";' in H)
ok("讀真數據", 'dataUrl: "scan.json"' in H)
bad = [w for w in ("signals-app-demo", "__DATA_BASE", "示範", "noindex", "DEMO_TAG", "initPanel", "tgRm", "/*__") if w in H]
ok("冇測試版、示範版嘅嘢", not bad, bad)
ok("BASE 寫死係空，網址改唔到數據來源", 'const BASE="";' in H)
ok("註冊 service worker", 'navigator.serviceWorker.register("sw.js")' in H)
ok("有 manifest 同圖示", all(x in H for x in ('rel="manifest"', 'href="icon.svg"', 'href="icon-192.png"')))
ok("入 app 動畫係圖示一筆", "function lcRun(" in H and 'sp.classList.add("out")' not in H)
ok("長網址會斷行（Trump 頁）", re.search(r"\.lg\{[^}]*overflow-wrap:break-word", H) is not None)
ok("service worker 快取有版本號", re.search(r'const CACHE = "signals-app-\d+";', (ROOT / "docs" / "sw.js").read_text(encoding="utf-8")) is not None)
T2 = build_html(test=True)
ok("測試版先有 ?data= 同獨立設定", "signals-app-demo" in T2 and "__DATA_BASE" in T2)
print(f"\n全部 {n} 項通過")
