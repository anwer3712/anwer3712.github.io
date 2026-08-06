# -*- coding: utf-8 -*-
"""2026-08-05 前台九項調整的驗收腳本。

⚠ 必須用會 compositing 的瀏覽器跑（本腳本用 headless chromium）。
   捲動驅動動畫（animation-timeline）在不 compositing 的視窗裡
   currentTime 恆為 null，拿那個當結論會得到「動畫全死」的假象。

用法：
    python -m http.server 8788 --directory <repo>     # 另一個終端
    python tests/ui_20260805_check.py [--url http://localhost:8788/] [--shots <dir>]
"""
import sys, io, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

R = []
def chk(name, cond, detail=""):
    R.append((bool(cond), name, str(detail)))

RAF = "async()=>{const r=()=>new Promise(x=>requestAnimationFrame(()=>requestAnimationFrame(x)));await r();await r();}"


def run(url, shots):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(600)
        # ⚠ 站上有 html{scroll-behavior:smooth}，window.scrollTo 會變成平滑動畫，
        #   量測時等不到位（曾量到 scrollY=11 而誤判動畫沒跑）。量測前一律關掉。
        pg.add_style_tag(content="html{scroll-behavior:auto !important}")

        # ── [1] 表格第一欄固定欄寬、純白、可橫捲 ──────────────────────────
        pg.evaluate("()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.add('active'))}")
        pg.wait_for_timeout(200)
        w = pg.evaluate("""()=>{const ws=[...document.querySelectorAll('table.mt')].map(t=>{
            const c=t.querySelector('tr th:first-child,tr td:first-child');
            return c?Math.round(c.getBoundingClientRect().width):0;}).filter(x=>x>0);
            return {n:ws.length,uniq:[...new Set(ws)]};}""")
        chk("[1] 全站 table.mt 第一欄欄寬一致", len(w["uniq"]) == 1, f"{w['n']} 張表，寬度集合 {w['uniq']}")
        base = pg.evaluate("""()=>{const t=[...document.querySelectorAll('table.mt')].find(x=>/精密運算/.test(x.textContent));
            if(!t)return null;const c=t.querySelector('tr td:first-child');
            return {w:Math.round(c.getBoundingClientRect().width),bg:getComputedStyle(c).backgroundColor,
                    ov:getComputedStyle(t.closest('.mt-wrap')).overflowX};}""")
        chk("[1] 基準表（這筆錢到底買到什麼）欄寬＝全站值", base and base["w"] == w["uniq"][0], base)
        chk("[1] 第一欄底色純白", base and base["bg"] == "rgb(255, 255, 255)", base and base["bg"])
        chk("[1] 第二欄可向左捲（容器 overflow-x:auto）", base and base["ov"] == "auto", base and base["ov"])

        # ── [4] 表頭不是灰底 ─────────────────────────────────────────────
        th = pg.evaluate("""()=>{const t=document.querySelector('table.mt th'),g=document.querySelector('.gottman-tbl th');
            return {mt:t?getComputedStyle(t).backgroundColor:'',got:g?getComputedStyle(g).backgroundColor:''};}""")
        chk("[4] table.mt 表頭白底", th["mt"] == "rgb(255, 255, 255)", th["mt"])
        chk("[4] gottman 表頭白底", th["got"] in ("rgb(255, 255, 255)", ""), th["got"])

        pg.evaluate("()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.querySelector('#tab-home').classList.add('active')}")

        # ── [6] 首頁動效真的在跑 ────────────────────────────────────────
        pg.evaluate("()=>window.scrollTo({top:700,behavior:'instant'})")
        pg.evaluate(RAF)
        sd = pg.evaluate("""()=>{const a=document.getAnimations().filter(x=>x.timeline&&x.timeline.constructor.name!=='DocumentTimeline');
            return {total:a.length,active:a.filter(x=>x.currentTime!==null).length,names:[...new Set(a.map(x=>x.animationName))].join(',')};}""")
        chk("[6] 首頁捲動驅動動畫全部 active", sd["total"] > 0 and sd["active"] == sd["total"], sd)
        dur = pg.evaluate("""()=>({hero:getComputedStyle(document.querySelector('#tab-home .hero'),'::before').animationDuration,
                                   ring:getComputedStyle(document.querySelector('.spin')).animationDuration})""")
        chk("[6] hero 呼吸 13s（原 22s）", "13s" in dur["hero"], dur["hero"])
        chk("[6] 五行環 16s（原 24s）", "16s" in dur["ring"], dur["ring"])

        # ── [2][7] 關於我們：三幕 + 品牌圖疊層 + 沿革線 ────────────────────
        pg.evaluate("()=>{const a=[...document.querySelectorAll('.nav-links .nav-top')].find(x=>x.textContent.includes('關於'));a&&a.click();}")
        pg.wait_for_timeout(400)
        # ⚠ 2026-08-06 起「走了九個世代的路」也是一段 .journey（.gen），底下同樣是 .jact。
        #   這裡量的是關於我們那段三幕，選擇器一律加 :not(.gen)，
        #   否則會把五幕那段刻意做的「逐幕加寬」當成三幕的右側空白過大。
        geo = pg.evaluate("""()=>{const j=document.querySelector('.journey:not(.gen)');
            return {h:j.offsetHeight,vh:innerHeight,cards:[...j.querySelectorAll('.jact')].map(c=>Math.round(c.getBoundingClientRect().width)),
                    wrap:Math.round(j.getBoundingClientRect().width),jm:j.querySelectorAll('.jact .jm').length};}""")
        chk("[2] 三幕整段仍高於視窗（sticky 才會觸發）", geo["h"] > geo["vh"], f"{geo['h']}px vs 視窗 {geo['vh']}px")
        chk("[2] 三幕右側空白已收窄（最大 <200px）", max(g := [geo["wrap"] - c for c in geo["cards"]]) < 200, f"空白 {g}")
        chk("[2] 三幕各補了一段內容", geo["jm"] == 3, geo["jm"])

        # ⚠ 2026-08-06 使用者裁決反轉：三幕上那層品牌圖疊層（.jveil，2026-08-05 要求 7）
        #   整組移除，全站只留關於我們頁尾那一張（#about-contact）。
        #   原本 [7] 那五條（起點透明／中段全滿／連續漸變／退場淡掉／壓在字框上）已無標的，
        #   改成兩條反向斷言，釘住「不會有人默默把它加回來」＋「收束句沒被一起刪掉」。
        gone = pg.evaluate("""()=>({veil:document.querySelectorAll('.jveil').length,
            book:document.querySelectorAll('.aboutbook,.bookcard').length,
            close:(document.querySelector('#tab-about .jclose')||{}).textContent||''})""")
        chk("[7] 三幕的品牌圖疊層已移除", gone["veil"] == 0 and gone["book"] == 0, gone)
        chk("[7] 三幕收束句留著（幕名的出處）",
            "即使身處萬丈深淵" in gone["close"], gone["close"][:24])

        # 沿革（走了九個世代的路）
        # ⚠ 2026-08-06 使用者要求 2：原本的 .timeline-v 垂直時間線整組拿掉，
        #   改成第二段三幕旅程 .journey.gen。舊的 .tvbead／tlineDraw／tvIn 已不存在，
        #   斷言改量新結構；「有釘住的珠子」「動畫掛上且在跑」這兩件事的意圖沒變。
        pg.evaluate("()=>{const t=document.querySelector('.journey.gen');t.scrollIntoView({block:'center'});}")
        pg.evaluate(RAF)
        tl = pg.evaluate("""()=>{const t=document.querySelector('.journey.gen'),b=t.querySelector('.jbead');
            const inGen=x=>x.effect&&x.effect.target&&t.contains(x.effect.target);
            const a=document.getAnimations().filter(x=>inGen(x)&&['actRise','genRise','railDraw','flareOpen','bgSink'].includes(x.animationName));
            return {bead:!!b, beadSticky:b?getComputedStyle(b).position:'',
                    acts:t.querySelectorAll('.jact').length,
                    anims:a.length, active:a.filter(x=>x.currentTime!==null).length,
                    h:t.offsetHeight, vh:innerHeight};}""")
        chk("[2] 沿革改用三幕旅程結構（五幕）", tl["acts"] == 5, tl["acts"])
        chk("[2] 沿革有釘住的珠子", tl["bead"] and tl["beadSticky"] == "sticky", tl["beadSticky"])
        chk("[2] 沿革動畫已掛上且 active", tl["anims"] > 0 and tl["active"] == tl["anims"], tl)
        chk("[2] 整段比視窗高（否則 sticky 不觸發）", tl["h"] > tl["vh"], f"{tl['h']} vs {tl['vh']}")
        chk("[2] 舊時間線已移除", pg.evaluate("()=>!document.querySelector('.timeline-v,.tvbead,.tv')"), "")

        # ── [3] 綠 ────────────────────────────────────────────────────
        col = pg.evaluate("""()=>{const gold=/--glow|--jin/;
            const bgs=[...document.querySelectorAll('#tab-about section.block')].map(b=>getComputedStyle(b).backgroundColor);
            const greenish=bgs.filter(c=>{const q=(c.match(/\\d+/g)||[]).map(Number);return q.length>=3&&q[1]>q[0]&&q[1]>q[2];}).length;
            const tp=getComputedStyle(document.querySelector('.transp')).backgroundColor;
            return {bgs,greenish,transp:tp};}""")
        chk("[3] 區塊背景已走木色階", col["greenish"] >= 2, f"{col['greenish']}/{len(col['bgs'])} 段偏綠：{col['bgs']}")
        # ── [5] 需求向量六分量那塊改深綠 ───────────────────────────────
        q = [int(x) for x in __import__("re").findall(r"\d+", col["transp"])][:3]
        chk("[5] 「把方法攤開給你看」底色由深藍改深綠", q[1] > q[2] and q[1] > q[0], col["transp"])

        # ── [8][9] 商品狀態與訂製物流付款 ──────────────────────────────
        biz = pg.evaluate("""()=>{const fake=[{id:'A',name:'上架',status:'上架',stock:3,imgs:['x'],spec:''},
                                              {id:'B',name:'售完',status:'上架',stock:0,imgs:['x'],spec:''},
                                              {id:'C',name:'下架',status:'下架',stock:3,imgs:['x'],spec:''}];
            const kept=fake.map(normProd).filter(p=>p.status!=='下架');
            return {kept:kept.map(p=>p.id), badge0:shopBadge({stock:0}), badge9:shopBadge({stock:9}),
                    ships:[...document.querySelectorAll('[name=ship]')].map(x=>x.value),
                    pays:[...document.querySelectorAll('#payOpts [name=pay]')].map(x=>x.value),
                    feeHome:shipFee('home'), feeStore:shipFee('store'), feeSelf:shipFee('self'),
                    labelHome:shipLabel('home')};}""")
        chk("[8] 已下架＝前台看不到", biz["kept"] == ["A", "B"], biz["kept"])
        chk("[8] 已售完＝看得到並標記", "已售完" in biz["badge0"] and "已售完" not in biz["badge9"], biz["badge0"])
        chk("[9] 訂製取貨含宅配到府", biz["ships"] == ["home", "store", "self"], biz["ships"])
        chk("[9] 宅配運費 130", biz["feeHome"] == 130 and biz["labelHome"] == "宅配到府", biz)
        chk("[9] 店到店 60／面交免運", biz["feeStore"] == 60 and biz["feeSelf"] == 0, biz)
        chk("[9] 訂製付款方式含現金", "cash" in biz["pays"], biz["pays"])

        pay = pg.evaluate("""()=>{const sv=(n,v)=>{const e=document.querySelector(`[name=${n}]`);e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));};
            const sr=(n,v)=>{const e=[...document.querySelectorAll(`[name=${n}]`)].find(x=>x.value===v);if(e){e.checked=true;e.dispatchEvent(new Event('change',{bubbles:true}));}};
            sv('a_wrist','17');sv('a_bead','8');sr('ship','home');sr('pay','cash');
            const o=collect();return {ship:o.ship,fee:o.ship_fee,pay:o.pay,label:o.pay_label,
                                      line:orderText(o).split('\\n').find(l=>l.startsWith('物流')),
                                      detail:document.querySelector('#pDetail').textContent};}""")
        chk("[9] 送單 payload 帶宅配與現金", pay["ship"] == "宅配到府" and pay["fee"] == 130 and pay["pay"] == "cash", pay)
        chk("[9] 前台試算把 130 加進去", "運130" in (pay["detail"] or ""), pay["detail"])
        chk("[9] 退化訂單文字寫出付款方式", "付款：" in (pay["line"] or ""), pay["line"])

        if shots:
            import os
            os.makedirs(shots, exist_ok=True)
            # ⚠ 2026-08-06 起導覽多了折疊子選單，`.nav-links a` 會連子項一起選到 → 一律用 .nav-top
            pg.evaluate("()=>{const a=[...document.querySelectorAll('.nav-links .nav-top')].find(x=>x.textContent.includes('關於'));a&&a.click();}")
            pg.wait_for_timeout(300)
            for tag, f in (("journey-0", 0.0), ("journey-50", 0.5), ("journey-100", 1.0)):
                pg.evaluate(f"()=>window.scrollTo({{top:{int(jtop - 800*0.6 + jh*f)},behavior:'instant'}})")
                pg.evaluate(RAF); pg.wait_for_timeout(150)
                pg.screenshot(path=os.path.join(shots, f"{tag}.png"))
            pg.evaluate("()=>{const t=document.querySelector('.journey.gen');t.scrollIntoView({block:'center'});}")
            pg.wait_for_timeout(200); pg.screenshot(path=os.path.join(shots, "timeline.png"))
            pg.evaluate("()=>{const a=[...document.querySelectorAll('.nav-links .nav-top')].find(x=>x.textContent.includes('首頁'));a&&a.click();window.scrollTo({top:0,behavior:'instant'});}")
            pg.wait_for_timeout(400); pg.screenshot(path=os.path.join(shots, "home.png"))
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8788/")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    run(a.url, a.shots)
    bad = [r for r in R if not r[0]]
    for ok, name, d in R:
        print(("  ✔ " if ok else "  ✘ ") + name + (f"   … {d}" if d else ""))
    print(f"\n{len(R)-len(bad)}/{len(R)} 通過" + ("" if not bad else f"，{len(bad)} 失敗"))
    sys.exit(1 if bad else 0)
