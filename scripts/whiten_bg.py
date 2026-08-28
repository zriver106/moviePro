#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把资产 sheet 的浅灰背景提成纯白。剧目无关。

Seedream 默认给的是**影棚渐变底**，不是纯白 —— 四角能到 250 以上，
中间和边缘却在 236–247。这层灰有两个害处（`资产制作逻辑.md` 第三步之二）：
合成时留脏边；模型会把背景材质当成这个物件的材质线索。

**不能整张提亮**：皮肤高光也在 240 上下，一起提就把脸提平了。
只动同时满足两条的像素：

    中性        三通道极差 ≤ SPREAD（灰底是中性的，皮肤偏暖、衣服偏冷）
    已经够亮    最小通道 ≥ FLOOR（黑西装、头发远在这之下）

再按亮度做软过渡，避免在主体边缘切出硬边。原图存 sheet.raw.png。

  .venv/bin/python scripts/whiten_bg.py --project 搞笑办公室连续剧1 --asset CHAR-莉莉
"""
import argparse
import os
import shutil
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FLOOR = 232      # 低于这个亮度的一律不动（黑西装、头发、深色道具）
SPREAD = 10      # 三通道极差上限：灰底中性，皮肤偏暖，超过就不动
SOFT = 246       # 到这个亮度就完全提到白，FLOOR→SOFT 之间线性过渡


def whiten(im):
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            lo, hi = min(r, g, b), max(r, g, b)
            if lo < FLOOR or hi - lo > SPREAD:
                continue
            t = 1.0 if lo >= SOFT else (lo - FLOOR) / (SOFT - FLOOR)
            px[x, y] = (round(r + (255 - r) * t), round(g + (255 - g) * t),
                        round(b + (255 - b) * t), a)
            n += 1
    return im, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--asset", required=True, help="资产 id，如 CHAR-莉莉")
    a = ap.parse_args()

    base = os.path.join(ROOT, "projects", a.project, "assets")
    for sub in ("char", "wardrobe", "prop", "location"):
        d = os.path.join(base, sub, a.asset)
        if os.path.isdir(d):
            break
    else:
        sys.exit(f"找不到资产 {a.asset}")

    sp = os.path.join(d, "sheet.png")
    raw = os.path.join(d, "sheet.raw.png")
    if not os.path.exists(raw):
        shutil.copy2(sp, raw)          # 原图只备份一次，别把提过的当原图
    im, n = whiten(Image.open(raw))
    im.save(sp)
    print(f"{a.asset}: 提白 {n} 像素（占 {n / (im.width * im.height) * 100:.1f}%）→ {sp}")
    print(f"  原图 {raw}")


if __name__ == "__main__":
    main()
