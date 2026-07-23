# 拍拍深五行水晶手串販售系統 v2.0（2026-07-12）

單人經營、五年耐用、AI 深度融入但不綁死任何供應商。**零框架、零建置、零 CDN**：兩個 HTML＋三支 n8n WF＋一個 postgres。

## 線上網址

| 什麼 | 網址 |
|---|---|
| 🛍️ 前台（客戶用） | **https://anwer3712.github.io/paipaishen-shop/** |
| 🔐 後台（店長用，PIN 門） | https://anwer3712.github.io/paipaishen-shop/admin.html（本機開 `admin.html` 也行） |
| ⚙️ n8n 控制台 | https://n8n.anwer3712.com （WF：`SALES_前台進件`／`SALES_進度查詢回覆`／`SALES_AI客服`） |
| 📦 GitHub repo | https://github.com/anwer3712/paipaishen-shop |

管理密鑰在本機 [管理密鑰_勿上傳.md](管理密鑰_勿上傳.md)（已被 .gitignore 排除）。

## 架構

```
客戶瀏覽器                                     店長
   │                                            │
   ▼                                            ▼
GitHub Pages（index.html 前台）           admin.html 後台（PIN＋AES-GCM 加密）
   │  問卷送出／進度查詢／同意排珠／AI客服        │  同步／推排珠／推階段／報價／營收分析
   └────────POST────────┐        ┌──────────────┘
                        ▼        ▼
        https://n8n.anwer3712.com/webhook/（cloudflared 隧道）
          ├─ pps-intake  進件：驗token→建單(單號S+日期+序號)→TG通知店長→回單號
          ├─ pps-status  查進度／客戶同意·調整·留言／後台list·update（ADMIN_TOKEN）
          └─ pps-chat    AI客服：守門→精確查表注入→Claude(haiku)→回覆
                        │
                        ▼
        postgres（n8n_postgres 容器）：sales_orders ＋ sales_events
        （n8n 掛掉？前台自動退化「複製訂單→LINE」，AI客服退化本地知識庫，營業不中斷）
```

既有重型管線（WF0–WF4／CP-WF、engine:8000、控制台 PANEL）完全未動，兩線並行。

## 前台功能（任務需求全覆蓋）

最新消息｜本店介紹＋聯絡通道｜成品欣賞（真實作品照＋lightbox）｜**運算方式・數值由來**（F 向量六分量、五派、Cap/Floor/Hamilton、珠數互動計算器、情侶 RV＋橋接＋階段係數表、95 石白名單、底價矩陣全表公開）｜訂製問卷（個人/情侶、即時試算、退化模式）｜**訂單進度查詢**（7 階段時間軸＋排珠提案「同意／要調整」＋留言）｜FAQ｜**AI 客服「小串」**（本地知識庫＋Claude 雙保險、可精確報價）。

## 後台功能

📈 總覽（營收/狀態/型態 SVG 圖表＋待辦焦點）｜📋 訂單（n8n 一鍵同步＋LINE 文字解析建檔＋狀態流 7 段雙向同步）｜🪷 排珠·訊息（提案推送給客戶確認＋客戶回覆佇列＋7 階段 LINE 通知文字產生器）｜🧾 報價（矩陣自動取價→品牌報價單 HTML 列印/PDF→金額同步進度頁）｜🔮 AI 一條龍（載包→組指令→複製貼任何 AI 或直連 API）｜⚙️ 設定（連線測試／明文備份匯出入／PIN 變更／危險區）。

## 安全設計

- **資料最小化**：絕不收出生地（真太陽時一律東經 120°）；生日僅用於運算。
- **前台**：CSP（connect-src 只允許 n8n 網域）、no-referrer、蜜罐欄位＋3 秒計時防機器人、所有動態文字 textContent 防 XSS、欄位長度上限。
- **webhook**：SITE_TOKEN 擋濫發；管理操作獨立 ADMIN_TOKEN（不在任何公開頁面）；進度查詢需「單號＋聯絡方式末四碼」雙因子；payload 大小/長度上限。
- **後台**：PIN → PBKDF2(15 萬輪) → AES-GCM 全庫加密存 localStorage；頁面本身零客戶資料；API 金鑰隨庫加密。
- **AI 客服**：金鑰只存 n8n 憑證（不進瀏覽器）；價格由程式查表、AI 禁止自算；系統提示鎖五類禁詞；聊天不提供匯款帳戶（防詐）。
- **合規**：全站文案過五類禁詞（無療效/財富/改運/保證/玄學物理字眼）；免責＋署名在頁尾與報告。

