#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测资产 sheet 的格位坐标，写回 cells_*.json。剧目无关。

**别用理论等分。** 出图模型排的格子不等分 —— 上一部剧实测房间 sheet 上行 708px
下行 697px，访客椅三格 1970/1915/1858。按理论值裁会裁歪半个身子，而且这种偏差
在缩图上看不出来，要到成片里才发现人少了条胳膊。

两种 sheet 版式，检测方法不一样：

  白底摆件式   主体浮在白底上，格与格之间是空白。按「非背景」投影找空隙
  深色满幅式   每格是一整块深色画面，格间只有一条细分隔线。**投影找不到空隙**
               （整张都是内容），改成找**低方差的分隔线**：分隔线那几行/列
               颜色几乎一致，方差接近 0，而画面内部方差很高

先试白底法，行列数对不上再试分隔线法。两种都允许**每行格数不同** ——
实测有 sheet 是上排 3 格下排 2 格，硬套统一列数会把两格并成一格。

行列数跟 cells.json 里声明的对不上就报错退出 —— **不猜**。
猜出来的格位不会报错，只会让下游裁出半个身子。

顺带出一张 `cells_debug.png`（在 sheet 上画出框和 key），**必须人看一眼**。

  .venv/bin/python scripts/measure_cells.py --project 漫剧战斗样片
  .venv/bin/python scripts/measure_cells.py --project 漫剧战斗样片 --only CHR-艾琳
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG_TOL = 26          # 跟背景色的距离超过这个值才算内容
MIN_RUN = 0.02       # 一段内容至少要占这条边的比例，短于此当噪点
PAD = 0.012          # 外接框往外放的余量，占短边比例


def bands(profile, total, min_run):
    """把一维 profile 切成「有内容的段」。段与段之间是空隙。"""
    out, start = [], None
    for i, v in enumerate(profile):
        if v > 0 and start is None:
            start = i
        elif v == 0 and start is not None:
            if i - start >= min_run:
                out.append((start, i))
            start = None
    if start is not None and len(profile) - start >= min_run:
        out.append((start, len(profile)))
    return out


