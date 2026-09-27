# 龍頭突破

美股超大型龍頭突破策略（規則 v2.1）嘅每日候選名單同持倉管理 app。回測結果，唔係投資建議。

## 點運作

| 部分 | 位置 | 做乜 |
|---|---|---|
| 每日掃描 | `scanner/scan.py`、`.github/workflows/daily-scan.yml` | 每個交易日香港時間 06:30 自動跑：Nasdaq 股票名單 + Yahoo 日線 → 計排名、合格條件、前高、止蝕位、大市燈號 → 更新 `docs/scan.json` |
| App | `docs/`（GitHub Pages） | 手機瀏覽器開，可以「加到主畫面」。讀 `scan.json`，按你自己嘅持倉計空位、掛單、止蝕、賣出提示 |
| APK | `android/`、`.github/workflows/build-apk.yml` | Android 外殼，打開就係上面個網頁 app。喺 Releases 下載 |
| 新聞同經濟數據 | `scanner/feeds.py`、`.github/workflows/feeds.yml` | 每 30 分鐘抓新聞（CNBC、Investing.com、MarketWatch、BBC、Al Jazeera、港台、聯儲局；排名股用 Yahoo 個股新聞）同美國經濟日曆（Nasdaq：實際、預測、上次），推去 `feeds` 分支（每次覆蓋）。App「新聞」分頁讀 `raw.githubusercontent.com` 上面嘅 `news.json`、`econ.json` |

持倉、交易紀錄只存喺手機（瀏覽器或者 APK 嘅 localStorage），唔會上傳。換手機、刪 app、清資料之前，喺「設定」複製備份。

## 第一次設定

1. **Settings → Pages**：Source 揀「Deploy from a branch」，Branch 揀 `main`，資料夾揀 `/docs`，按 Save。一兩分鐘後網址係 `https://<用戶名>.github.io/<repo 名>/`。
2. **Actions** 頁：如果見到提示，按「I understand my workflows, go ahead and enable them」。
3. 想即刻更新數據：Actions → 每日掃描 → Run workflow。
4. APK：Actions → 打包 APK → Run workflow，完成後喺 Releases 下載 `app-debug.apk`。
5. 新聞：Actions → 新聞同經濟數據 → Run workflow（之後每 30 分鐘自動跑）。

## 規則

每日收市後：大市綠燈（NDX > 200 日線，或 NDX > 21 日 EMA > 50 日線）先買；成交額頭 50 名入面按 RS 排名，合格（收市 > 200 日線、50 日線 > 200 日線、收市 ≥ 52 週高 × 0.75）而收市仲低過前高嘅股，喺前高掛 buy-stop。每隻 20%（排第 1 用 30%），最多 5 隻。止蝕 = 最近 swing low − 0.2 ATR；收市到 2R 推上成本；之後跟 swing low 上移。收市跌穿 200 日線、星期五排名跌出頭 12、大市紅燈就賣。帳戶由星期五高位跌 25% 就剎車（最多 2 隻）。
