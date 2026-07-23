# P4 端到端驗收清單（逐項打勾版）

> 展開自 `D:\ALL-AI\06_MEMORY\水晶手串改版總規劃_20260717.md` §二 P4 五條。
> 測試資料＝本 kit `payloads/` 三份 JSON；模擬按鈕方法見 `resume_click.md`；文案合規掃描用 `scan_compliance.py`。
> 全部打勾＝P4 過；任何一項卡住 → 記到驗收報告、停手回報，勿自行改規格。

## 0. 前置

- [ ] n8n 活庫已備份到 `07_ARCHIVE\n8n_live_backup_20260717\`（回滾點存在才開測）。
    怎麼驗：`ls D:\ALL-AI\07_ARCHIVE\n8n_live_backup_20260717\`，17+ 支 JSON。
- [ ] 引擎容器活著：`docker exec n8n wget -qO- http://engine:8000/docs`（或任一 endpoint）回 200。

## 1. 引擎測試全綠（P4-1）

- [ ] golden 288 全過。怎麼驗：引擎 repo（`C:\Users\User\skillss\engine`）跑測試套件，看 288 pass。
- [ ] 12 e2e 全過。同上套件。
- [ ] E1 新不變量測試綠：錦囊晶石 ∩ 主方案晶石 ＝ ∅；三軌各自 Hamilton 誤差 ≤0.05。
- [ ] E2 測試綠：alternatives 每石 3 替代、同主五行、無重複。
- [ ] （抽查）`/compute` 用 `payloads/single_1track.json` 的王小明生辰打一發，
    四柱應為 壬申/戊申/癸亥/己未、癸水日主身強、用神 土木火（2026-07-17 盤點實測基準）。

## 2. 個人 1 條全鏈（P4-2，payload＝single_1track.json）

- [ ] **進件**：POST `/n8n-go-home`（經前台表單或直接 curl payload）→ 回 `{ok:true, order_id}`。
    看哪裡：webhook response＋postgres `orders` 表新 row `status=pending_review`。
- [ ] **TG 通知**：老闆 TG（chat 8410048576）收到新單待審。
- [ ] **HITL1 信四表齊**：Gmail「[HITL1] 新單待審」含
    ①客戶資料區 12 欄（姓名/性別/生日＋時辰/珠徑/手圍/核心功能/痛點/視覺體感/訂製數量/物流/聯絡/加購）
    ②命盤自檢（四柱/身強弱/五行%/用神/不變量）
    ③主方案排珠表＋主方案替代表 ④錦囊排珠表＋錦囊替代表。
    三顆鈕：✅確認排珠／✏️調整配置／❌退回。
- [ ] **WF1c 升級表單**：點 ✅確認排珠 → 開 n8n Form；單選【不推薦/150/300】＋10 上傳格＋理由欄。
    測試選 300＋傳 6 張照片＋填理由 → 提交。
    看哪裡：Google Drive 訂單資料夾出現 6 檔（anyone-reader）；DB 單一 jsonb 寫入 links＋選項；WF1 wait 被 resume（execution 續跑）。
- [ ] **預審信（N5）**：/report 過 DEEP 後老闆收到預審信（渲染好的客戶報價信 HTML）＋✅寄發/❌退回 兩鈕。
- [ ] **客戶信六段順序（N6）**：點 ✅寄發 → 客戶信到，順序＝
    §1 生辰複述→命格→特質→流年困境（liunian_desc）→人生主題建議
    §2 主方案配置表（晶石/五行/理由）
    §3 主方案概略價→錦囊前言（「輔助手串」新文案；禁「小巧精緻隨身錦囊」字樣）
    §4 組合價 ①vs②（訂1條階梯）
    §5 升級推薦區（300＋照片對比＋理由——本案有推薦所以必須出現）
    §6 行動鈕。
    怎麼驗：把信 HTML 存檔跑 `python scan_compliance.py 該檔` → 0 命中。
- [ ] **confirm 頁階梯價**：信內鈕 → confirm.html 帶 token → 顯示 ①主方案 699／②主+錦囊 1398（16cm×8mm）＋升級 +300 選項；選②＋升級 → 總計 NT$1,698。
- [ ] **收款**：confirm 送出 → resume `?confirm=true&plan=2&upgrade=true` → 老闆收「待確認收款」信 → 點 ✅已收款。
    看哪裡：DB status → confirmed。
- [ ] **出貨明細（N8）**：WF3 建檔→Slides 生成→點 📦已出貨 → 客戶出貨信**含排珠明細表**；總價含升級 300。
- [ ] **30 天分支**：WF4 wait 節點存在且 IF 情侶判斷走「否」→ 個人版關懷信模板。
    怎麼驗：看 execution 圖走向即可，不用真等 30 天（或暫調 wait 時間）。

## 3. 個人 2 條差異點（P4-3，payload＝single_2track.json）

- [ ] 進件 qty=2 → 引擎收到 tracks=B（2 條）。看哪裡：WF1『欄位對應』出口 JSON。
- [ ] 報價信 §4 呈現 **②雙條 vs ③完整三條**（不是①vs②）；③文案含本源重置（夜間睡前/靜心、最柔晶石）。
- [ ] 價格：②=底價×2=1398、③=底價×3=2097（16cm×8mm 底價 699）。
- [ ] 三條晶石互不重複（引擎 E1 不變量，信面上抽查一次）。

## 4. 情侶鏈鏡像（P4-4，payload＝couple.json）

- [ ] POST `/couple-intake` → CP-WF1 跑雙 /compute＋融合排珠。
- [ ] **TG 通知有**（修 bug4：CP 版本補 TG＋resume_url）。
- [ ] HITL1 信雙盤＋融合；✅確認排珠 → CP 版升級表單 **20 格**（標「第 n 組 升級前/後」）。
- [ ] 客戶信：雙串報價、**無**錦囊/本源推銷段（§3-4 加購梯不出現）、升級推薦區保留。
- [ ] 出貨走 `/ship` 併回 WF4，`is_couple:true` → 30 天走情侶關懷分支。
- [ ] 信件 HTML 跑 scan_compliance.py → 0 命中。

## 5. 三條負向路徑（P4-5）

- [ ] **想討論**：confirm 頁（或信內鈕）`confirm=feedback` → 老闆收 NOTIFY_BOSS「客戶想討論」通知，流程**不進收款**（修 bug1）。看哪裡：execution IF 分支＋老闆信/TG。
- [ ] **❌退回**：HITL1 信點 ❌ → `?approve=false` → DB status=rejected，流程停（修 bug2；rejected 分支第一次真的走得到）。
- [ ] **預審退回**：預審信點 ❌ → 回 WF1b 調整表單連結（裁決6），WF1 殭屍 wait 有被 resume 清掉（修 bug3）。

## 6. 收尾

- [ ] 三頁前台（index/confirm/admin）＋所有新信件模板全數過 `scan_compliance.py`（基準見驗收報告）。
- [ ] 驗收報告寫入交接卡／SHARED_MEMORY（由 Fable 收工，worker 不碰封聖層）。
