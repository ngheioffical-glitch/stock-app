# app 原始碼

`docs/index.html` 係由呢度砌出嚟，**唔好直接改**（`tests/test_app_build.py` 會檢查兩邊一樣）。

| 檔 | 係乜 |
|---|---|
| `engine.html` | 全部功能（舊 app）：數據、細分頁、設定、股票頁。加功能或者改文字改呢個 |
| `shell.html` | 新介面：底欄、手勢、動畫、今日頁、推入頁、sheet、搜尋、日夜、入 app 動畫 |
| `build.py` | 砌埋兩個寫去 `docs/index.html`；抽唔到（結構改咗）會即刻報錯 |
| `ui_test.js` | 瀏覽器測試（排版、對比、手勢、動畫、返回鍵），約 450 項 |

改完：

```bash
python app-src/build.py
```

再升 `docs/sw.js` 嘅 `CACHE` 號碼，跑 `python tests/run_all.py`，先 commit。

## 瀏覽器測試

測試版用固定 11-03 快照，設定存去 `signals-app-demo`，唔郁真設定。呢個版本唔好放上 `docs/`。

```bash
python app-src/build.py --test ../tmp/ui_demo/app_ui_e.html
```

用 Trading 資料夾做根目錄開本機網頁（Claude app 嘅 `ui-demo` 預覽），開 `<測試版>?nosplash=1&data=snap/`，喺頁面 console 行：

```js
await (new (Object.getPrototypeOf(async function(){}).constructor)(await (await fetch('/stock-app/app-src/ui_test.js?'+Date.now())).text()))()
```

回傳 `{pass, fail:[...]}`。尺寸用 375×812 同 360×640。視窗要喺前面（量 `requestAnimationFrame` 每秒約 120 格），否則動畫停咗會出假失敗。

只驗到邏輯、排版同對比。真機手感、Android 手勢返回、震動要手機試。
