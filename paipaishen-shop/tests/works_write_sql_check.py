# -*- coding: utf-8 -*-
"""pps2-works 寫入 op 的 SQL 驗收（不需要部署 n8n，直接打 DB）。

為什麼要有這支：那三句 SQL 是整個寫入 op 唯一會真的改到資料的地方。
workflow 的結構驗證（節點接線）不會告訴你 SQL 對不對，而 SQL 錯的代價是資料沒了。
所以在部署之前先把 SQL 逐句對真表跑過，尤其是**空 id 的 DELETE**——
`WHERE id = NULLIF($1,'')::bigint`，如果哪天有人手滑寫成 `WHERE $1 = '' OR id = ...`
就會把整張表刪光，這支測試就是釘住那件事的。

用法：python tests/works_write_sql_check.py
       （只用 docker exec psql，跟 tests/products_ui_check.py 同一條通道）

⚠ 這支會在 pps2_work_group 建臨時列（標題以 __wtest__ 開頭）並在結束時刪掉。
   即使中途失敗，finally 也會清。清的條件是 title LIKE '__wtest__%'，
   碰不到任何真資料。
"""
import json
import subprocess
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

R = []


def chk(name, cond, detail=""):
    R.append((bool(cond), name, str(detail)))


def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "n8n_postgres", "psql", "-U", "n8n", "-d", "n8n", "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def q(s):
    """把值包成 postgres 字串常值。用 dollar-quoting 避開 JSON 裡的單引號地獄。"""
    return "$pps$" + s + "$pps$"


# ── 三句 SQL 逐字取自 _scratch/build_works_write.py，不要各寫一份 ──────────
SAVE_SQL = """WITH p AS (SELECT {j}::jsonb AS j),
ins AS (
  INSERT INTO pps2_work_group(title, cover_url, photos, sort_order, status)
  SELECT j->>'title', j->>'cover_url', COALESCE(j->'photos','[]'::jsonb),
         COALESCE((j->>'sort_order')::int, 0), COALESCE(j->>'status','上架')
  FROM p WHERE (j->>'id') IS NULL
  RETURNING id
),
upd AS (
  UPDATE pps2_work_group w SET
    title      = p.j->>'title',
    cover_url  = p.j->>'cover_url',
    photos     = COALESCE(p.j->'photos','[]'::jsonb),
    sort_order = COALESCE((p.j->>'sort_order')::int, 0),
    status     = COALESCE(p.j->>'status','上架'),
    updated_at = NOW()
  FROM p WHERE (p.j->>'id') IS NOT NULL AND w.id = (p.j->>'id')::bigint
  RETURNING w.id
)
SELECT id FROM ins UNION ALL SELECT id FROM upd"""

DELETE_SQL = """DELETE FROM pps2_work_group
WHERE id = NULLIF({v}, '')::bigint
RETURNING id"""

LIST_ALL_SQL = """SELECT id, title, cover_url, photos, sort_order, status
FROM pps2_work_group
ORDER BY sort_order ASC, id ASC"""


def save(work):
    return [x for x in psql(SAVE_SQL.format(j=q(json.dumps(work, ensure_ascii=False)))).splitlines() if x]


def delete(v):
    # ⚠ psql -At 在 DELETE … RETURNING 之後還會多印一行指令標籤（"DELETE 0"／"DELETE 1"）。
    #   那不是資料列。第一版沒濾掉，三條斷言全紅——紅的是量法不是行為
    #   （列數前後沒變已經證明沒誤刪）。SELECT 沒有這個標籤，所以只有這裡要濾。
    out = psql(DELETE_SQL.format(v=q(str(v)))).splitlines()
    return [x for x in out if x and not x.startswith("DELETE ")]


