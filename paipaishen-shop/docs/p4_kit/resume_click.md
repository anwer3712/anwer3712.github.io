# 模擬點信按鈕（resume webhook）操作手冊

> P4 驗收時不必真收信真點鈕——直接對該筆 execution 的 resumeUrl 發 GET/POST 即可。
> 按鈕表抄自 `水晶手串n8n流程盤點與錦囊討論_20260717.md` §二（已驗），新按鈕標【新】＝本次改版新增，實際參數以 P2 匯入後的 workflow 為準。

## 1. 撈 resumeUrl

n8n 的 `wait`（resume=webhook）節點，每筆 execution 有專屬 resume 網址，格式：

```
https://n8n.anwer3712.com/webhook-waiting/{executionId}
```

三種拿法（擇一）：

1. **DB 直撈（個人 WF1 有存）**：WF1 進件時把 `$execution.resumeUrl` 寫進 orders 表（節點「存 resume_url」）。
   ```
   docker exec n8n_postgres psql -U n8n -d n8n -c "SELECT order_no, resume_url FROM orders ORDER BY created_at DESC LIMIT 5;"
   ```
   （欄位名以實際 schema 為準；CP-WF1 本次改版後也會存——修 bug4。）
2. **n8n UI**：Executions → 找該筆 waiting 的執行 → 網址列的 executionId → 拼上面格式。
3. **信件原始碼**：老闆信裡按鈕 href 就是完整 resumeUrl＋query，直接複製。

## 2. 按鈕 × query 參數對照表

| 信 / 頁面 | 按鈕 | 請求 |
|---|---|---|
| WF1/CP-WF1 老闆審核信 | ✅確認排珠 | 舊：`GET {resumeUrl}?approve=true`。改版後【新】：改為開 WF1c 升級表單，表單提交後由 WF1c resume（approve=true＋upgrade payload），驗收時直接填表單模擬 |
| WF1/CP-WF1 老闆審核信 | ✏️調整配置 | `https://n8n.anwer3712.com/form/wf1-adjust`（開 WF1b 表單，非 resume；CP 版 form 路徑另查） |
| WF1/CP-WF1 老闆審核信 | ❌退回【新】 | `GET {resumeUrl}?approve=false` → DB rejected，流程停 |
| 預審信（N5）【新】 | ✅寄發 | `GET {resumeUrl}?preview=ok`（參數名以 P2 實作為準，可能是 approve=true——匯入後看 IF 節點條件） |
| 預審信（N5）【新】 | ❌退回調整 | 信內附 WF1b 表單連結；wait 的否定 resume 參數以 P2 實作為準 |
| WF2 客戶報價信 | 👉我要下單 | 舊：`GET {resumeUrl}?confirm=true&plan=main`。改版後【新】：鈕連到 confirm.html?token=...，由確認頁 POST resume：`?confirm=true&plan={1|2|3}&upgrade={true|false}` |
| WF2 客戶報價信／confirm 頁 | 💬想討論 | `GET {resumeUrl}?confirm=feedback` → 【新】IF 判斷後 NOTIFY_BOSS「客戶想討論」，不進收款 |
| WF2 收款信 | ✅已收款 | `GET {resumeUrl}?paid=true` |
| WF3 待出貨信 | 📦已出貨 | `GET {resumeUrl}`（無參數） |

## 3. 指令範例

```bash
# 模擬老闆點「❌退回」
curl -s "https://n8n.anwer3712.com/webhook-waiting/{executionId}?approve=false"

# 模擬客戶在 confirm 頁選 ②＋要升級（POST 版，鍵名以 P2 契約為準）
curl -s -X POST "https://n8n.anwer3712.com/webhook-waiting/{executionId}?confirm=true&plan=2&upgrade=true"

# 模擬「想討論」
curl -s "https://n8n.anwer3712.com/webhook-waiting/{executionId}?confirm=feedback"
```

驗完每一發都去看：①該 execution 是否 resume 續跑（n8n UI）②IF 分支走向 ③DB status 變化。

## 4. 陷阱備忘

- resumeUrl **一次性**：resume 過的 execution 再打會 404，要重新進件產生新單。
- WF1b 觸發（✏️調整路線）改版後會順手 resume 掉 WF1 的 wait（修 bug3）——驗負向路徑時注意別把殭屍清理誤判成流程錯誤。
- wait 節點若設了 timeout，過期的 execution 也 resume 不了。
