#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流年入文案驗收（2026-08-03）。

對應工單驗收表：
  2  涵蓋   全站「講運算」的地方都提到流年
  3  禁詞   scan_compliance.py 命中 ≤ 基線 5，新增 0
  4  一致性 個人線與情侶線講法不衝突（同一組數字：0.12、調候模式仍 0.12）
  5  溢出   1280 與 375 兩個寬度零水平溢出

另加一項工單沒寫但非驗不可的：FAQ 陣列的寫死索引。客服快答用 FAQ[5][8][9][11]
[13][15][19][20][21][22][1][4]，新題插在中間會全部錯位（陣列末尾有註解警告）。

用法：python tests/liunian_copy_check.py [--headed]
"""
import argparse
import functools
import http.server
import os
import pathlib
import re
import socketserver
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8733
BASELINE = {"index.html": 5, "config.js": 0}   # 動工前實測（2026-08-03）

FAILS = []

# 客服快答寫死的索引 → 該位置應該是哪一題
PINNED = {
    1: "跟市面上的水晶手串差在哪？", 4: "戴了會帶來好運、帶來財富、擋掉身邊的麻煩人嗎？",
    5: "價格怎麼算？", 8: "珠徑跟顆數怎麼決定？", 9: "下單到收到要多久？",
    11: "可以幫家人或朋友訂嗎？", 13: "我的生日資料安全嗎？", 15: "不知道出生時辰可以訂嗎？",
    19: "可以退換貨嗎？", 20: "設計可以修改嗎？", 21: "怎麼付款？",
    22: "情侶對串跟買兩條個人款差在哪？",
}

# 「講運算」的地方 → 那一段必須出現的流年字樣
COVERAGE = [
    ("需求向量六分量說明", "「流年」占 0.12"),
    ("調候動態切換：流年不隨之起伏", "流年那一格在兩種模式下都是 0.12"),
    ("五派表：流年有第二個入口", "流年在整套運算裡出現兩次"),
    ("情侶雙人融合：流年先於合成", "流年是在合成之前、各自那一步就先算完的"),
    ("確定論運算卡", "當年的流年也算一項輸入"),
    ("FAQ 專題", "「流年」是什麼？它在你們的運算裡做什麼？"),
    ("FAQ 情侶對串", "兩人的基準盤各自先被當年的流年推過一輪"),
    ("FAQ 生日資料（唯一輸入源那句要改掉）", "另一個輸入是你下單當年的年份"),
    ("客服快答", "'流年','當年','年份','太歲'"),
]


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — %s" % detail) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def static_checks():
    print("\n[靜態] 涵蓋 ＋ 禁詞 ＋ FAQ 索引")
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    cfg = (ROOT / "config.js").read_text(encoding="utf-8")

    for label, needle in COVERAGE:
        check("涵蓋：%s" % label, needle in src, "" if needle in src else "找不到 %r" % needle)
    check("涵蓋：核心功能『全面校準』說明", "流年" in cfg,
          [l.strip()[:40] for l in cfg.splitlines() if "流年" in l][:1])

    # 個人線與情侶線用的是同一組數字，不能各講各的
    check("一致性：0.12 只有一個版本",
          src.count("流年那一格在兩種模式下都是 0.12") == 1 and "流年仍是 0.12" in src)

    # FAQ 寫死索引
    blk = src[src.index("const FAQ = ["):]
    qs = [m.group(1) for m in re.finditer(r"\{g:'.*?',q:'(.*?)'", blk)]
    for i, expect in PINNED.items():
        got = qs[i] if i < len(qs) else "(超出範圍)"
        check("FAQ[%d] 仍是「%s」" % (i, expect[:12]), got == expect, got)
    check("流年題 append 在陣列尾端", qs and "流年" in qs[-1], qs[-1] if qs else "")

    for f, base in BASELINE.items():
        out = subprocess.run([sys.executable, str(ROOT / "docs/p4_kit/scan_compliance.py"), f],
                             cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        n = re.search(r"共 (\d+) 處命中", out.stdout or "")
        n = int(n.group(1)) if n else -1
        check("禁詞 %s ≤ 基線 %d" % (f, base), n == base, "實得 %d" % n)


def live_checks(headed):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n[瀏覽器] SKIP：沒有 playwright")
        return
    print("\n[瀏覽器] 渲染 ＋ 客服快答 ＋ 溢出")
    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=not headed)
            pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/index.html#faq" % PORT)
            pg.wait_for_selector("#faqWrap details.acc", timeout=15000)
            check("頁面沒有 JS 例外", not errs, errs[:2])

            # 流年題真的渲染進 FAQ 手風琴（而不是只躺在陣列裡）
            hit = pg.locator("details.acc summary", has_text="流年").count()
            check("FAQ 手風琴出現流年題", hit >= 1, hit)

            # 客服快答：問「流年」要回到流年那題
            ans = pg.evaluate("() => (typeof localBrain==='function') ? localBrain('流年是什麼') : null")
            check("客服快答 命中流年題", bool(ans) and "0.12" in ans, (ans or "")[:40])

            # 運算原理區看得到（關於我們分頁）
            pg.goto("http://127.0.0.1:%d/index.html#about" % PORT)
            pg.wait_for_selector(".transp", timeout=15000)
            txt = pg.locator(".transp").inner_text()
            check("運算原理區可見流年說明", "流年" in txt and "0.12" in txt)

            for w, h in ((1280, 900), (375, 812)):
                pg.set_viewport_size({"width": w, "height": h})
                pg.wait_for_timeout(400)
                over = pg.evaluate(
                    "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                check("寬 %d 零水平溢出" % w, over <= 0, "溢出 %spx" % over)
            br.close()
    finally:
        srv.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    static_checks()
    live_checks(a.headed)
    print("\n%s（%d 項失敗）" % ("全部通過" if not FAILS else "有失敗項", len(FAILS)))
    for f in FAILS:
        print("  - %s" % f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
