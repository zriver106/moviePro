#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产背景门禁：逐格检查背景是不是真的干净。剧目无关。

**为什么不能只看四角**：四角是「背景干净」的代理指标，主体碰到角就误报。
实测 `PROP-小简历/pinched` 四角最小值 193 —— 那不是背景脏，是捏纸的手
和袖口伸到了右上角。**代理指标失效时要换指标，不是放宽阈值**：放宽会把
真正的灰底一起放过去。

**只量「环上有多少像素接近纯白」也不够** —— 那会把「深色主体占满格子」
（黑西装碰到边，像素值 0）和「背景是灰的」（像素值 240）判成同一种失败。

真正要抓的是**中灰平台**：影棚渐变底会在 150–247 之间堆一大片像素，
而深色主体的像素远在 150 以下。所以量的是环上落在 [150, 247] 的比例，
超过 5% 判灰底。主体是黑的、白的都不误伤，只有「本该是白背景但发灰」会响。

  .venv/bin/python scripts/check_assets_bg.py --project 搞笑办公室连续剧1
  .venv/bin/python scripts/check_assets_bg.py --project 搞笑办公室连续剧1 --fix
"""
import argparse
import json
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WHITE = 248          # 「接近纯白」的下限
GREY_LO = 150        # 中灰平台的下界：比这还暗的算主体，不算背景
RING = 0.03          # 边框环宽度，占短边比例
MAX_GREY = 0.05      # 环上中灰像素占比的上限，超了就是灰底


def ring_grey(t):
    """返回 (环上中灰像素占比, 环上纯白占比)。透明底直接判过。

    中灰 = [GREY_LO, WHITE)。这一段是「本该白却发灰」的特征区间：
    影棚渐变底、没提干净的底、JPEG 压出来的脏边全落在这里。
    深色主体在 GREY_LO 以下，不计入。
    """
    t = t.convert("RGBA")
    w, h = t.size
    m = max(3, int(min(w, h) * RING))
    px = t.load()
    vals, alpha0 = [], 0
    for x in range(0, w, 2):
        for y in list(range(0, m)) + list(range(h - m, h)):
            r, g, b, a = px[x, y]
            (vals.append(min(r, g, b)) if a else None)
            alpha0 += (a == 0)
    for y in range(m, h - m, 2):
        for x in list(range(0, m)) + list(range(w - m, w)):
            r, g, b, a = px[x, y]
            (vals.append(min(r, g, b)) if a else None)
            alpha0 += (a == 0)
    if not vals:
        return 0.0, 1.0             # 整条环都是透明的
    n = len(vals)
    return (sum(GREY_LO <= v < WHITE for v in vals) / n,
            sum(v >= WHITE for v in vals) / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--quiet", action="store_true", help="只列不合格的")
    a = ap.parse_args()

    A = os.path.join(ROOT, "projects", a.project, "assets")
    bad = []
    for sub in ("char", "wardrobe", "prop", "location"):
        d = os.path.join(A, sub)
        if not os.path.isdir(d):
            continue
        for aid in sorted(os.listdir(d)):
            cj = os.path.join(d, aid, "cells.json")
            sp = os.path.join(d, aid, "sheet.png")
            if not (os.path.exists(cj) and os.path.exists(sp)):
                continue
            # 场景本身就是环境，不受纯白约束
            skip = (sub == "location")
            im = Image.open(sp)
            for c in json.load(open(cj, encoding="utf-8"))["cells"]:
                x, y, w, h = c["bbox"]
                grey, white = ring_grey(im.crop((x, y, x + w, y + h)))
                # 豁免必须写在 cells.json 里并带理由 —— 门禁不能靠人记得
                ok = skip or grey <= MAX_GREY or bool(c.get("bg_exempt"))
                if not ok:
                    bad.append((aid, c["key"], grey, white))
                if not a.quiet:
                    tag = ("场景" if skip else
                           "豁免" if c.get("bg_exempt") and grey > MAX_GREY else
                           "✓" if ok else "✗")
                    print(f"{aid:26s} {c['key']:20s} 中灰 {grey * 100:5.1f}%  "
                          f"纯白 {white * 100:5.1f}%  {tag}")
    print()
    if bad:
        print(f"不合格 {len(bad)} 格：")
        for aid, k, grey, white in bad:
            print(f"  ✗ {aid}/{k}  边框环上 {grey * 100:.1f}% 是中灰"
                  f"（上限 {MAX_GREY * 100:.0f}%），纯白只占 {white * 100:.1f}%")
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
