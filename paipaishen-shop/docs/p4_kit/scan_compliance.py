#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_compliance.py -- 水晶手串文案合規掃描（五類禁詞：療效/財富招財/改運避邪/絕對保證/玄學物理）。
用法：python scan_compliance.py <檔案或目錄...> [--ext .html,.md,.txt]
自測：python scan_compliance.py --selftest

白名單（不算命中）：
  1. 「保證同一份生辰...」演算法說明句（解釋計算可重現，非行銷保證）。
  2. CSS 的 100%（前一字元是 `:` 或 `,`，涵蓋 <style> 區塊與 inline style="..." 屬性）。

輸出：逐行印「檔案:行號: [類別] 「關鍵字」 -> 該行內容」；結尾印總命中數。
Exit code：有命中 -> 1，無命中 -> 0（方便串進其他腳本判斷 pass/fail）。
"""
import sys
import argparse
import pathlib

# 五類禁詞（對齊 README「無療效/財富/改運/保證/玄學物理字眼」的既有分類）
CATEGORIES = {
    "療效":     ["治療", "治癒", "改善", "療效"],
    "財富招財": ["招財", "財運", "保證獲利"],
    "改運避邪": ["改運", "轉運", "避邪", "防小人", "招桃花"],
    "絕對保證": ["絕對", "保證", "100%", "必定"],
    "玄學物理": ["能量", "氣場", "頻率", "磁場", "能量波"],
}

WHITELIST_SENTENCE = "保證同一份生辰"  # 見 index.html「運算方式」節：演算法可重現性說明，非行銷保證


def is_css_percent(line, idx):
    """100% 是版面數值就不算：緊接在 : 或 , 之後（CSS 規則／inline style），
    或緊接在 =" 之後（HTML 屬性值如 width="100%"）。"""
    if idx > 0 and line[idx - 1] in (":", ","):
        return True
    if idx >= 2 and line[idx - 1] == '"' and line[idx - 2] == "=":
        return True
    # 後接 ) -> CSS 函式內數值（linear-gradient 色標、calc 等）
    after = idx + len("100%")
    return after < len(line) and line[after] == ")"


def scan_line(line):
    """回傳這一行命中的 (類別, 關鍵字) list，已套用白名單。"""
    hits = []
    for cat, words in CATEGORIES.items():
        for w in words:
            start = 0
            while True:
                idx = line.find(w, start)
                if idx < 0:
                    break
                start = idx + len(w)
                if w == "保證" and WHITELIST_SENTENCE in line:
                    continue
                if w == "100%" and is_css_percent(line, idx):
                    continue
                hits.append((cat, w))
    return hits


def scan_file(path):
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    results = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for cat, w in scan_line(line):
            results.append((lineno, cat, w, line.strip()))
    return results


def collect_files(paths, exts):
    files = []
    for p in paths:
        pp = pathlib.Path(p)
        if pp.is_dir():
            files += [f for f in pp.rglob("*") if f.suffix.lower() in exts]
        elif pp.is_file():
            files.append(pp)
        else:
            print(f"[警告] 找不到路徑：{p}", file=sys.stderr)
    return sorted(set(files))


def selftest():
    assert any(c == "絕對保證" and w == "保證" for c, w in scan_line("我們保證這串一定有效"))
    assert not any(w == "保證" for c, w in scan_line("這保證同一份生辰資料，跑幾次都是同一套邏輯"))
    assert not any(w == "100%" for c, w in scan_line('<div style="width:100%">'))
    assert not any(w == "100%" for c, w in scan_line("grid-template-columns:100% ,repeat(2,100%)"))
    assert not any(w == "100%" for c, w in scan_line('<svg viewBox="0 0 480 190" width="100%"></svg>'))
    assert not any(w == "100%" for c, w in scan_line("background:linear-gradient(180deg,var(--warm) 100%);"))
    assert any(w == "100%" for c, w in scan_line("配戴後 100% 心想事成"))
    assert any(w == "100%" for c, w in scan_line("滿意度「100%」保證退費"))
    assert any(w == "能量" for c, w in scan_line("感受晶石的能量流動"))
    assert scan_line("五行配比與晶石名稱、顆數") == []
    print("selftest OK")


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
        sys.exit(0)
    ap = argparse.ArgumentParser(description="水晶手串文案合規掃描（五類禁詞，含白名單）")
    ap.add_argument("paths", nargs="+", help="要掃描的檔案或目錄（目錄會遞迴掃 --ext 指定的副檔名）")
    ap.add_argument("--ext", default=".html,.htm,.md,.txt", help="目錄模式掃描的副檔名，逗號分隔（預設 .html,.htm,.md,.txt）")
    args = ap.parse_args()

    exts = tuple(e.strip().lower() for e in args.ext.split(","))
    files = collect_files(args.paths, exts)

    total = 0
    for f in files:
        for lineno, cat, w, line in scan_file(f):
            total += 1
            print(f"{f}:{lineno}: [{cat}] 「{w}」 -> {line}")

    if not files:
        print("沒有找到可掃描的檔案。")
    print(f"\n共 {total} 處命中（掃了 {len(files)} 個檔案）。")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
