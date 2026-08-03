#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""後台商品表單 ＋ 前台商品卡驗收（2026-08-03 商品管理修復）。

對應工單驗收表：
  1  下拉欄位      每一個 select 都有選項（不只「（請選擇）」）
  3  size_cm/bead_mm 表單補上
  4  多圖          後台清單 3 張、前台商品卡與 modal 3 張
  5  拖曳排序／刪單張 實測可用
  6  兩個新欄位    線材、配飾材質 後台可選、前台顯示

用法：
    python tests/products_ui_check.py                 # 全跑
    python tests/products_ui_check.py --headed        # 看得到瀏覽器
    python tests/products_ui_check.py --keep-shots    # 保留截圖（預設就會留）

會在 DB 建一筆 __TEST__ 商品給前台用，跑完必定刪除。
依賴：playwright（含 chromium）。沒有就直接說跳過，不假裝通過。
"""
import argparse
import functools
import hashlib
import hmac
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tests" / "_shots"
PORT = 8732
API = "http://localhost:5678/webhook"
SITE_TOKEN = "pps_07ae287ed522c33e0422fdd4837d97bf"
TEST_NAME = "__TEST__ui_check_三圖商品"
PHOTOS = ["photos/w2.jpg", "photos/w3.jpg", "photos/works/w08.jpg"]

FAILS = []


def check(name, ok, detail=""):
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — %s" % detail) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


# ───────────────────────── DB / API 小工具 ─────────────────────────
def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "n8n_postgres", "psql", "-U", "n8n", "-d", "n8n", "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def auth():
    secret = json.loads(psql("select value from pps2_settings where key='auth_secret'"))
    actor, role, exp = "__test__", "owner", int(time.time()) + 600
    msg = "%s|%s|%d" % (actor, role, exp)
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {"role_token": "%s|%s" % (msg, sig), "actor": actor, "role": role}


def post(body):
    req = urllib.request.Request(API + "/pps2-products",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def seed_product():
    post(dict(op="save", **auth(), product=dict(
        name=TEST_NAME, category="現貨", layout="五行相生搭配法", aesthetic="輕盈流光",
        cord_type="蠶絲線", accessory_material="銀", size_cm=17.5, bead_mm=10,
        price=1234, stock=5, photos=PHOTOS, description="UI 驗收用測試商品",
        status="上架", crystals=["白水晶"], low_stock_mode="inherit", low_stock_value=0)))


def drop_product():
    psql("delete from pps2_products where name='%s'" % TEST_NAME)


# ───────────────────────── 本機靜態站 ─────────────────────────
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ───────────────────────── 後台 ─────────────────────────
SELECTS = [("#p_cat", "分類"), ("#p_bead", "排珠法"), ("#p_feel", "體感"),
           ("#p_cord", "線材"), ("#p_acc", "配飾材質")]


def admin_checks(page):
    print("\n[後台] 新增商品表單")
    page.goto("http://127.0.0.1:%d/admin.html" % PORT)
    page.wait_for_selector("#gate", state="visible")
    # 首次進站＝建立管理員（localStorage 空的）
    page.fill("#setUser", "owner")
    page.fill("#setPin1", "1234")
    page.fill("#setPin2", "1234")
    page.click("text=建立後台")
    page.wait_for_selector("#app", state="visible", timeout=20000)

    page.click("text=📦 商品庫存")
    page.click("text=＋ 新增商品")
    page.wait_for_selector("#p_name", timeout=10000)

    # 驗收 1：每一個 select 都要有真的選項（扣掉「（請選擇）」那一個）
    for sel, label in SELECTS:
        opts = page.eval_on_selector_all(
            sel + " option", "els=>els.map(e=>e.value).filter(Boolean)")
        check("下拉「%s」有選項" % label, len(opts) > 0, "%d 項: %s" % (len(opts), opts[:4]))

    # 驗收 3：DB 本來就有欄位卻沒地方填的兩欄
    check("表單有 手圍長度 cm", page.locator("#p_size").count() == 1)
    check("表單有 珠徑 mm", page.locator("#p_bmm").count() == 1)

    # 驗收 4：三個網址 → 三個縮圖
    page.fill("#p_img", ",".join(PHOTOS))
    page.dispatch_event("#p_img", "input")
    page.wait_for_timeout(300)
    n = page.locator("#p_imgList .imgchip").count()
    check("貼 3 個網址 → 後台清單 3 張", n == 3, "實得 %d" % n)
    first = page.locator("#p_imgList .imgchip .n").first.inner_text()
    check("第 1 張標示為主圖", first == "主圖", first)

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.locator("#modalRoot").screenshot(path=str(SHOTS / "admin-product-modal.png"))
    print("      截圖 → tests/_shots/admin-product-modal.png")

    # 驗收 5a：拖曳排序。用真事件打真 listener（HTML5 DnD 在無頭瀏覽器不可靠，
    # 這裡直接對 .imgchip 派發 dragstart/dragover/drop，走的仍是 prodImgSync 掛的那組監聽）
    page.evaluate("""() => {
      const chips = document.querySelectorAll('#p_imgList .imgchip');
      const dt = new DataTransfer();
      chips[2].dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));
      chips[0].dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:dt}));
      chips[0].dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));
    }""")
    page.wait_for_timeout(200)
    order = page.input_value("#p_img").split(",")
    check("拖曳排序：第 3 張拖到最前", order[0] == PHOTOS[2], order)

    # 驗收 5b：刪單張
    page.locator("#p_imgList .imgchip .x").first.click()
    page.wait_for_timeout(200)
    n = page.locator("#p_imgList .imgchip").count()
    left = page.input_value("#p_img").split(",")
    check("刪單張後剩 2 張", n == 2 and len(left) == 2, "chips=%d value=%s" % (n, left))

    # 上限 5：貼 7 個要截到 5 並出警語
    page.fill("#p_img", ",".join(["photos/w%d.jpg" % i for i in range(1, 8)]))
    page.dispatch_event("#p_img", "input")
    page.wait_for_timeout(200)
    n = page.locator("#p_imgList .imgchip").count()
    warn = page.locator("#p_imgList .warn-t").count()
    check("超過 5 張會截斷並提示", n == 5 and warn == 1, "chips=%d warn=%d" % (n, warn))


# ───────────────────────── 前台 ─────────────────────────
def shop_checks(page):
    print("\n[前台] 商品卡與 modal")
    # 走 config.js 裡的正式 N8N_BASE（公開網域），測的就是使用者實際會走的那條路。
    # #shop 是必要的：分頁靠 hash 路由，.tab 沒 active 就整段 display:none
    page.goto("http://127.0.0.1:%d/index.html#shop" % PORT)
    # 商品卡是 .reveal（opacity:0 直到 IntersectionObserver 給 .in）。
    # 進場動效不是這支要驗的東西（visual_check.py 管那個），這裡直接把 .in 補上，
    # 免得驗收卡在動效而不是卡在商品資料。
    page.wait_for_selector("#prodGrid .prod", state="attached", timeout=30000)
    page.evaluate("()=>document.querySelectorAll('.reveal').forEach(e=>e.classList.add('in'))")
    card = page.locator('#prodGrid .prod:has-text("%s")' % TEST_NAME)
    if card.count():
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
    check("商品卡出現在前台", card.count() == 1, card.count())
    if card.count() != 1:
        return
    spec = card.locator(".price small").inner_text()
    check("卡上規格含 線材", "蠶絲線" in spec, spec)
    check("卡上規格含 配飾材質", "銀配飾" in spec, spec)
    check("卡上規格含 珠徑/手圍", "10mm" in spec and "17.5cm" in spec, spec)
    main = card.locator(".ph img").get_attribute("src")
    check("卡片主圖是第 1 張（不是 photos/w1.jpg 預設圖）", main.endswith(PHOTOS[0]), main)

    card.click()
    page.wait_for_selector("#prodModal.on", timeout=10000)
    thumbs = page.locator("#mThumbs img").count()
    check("modal 縮圖 3 張", thumbs == 3, "實得 %d" % thumbs)
    meta = page.locator("#mMeta").inner_text()
    check("modal 顯示排珠法／體感", "五行相生搭配法" in meta and "輕盈流光" in meta, meta)
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.locator("#prodModal").screenshot(path=str(SHOTS / "shop-product-modal.png"))
    print("      截圖 → tests/_shots/shop-product-modal.png")

    # 溢出：文字變長不能撐破版面
    for w, h in ((1280, 900), (375, 812)):
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(300)
        over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("寬 %d 零水平溢出" % w, over <= 0, "溢出 %spx" % over)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--keep-shots", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP：沒有 playwright，這支不跑。pip install playwright && playwright install chromium")
        sys.exit(2)

    srv = serve()
    seed_product()
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=not args.headed)
            ctx = br.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.on("pageerror", lambda e: FAILS.append("console error: %s" % e))
            admin_checks(page)
            shop_checks(ctx.new_page())
            br.close()
    finally:
        drop_product()
        srv.shutdown()
        print("\n[cleanup] 已刪除 %s，pps2_products 剩 %s 筆" % (TEST_NAME, psql("select count(*) from pps2_products")))

    print("\n%s（%d 項失敗）" % ("全部通過" if not FAILS else "有失敗項", len(FAILS)))
    for f in FAILS:
        print("  - %s" % f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