def gutter_bands(vals, lo_ratio=0.35, min_run=2):
    """按方差找分隔线。返回「内容段」列表。

    分隔线的方差接近 0，画面内部方差高。阈值取整条序列中位数的 lo_ratio 倍 ——
    用中位数不用均值，因为画面里大面积暗部会把均值拉低。
    """
    srt = sorted(vals)
    med = srt[len(srt) // 2] or 1e-9
    thr = med * lo_ratio
    out, start = [], None
    for i, v in enumerate(vals):
        if v > thr and start is None:
            start = i
        elif v <= thr and start is not None:
            if i - start >= min_run:
                out.append((start, i))
            start = None
    if start is not None and len(vals) - start >= min_run:
        out.append((start, len(vals)))
    return out


def col_std(px, w, h, step, y0, y1):
    out = []
    for x in range(0, w, step):
        vs = [sum(px[x, y]) / 3 for y in range(y0, y1, step)]
        m = sum(vs) / len(vs)
        out.append((sum((v - m) ** 2 for v in vs) / len(vs)) ** 0.5)
    return out


def row_std(px, w, h, step):
    out = []
    for y in range(0, h, step):
        vs = [sum(px[x, y]) / 3 for x in range(0, w, step)]
        m = sum(vs) / len(vs)
        out.append((sum((v - m) ** 2 for v in vs) / len(vs)) ** 0.5)
    return out


def measure_dark_gutters(path, cols, rows):
    """发光式：黑底上的发光特效，按**最暗的那条缝**切。

    前两种方法都会栽在这类图上：白底投影法要求格与格之间是空白，
    而这里整张底都是黑的；分隔线方差法要求缝里颜色一致而画面内部方差高，
    可黑底特效的大片背景方差同样接近 0，缝和背景分不开
    （护盾那张实测切出 11 格，每行 [7,2,2]）。

    这里换的指标是**亮度**：缝一定是这张图上最暗的一行/一列。
    只在「声明的格数所要求的位置附近」开窗搜（±SEARCH 的画幅比例），
    在窗内找亮度最低的那条 —— **窗是理论的，落点是实测的**，
    所以它报告的是缝实际在哪，不是假定它在正中间。

    找到的缝必须明显暗于两侧格子内部，否则判失败退出，**不猜**。
    """
    SEARCH = 0.10          # 开窗半宽，占画幅比例
    DARK = 0.6             # 缝的亮度要低于两侧中位亮度的这个倍数

    im = Image.open(path).convert("L")
    w, h = im.size
    a = np.asarray(im, dtype=np.float32)
    colmean, rowmean = a.mean(axis=0), a.mean(axis=1)

    def cuts(profile, n, total):
        """找 n-1 条内缝的位置。"""
        out = []
        for i in range(1, n):
            centre = int(total * i / n)
            half = max(2, int(total * SEARCH))
            lo, hi = max(1, centre - half), min(total - 1, centre + half)
            win = profile[lo:hi]
            if len(win) == 0:
                return None, f"第 {i} 条缝的搜索窗是空的"
            pos = lo + int(np.argmin(win))
            med = float(np.median(profile))
            if med > 0 and profile[pos] > med * DARK:
                return None, (f"第 {i} 条缝没找到：最暗处亮度 {profile[pos]:.1f}，"
                              f"整体中位 {med:.1f}，不够暗")
            out.append(pos)
        return out, None

    xs, err = cuts(colmean, cols, w)
    if err:
        return None, f"竖缝：{err}"
    ys, err = cuts(rowmean, rows, h)
    if err:
        return None, f"横缝：{err}"

    xb = [0] + xs + [w]
    yb = [0] + ys + [h]
    cells = []
    for r in range(rows):
        for c in range(cols):
            cells.append([xb[c], yb[r], xb[c + 1] - xb[c], yb[r + 1] - yb[r]])
    return cells, None


def measure_panels(path, want_total):
    """深色满幅式：按分隔线切，允许每行格数不同。"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    step = max(1, min(w, h) // 500)
    rb = gutter_bands(row_std(px, w, h, step))
    cells = []
    for (ry0, ry1) in rb:
        y0, y1 = ry0 * step, min(h, ry1 * step)
        cb = gutter_bands(col_std(px, w, h, step, y0, y1))
        for (cx0, cx1) in cb:
            x0, x1 = cx0 * step, min(w, cx1 * step)
            cells.append([x0, y0, x1 - x0, y1 - y0])
    return (cells, None) if len(cells) == want_total else (
        None, f"分隔线法切出 {len(cells)} 格（每行 "
              f"{[len(gutter_bands(col_std(px, w, h, step, a*step, min(h,b*step)))) for a,b in rb]}），"
              f"声明 {want_total} 格")


def measure(path, want_rows, want_cols):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    # 背景色取四角的众数 —— 白底、透明底转白、浅灰底都能覆盖
    corners = [px[1, 1], px[w - 2, 1], px[1, h - 2], px[w - 2, h - 2]]
    bg = Counter(corners).most_common(1)[0][0]

    step = max(1, min(w, h) // 900)          # 大图抽样，够用且快
    mask = [[0] * ((w + step - 1) // step) for _ in range((h + step - 1) // step)]
    for yi, y in enumerate(range(0, h, step)):
        row = mask[yi]
        for xi, x in enumerate(range(0, w, step)):
            r, g, b = px[x, y]
            row[xi] = 1 if (abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])) > BG_TOL else 0

    mh, mw = len(mask), len(mask[0])
    rowsum = [sum(r) for r in mask]
    rb = bands(rowsum, mh, max(2, int(mh * MIN_RUN)))
    if len(rb) != want_rows:
        return None, f"投影找到 {len(rb)} 行，声明 {want_rows} 行"

    cells = []
    for (y0, y1) in rb:
        colsum = [sum(mask[y][x] for y in range(y0, y1)) for x in range(mw)]
        cb = bands(colsum, mw, max(2, int(mw * MIN_RUN)))
        if len(cb) != want_cols:
            return None, f"某一行里投影找到 {len(cb)} 列，声明 {want_cols} 列"
        for (x0, x1) in cb:
            pad = int(min(w, h) * PAD)
            bx = max(0, x0 * step - pad)
            by = max(0, y0 * step - pad)
            bw = min(w - bx, (x1 - x0) * step + 2 * pad)
            bh = min(h - by, (y1 - y0) * step + 2 * pad)
            cells.append([bx, by, bw, bh])
    return cells, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    # **逗号分隔，跟 gen_asset.py 一致。** 旧版只认单个 id，传一串进来
    # 一个都匹配不上 —— 而循环体没跑过，`bad` 就是空的，末尾照样打印
    # 「全部量完」。**「一个都没做」和「全做完了」打印同一句话**，
    # 这是又一个假绿灯：实测传了 8 个资产进去，写回 0 个 bbox、0 张 debug 图，
    # 退出码 0。
    ap.add_argument("--only", help="只做这几个，逗号分隔")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base = os.path.join(ROOT, "projects", a.project, "assets")
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    bad, done = [], 0
    for f in sorted(glob.glob(os.path.join(base, "*", "*", "cells_*.json"))):
        aid = os.path.basename(os.path.dirname(f))
        if only and aid not in only:
            continue
        d = json.load(open(f, encoding="utf-8"))
        sp = os.path.join(os.path.dirname(f), d["sheet"])
        if not os.path.exists(sp):
            bad.append(f"{aid}/{d['sheet']} 图不存在")
            continue
        # grid 写成 "3x2" 时按「3 列 2 行」读 —— 跟 cells 的 left-to-right,
        # top-to-bottom 顺序一致
        cols, rows = (int(x) for x in d["grid"].lower().split("x"))
        n = len(d["cells"])
        # **特效 sheet 一律按格子矩形切，不按内容外接框。**
        # 两种 bbox 语义混在一起会让下游的质检指标失去意义：内容外接框紧贴主体，
        # 框内几乎全是主体和它的辉光，于是「全透占比」「灰纱占比」这类
        # 「这张图透不透」的指标全部误报（冰棱那格实测灰纱 62%，
        # 而那 62% 是冰棱自己的蓝色辉光，不是背景）。
        # 叠加片本来也该保留格内的位置和辉光衰减，切成紧框反而丢信息。
        is_vfx = os.path.basename(os.path.dirname(os.path.dirname(f))) == "vfx"
        if is_vfx and cols * rows == n:
            boxes, err = measure_dark_gutters(sp, cols, rows)
        else:
            boxes, err = measure(sp, rows, cols)
        if boxes and len(boxes) != n:
            boxes, err = None, f"白底法量到 {len(boxes)} 格，声明 {n} 格"
        if not boxes:
            boxes, err2 = measure_panels(sp, n)     # 深色满幅式
        if not boxes and cols * rows == n:
            # 发光式（黑底特效）：前两法都要求缝和内容在「有无内容」或
            # 「方差高低」上分得开，黑底发光图两条都不成立。换按亮度找最暗的缝。
            boxes, err3 = measure_dark_gutters(sp, cols, rows)
            err2 = err2 if boxes else f"{err2}；发光式：{err3}"
        if not boxes:
            bad.append(f"{aid}/{d['sheet']}：{err2}")
            continue
        for c, b in zip(d["cells"], boxes):
            c["bbox"] = b
        d.pop("note", None)
        d["bbox_note"] = "实测内容外接框（scripts/measure_cells.py），非理论等分"
        if not a.dry_run:
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            im = Image.open(sp).convert("RGB")
            dr = ImageDraw.Draw(im)
            for c in d["cells"]:
                x, y, bw, bh = c["bbox"]
                dr.rectangle([x, y, x + bw, y + bh], outline=(255, 0, 0), width=6)
                dr.text((x + 12, y + 12), c["key"], fill=(255, 0, 0))
            im.save(os.path.join(os.path.dirname(f),
                                 f"cells_debug_{os.path.basename(f)[6:-5]}.png"))
        done += 1
        print(f"  ✓ {aid}/{d['sheet']}  {d['grid']}  {n} 格")
        for c in d["cells"]:
            print(f"      {c['key']:16s} {c['bbox']}")

    if bad:
        print("\n量不出来的（**不猜**，猜出来的格位不报错，只会让下游裁出半个身子）：")
        for x in bad:
            print(f"  ✗ {x}")
        sys.exit(1)
    if not done:
        # 过滤器一个都没匹配上，不许报成功。
        sys.exit(f"一个资产都没匹配上（--only {a.only}）。**没做成不能打印做完了。**")
    print(f"\n量完 {done} 张。**看一眼各资产目录下的 cells_debug_*.png 再往下走。**")


if __name__ == "__main__":
    main()