def run():
    total0 = int(psql("SELECT count(*) FROM pps2_work_group"))
    made = []
    try:
        # ── 1 新增：沒有 id ＝ INSERT，回一個新 id ──────────────────────
        rows = save({"id": None, "title": "__wtest__新增", "cover_url": "https://x/c.jpg",
                     "photos": ["https://x/1.jpg", "https://x/2.jpg"],
                     "sort_order": 7, "status": "上架"})
        chk("[save] 沒有 id ＝ 新增一列", len(rows) == 1 and rows[0].isdigit(), rows)
        if not (len(rows) == 1 and rows[0].isdigit()):
            return
        wid = rows[0]
        made.append(wid)
        got = psql("SELECT title||'|'||cover_url||'|'||jsonb_array_length(photos)||'|'"
                   "||sort_order||'|'||status FROM pps2_work_group WHERE id=%s" % wid)
        chk("[save] 五個欄位都照著寫進去", got == "__wtest__新增|https://x/c.jpg|2|7|上架", got)

        # ── 2 更新：帶著存在的 id ＝ UPDATE，不會多生一列 ────────────────
        n_before = int(psql("SELECT count(*) FROM pps2_work_group"))
        rows = save({"id": wid, "title": "__wtest__改過", "cover_url": "https://x/c2.jpg",
                     "photos": [], "sort_order": 3, "status": "下架"})
        n_after = int(psql("SELECT count(*) FROM pps2_work_group"))
        chk("[save] 帶 id ＝ 更新那一列，不新增", rows == [wid] and n_after == n_before,
            "回 %s｜列數 %d→%d" % (rows, n_before, n_after))
        got = psql("SELECT title||'|'||jsonb_array_length(photos)||'|'||sort_order||'|'||status "
                   "FROM pps2_work_group WHERE id=%s" % wid)
        chk("[save] 更新後五欄都換了（含 photos 清空、狀態轉下架）",
            got == "__wtest__改過|0|3|下架", got)

        # ── 3 id 不存在：0 列，且什麼都不能動 ────────────────────────────
        n_before = int(psql("SELECT count(*) FROM pps2_work_group"))
        rows = save({"id": "999999999", "title": "__wtest__幽靈", "cover_url": "",
                     "photos": [], "sort_order": 0, "status": "上架"})
        n_after = int(psql("SELECT count(*) FROM pps2_work_group"))
        chk("[save] id 在雲端不存在 → 回 0 列（讓後台講得出真正原因）",
            rows == [] and n_after == n_before, "回 %s｜列數 %d→%d" % (rows, n_before, n_after))

        # ── 4 list_all 看得到下架的（這正是後台非用它不可的理由）─────────
        listed = psql(LIST_ALL_SQL)
        chk("[list_all] 撈得到剛剛轉成下架的那一列",
            any(l.startswith(wid + "|") for l in listed.splitlines()),
            listed.splitlines()[:4])
        pub = psql("SELECT count(*) FROM pps2_work_group WHERE status='上架'")
        chk("[list_all] 回的列數 > 公開端點（＝真的多含下架的）",
            len(listed.splitlines()) > int(pub), "全部 %d vs 上架 %d" % (len(listed.splitlines()), int(pub)))

        # ── 5 🔴 空 id 的 DELETE 絕不能誤刪 ─────────────────────────────
        # NULLIF('','')→NULL，`id = NULL` 永遠不成立 → 0 列。
        # 這條是整支測試最重要的一條：寫錯的話整張表會被清空。
        n_before = int(psql("SELECT count(*) FROM pps2_work_group"))
        rows = delete("")
        n_after = int(psql("SELECT count(*) FROM pps2_work_group"))
        chk("[delete] 🔴 空 id 不刪任何東西（不是刪光全表）",
            rows == [] and n_after == n_before, "回 %s｜列數 %d→%d" % (rows, n_before, n_after))

        # ── 6 正常刪除 ──────────────────────────────────────────────────
        rows = delete(wid)
        chk("[delete] 刪得掉指定那一列", rows == [wid], rows)
        left = psql("SELECT count(*) FROM pps2_work_group WHERE id=%s" % wid)
        chk("[delete] 刪完真的不在了", left == "0", left)
        if rows == [wid]:
            made.remove(wid)

        # ── 7 刪不存在的 id：0 列，不報錯 ───────────────────────────────
        rows = delete("999999999")
        chk("[delete] 刪一個不存在的 id → 0 列（後台才講得出「可能已被刪掉」）", rows == [], rows)

        # ── 8 DB 的 CHECK 還在守（photos 上限 5）──────────────────────
        # 應用層先切到 5，但真正的防線是這條 CHECK：寫入端不只一個。
        try:
            save({"id": None, "title": "__wtest__六張", "cover_url": "",
                  "photos": ["u%d" % i for i in range(6)], "sort_order": 0, "status": "上架"})
            chk("[DB] photos 超過 5 張會被 CHECK 擋下", False, "竟然寫進去了")
        except RuntimeError as e:
            chk("[DB] photos 超過 5 張會被 CHECK 擋下",
                "photos_max5" in str(e), str(e).splitlines()[0][:90])
    finally:
        # 條件寫死 __wtest__ 前綴，碰不到任何真資料
        psql("DELETE FROM pps2_work_group WHERE title LIKE '\\_\\_wtest\\_\\_%'")
        total1 = int(psql("SELECT count(*) FROM pps2_work_group"))
        chk("[收尾] 測完的總列數回到測前", total1 == total0, "%d → %d" % (total0, total1))


if __name__ == "__main__":
    run()
    for ok, name, d in R:
        print(("  ✔ " if ok else "  ✘ ") + name + ("   … " + d if d else ""))
    bad = [r for r in R if not r[0]]
    print("\n%d/%d 通過%s" % (len(R) - len(bad), len(R), "" if not bad else "，%d 失敗" % len(bad)))
    sys.exit(1 if bad else 0)
