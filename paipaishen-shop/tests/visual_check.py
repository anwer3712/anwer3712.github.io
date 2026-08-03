#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前台視覺敘事驗收（2026-08-03 綠色主色化 ＋ 三幕捲動 ＋ 換品牌圖）。

用法：
    python tests/visual_check.py                 # 全部九項
    python tests/visual_check.py --only contrast # 只跑某一項
    python tests/visual_check.py --keep-shots    # 保留截圖到 tests/_shots/

為什麼放在版控裡：上一棒的三支驗收腳本只活在 session 的 scratchpad，session 一結束就消失，
下一棒查「腳本在哪」查不到。2026-08-03 起前台驗收腳本一律進 tests/。

依賴：playwright（含 chromium）、Pillow。都沒有就只跑得動靜態那幾項，腳本會直接說哪幾項被跳過。
"""
import argparse
import http.server
import json
import re
import socketserver
import subprocess
import sys
import threading
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
SHOTS = ROOT / "tests" / "_shots"
PORT = 8731

FAILS = []
SKIPS = []


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


# ───────────────────────── WCAG 對比度 ─────────────────────────
def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ═══════════ 1. 綠色比重（靜態）═══════════
# 改動前基線（commit ff09724 逐字實測，非工單轉述）：
#   var(--mu) 10 次（含 --grad-jade 定義本身那次；分佈在 3 條 CSS 規則、2 個 inline style、
#   2 段 JS 產生的 SVG、1 個 JS 配色表）、var(--grad-jade) 0 次、--mu-lit／--line-mu 當時不存在。
#   工單寫「只用在兩處」是只數了 CSS 規則、漏掉 .tstep.done 與 JS／inline 那幾處。
BASE_MU = 10
BASE_JADE = 0


def t_green(src):
    print("\n【1】綠色比重")
    mu = len(re.findall(r"var\(--mu\)", src))
    mulit = len(re.findall(r"var\(--mu-lit\)", src))
    linemu = len(re.findall(r"var\(--line-mu\)", src))
    jade = len(re.findall(r"var\(--grad-jade\)", src))
    total = mu + mulit + linemu + jade
    print(f"       --mu={mu}  --mu-lit={mulit}  --line-mu={linemu}  --grad-jade={jade}  合計={total}")
    check("--mu 引用未減少", mu >= BASE_MU, f"{BASE_MU} -> {mu}")
    check("--grad-jade 不再是死變數", jade > BASE_JADE, f"{BASE_JADE} -> {jade}")
    check("綠色總引用 >= 20 處", total >= 20, f"{total} 處")


# ═══════════ 2. 對比度（靜態，色票對背景）═══════════
PAIRS = [
    ("--mu 正文/標籤 對 --paper",        "#2D6A4F", "#FBF9F4", 4.5),
    ("--mu 對紙色梯最深階 #F0E9DA",       "#2D6A4F", "#F0E9DA", 4.5),
    ("--mu 對卡片白 #fff",               "#2D6A4F", "#FFFFFF", 4.5),
    ("--mu-lit 對 --abyss",              "#8FCFAE", "#101828", 4.5),
    ("--mu-lit 對 --abyss-2",            "#8FCFAE", "#182236", 4.5),
    (".msg.ok 修正後",                    "#2D6A4F", "#E4EEE7", 4.5),
    (".msg.warn 修正後",                  "#85631F", "#F9ECD8", 4.5),
    ("(修正前) .msg.ok #4d7a5f",          "#4D7A5F", "#E4EEE7", 0.0),
    ("(修正前) .msg.warn #96702c",        "#96702C", "#F9ECD8", 0.0),
]


def t_contrast():
    print("\n【2】對比度（AA 正文門檻 4.5）")
    for name, fg, bg, need in PAIRS:
        r = contrast(hex2rgb(fg), hex2rgb(bg))
        if need == 0.0:
            print(f"  [info] {name}: {r:.2f}（舊值，僅供對照）")
        else:
            check(f"{name} = {r:.2f}", r >= need, f"門檻 {need}")


# ═══════════ 5. 新圖已就位、舊遮蔽已退場（靜態）═══════════
def t_images(src):
    print("\n【5】新品牌圖")
    check("hero 背景＝新圖", "url(photos/brand/S__9019531.jpg)" in src)
    check("關於我們 img src＝新圖", 'src="photos/brand/S__9019531.jpg"' in src)
    check("舊圖 S__8962095 已無任何引用", "S__8962095" not in src)
    check("185px 裁切窗（.bookcard .win）已移除", ".bookcard .win" not in src and 'class="win"' not in src)
    blurs = [int(x) for x in re.findall(r"blur\((\d+)px\)", src)]
    hero_blur = re.search(r"S__9019531\.jpg\)[^}]*?filter:blur\((\d+)px\)", src, re.S)
    check("hero blur 已降到 <= 10px", bool(hero_blur) and int(hero_blur.group(1)) <= 10,
          f"實測 {hero_blur.group(1)}px" if hero_blur else f"未比對到；全檔 blur 值={blurs}")
    check("caption 已換成核心思想", "即使身處萬丈深淵，依舊在你身旁，散發前行的光芒" in src)
    # 2026-08-04 使用者裁決 A：關於我們改單張大圖。
    # 舊斷言是「上限 360px」，那正是使用者點名「圖被縮到只剩配圖」的那條規則，已作廢。
    # 新的合規手段＝.bcmask 局部柔焦蓋掉店章下那行英文（幾何位置在 t_browser 實測）。
    check("danny.webp 已從關於我們移除", "danny.webp" not in src.split("<body")[-1])
    check("bookcard 360px 上限已拿掉", "max-width:360px" not in src)
    check("店章英文遮罩 .bcmask 存在", ".bcmask" in src and 'class="bcmask"' in src)


# ═══════════ 8. 禁詞掃描（用 repo 現成的，不自造）═══════════
BASELINE_HITS = 5


def t_compliance():
    print("\n【8】禁詞掃描（docs/p4_kit/scan_compliance.py）")
    p = subprocess.run([sys.executable, str(ROOT / "docs/p4_kit/scan_compliance.py"), str(INDEX)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"共 (\d+) 處命中", p.stdout or "")
    n = int(m.group(1)) if m else -1
    check(f"命中數 {n} <= 基線 {BASELINE_HITS}", 0 <= n <= BASELINE_HITS, f"新增 {n - BASELINE_HITS}")


# ═══════════ 需要瀏覽器的項目 ═══════════
JS_REVEAL = """() => {
  const els = [...document.querySelectorAll('.tab.active .reveal')];
  return els.map(e => +getComputedStyle(e).opacity);
}"""

JS_PROGRESS = """() => {
  const j = document.querySelector('.journey');
  if (!j) return null;
  const rail = document.querySelector('.jrail');
  const anims = j.getAnimations({subtree:true}).concat(rail ? rail.getAnimations({subtree:true}) : []);
  const by = {};
  for (const a of anims) {
    const n = a.animationName || (a.effect && a.effect.getKeyframes && '?') || '?';
    const p = a.effect.getComputedTiming().progress;
    if (p !== null && p !== undefined) by[n] = Math.round(p * 1000) / 1000;
  }
  const bead = document.querySelector('.jbead');
  return { progress: by, beadTop: bead ? Math.round(bead.getBoundingClientRect().top) : null,
           vh: window.innerHeight, scrollY: Math.round(window.scrollY) };
}"""


# playwright 套件版本常比本機下載好的 chromium 新一版，直接 launch() 會找不到執行檔。
# 這裡自己挑一個存在的：先找 ms-playwright 底下的 chromium-*（注意目錄名是 chrome-win64 不是 chrome-win），
# 都沒有才退回系統 Chrome／Edge。用 --pw-exe 可手動指定。
def find_chromium(override=""):
    if override:
        return override
    root = pathlib.Path.home() / "AppData/Local/ms-playwright"
    cands = sorted(root.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True) if root.exists() else []
    cands += [pathlib.Path(p) for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]
    for c in cands:
        if c.exists():
            return str(c)
    return ""


def serve():
    handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), lambda *a: handler(*a, directory=str(ROOT)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def t_browser(keep_shots, pw_exe=""):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        SKIPS.append("【3】【4】【6】【7】：未安裝 playwright")
        print("\n[SKIP] 未安裝 playwright，跳過 3/4/6/7")
        return
    try:
        from PIL import Image
    except ImportError:
        Image = None

    SHOTS.mkdir(parents=True, exist_ok=True)
    httpd = serve()
    base = f"http://127.0.0.1:{PORT}/index.html"
    try:
        exe = find_chromium(pw_exe)
        if not exe:
            SKIPS.append("【3】【4】【6】【7】：找不到可用的 chromium")
            print("\n[SKIP] 找不到 chromium，跳過 3/4/6/7（可用 --pw-exe 指定）")
            return
        print(f"\n（瀏覽器：{exe}）")
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=exe)

            # ── 【7】水平溢出：1280 與 375 ──
            print("\n【7】水平溢出")
            for w, h in ((1280, 900), (375, 812)):
                pg = br.new_page(viewport={"width": w, "height": h})
                for tab in ("home", "about"):
                    pg.goto(f"{base}#{tab}", wait_until="load")
                    pg.wait_for_timeout(500)
                    sw, iw = pg.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
                    check(f"{w}px / #{tab} 無水平溢出", sw <= iw, f"scrollWidth={sw} innerWidth={iw}")
                pg.close()

            # ── 【5b】圖片變形守門（換圖那一輪抓到 danny.webp 被 height 屬性拉成 319×1120）──
            print("\n【5b】圖片長寬比未被拉變形")
            js_ratio = """()=>[...document.querySelectorAll('.tab.active img')].filter(i=>i.naturalWidth)
              .map(i=>{const r=i.getBoundingClientRect(), cs=getComputedStyle(i);
                const nat=i.naturalWidth/i.naturalHeight, got=r.width/r.height;
                return {src:i.src.split('/').pop(), off:+Math.abs(nat-got).toFixed(3), fit:cs.objectFit};})
              .filter(x=>x.off>0.03 && x.fit==='fill')"""
            pg = br.new_page(viewport={"width": 1280, "height": 820})
            bad_all = []
            for tab in ("home", "shop", "custom", "works", "about", "faq", "track"):
                pg.goto(f"{base}#{tab}", wait_until="load")
                pg.wait_for_timeout(700)
                bad_all += [dict(b, tab=tab) for b in pg.evaluate(js_ratio)]
            check("七個分頁的 img 都沒被拉變形（object-fit:fill 者）", not bad_all, str(bad_all) if bad_all else "0 張")
            pg.close()

            # ── 【5c】關於我們大圖：遮罩要真的蓋住店章下那行英文 ──
            # 英文在原圖 923×1152 的位置＝x 55~140、y 983~1016（逐列取像素量出來的）。
            # 這裡把它換算成畫面座標，要求 .bcmask 的矩形完全包住它。
            # 改版位或換圖時這條會先紅，是刻意的：那代表遮罩要重量。
            print("\n【5c】關於我們大圖與店章英文遮罩")
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(f"{base}#about", wait_until="load")
            pg.wait_for_timeout(800)
            # 量的是「元素自身座標」不是螢幕座標：.bookcard 有 rotate(-1.6deg)，
            # getBoundingClientRect 回的是旋轉後的外接矩形，會比實際大一圈、左右各偏幾 px，
            # 拿它比對會得到假的落差。圖與遮罩一起轉，所以在容器本地座標系裡比才精確。
            geo = pg.evaluate("""()=>{const box=document.querySelector('.bcimg');
              const img=document.querySelector('.bookcard img');
              const m=document.querySelector('.bcmask');if(!img||!m||!box)return null;
              const cw=box.offsetWidth, ch=box.offsetHeight, cs=getComputedStyle(m);
              const px=v=>parseFloat(v)||0;
              const ml=px(cs.left), mt=px(cs.top), mw=px(cs.width), mh=px(cs.height);
              return {imgW:Math.round(cw),
                      en:{l:55/923*cw, t:983/1152*ch, r:140/923*cw, b:1016/1152*ch},
                      mask:{l:ml, t:mt, r:ml+mw, b:mt+mh}};}""")
            if not geo:
                check("關於我們大圖＋遮罩存在", False, "找不到 .bookcard img 或 .bcmask")
            else:
                check(f"關於我們是大圖（顯示寬 {geo['imgW']}px > 420）", geo["imgW"] > 420, f"實得 {geo['imgW']}px")
                en, mk = geo["en"], geo["mask"]
                covered = mk["l"] <= en["l"] and mk["t"] <= en["t"] and mk["r"] >= en["r"] and mk["b"] >= en["b"]
                check("遮罩完全蓋住店章下那行英文", covered,
                      "英文 %s / 遮罩 %s" % ({k: round(v) for k, v in en.items()},
                                             {k: round(v) for k, v in mk.items()}))
            pg.close()

            # ── 【6】hero h1 對新背景的實測對比 ──
            print("\n【6】hero h1 可讀性")
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(f"{base}#home", wait_until="load")
            pg.wait_for_timeout(1800)  # 等 heroLight 播完，量的是定稿亮度
            box = pg.evaluate("""() => { const h = document.querySelector('#tab-home .hero h1');
                const r = h.getBoundingClientRect();
                return {x:Math.round(r.x), y:Math.round(r.y), width:Math.round(r.width), height:Math.round(r.height)}; }""")
            pg.evaluate("() => document.querySelector('#tab-home .hero h1').style.visibility='hidden'")
            pg.wait_for_timeout(150)
            shot = SHOTS / "hero_h1_bg.png"
            pg.screenshot(path=str(shot), clip=box)
            pg.evaluate("() => document.querySelector('#tab-home .hero h1').style.visibility=''")
            if Image:
                im = Image.open(shot).convert("RGB")
                px = list(im.getdata())
                lums = [luminance(p) for p in px]
                worst = max(lums)                       # 最亮的底 = 白字最難讀之處
                mean = sum(lums) / len(lums)
                c_worst = 1.05 / (worst + 0.05)   # 白字 L=1；底愈亮對比愈差 → 取最亮像素當最壞情形
                c_mean = 1.05 / (mean + 0.05)
                check(f"h1 白字對最亮底像素 = {c_worst:.2f}", c_worst >= 4.5, "AA 4.5")
                print(f"       （平均底色對比 {c_mean:.2f}，取樣 {len(px)} 像素，底圖 {shot.name}）")
            else:
                SKIPS.append("【6】對比計算：未安裝 Pillow")
                print("  [SKIP] 未安裝 Pillow，只留截圖")
            pg.close()

            # ── 【3】三幕捲動：一條連續的線 ──
            print("\n【3】三幕捲動旅程")
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(f"{base}#about", wait_until="load")
            pg.wait_for_timeout(600)
            supported = pg.evaluate("() => CSS.supports('animation-timeline','view()')")
            top = pg.evaluate("() => { const j=document.querySelector('.journey'); const r=j.getBoundingClientRect();"
                              "return {top: Math.round(r.top + window.scrollY), h: Math.round(r.height)}; }")
            VH = 900
            check("旅程比視窗高（真的要捲過去）", top["h"] > VH, f"高 {top['h']}px / 視窗 {VH}px")
            # 取樣範圍＝整段旅程從進畫面到離開畫面（軌道的畫線區間橫跨 entry 與 contain）。
            y0, y1 = top["top"] - VH, top["top"] + top["h"]
            # 珠子只在「軌道頂端已捲過 46vh、且軌道底端還沒到」這段才會釘住；
            # 進場前它在軌道頂端跟著捲，那是對的，不該拿來當釘住失敗的證據。
            pin0, pin1 = top["top"] - .46 * VH, top["top"] + top["h"] - .46 * VH
            samples = []
            steps = 9
            for i in range(steps):
                y = y0 + int((y1 - y0) * i / (steps - 1))
                pg.evaluate(f"() => window.scrollTo(0, {max(y, 0)})")
                pg.wait_for_timeout(260)
                s = pg.evaluate(JS_PROGRESS)
                samples.append(s)
                if keep_shots:
                    pg.screenshot(path=str(SHOTS / f"journey_{i}.png"))
            rail = [s["progress"].get("railDraw") for s in samples]
            print(f"       取樣捲動位置 y = {y0} .. {y1}")
            print(f"       railDraw 進度：{rail}")
            print(f"       jbead 視窗內 top：{[s['beadTop'] for s in samples]}（期望 ≈ 0.46×{VH} = {int(.46*VH)}）")
            if supported:
                seen = [v for v in rail if v is not None]
                check("軌道進度隨捲動單調前進（一條線，不是各自淡入）",
                      len(seen) >= 3 and all(b >= a - 0.02 for a, b in zip(seen, seen[1:])) and max(seen) - min(seen) > .9,
                      f"{min(seen):.2f} -> {max(seen):.2f}" if seen else "未取到")
                want = .46 * VH
                mids = [s["beadTop"] for s in samples
                        if s["beadTop"] is not None and pin0 <= s["scrollY"] <= pin1]
                check(f"陪伴的珠子全程釘住不離場（依舊在你身旁，釘住區間 {len(mids)}/{steps} 個取樣點）",
                      len(mids) >= 3 and all(abs(m - want) <= 8 for m in mids),
                      f"最大偏離 {max(abs(m-want) for m in mids):.0f}px" if mids else "未取到")
                check("三幕各自演出（railDraw／actRise／bgSink／flareOpen 都在跑）",
                      {"actRise", "bgSink", "flareOpen"} <= set().union(*[set(s["progress"]) for s in samples]),
                      str(sorted(set().union(*[set(s["progress"]) for s in samples]))))
            else:
                SKIPS.append("【3】：此 chromium 不支援 animation-timeline:view()，只驗降級版")
                print("  [SKIP] 不支援 animation-timeline，改驗降級靜態版")
            pg.close()

            # ── 【4】reduced-motion：停在定稿狀態 ──
            print("\n【4】prefers-reduced-motion: reduce")
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
            pg = ctx.new_page()
            pg.goto(f"{base}#about", wait_until="load")
            pg.wait_for_timeout(700)
            st = pg.evaluate("""() => {
                const rail = document.querySelector('.jrail');
                const t = getComputedStyle(rail, '::before').transform;
                const flare = document.querySelector('.jflare');
                const fs = getComputedStyle(flare);
                const a1 = getComputedStyle(document.querySelector('.jact.a1'));
                return { railT: t, flareOpacity: +fs.opacity, flareScale: fs.scale,
                         a1Opacity: +a1.opacity, anims: document.querySelectorAll('.journey').length &&
                           document.querySelector('.journey').getAnimations({subtree:true}).length };
            }""")
            print(f"       {json.dumps(st, ensure_ascii=False)}")
            check("軌道停在畫滿（不是停在起始的空狀態）",
                  st["railT"] in ("none", "matrix(1, 0, 0, 1, 0, 0)"), st["railT"])
            check("光已散開（flare opacity = 1）", abs(st["flareOpacity"] - 1) < .01, st["flareOpacity"])
            check("第一幕在定稿亮度（opacity = 1）", abs(st["a1Opacity"] - 1) < .01, st["a1Opacity"])
            check("reduce 下沒有捲動驅動動畫在跑", st["anims"] == 0, f"{st['anims']} 個")
            ops = pg.evaluate(JS_REVEAL)
            check(f"reveal 類元素可見度全為 1（{len(ops)} 個）", bool(ops) and all(abs(o - 1) < .01 for o in ops),
                  f"最小值 {min(ops) if ops else 'n/a'}")
            if keep_shots:
                pg.screenshot(path=str(SHOTS / "reduced_motion_about.png"), full_page=True)
            ctx.close()
            br.close()
    finally:
        httpd.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--keep-shots", action="store_true")
    ap.add_argument("--pw-exe", default="", help="手動指定 chromium 執行檔")
    a = ap.parse_args()
    src = INDEX.read_text(encoding="utf-8")
    run = lambda k: (not a.only) or a.only == k

    if run("green"):
        t_green(src)
    if run("contrast"):
        t_contrast()
    if run("images"):
        t_images(src)
    if run("compliance"):
        t_compliance()
    if run("browser"):
        t_browser(a.keep_shots, a.pw_exe)

    print("\n" + "═" * 56)
    for s in SKIPS:
        print(f"  [SKIP] {s}")
    if FAILS:
        print(f"  不通過 {len(FAILS)} 項：")
        for f in FAILS:
            print(f"    - {f}")
        sys.exit(1)
    print("  全部通過。")


if __name__ == "__main__":
    main()
