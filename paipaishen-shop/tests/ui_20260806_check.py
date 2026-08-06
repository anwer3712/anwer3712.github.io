# -*- coding: utf-8 -*-
"""2026-08-06 前台三項（章節導覽／DANNY 捲簾／沿革改捲動動畫）的驗收腳本。

⚠ 必須用會 compositing 的瀏覽器跑（本腳本用 headless chromium）。
   捲動驅動動畫（animation-timeline）在不 compositing 的視窗裡 currentTime 恆為 null，
   拿那個當結論會得到「動畫全死」的假象（2026-08-05 踩過，見交接卡「本輪更正的判斷」）。

用法：
    python -m http.server 8788 --directory <repo>     # 另一個終端
    python tests/ui_20260806_check.py [--url http://localhost:8788/]
"""
import sys, io, argparse, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

R = []
def chk(name, cond, detail=""):
    R.append((bool(cond), name, str(detail)))

RAF = "async()=>{const r=()=>new Promise(x=>requestAnimationFrame(()=>requestAnimationFrame(x)));await r();await r();}"


def run(url):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(700)
        # 站上有 html{scroll-behavior:smooth}，量測前一律關掉，否則等不到位
        pg.add_style_tag(content="html{scroll-behavior:auto !important}")

        # ══ [4] 章節導覽：頁首折疊 ＋ 浮動章節鈕 ════════════════════════
        toc = pg.evaluate("""()=>{
            const items=[...document.querySelectorAll('#navLinks .nav-item')];
            return {items:items.length,
                    withSub:items.filter(i=>i.querySelector('.nav-sub')).length,
                    subCounts:items.map(i=>i.querySelectorAll('.nav-sub a').length),
                    tops:items.map(i=>i.querySelector('.nav-top')?1:0).reduce((a,c)=>a+c,0),
                    ball:!!document.querySelector('#tocBall'),
                    panel:!!document.querySelector('#tocPanel')};}""")
        chk("[4] 七個分頁都包成 .nav-item", toc["items"] == 7 and toc["tops"] == 7, toc)
        # 現貨／常見問題／訂單查詢三頁本來就只有一個區塊、一個標題，
        # 掛一條的折疊選單是噪音不是功能，所以那三頁沒有是預期行為。
        chk("[4] 有內容分層的分頁都掛得出章節子選單", toc["withSub"] >= 4, toc["subCounts"])
        cust = pg.evaluate("""()=>{const i=[...document.querySelectorAll('#navLinks .nav-item')]
            .find(x=>x.querySelector('.nav-top').getAttribute('href')==='#custom');
            return i?i.querySelectorAll('.nav-sub a').length:0;}""")
        chk("[4] 長頁（訂製服務）走 h3 退路也撈得到章節", cust >= 3, cust)
        chk("[4] 有子選單的分頁至少列 2 條（1 條不值得折疊）",
            all(c == 0 or c >= 2 for c in toc["subCounts"]), toc["subCounts"])
        chk("[4] 浮動章節鈕與面板都在", toc["ball"] and toc["panel"], toc)

        # 每個列進子選單的章節，對應的 section 一定要有 id（不然點了跳不動）
        ids = pg.evaluate("""()=>{const bad=[];
            document.querySelectorAll('#navLinks .nav-sub a').forEach(a=>{
              const sec=(a.getAttribute('href')||'').split('/')[1];
              if(!sec || !document.getElementById(sec)) bad.push(a.getAttribute('href'));});
            return bad;}""")
        chk("[4] 每條章節連結都指到存在的 section", len(ids) == 0, ids)

        # 實際點一條子選單連結，要真的切分頁＋捲到那一段
        jump = pg.evaluate("""async()=>{
            const a=[...document.querySelectorAll('#navLinks .nav-sub a')].find(x=>x.getAttribute('href').startsWith('#about/'));
            if(!a) return {skip:true};
            a.click();
            await new Promise(r=>setTimeout(r,500));
            const sec=document.getElementById(a.getAttribute('href').split('/')[1]);
            return {skip:false, hash:location.hash, tab:document.querySelector('.tab.active').id,
                    top:Math.round(sec.getBoundingClientRect().top)};}""")
        chk("[4] 點章節會切到該分頁", jump.get("skip") or jump["tab"] == "tab-about", jump)
        chk("[4] 點章節會捲到那一段（標題不被 header 吃掉）",
            jump.get("skip") or 0 <= jump["top"] <= 130, jump)
        chk("[4] hash 帶得出章節（可分享的深連結）",
            jump.get("skip") or "/" in jump.get("hash", ""), jump.get("hash"))

        # 舊格式 hash 不能壞
        old = pg.evaluate("""async()=>{location.hash='#faq';await new Promise(r=>setTimeout(r,400));
            return {tab:document.querySelector('.tab.active').id,title:document.title};}""")
        chk("[4] 舊格式 hash（#faq）照舊可用", old["tab"] == "tab-faq" and "常見問題" in old["title"], old)

        # 浮動面板：開得起來、列的是「目前這一頁」、捲動時標出現在在哪
        panel = pg.evaluate("""async()=>{location.hash='#about';await new Promise(r=>setTimeout(r,400));
            document.querySelector('#tocBall').click();
            await new Promise(r=>setTimeout(r,200));
            const on=document.querySelector('#tocPanel').classList.contains('on');
            const links=[...document.querySelectorAll('#tocPanel a[data-sec]')];
            const nav=[...document.querySelectorAll('#navLinks .nav-item')].find(i=>i.querySelector('.nav-top').getAttribute('href')==='#about');
            return {on, links:links.length, nav:nav.querySelectorAll('.nav-sub a').length,
                    allAbout:links.every(a=>a.getAttribute('href').startsWith('#about/'))};}""")
        chk("[4] 章節鈕點得開", panel["on"], panel)
        chk("[4] 面板只列目前這一頁的章節，且與頁首子選單同一份",
            panel["allAbout"] and panel["links"] == panel["nav"] and panel["links"] >= 2, panel)

        spy = pg.evaluate("""async()=>{const links=[...document.querySelectorAll('#tocPanel a[data-sec]')];
            const want=links[links.length-1].dataset.sec;
            const t=document.getElementById(want);
            window.scrollTo({top:t.getBoundingClientRect().top+scrollY-40,behavior:'instant'});
            window.dispatchEvent(new Event('scroll'));
            await new Promise(r=>setTimeout(r,150));
            const now=document.querySelector('#tocPanel a.now');
            return {now:now?now.dataset.sec:'', want};}""")
        chk("[4] 捲到哪就標到哪（scroll-spy）", spy["now"] == spy["want"], spy)

        # 手機：▾ 鈕看得到、按了會展開（桌機是 hover，手機沒有 hover 就等於沒這功能）
        pg.set_viewport_size({"width": 390, "height": 780})
        pg.wait_for_timeout(250)
        mob = pg.evaluate("""async()=>{document.querySelector('#burger').click();
            await new Promise(r=>setTimeout(r,250));
            const item=[...document.querySelectorAll('#navLinks .nav-item')].find(i=>i.querySelector('.nav-exp'));
            if(!item) return {skip:true};
            const btn=item.querySelector('.nav-exp');
            const vis=getComputedStyle(btn).display!=='none';
            btn.click(); await new Promise(r=>setTimeout(r,250));
            const sub=item.querySelector('.nav-sub');
            return {skip:false,vis,open:item.classList.contains('open'),
                    h:Math.round(sub.getBoundingClientRect().height),
                    aria:btn.getAttribute('aria-expanded')};}""")
        chk("[4] 手機看得到 ▾ 展開鈕", mob.get("skip") or mob["vis"], mob)
        chk("[4] 手機按 ▾ 會展開子選單", mob.get("skip") or (mob["open"] and mob["h"] > 20), mob)
        chk("[4] 展開狀態有寫進 aria-expanded", mob.get("skip") or mob["aria"] == "true", mob)
        pg.set_viewport_size({"width": 1280, "height": 800})
        pg.wait_for_timeout(250)

        # ══ [1] DANNY 捲簾浮現 ═══════════════════════════════════════════
        pg.evaluate("()=>{location.hash='#about'}")
        pg.wait_for_timeout(450)
        img = pg.evaluate("""()=>{const i=document.querySelector('.dannyveil img');
            if(!i) return {miss:true};
            return {miss:false,src:i.getAttribute('src'),nw:i.naturalWidth,nh:i.naturalHeight,
                    lazy:i.getAttribute('loading'),alt:(i.getAttribute('alt')||'').length};}""")
        # ⚠ 2026-08-06 使用者訂正：這裡要的一直是 S__9019531.jpg（＝ hero 與關於我們共用的那張書封）。
        #   第一版寫成從 git 歷史挖回來的舊書封，那張是 2026-08-04 使用者裁決拿掉的。
        #   斷言釘死檔名，不再只檢查「有圖」——「有圖」放什麼圖都會綠。
        chk("[1] 頁尾品牌圖＝S__9019531.jpg", not img["miss"] and "S__9019531.jpg" in (img.get("src") or ""), img)
        chk("[1] 圖檔載得到（不是破圖）", not img["miss"] and img["nw"] > 0 and img["nh"] > 0, img)
        chk("[1] 有 alt 文字", not img["miss"] and img["alt"] >= 6, img)

        pos = pg.evaluate("""()=>{const f=document.querySelector('.dannyveil');
            const tp=document.querySelector('.transp'), h2=[...document.querySelectorAll('#tab-about h2')].find(x=>x.textContent.includes('來找我們'));
            const y=e=>e?e.getBoundingClientRect().top+scrollY:-1;
            return {danny:Math.round(y(f)),transp:Math.round(y(tp)),lai:Math.round(y(h2))};}""")
        chk("[1] 位置在「把方法攤開給你看」與「來找我們」之間",
            pos["transp"] < pos["danny"] < pos["lai"], pos)

        # 捲簾：量兩個捲動位置的 mask-size 與 filter，要從「遮住＋灰」走到「全開＋全彩」
        roll = pg.evaluate("""async()=>{const f=document.querySelector('.dannyveil'),i=f.querySelector('img');
            const raf=()=>new Promise(x=>requestAnimationFrame(()=>requestAnimationFrame(x)));
            const read=()=>{const s=getComputedStyle(i);return {mask:s.maskSize||s.webkitMaskSize,filter:s.filter};};
            const top=f.getBoundingClientRect().top+scrollY;
            const out=[];
            for(const off of [innerHeight*0.98, innerHeight*0.55, -innerHeight*0.12]){
              window.scrollTo({top:top-off,behavior:'instant'}); await raf(); out.push(read());
            }
            const a=document.getAnimations().filter(x=>x.animationName==='dannyRoll');
            return {steps:out, anims:a.length, active:a.filter(x=>x.currentTime!==null).length};}""")
        def masky(m):
            n = re.findall(r"([\d.]+)%", m or "")
            return float(n[-1]) if n else -1.0
        seq = [masky(s["mask"]) for s in roll["steps"]]
        chk("[1] 捲簾動畫掛上且在跑", roll["anims"] > 0 and roll["active"] == roll["anims"], roll)
        chk("[1] 遮罩由小到大拉開（捲簾）", seq[0] < seq[1] < seq[2], f"mask 高度序列 {seq}")
        chk("[1] 一開始是遮住的", seq[0] < 20, seq)
        chk("[1] 捲完整張全開（遮罩高過圖）", seq[-1] > 100, seq)
        chk("[1] 一開始是灰的（慢慢變鮮明）", "grayscale" in (roll["steps"][0]["filter"] or ""), roll["steps"][0]["filter"])
        chk("[1] 捲完回到全彩", roll["steps"][-1]["filter"] in ("none", "grayscale(0) contrast(1) brightness(1)"),
            roll["steps"][-1]["filter"])

        # ══ [2] 沿革改成捲動動畫 ═════════════════════════════════════════
        gen = pg.evaluate("""async()=>{const t=document.querySelector('.journey.gen');
            if(!t) return {miss:true};
            t.scrollIntoView({block:'center'});
            await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
            const acts=[...t.querySelectorAll('.jact')];
            const inT=x=>x.effect&&x.effect.target&&t.contains(x.effect.target);
            const a=document.getAnimations().filter(inT);
            return {miss:false,acts:acts.length,
                    widths:acts.map(x=>Math.round(x.getBoundingClientRect().width)),
                    rail:!!t.querySelector('.jrail'),bead:!!t.querySelector('.jbead'),
                    flare:!!t.querySelector('.jflare'),
                    anims:a.length,active:a.filter(x=>x.currentTime!==null).length,
                    old:!!document.querySelector('.timeline-v,.tvbead,.tv')};}""")
        chk("[2] 舊的垂直時間線已整組移除", not gen.get("miss") and not gen["old"], gen)
        chk("[2] 換成五幕捲動旅程", not gen.get("miss") and gen["acts"] == 5, gen)
        chk("[2] 軌道／珠子／光都在（＝跟深淵在旁光芒同一套）",
            not gen.get("miss") and gen["rail"] and gen["bead"] and gen["flare"], gen)
        # 嚴格遞增，不是「不遞減」：前一版有兩幕被 .wrap 夾成同寬，看起來像第四幕沒做事
        chk("[2] 五幕逐幕加寬（嚴格遞增）",
            not gen.get("miss") and all(a < b for a, b in zip(gen["widths"], gen["widths"][1:])), gen.get("widths"))
        chk("[2] 這一段的捲動動畫全部 active",
            not gen.get("miss") and gen["anims"] > 0 and gen["active"] == gen["anims"], gen)

        # 五段年份與原本那一行文字一字未動
        # ⚠ 只取 .n（年份）＋ .jd（原本那一行），不取整張卡的 textContent：
        #   2026-08-06 使用者要求 3 在每一幕下面加了一塊 .gfix 對照（新增內容，不是改動），
        #   量整張卡會把新增的簡述一起算進來，變成「一字未動」永遠紅。
        txt = pg.evaluate("""()=>[...document.querySelectorAll('.journey.gen .jact')]
            .map(a=>[...a.querySelectorAll(':scope>.n,:scope>.jd')].map(x=>x.textContent).join('').replace(/\\s+/g,''))""")
        want = ["2024系統雛形起步，第一代八字符號配珠邏輯成形。",
                "2024–2025導入五派硬仲裁與需求向量，配珠從經驗走向量化。",
                "2025加入心理學降維轉譯與Gottman七維，情侶對串成形。",
                "2025–2026建立合規防火牆與GoldenSet回測，禁詞熔斷上線。",
                "2026-07-12封裝為v1.1一條龍最終執行包，個人與情侶雙線定版。"]
        chk("[2] 五段文字一字未動", txt == want, txt)

        # ══ [3] 五幕的「卡了什麼 → 解了什麼」對照 ════════════════════════
        fx = pg.evaluate("""()=>{const acts=[...document.querySelectorAll('.journey.gen .jact')];
            return acts.map(a=>{const f=a.querySelector('.gfix');
              if(!f) return {miss:true};
              const was=f.querySelector('.was'), now=f.querySelector('.now');
              const li=[...f.querySelectorAll('.was li')];
              return {miss:false, lis:li.length,
                      strike:li.every(x=>getComputedStyle(x).textDecorationLine.includes('line-through')),
                      nowLen:(now.querySelector('p').textContent||'').trim().length,
                      cols:getComputedStyle(f).gridTemplateColumns.split(' ').length,
                      wasTop:Math.round(was.getBoundingClientRect().top),
                      nowTop:Math.round(now.getBoundingClientRect().top)};});}""")
        chk("[3] 五幕都有簡述（對照塊）", all(not x["miss"] for x in fx), fx)
        chk("[3] 左欄是已作廢的限制（有刪除線）",
            all(x["lis"] >= 1 and x["strike"] for x in fx), [(x["lis"], x["strike"]) for x in fx])
        chk("[3] 右欄真的有內容（每幕 >= 30 字）",
            all(x["nowLen"] >= 30 for x in fx), [x["nowLen"] for x in fx])
        # 桌機是左右兩欄；同一列＝左右並排，不是上下堆疊
        chk("[3] 桌機呈現是左右對照", all(x["cols"] == 2 and x["wasTop"] == x["nowTop"] for x in fx), fx)

        # ══ [5] 訂製服務子選單分 A／B 兩組，且點 B 會自動切到情侶對串 ═════
        # 使用者回報的症狀：預設是個人手串，所以只有 A 那組會動，B 那組整組沒反應。
        # 根因＝#duoInfo 整塊 display:none，scrollIntoView 對隱藏元素完全不動。
        sub = pg.evaluate("""async()=>{location.hash='#custom';await new Promise(r=>setTimeout(r,400));
            const item=[...document.querySelectorAll('#navLinks .nav-item')]
              .find(n=>n.querySelector('.nav-top').getAttribute('href')==='#custom');
            const rows=[...item.querySelector('.nav-sub').children];
            return {groups:rows.filter(r=>r.tagName==='B').map(r=>r.textContent.trim()),
                    links:rows.filter(r=>r.tagName==='A').map(r=>({t:r.textContent.trim(),h:r.getAttribute('href')})),
                    order:rows.map(r=>r.tagName).join('')};}""")
        chk("[5] 子選單分成 A 個人手串／B 情侶對串兩組",
            len(sub["groups"]) == 2 and "個人手串" in sub["groups"][0] and "情侶對串" in sub["groups"][1], sub["groups"])
        chk("[5] A 組 4 條、B 組 6 條", sub["order"] == "B" + "A" * 4 + "B" + "A" * 6, sub["order"])
        chk("[5] 十條落點與使用者指定的一致",
            [x["h"] for x in sub["links"]] == [
                "#custom/cu-intro", "#custom/cu-aes", "#custom/cu-wrist", "#custom/order",
                "#custom/cu-rv", "#custom/cu-bridge", "#custom/cu-pair", "#custom/cu-gottman",
                "#custom/cu-wrist", "#custom/order"], sub["links"])
        chk("[5] 每條落點在頁面上都存在",
            pg.evaluate("()=>%s.every(h=>!!document.getElementById(h.split('/')[1]))"
                        % json.dumps([x["h"] for x in sub["links"]])), sub["links"])

        # 真的點下去：B 組四條（情侶專屬那幾條）每一條都要「切到情侶模式 ＋ 元素量得到框」
        def click_sub(href):
            return pg.evaluate("""async(h)=>{
                const a=[...document.querySelectorAll('#navLinks .nav-sub a')].find(x=>x.getAttribute('href')===h);
                a.click(); await new Promise(r=>setTimeout(r,700));
                const el=document.getElementById(h.split('/')[1]);
                const r=el.getBoundingClientRect();
                return {mode:(document.querySelector('#modeSeg button.on')||{}).dataset.mode,
                        visible:el.getClientRects().length>0,
                        top:Math.round(r.top), title:(document.getElementById('orderTitle')||{}).textContent};}""", href)
        for h in ("#custom/cu-rv", "#custom/cu-bridge", "#custom/cu-pair", "#custom/cu-gottman"):
            r = click_sub(h)
            chk(f"[5] 點 {h} 會自動切到情侶對串", r["mode"] == "couple", r)
            # 落點要真的捲到視窗上緣附近（header 78px），不是停在原地
            chk(f"[5] 點 {h} 真的捲到那一段", r["visible"] and -20 <= r["top"] <= 220, r)
        back = click_sub("#custom/cu-aes")
        chk("[5] 點回 A 組會切回個人手串", back["mode"] == "single" and back["visible"], back)
        chk("[5] 切模式時問卷標題跟著換", "個人手串" in (back["title"] or ""), back)

        # 關於我們 ▸ 聯絡我 → 頁尾那張品牌圖
        # ⚠ 這一段是整頁最遠的落點（約 6400px），smooth 捲完要一秒多。
        #   固定 sleep 900ms 會量到「還在飛的半路」（實測 top=483），那是計時器太短，不是功能壞掉。
        #   所以等 scrollY 連續三幀不變才量。
        con = pg.evaluate("""async()=>{location.hash='#about';await new Promise(r=>setTimeout(r,400));
            const item=[...document.querySelectorAll('#navLinks .nav-item')]
              .find(n=>n.querySelector('.nav-top').getAttribute('href')==='#about');
            const a=[...item.querySelectorAll('.nav-sub a')].find(x=>x.textContent.trim()==='聯絡我');
            if(!a) return {miss:true};
            a.click();
            let last=-1, same=0;
            for(let i=0;i<120 && same<3;i++){ await new Promise(r=>setTimeout(r,50));
              if(Math.round(scrollY)===last) same++; else { same=0; last=Math.round(scrollY); } }
            const el=document.getElementById('about-contact');
            return {miss:false, href:a.getAttribute('href'), top:Math.round(el.getBoundingClientRect().top),
                    vh:innerHeight, atBottom:Math.ceil(scrollY+innerHeight)>=document.body.scrollHeight-2,
                    img:!!el.querySelector('img')};}""")
        chk("[5] 關於我們子選單有「聯絡我」", not con.get("miss") and con["href"] == "#about/about-contact", con)
        # 落點捲到頂端；除非頁面已經捲到底捲不動了，那就只要求它在視窗內看得到
        chk("[5] 聯絡我落在頁尾那張品牌圖上",
            not con.get("miss") and con["img"]
            and (-20 <= con["top"] <= 220 or (con["atBottom"] and 0 <= con["top"] < con["vh"])), con)

        # ══ 沒把既有的東西弄壞 ═══════════════════════════════════════════
        # ⚠ 2026-08-06 使用者裁決反轉：三幕上的 .jveil 疊層整組移除（全站只留頁尾一張圖）。
        #   原本兩條回歸（疊層存在／veilIn active）已無標的，改成「三幕本身沒被誤傷」＋
        #   「疊層真的不在了」。三幕自己的動畫（actRise／railDraw／flareOpen／bgSink）照樣要 active。
        keep = pg.evaluate("""async()=>{location.hash='#about';await new Promise(r=>setTimeout(r,400));
            const j=document.querySelector('.journey:not(.gen)');
            j.scrollIntoView({block:'center'});
            await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
            const inJ=x=>x.effect&&x.effect.target&&j.contains(x.effect.target);
            const a=document.getAnimations().filter(inJ);
            return {acts:j.querySelectorAll('.jact').length,veil:document.querySelectorAll('.jveil').length,
                    imgs:document.querySelectorAll('#tab-about img').length,
                    anims:a.length,active:a.filter(x=>x.currentTime!==null).length};}""")
        chk("[回歸] 關於我們的三幕沒被動到", keep["acts"] == 3, keep)
        chk("[回歸] 三幕自己的捲動動畫仍 active",
            keep["anims"] > 0 and keep["active"] == keep["anims"], keep)
        chk("[2b] 三幕的疊層圖已移除，關於我們整頁只剩頁尾那一張圖",
            keep["veil"] == 0 and keep["imgs"] == 1, keep)

        nav = pg.evaluate("""async()=>{const out={};
            for(const t of ['home','shop','custom','works','about','faq','track']){
              location.hash='#'+t; await new Promise(r=>setTimeout(r,260));
              out[t]=document.querySelector('.tab.active').id==='tab-'+t;}
            return out;}""")
        chk("[回歸] 七個分頁全切得過去", all(nav.values()), nav)
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8788/")
    a = ap.parse_args()
    run(a.url)
    bad = [r for r in R if not r[0]]
    for ok, name, d in R:
        print(("  ✔ " if ok else "  ✘ ") + name + (f"   … {d}" if d else ""))
    print(f"\n{len(R)-len(bad)}/{len(R)} 通過" + ("" if not bad else f"，{len(bad)} 失敗"))
    sys.exit(1 if bad else 0)
