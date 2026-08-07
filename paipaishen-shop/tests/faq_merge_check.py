#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""官網 FAQ 與後台 FAQ 合併驗收（2026-08-05）。

合併後官網 FAQ 的真值是同源靜態檔 faq.json（後台編輯器存出、使用者 push），
index.html 裡那份陣列退居 fail-safe：faq.json 404／壞掉時照樣把 FAQ 區渲染完整。

這支釘的是三件事：
  1  faq.json 載入成功時題數與內建那份對得上，且每一題都渲染進手風琴
  2  faq.json 取不到時降級生效（FAQ 區不得空白、不得有未捕捉例外）
  3  客服快答那 12 條原本寫死索引的問句，回答與合併前逐字相同

第 3 點的基準檔是 tests/faq_localbrain_baseline.json，
在動工前於 origin/main（6a685cb）跑 --dump 產出，之後只讀不寫。

用法：
  python tests/faq_merge_check.py            # 跑驗收
  python tests/faq_merge_check.py --dump     # 重產基準檔（只有刻意要改答案時才跑）
  python tests/faq_merge_check.py --headed   # 開著瀏覽器看
"""
import argparse
import functools
import http.server
import json
import os
import pathlib
import re
import shutil
import socketserver
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_FILE = pathlib.Path(__file__).resolve().parent / "faq_localbrain_baseline.json"
PORT = 8735
BASELINE_BAN = {"index.html": 5, "config.js": 0, "admin.html": 26}   # 動工前實測（2026-08-05）

FAILS = []

# 合併前寫死的索引 → 一句會走到那條規則的問句。
# 問句要挑不會先被上面幾條規則攔走的，順序即 localBrain 的比對順序。
PROBES = [
    ("FAQ[5]  價格怎麼算",       "價格怎麼算"),
    ("FAQ[9]  下單到收到要多久",  "要多久才會拿到"),
    ("FAQ[21] 怎麼付款",         "怎麼付款"),
    ("FAQ[8]  珠徑跟顆數",       "珠徑怎麼選"),
    ("FAQ[11] 幫家人朋友訂",     "可以幫朋友訂嗎"),
    ("FAQ[15] 不知道出生時辰",   "不知道時辰"),
    ("FAQ[13] 生日資料安全",     "個資會不會外洩"),
    ("FAQ[20] 設計可以修改",     "設計可以改嗎"),
    ("FAQ[9]+ 訂單進度（帶後綴）", "查進度"),
    ("FAQ[1]  跟市面上差在哪",    "用什麼水晶"),
    ("FAQ[22] 情侶對串",         "情侶對串"),
    ("FAQ[19] 可以退換貨",       "可以退嗎"),
    ("FAQ[4]  戴了會帶來好運",    "會帶來好運嗎"),
    ("FAQ[末] 流年",             "流年是什麼"),
]


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — %s" % detail) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Reusable(socketserver.TCPServer):
    allow_reuse_address = True          # 要在 bind 之前就成立，實例化之後才設是來不及的


def serve(directory, port=PORT):
    handler = functools.partial(Quiet, directory=str(directory))
    srv = Reusable(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def probe_answers(pg):
    """把 14 條問句餵給 localBrain，回一份 {標籤: 回答}。"""
    out = {}
    for label, q in PROBES:
        out[label] = pg.evaluate(
            "q => (typeof localBrain==='function') ? localBrain(q) : null", q)
    return out


def dump(headed):
    from playwright.sync_api import sync_playwright
    srv = serve(ROOT)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=not headed)
            pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            pg.goto("http://127.0.0.1:%d/index.html#faq" % PORT)
            pg.wait_for_selector("#faqWrap details.acc", timeout=15000)
            ans = probe_answers(pg)
            br.close()
    finally:
        srv.shutdown()
    missing = [k for k, v in ans.items() if not v]
    if missing:
        print("✗ 這幾條問句沒有命中任何規則，基準檔不產：%s" % missing)
        sys.exit(1)
    BASE_FILE.write_text(json.dumps(ans, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✔ 已寫出基準檔 %s（%d 條）" % (BASE_FILE.name, len(ans)))


def static_checks():
    print("\n[靜態] faq.json 結構 ＋ 禁詞")
    src = (ROOT / "index.html").read_text(encoding="utf-8")

    # 內建那份（fail-safe 用）：每一題都要有穩定鍵，且鍵不重複
    blk = src[src.index("const FAQ_BUILTIN = ["):]
    keys = re.findall(r"\{k:'([^']+)'", blk[:blk.index("\n];")])
    check("內建 FAQ 每題都有穩定鍵 k", len(keys) == 31, "%d 題" % len(keys))
    check("穩定鍵沒有重複", len(set(keys)) == len(keys),
          [k for k in keys if keys.count(k) > 1])

    # 客服快答不准再出現寫死索引
    brain = src[src.index("function localBrain("):]
    brain = brain[:brain.index("\n}")]
    hard = re.findall(r"FAQ\[\d+\]", brain)
    check("客服快答已無寫死索引", not hard, hard)

    fj = json.loads((ROOT / "faq.json").read_text(encoding="utf-8"))
    check("faq.json 是陣列", isinstance(fj, list))
    check("faq.json 題數＝內建題數", len(fj) == len(keys), "%d vs %d" % (len(fj), len(keys)))
    # 欄名照 pps2_faq 的 schema（sql/pps2_schema.sql），另兩欄是 DB 沒有的前台欄位
    cols = {"category", "question", "answer", "sort_order", "status", "key", "answer_html"}
    bad = [r.get("key") for r in fj if set(r) - cols]
    check("faq.json 欄名全在允許集合內", not bad, bad)
    check("faq.json 的 key 與內建那份一一對上",
          [r["key"] for r in fj] == keys,
          [a for a, b in zip([r.get("key") for r in fj], keys) if a != b][:3])

    for f, base in BASELINE_BAN.items():
        out = subprocess.run([sys.executable, str(ROOT / "docs/p4_kit/scan_compliance.py"), f],
                             cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        n = re.search(r"共 (\d+) 處命中", out.stdout or "")
        n = int(n.group(1)) if n else -1
        check("禁詞 %s ＝基線 %d" % (f, base), n == base, "實得 %d" % n)
    # faq.json 是新增的公開檔，一起掃。基線 2 都是「置信度 100%／70%」那一題帶來的，
    # 跟 index.html:2383 那兩處同一句話（faq.json 是那份內容的鏡像，所以命中會跟著複製一份）。
    # 這兩處在 index.html 早就是既有基線的一部分，不是這次新增的說法。
    out = subprocess.run([sys.executable, str(ROOT / "docs/p4_kit/scan_compliance.py"), "faq.json"],
                         cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    n = re.search(r"共 (\d+) 處命中", out.stdout or "")
    n = int(n.group(1)) if n else -1
    check("禁詞 faq.json ＝基線 2（置信度那題的鏡像）", n == 2, "實得 %d" % n)


def live_checks(headed):
    from playwright.sync_api import sync_playwright
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))

    # 降級測試要在一份「沒有 faq.json」的複本上跑，不動工作目錄
    fallback_dir = ROOT / "_scratch" / "faq_no_json"
    if fallback_dir.exists():
        shutil.rmtree(fallback_dir)
    fallback_dir.mkdir(parents=True)
    for name in ("index.html", "config.js"):
        shutil.copy2(ROOT / name, fallback_dir / name)

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=not headed)

        # ── 1) 正常：讀得到 faq.json ──
        print("\n[瀏覽器] faq.json 載入成功")
        srv = serve(ROOT)
        try:
            pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/index.html#faq" % PORT)
            pg.wait_for_selector("#faqWrap details.acc", timeout=15000)
            pg.wait_for_timeout(600)                       # 等 faq.json 那次 fetch 重畫完
            n_live = pg.locator("#faqWrap details.acc").count()
            n_json = len(json.loads((ROOT / "faq.json").read_text(encoding="utf-8")))
            check("頁面沒有 JS 例外", not errs, errs[:2])
            check("手風琴題數＝faq.json 題數", n_live == n_json, "%d vs %d" % (n_live, n_json))
            check("FAQ 真的來自 faq.json（不是內建）",
                  pg.evaluate("() => window.__FAQ_SRC__") == "faq.json",
                  pg.evaluate("() => window.__FAQ_SRC__"))
            check("JSON-LD FAQPage 只有一份",
                  pg.evaluate("() => [...document.querySelectorAll('script[type=\"application/ld+json\"]')]"
                              ".filter(s=>s.textContent.includes('FAQPage')).length") == 1)

            print("\n[瀏覽器] 客服快答逐字回歸（12 條寫死索引 ＋ 進度後綴 ＋ 流年）")
            now = probe_answers(pg)
            for label, _ in PROBES:
                check("逐字相同：%s" % label, now[label] == base[label],
                      "" if now[label] == base[label] else "改前 %r／改後 %r"
                      % ((base[label] or "")[:28], (now[label] or "")[:28]))

            print("\n[瀏覽器] 溢出")
            for w, h in ((1280, 900), (375, 812)):
                pg.set_viewport_size({"width": w, "height": h})
                pg.wait_for_timeout(400)
                over = pg.evaluate(
                    "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                check("寬 %d 零水平溢出" % w, over <= 0, "溢出 %spx" % over)
                # FAQ 裡的表格自己捲，不准把頁面撐開
                tbl = pg.evaluate(
                    "() => Math.max(0,...[...document.querySelectorAll('#faqWrap .mt-wrap')]"
                    ".map(e=>e.scrollWidth-e.clientWidth>0?0:0), 0)")
                check("寬 %d FAQ 表格未撐破版面" % w, tbl == 0, tbl)
            pg.close()
        finally:
            srv.shutdown()

        # ── 2) 降級：faq.json 404 ──
        print("\n[瀏覽器] faq.json 404 降級")
        srv = serve(fallback_dir, PORT + 1)
        try:
            pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            r404 = []
            pg.on("response", lambda r: r404.append(r.status) if r.url.endswith("faq.json") else None)
            pg.goto("http://127.0.0.1:%d/index.html#faq" % (PORT + 1))
            pg.wait_for_selector("#faqWrap details.acc", timeout=15000)
            pg.wait_for_timeout(600)
            check("faq.json 真的是 404", 404 in r404, r404)
            n_fb = pg.locator("#faqWrap details.acc").count()
            check("降級後 FAQ 區仍完整（31 題）", n_fb == 31, n_fb)
            check("降級時 console 無未捕捉例外", not errs, errs[:2])
            check("降級來源標記＝builtin",
                  pg.evaluate("() => window.__FAQ_SRC__") == "builtin",
                  pg.evaluate("() => window.__FAQ_SRC__"))
            fb = probe_answers(pg)
            same = [l for l, _ in PROBES if fb[l] != base[l]]
            check("降級時客服快答仍逐字相同", not same, same)
            pg.close()
        finally:
            srv.shutdown()
        br.close()
    shutil.rmtree(fallback_dir, ignore_errors=True)


def admin_roundtrip(headed):
    """端到端：後台改一題 → 存成 faq.json → 官網顯示更新。

    存出的檔案落到一份臨時站台目錄，不動工作目錄裡那份 faq.json。
    """
    from playwright.sync_api import sync_playwright
    print("\n[瀏覽器] 後台改一題 → 匯出 → 官網顯示更新")
    site = ROOT / "_scratch" / "faq_roundtrip"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for name in ("index.html", "config.js"):
        shutil.copy2(ROOT / name, site / name)

    NEW = "【端到端測試改過的答案】底價看手圍乘珠徑查矩陣。"
    srv = serve(ROOT)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=not headed)
            ctx = br.new_context(viewport={"width": 1280, "height": 900},
                                 accept_downloads=True)
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/admin.html" % PORT)

            # 首次啟用：本機建 owner 帳號（後台本來就能離線用，這一段不碰雲端）
            pg.wait_for_selector("#setPin1", timeout=15000)
            pg.fill("#setPin1", "1234")
            pg.fill("#setPin2", "1234")
            pg.click("text=建立後台")
            pg.wait_for_selector("#nav button", timeout=15000)

            pg.evaluate("() => switchTab('notify')")          # FAQ 管理住在「通知客服」分頁
            pg.wait_for_selector("#faqTbl tr:nth-child(7)", timeout=15000)
            rows = pg.locator("#faqTbl tr").count() - 1
            check("後台讀到 faq.json", rows == 31, "%d 題" % rows)

            # 第 6 題＝pricing（價格怎麼算），改它的純文字答案
            pg.locator("#faqTbl tr").nth(6).get_by_text("編輯").click()
            pg.wait_for_selector("#f_a", timeout=5000)
            check("編輯的是 pricing 那題",
                  pg.input_value("#f_k") == "pricing", pg.input_value("#f_k"))
            pg.fill("#f_a", NEW)
            pg.fill("#f_h", "")                               # 表格版清掉，官網才會顯示純文字這版
            pg.click("#modalF .gold")

            # 2026-08-07 起「存成／讀回 faq.json」改成離線備援，收在 <details> 裡（預設收合）。
            # 主要路徑改成「☁ 發布到官網」（寫 pps2_settings.site_faq）——那條要連 n8n，
            # 不在這支離線端到端測試的範圍，所以這裡仍然驗存檔那條路：它是 n8n 掛掉時的退路，
            # 退路壞了不會有人發現，正是最需要被測的東西。收合的 <details> 裡的按鈕
            # Playwright 判定為 not visible，要先把它展開。
            pg.evaluate("""()=>{const b=[...document.querySelectorAll('#sec-faq details')]
                .find(d=>d.textContent.includes('faq.json')); if(b) b.open=true;}""")
            with pg.expect_download() as dl:
                pg.click('#sec-faq button:has-text("存成 faq.json")')   # 說明文字裡也有這串，要指名按鈕
            path = dl.value
            check("存出的檔名是 faq.json", path.suggested_filename == "faq.json",
                  path.suggested_filename)
            path.save_as(str(site / "faq.json"))
            check("後台這一段沒有 JS 例外", not errs, errs[:2])
            ctx.close()

            exported = json.loads((site / "faq.json").read_text(encoding="utf-8"))
            check("匯出的仍是 31 題", len(exported) == 31, len(exported))
            check("匯出的 sort_order 重編成 0..n",
                  [r["sort_order"] for r in exported] == list(range(len(exported))))
            br.close()
    finally:
        srv.shutdown()

    srv = serve(site, PORT + 2)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=not headed)
            pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/index.html#faq" % (PORT + 2))
            pg.wait_for_selector("#faqWrap details.acc", timeout=15000)
            pg.wait_for_timeout(600)
            # 手風琴沒展開時 inner_text 讀不到答案，要走 textContent
            body = pg.evaluate("() => document.getElementById('faqWrap').textContent")
            check("官網 FAQ 出現後台改過的那句", NEW in body,
                  "找不到" if NEW not in body else "")
            check("官網題數仍是 31", pg.locator("#faqWrap details.acc").count() == 31,
                  pg.locator("#faqWrap details.acc").count())
            ans = pg.evaluate("() => localBrain('價格怎麼算')")
            check("客服快答也跟著換成新答案（靠鍵找得到）", ans == NEW, (ans or "")[:30])
            check("官網這一段沒有 JS 例外", not errs, errs[:2])
            br.close()
    finally:
        srv.shutdown()
    shutil.rmtree(site, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="重產客服快答基準檔")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    if a.dump:
        dump(a.headed)
        return
    static_checks()
    live_checks(a.headed)
    admin_roundtrip(a.headed)
    print("\n%s（%d 項失敗）" % ("全部通過" if not FAILS else "有失敗項", len(FAILS)))
    for f in FAILS:
        print("  - %s" % f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
