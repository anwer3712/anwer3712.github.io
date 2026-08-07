#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-08-06 後台商品「本機殘留」修復 ＋ 通知模板接後台 驗收腳本。

純靜態檢查（regex/substring 掃 admin.html 原始碼 ＋ n8n 匯出 json），
不需要瀏覽器、不需要連 n8n。跟 tests/faq_merge_check.py 的「靜態檢查」那半邊同一種做法。

用法：
    python tests/admin_20260806_check.py
"""
import io
import json
import pathlib
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN = ROOT / "admin.html"
NOTIFYBOSS = ROOT / "_scratch" / "wf-20260806" / "out_notifyboss.json"
# 範圍守衛的比較基準＝「本輪開工前的那個 commit」。
# ⚠ 這個值每開新的一輪就要跟著往前推。留在舊值的話，守衛比較的是好幾輪以前的差異，
#   於是每一輪合法的改動都會被判成「動到範圍外」——一個永遠紅的守衛等於沒有守衛，
#   下一個人只會學會忽略它。2026-08-06 那一輪的基準是 cd2cffc，已合併進 f7405e6。
#   2026-08-07 推到 e9fa481＝隱私政策上站那一輪的開工點（前兩輪 59ceedb／e9fa481 都已上線）。
BASE_COMMIT = "e9fa481"

R = []


def check(name, cond, detail=""):
    R.append((bool(cond), name, str(detail)))


def func_body(src, name):
    """抓 function <name>(...){ ... } 的函式體（用大括號配對，不是正則貪婪切）。"""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*{", src)
    if not m:
        return None
    i = m.end()
    depth = 1
    start = i
    while depth > 0 and i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def main():
    src = ADMIN.read_text(encoding="utf-8")

    # [1] local- 徽章渲染
    check("[1] admin.html 有 local- 徽章渲染（'只在本機' 命中 >=1）",
          src.count("只在本機") >= 1, "命中 %d 次" % src.count("只在本機"))

    # [2] loadProducts 不再整包覆蓋
    lp = func_body(src, "loadProducts")
    check("[2] loadProducts 函式體內含 'local-'", lp is not None and "local-" in lp,
          "" if lp is None else "找到函式體")

    # [3] 補推鈕存在且刪 id 欄
    push = func_body(src, "pushLocalProducts")
    check("[3] pushLocalProducts 函式體內同時有 'delete' 與 'local-'",
          push is not None and "delete" in push and "local-" in push,
          "" if push is None else "找到函式體")
    check("[3] 商品分頁工具列有補推鈕（onclick=\"pushLocalProducts()\"）",
          'onclick="pushLocalProducts()"' in src)

    # [4] queueSettings 送的是 payload:{key,value}（不是整包 settings）。
    #     鍵名在 SETTINGS_PUSH 那張表上，不在函式體裡，所以兩邊分開斷言。
    qs = func_body(src, "queueSettings")
    check("[4] queueSettings 送 payload:{key,value}",
          qs is not None and "payload:{key:k,value:v}" in qs.replace(" ", ""),
          "" if qs is None else "找到函式體")
    check("[4] 送的鍵表含 notify_templates",
          re.search(r"const\s+SETTINGS_PUSH\s*=\s*\{[^;]*?notify_templates\s*:", src, re.S) is not None, "")
    check("[4] 已不再送整包 settings 物件",
          "op:'settings_set',settings:" not in src.replace(" ", ""), "")

    # [5] template_key 取代 template
    tt = func_body(src, "testTpl")
    check("[5] 'template_key' 全檔命中 >=1", src.count("template_key") >= 1,
          "命中 %d 次" % src.count("template_key"))
    tt_clean = (tt or "").replace("template_key", "")
    check("[5] testTpl 函式體內不再有裸的 \"template:'\"（改用 template_key）",
          tt is not None and "template:'" not in tt_clean, "" if tt is None else "找到函式體")

    # [6] 五個模板鍵齊全
    need_keys = ["order_created", "shipped", "birthday", "shop_order_boss", "hitl1_boss"]
    tpl_block_m = re.search(r"templates:\{(.*?)\n\s*\}\},", src, re.S)
    tpl_block = tpl_block_m.group(1) if tpl_block_m else ""
    missing = [k for k in need_keys if (k + ":{") not in tpl_block]
    check("[6] DB.settings.templates 五個鍵齊全", not missing, "缺：%s" % missing if missing else "五鍵都在")

    # [7] 模板欄位用 html；ensureSettingsShape 有 body→html 搬移
    html_hits = tpl_block.count("html:")
    check("[7] 模板預設值裡 'html:' 命中 >=5", html_hits >= 5, "命中 %d 次" % html_hits)
    ess = func_body(src, "ensureSettingsShape")
    check("[7] ensureSettingsShape 有 body→html 一次性搬移",
          ess is not None and "t.body" in ess and "t.html" in ess and "body" in ess and "html" in ess,
          "" if ess is None else "找到函式體")

    # [8] out_notifyboss.json 結構
    nb = None
    try:
        nb = json.loads(NOTIFYBOSS.read_text(encoding="utf-8"))
    except Exception as e:
        check("[8] out_notifyboss.json 可 json.load", False, str(e))
    if nb is not None:
        check("[8] out_notifyboss.json 可 json.load", True)
        nnodes = len(nb.get("nodes", []))
        check("[8] 節點數 > 6", nnodes > 6, "實得 %d" % nnodes)
        names = [n.get("name") for n in nb.get("nodes", [])]
        check("[8] 仍含節點「推LINE老闆」", "推LINE老闆" in names, names)
        raw = NOTIFYBOSS.read_text(encoding="utf-8")
        check("[8] 仍含字面值 chatId '8410048576'", "8410048576" in raw)

        # [9] 套版有 fallback
        code = ""
        for n in nb.get("nodes", []):
            if n.get("name") == "整理通知內容":
                code = n.get("parameters", {}).get("jsCode", "")
        check("[9] 套版程式碼含 'template_key'", "template_key" in code)
        check("[9] 套版程式碼仍含原本的 'tg_text'（fallback 沒被拔掉）", "tg_text" in code)

    # [10] 禁詞掃描 admin.html ＝ 26（基線，見 faq_merge_check.py 的 BASELINE_BAN）
    out = subprocess.run(
        [sys.executable, str(ROOT / "docs/p4_kit/scan_compliance.py"), "admin.html"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        env={"PYTHONIOENCODING": "utf-8"})
    m = re.search(r"共 (\d+) 處命中", out.stdout or "")
    n_hits = int(m.group(1)) if m else -1
    check("[10] 禁詞掃描 admin.html ＝ 26（基線）", n_hits == 26, "實得 %d" % n_hits)

    # ── 複驗時補的兩條（2026-08-06 主線審過線 B 的產出後加）─────────────
    # [12] queueSettings 必須逐鍵送，且每個 caller 只送自己編輯的那個鍵。
    #      這一頁從來沒呼叫過 settings_get（DB.settings 純本機），
    #      「每次全推」會讓一台 localStorage 是預設值的電腦把雲端真設定整組蓋掉。
    check("[12] admin.html 沒有任何讀回設定的呼叫（逐鍵送的前提）",
          "op:'settings_get'" not in src and 'op:"settings_get"' not in src,
          "有的話這條假設要重新評估")
    check("[12] queueSettings 收具名的鍵（不是無參數全推）",
          re.search(r"function\s+queueSettings\s*\(\s*\.\.\.\s*keys\s*\)", src) is not None, "")
    callers = {
        "saveLowThresh": "low_stock_threshold",
        "savePayAccounts": "payment_accounts",
        "saveTpl": "notify_templates",
    }
    for fn, key in callers.items():
        body = func_body(src, fn) or ""
        check("[12] %s() 只推 %s" % (fn, key),
              ("queueSettings('%s')" % key) in body, body[-90:] if body else "找不到函式體")
    sv = func_body(src, "saveSettings") or ""
    check("[12] saveSettings() 推金流／追蹤三鍵",
          "queueSettings('ecpay','ga4_id','meta_pixel_id')" in sv, sv[-90:] if sv else "找不到函式體")
    check("[12] 沒有殘留的無參數 queueSettings() 呼叫",
          not re.search(r"queueSettings\(\s*\)", src), "")

    # [13] 真正的寄信路徑（出貨通知）也要走 template_key。
    #      只修 testTpl 的話，測試信是對的、實際寄給客戶的那封還是空的。
    check("[13] 出貨通知走 template_key",
          "template_key:'shipped'" in src and "template:'shipped'" not in src, "")

    # [11] git diff --stat 只動 admin.html + tests/ + _scratch/
    # -c core.quotepath=false：預設 git 會把非 ASCII 路徑印成 "docs/\351\232\261..."
    # （帶引號＋八進位跳脫），於是 startswith("docs/") 永遠比不到，中文檔名一律被誤判成範圍外。
    diff = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--stat", BASE_COMMIT],
                           cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    changed = []
    for line in (diff.stdout or "").splitlines():
        m2 = re.match(r"\s*(\S.*?)\s+\|\s+\d+", line)
        if m2:
            changed.append(m2.group(1).strip())
    # 這條原本是工單的範圍守衛（線 B 只准動 admin.html）。線 A（index.html 那三項）
    # 併進來之後，允許清單擴成「本輪兩條線授權的檔案聯集」——
    # 守的仍然是同一件事：這一輪不該有任何其他檔案被順手改到。
    # 2026-08-07 加 scripts/：交接卡 H 的裁決是「提交」——
    # scripts/photo_publish.py 的 DB 同步按鈕本來就在 working tree 裡等著進版控，
    # 它是這一輪授權範圍的一部分，不是被順手改到的。
    # 2026-08-07 隱私政策上站這一輪授權的範圍：index.html（#privacy 分頁＋頁尾連結）、
    # sitemap.xml（多一條 #privacy）、faq.json（生日資料安全那題改指向政策）、
    # docs/（政策定稿與根據對照表）。FAQ 那題同一句話在 tests/ 的基準檔也要跟著改，
    # tests/ 本來就在允許清單裡。
    ALLOWED_FILES = {"admin.html", "index.html", "sitemap.xml", "faq.json"}
    ALLOWED_DIRS = ("tests/", "_scratch/", "photos/brand/", "scripts/", "docs/")
    bad = [f for f in changed if f not in ALLOWED_FILES and not f.startswith(ALLOWED_DIRS)]
    check("[11] git diff --stat 只動本輪授權的檔",
          not bad, "動到範圍外的檔：%s（清單：%s）" % (bad, changed) if bad else ("動到：%s" % changed))

    for ok, name, detail in R:
        print(("  ✔ " if ok else "  ✘ ") + name + (("   … " + detail) if detail else ""))
    bad_r = [r for r in R if not r[0]]
    print("\n%d/%d 通過" % (len(R) - len(bad_r), len(R)) + ("" if not bad_r else "，%d 失敗" % len(bad_r)))
    sys.exit(1 if bad_r else 0)


if __name__ == "__main__":
    main()
