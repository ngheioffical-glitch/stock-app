# 龍頭突破

美股超大型龍頭突破策略（規則 v2.1）嘅每日候選名單同持倉管理 app。回測結果，唔係投資建議。

## 點運作

| 部分 | 位置 | 做乜 |
|---|---|---|
| 每日掃描 | `scanner/scan.py`、`.github/workflows/daily-scan.yml` | 每個交易日香港時間 06:30 自動跑：Nasdaq 股票名單 + Yahoo 日線 → 計排名、合格條件、前高、止蝕位、大市燈號 → 更新 `docs/scan.json` |
| App | `docs/`（GitHub Pages） | 手機瀏覽器開，可以「加到主畫面」。讀 `scan.json`，按你自己嘅持倉計空位、掛單、止蝕、賣出提示 |
| APK | `android/`、`.github/workflows/build-apk.yml` | Android 外殼，打開就係上面個網頁 app。喺 Releases 下載 |
| 新聞同經濟數據 | `scanner/feeds.py`、`.github/workflows/feeds.yml` | 抓新聞（CNBC、Investing.com、MarketWatch、BBC、Al Jazeera、港台、聯儲局；排名股用 Yahoo 個股新聞）同美國經濟日曆（Nasdaq：實際、預測、上次），推去 `feeds` 分支（每次覆蓋）。App「新聞」分頁讀 `raw.githubusercontent.com` 上面嘅 `news.json`、`econ.json`。2026-10-24 起（老師：「淨係新聞密就得，其他全部淨係排程」）：新聞開市時間每 15–30 分鐘、收市後每 4 個鐘或者期貨大郁、開 app 新聞超過 15 分鐘自動更新；同一個 workflow 嘅其他數據（Serenity、Trump、BTC 燈號、恐慌貪婪、巨鯨、債息、商品、大額轉帳、業績、宏觀來源，同 AI 宏觀思考、加密重點、大額轉帳分析、商品分析）淨係香港 06:29、19:41（平日加 21:11）或者 app 撳「重新整理」先更新（`scanner/feeds_gate.py` 嘅 `FULL_CRONS`）。App 定時淨係讀新聞 |
| AI 接駁層 | `scanner/llm.py` | 所有 AI 功能經呢度叫。揀邊個：有 `DEEPSEEK_API_KEY` 就用 DeepSeek（收錢、預付；翻譯、重點、雷達、上網查證用 deepseek-flash，研究報告用 deepseek-v4-pro；上網搜尋用佢嘅 Search API，先叫 AI 寫關鍵字，搜完先叫佢根據結果答），冇就有 `MISTRAL_API_KEY` 用 Mistral，再冇就 Gemini（`GEMINI_API_KEY`）。主力出錯、超時、格式唔啱、餘額用晒或者用晒預算，就自動用 Gemini 後備，app 會標明。2026-10-24 起輕鬆嘢（翻譯、經濟數據解讀、聯儲局總結、雷達／Meme／題材導讀，`ask(light=True)`）先用免費 Gemini，Gemini 出錯或者額度爆先用 DeepSeek（`AI_LIGHT=""` 關咗）。收錢 AI 上限：每日 US$1（`AI_PAID_DAILY_USD`）、試用總額 US$10（`AI_PAID_TOTAL_USD`），所有 workflow 加埋計（各自寫自己嘅 `ai_usage` 帳本，再讀埋其他嘅）。DeepSeek 繁忙時段（香港平日 09–12、14–18 時，全價）一律唔用、自動轉 Gemini（`DEEPSEEK_PEAK_OK=1` 先照用）；有 AI 嘅排程全部放喺非繁忙時段（2026-10-23 老師要求）。轉 Claude Opus 5.5 就設 `AI_PROVIDER=claude`（要 `ANTHROPIC_API_KEY`）。GitHub Models 2026-07-30 停用，已拎走 |
| 外匯同跨市場 | `scanner/fx.py`、`scanner/commod.py`、`scanner/ai.py`（commod_ai） | 2026-10-25：美元指數、美元兌日圓、歐元兌美元、美元兌人民幣（在岸 CNY=X，Yahoo 冇離岸歷史）、美元兌瑞郎：價、升跌、52 週位置、近 1 年每星期同納指相關；異動（美元兌日圓 5 日 ≤ −3%、美元指數 20 日 ±3%、黃金 5 日 ≥ +4%）入 AI 今日重點；過去 5 日避險跡象（金、日圓、瑞郎、美債價）只寫「可能」。AI「外匯、商品同股市」同商品分析合併一份。跟 feeds 全部更新排程。App「資訊 → 外匯」。只係資訊；歷史影響有幾大喺 `stock-strategy/LAB_FX.md`（Trading repo），唔改規則 |
| 個股研究 | `scanner/research.py`、`.github/workflows/research.yml` | 一隻股票一份報告（`docs/research/`）：程式攞 Yahoo、SEC 數據 → Claude 上網搜尋 → 固定格式寫評級、情境假設、好淡理由 → 程式按公式計公允價值同星級 → Claude 寫結論。App「研究」分頁睇；成本同倉位只存手機 |
| 測試 | `tests/`、`.github/workflows/tests.yml` | `python tests/run_all.py` 跑晒：計錢邏輯（`test_model_logic.py`：領導股、三隻 ETF 腳、再平衡嘅手計例子，冇事後數據，同 `tests/fixtures/model_golden.json` 黃金檔比較；有意改規則先用 `UPDATE_GOLDEN=1` 重寫）、發佈前檢查、AI 接駁層、新聞分流、盤中掃描、事件線、研究、BTC 燈號、空投分析（假 AI、假數據、封鎖上網、唔用真 key、唔使錢），再用 `node --check` 檢查 app 嘅 JavaScript 語法。每日掃描 commit 之前會跑 `scanner/check_data.py`，scan.json／model_cont.json 唔啱就沿用上一份再報錯。改 `scanner/*.py`、`tests/`、`docs/index.html`、`docs/sw.js` push 上嚟就自動跑，失敗 GitHub 寄 email。改程式記得加返測試 |

