# -*- coding: utf-8 -*-
"""pps2-products 端到端驗收：後台存檔 → DB 落地 → 後台讀回 → 前台讀出。

驗的是 2026-08-03 那組 bug 有沒有真的修好：
  A. 後台表單欄名與 pps2_products 欄名對不上，list_admin 回來的原始列後台認不得
  B. 圖片 URL 以逗號字串送出，n8n 只認 Array，photos 整包掉成 [] → 前台只剩一張預設圖
  C. 新增 category / cord_type / accessory_material 三欄

用法：
    python tests/products_api_check.py                      # 打 localhost:5678
    python tests/products_api_check.py --base https://n8n.anwer3712.com/webhook

會建一筆 name 以 __TEST__ 開頭的商品，跑完必定刪除（finally）。
"""
import argparse
import hashlib
import hmac
import json
import subprocess
import sys
import time
import urllib.request

SITE_TOKEN = "pps_07ae287ed522c33e0422fdd4837d97bf"
TEST_NAME = "__TEST__products_api_check"
PHOTOS = ["https://example.com/a.jpg", "https://example.com/b.jpg", "https://example.com/c.jpg"]

fails = []


def check(label, cond, got=None):
    if cond:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s   got=%r" % (label, got))
        fails.append(label)


def psql(sql):
    """直接查 DB。n8n 的資料庫是 n8n_postgres 容器，帳號 n8n（不是 postgres）。"""
    out = subprocess.run(
        ["docker", "exec", "n8n_postgres", "psql", "-U", "n8n", "-d", "n8n", "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def role_token(actor="__test__", role="owner", ttl=600):
    """role_token = actor|role|exp|hmac_sha256(actor|role|exp, auth_secret)  —— 見 pps2-products「驗Token」"""
    secret = json.loads(psql("select value from pps2_settings where key='auth_secret'"))
    exp = int(time.time()) + ttl
    msg = "%s|%s|%d" % (actor, role, exp)
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return "%s|%s" % (msg, sig), actor, role


def post(base, body):
    req = urllib.request.Request(
        base.rstrip("/") + "/pps2-products",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5678/webhook")
    args = ap.parse_args()

    tok, actor, role = role_token()
    auth = {"role_token": tok, "actor": actor, "role": role}

    product = dict(
        name=TEST_NAME, category="現貨", layout="五行相生搭配法", aesthetic="輕盈流光",
        cord_type="蠶絲線", accessory_material="銀", size_cm=17.5, bead_mm=10,
        price=1234, stock=7, photos=PHOTOS, description="測試用描述",
        status="上架", crystals=["白水晶", "粉晶"],
        low_stock_mode="custom", low_stock_value=3,
    )

    try:
        print("\n[1] op:save —— 後台送出（表單欄名＝DB 欄名）")
        r = post(args.base, dict(op="save", product=product, **auth))
        check("save 回 ok", r.get("ok") is True, r)

        print("\n[2] psql —— 每一欄都要真的落地")
        row = psql(
            "select row_to_json(t) from (select category,layout,aesthetic,cord_type,accessory_material,"
            "size_cm,bead_mm,price,stock,photos,description,status,low_stock_mode,low_stock_value,crystals "
            "from pps2_products where name='%s') t" % TEST_NAME
        )
        check("DB 有這一列", bool(row), row)
        if not row:
            return
        d = json.loads(row)
        print("      %s" % json.dumps(d, ensure_ascii=False))
        check("category", d["category"] == "現貨", d["category"])
        check("layout", d["layout"] == "五行相生搭配法", d["layout"])
        check("aesthetic", d["aesthetic"] == "輕盈流光", d["aesthetic"])
        check("cord_type", d["cord_type"] == "蠶絲線", d["cord_type"])
        check("accessory_material", d["accessory_material"] == "銀", d["accessory_material"])
        check("size_cm", float(d["size_cm"]) == 17.5, d["size_cm"])
        check("bead_mm", d["bead_mm"] == 10, d["bead_mm"])
        check("description", d["description"] == "測試用描述", d["description"])
        check("status", d["status"] == "上架", d["status"])
        check("crystals", d["crystals"] == ["白水晶", "粉晶"], d["crystals"])
        check("low_stock_value", d["low_stock_value"] == 3, d["low_stock_value"])
        # 這條是 B 的核心：三段全部要在，不是 [] 也不是只剩一段
        check("photos 三段都在", d["photos"] == PHOTOS, d["photos"])

        print("\n[3] op:list_admin —— 後台讀回來的鍵名要跟表單同一套")
        r = post(args.base, dict(op="list_admin", **auth))
        me = [p for p in r.get("products", []) if p.get("name") == TEST_NAME]
        check("list_admin 找得到", len(me) == 1, len(me))
        if me:
            p = me[0]
            for k in ("category", "layout", "aesthetic", "cord_type", "accessory_material",
                      "size_cm", "bead_mm", "photos", "description", "status"):
                check("list_admin.%s 非空" % k, p.get(k) not in (None, "", []), p.get(k))
            check("list_admin.photos 三段", p.get("photos") == PHOTOS, p.get("photos"))

        print("\n[4] op:list —— 前台契約（desc/active + photos 給 normProd 用）")
        r = post(args.base, dict(op="list", token=SITE_TOKEN))
        me = [p for p in r.get("products", []) if p.get("name") == TEST_NAME]
        check("前台清單找得到（上架才會出現）", len(me) == 1, len(me))
        if me:
            p = me[0]
            check("前台 photos 三段", p.get("photos") == PHOTOS, p.get("photos"))
            check("前台 desc", p.get("desc") == "測試用描述", p.get("desc"))
            check("前台 active", p.get("active") is True, p.get("active"))
            check("前台 category 是真值不是 layout", p.get("category") == "現貨", p.get("category"))
            check("前台 cord_type", p.get("cord_type") == "蠶絲線", p.get("cord_type"))
            check("前台 accessory_material", p.get("accessory_material") == "銀", p.get("accessory_material"))
            # normProd 的 spec 需要這兩欄，舊版被「包裝商品清單」吃掉了
            check("前台 size_cm", p.get("size_cm") is not None, p.get("size_cm"))
            check("前台 bead_mm", p.get("bead_mm") == 10, p.get("bead_mm"))

        print("\n[5] op:save 更新 —— 改圖片數量要跟著變（不是只會新增）")
        pid = psql("select id from pps2_products where name='%s'" % TEST_NAME)
        upd = dict(product, id=int(pid), photos=PHOTOS[:2], status="下架")
        r = post(args.base, dict(op="save", product=upd, **auth))
        check("update 回 ok", r.get("ok") is True, r)
        got = json.loads(psql("select photos from pps2_products where id=%s" % pid))
        check("update 後 photos 剩兩段", got == PHOTOS[:2], got)
        st = psql("select status from pps2_products where id=%s" % pid)
        check("update 後 status 下架", st == "下架", st)

        # [6] 2026-08-07 補：這條缺了兩年——[4] 只驗上架品出得來，沒人驗下架品出不來。
        # 擋住下架品的是 n8n「查上架商品」的 WHERE status='上架'（前台 op:'list' 走那支），
        # 不是前台的 filter：公開回應根本不帶 status 欄，前台若只判 status 那半會恆為 true。
        # 有人「簡化」掉那句 WHERE、或把 op:'list' 改接到「查全部商品」，只有這條會紅。
        print("\n[6] op:list —— 下架品不得出現在公開清單（擋 SQL 那道門的守衛）")
        r = post(args.base, dict(op="list", token=SITE_TOKEN))
        pub = r.get("products", [])
        me2 = [p for p in pub if p.get("name") == TEST_NAME]
        check("下架後前台清單找不到它", len(me2) == 0, "仍回傳 %d 筆：%s" % (len(me2), me2[:1]))
        # 順帶釘住前台 filter 依賴的欄位形狀：公開清單一律帶 active、一律不帶 status。
        # 這兩條一旦反過來，index.html 的 `p.active !== false` 就會失效而且沒人會發現。
        if pub:
            check("公開清單每筆都帶 active",
                  all("active" in p for p in pub),
                  [p.get("name") for p in pub if "active" not in p])
            check("公開清單不帶 status（前台才不能只判 status）",
                  all("status" not in p for p in pub),
                  [p.get("name") for p in pub if "status" in p])
    finally:
        n = psql("delete from pps2_products where name='%s' returning id" % TEST_NAME)
        print("\n[cleanup] 已刪除測試列: %s" % (n or "(無)"))
        left = psql("select count(*) from pps2_products")
        print("[cleanup] pps2_products 剩 %s 筆" % left)

    print("\n%s  (%d 項失敗)" % ("全部通過" if not fails else "有失敗項", len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