## 日常流程（每單約 5 分鐘人工）

1. TG 跳新單通知 → 開後台 → 「⇩ 從 n8n 同步」。
2. 🔮 AI 一條龍複製指令 → 貼任何 AI → 得 GEM1。
3. 🪷 把配珠段落貼「排珠·訊息」→ 推送 → 用「階段通知文字」LINE 客戶。
4. 客戶在進度頁按同意（TG 會通知你）→ 🧾 報價一鍵出單 → LINE 報價文字。
5. 客戶匯款 → 訂單列表點狀態推進（自動同步，客戶進度頁即時更新）→ 製作 → 出貨 → 售後。

## 部署・維護

- **改前台/後台**：編輯 HTML → `git add -A && git commit && git push` → Pages 約 30 秒自動更新。
- **改價目**：前台 `index.html` CONFIG.price＋後台 `admin.html` PRICE＋AI 客服 WF『守門組料』ROWS（三處同步改；正典源＝價目表 xlsx）。
- **改 WF**：n8n 介面直接改；或改 `n8n_SALES_suite.json` 後 `docker cp`＋`docker exec n8n n8n import:workflow --input=/tmp/suite.json`＋逐支 `update:workflow --active=true`＋`docker restart n8n`。
- **備份**：後台設定分頁每週匯出 JSON 丟 `backup\`；postgres 資料在 `n8n_postgres` volume。

## 為什麼五年後還能用

| 風險 | 對策 |
|---|---|
| AI 供應商/模型更迭 | 客服模型名寫在 WF 一格就能換；後台一條龍＝複製貼任何聊天 AI，永不過期；直連 API 四供應商可換 |
| 框架/CDN 停更 | 純原生 HTML/CSS/JS，零外部載入 |
| n8n/隧道掛掉 | 前台退化「複製訂單→LINE」；AI 客服退化本地知識庫；營業不中斷 |
| GitHub Pages 出事 | 兩個 HTML 是自含檔案，丟任何靜態空間（或直接傳檔）即可營業 |
| 規則改版 | 命理規則唯一入口＝兩支一條龍包 md；價目三處對照本表改 |
| 資料遺失 | postgres volume＋後台明文 JSON 匯出＋刪單先進垃圾桶 |
| 忘記後台 PIN | 資料解不開＝用備份 JSON 重匯（所以要定期匯出） |

## 回滾

- 網站：`git revert` 或 GitHub 網頁改回舊 commit；整包刪 repo 也不影響本機檔。
- n8n：改動前活體 14 支全量備份在 `D:\ALL-AI\07_ARCHIVE\n8n_live_backup_20260712\`；SALES 三支刪掉即回原狀（不碰既有管線）。
- 業務資料表：`sales_orders`/`sales_events` 為新增表，`DROP TABLE` 即淨空，不影響既有 `orders` 表。
- 舊版 README／一條龍包 v1.0：`07_ARCHIVE\` 對應資料夾。

## 附：全機 n8n Workflow 清單（2026-07-12）

活體 17 支＝既有 14（WF0–4、WF1b、CP-WF1/1b/2/3、控制台×2、報價自動化、教學）＋SALES 新 3 支。
檔案版：個人線 `D:\ALL-AI\skillss\n8n\deploy\`、情侶線 `D:\ALL-AI\skillss\n8n\`、SALES `本資料夾 n8n_SALES_suite.json`、快照 `CLAUDE\n8n-workflows\`。

---
*拍拍深五行水晶設計研究所 · 販售系統 v2.0 · 2026-07-12 由 Claude（Fable 5）設計建置並實測交付*