持倉、交易紀錄只存喺手機（瀏覽器或者 APK 嘅 localStorage），唔會上傳。換手機、刪 app、清資料之前，喺「設定」複製備份。

## 第一次設定

1. **Settings → Pages**：Source 揀「Deploy from a branch」，Branch 揀 `main`，資料夾揀 `/docs`，按 Save。一兩分鐘後網址係 `https://<用戶名>.github.io/<repo 名>/`。
2. **Actions** 頁：如果見到提示，按「I understand my workflows, go ahead and enable them」。
3. 想即刻更新數據：Actions → 每日掃描 → Run workflow。
4. APK：Actions → 打包 APK → Run workflow，完成後喺 Releases 下載 `app-debug.apk`。
5. 新聞：Actions → 新聞同經濟數據 → Run workflow（之後每 30 分鐘自動跑）。
6. AI：Settings → Secrets and variables → Actions → 加 `DEEPSEEK_API_KEY`（platform.deepseek.com 開嘅 API key，要預先增值；2026-10-23 老師開咗叫 `DDEEPSEEK_API_KEY`，workflow 兩個名都收）。冇就用 Gemini（`GEMINI_API_KEY`，免費但成日 429）。想用 Claude 就加 `ANTHROPIC_API_KEY` 再設 `AI_PROVIDER=claude`。

## 規則

每日收市後：大市綠燈（NDX > 200 日線，或 NDX > 21 日 EMA > 50 日線）先買；成交額頭 50 名入面按 RS 排名，合格（收市 > 200 日線、50 日線 > 200 日線、收市 ≥ 52 週高 × 0.75）而收市仲低過前高嘅股，喺前高掛 buy-stop。每隻 20%（排第 1 用 30%），最多 5 隻。止蝕 = 最近 swing low − 0.2 ATR；收市到 2R 推上成本；之後跟 swing low 上移。收市跌穿 200 日線、星期五排名跌出頭 12、大市紅燈就賣。帳戶由星期五高位跌 25% 就剎車（最多 2 隻）。
