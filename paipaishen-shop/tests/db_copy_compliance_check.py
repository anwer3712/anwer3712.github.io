# -*- coding: utf-8 -*-
"""公開站上「來自 DB 的文案」禁詞掃描。

為什麼需要這一支：`docs/p4_kit/scan_compliance.py` 掃的是 index.html／config.js／admin.html
三個**靜態檔**。但公開站上實際被客人讀到的字，有一大半不在那三個檔裡——
商品名稱與描述是 `pps2_products` 的欄位，執行期才被塞進頁面。
結果就是靜態掃描一直回報「命中 5＝基線」，而唯一一件上架商品的描述裡有四個禁詞。

⚠ 這支會**連 DB**（跟 tests/products_ui_check.py 同一條 docker exec psql 通道），
   所以它不會被併進 visual_check 的靜態那一段——那一段刻意不依賴 docker。

用法：python tests/db_copy_compliance_check.py
"""
import importlib.util
import io
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

spec = importlib.util.spec_from_file_location("sc", "docs/p4_kit/scan_compliance.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

# 已知的誤判，逐條寫明理由。放行的是「整句」，不是關鍵字——
# 關鍵字放行等於把守門關掉，整句放行只放行這一句。
FALSE_POSITIVES = [
    # 「醫療效能」裡面夾著「療效」。這句是免責聲明，語意剛好相反。
    "不具備任何醫療效能",
    # 「不具備…具體結果保證」——否定句。LESSONS 早就記過掃描器不看否定詞。
    "具體結果保證",
]


def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "n8n_postgres", "psql", "-U", "n8n", "-d", "n8n", "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout


def scan(label, text):
    """⚠ 誤判要用「遮掉那幾個字」處理，不能用「跳過整行」。

    第一版寫成 `if any(fp in line): continue`，而商品描述在這裡是被壓成單一行的，
    於是一條免責聲明的誤判把整段描述（含四個真命中）全部豁免掉，測試回報 0 處命中。
    量錯範圍的綠燈——跟 2026-08-06 visual_check 那條 split("<body")[-1] 同族。
    """
    hits = []
    for line in (text or "").splitlines():
        probe = line
        for fp in FALSE_POSITIVES:
            probe = probe.replace(fp, "〇" * len(fp))   # 只蓋掉那幾個字，其餘照掃
        for cat, w in sc.scan_line(probe):
            hits.append((label, cat, w, line.strip()))
    return hits


def run():
    hits = []
    # 只掃「上架」的：下架的客人看不到，拿它當紅燈會讓人開始無視這支測試
    rows = psql("SELECT id||E'\\t'||coalesce(name,'')||E'\\t'||replace(coalesce(description,''),E'\\n','  ') "
                "FROM pps2_products WHERE status='上架'")
    n_prod = 0
    for row in rows.splitlines():
        if not row.strip():
            continue
        n_prod += 1
        pid, name, desc = (row.split("\t") + ["", ""])[:3]
        hits += scan("商品 #%s 名稱" % pid, name)
        hits += scan("商品 #%s 描述" % pid, desc)

    # 作品集群組的標題也會上公開站
    rows = psql("SELECT id||E'\\t'||coalesce(title,'') FROM pps2_work_group WHERE status='上架'")
    n_work = 0
    for row in rows.splitlines():
        if not row.strip():
            continue
        n_work += 1
        wid, title = (row.split("\t") + [""])[:2]
        hits += scan("作品集 #%s 標題" % wid, title)

    print("掃了 %d 件上架商品、%d 組上架作品集" % (n_prod, n_work))
    seen = set()
    for label, cat, w, line in hits:
        k = (label, cat, w)
        if k in seen:
            continue
        seen.add(k)
        print("  ✘ [%s] %s「%s」→ %s" % (cat, label, w, line[:70]))
    if not hits:
        print("  ✔ 0 處命中")
    print("\n%s（%d 處命中，基線＝0）" % ("通過" if not hits else "不通過", len(seen)))
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(run())
