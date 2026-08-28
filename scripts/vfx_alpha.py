#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把黑底特效 sheet 抠成 RGBA 透明底，按格裁出单格 PNG。剧目无关。

## 为什么是黑底抠，不是直接要透明底

Seedream **只返回 JPEG**，JPEG 没有 alpha 通道 —— 跟它说「透明背景」它会画一张
灰白格子的假棋盘底，那比白底还糟。所以链路是「黑底出图 → 本地抠」。

**发光特效在黑底上抠比白底干净得多。** 辉光的边缘是加色的：一片火星在黑底上
的像素值就等于它自己发出的光，抠出来的 alpha 直接就是它的亮度；同一片火星在
白底上，边缘像素是「白底透出来 + 火星发光」，两者混在一个值里分不开，
抠完必留一圈白边。

## alpha 怎么取

    alpha = max(R, G, B)          亮度即不透明度
    RGB   = 原色 / (alpha/255)     反预乘，还原成直通 alpha

出图是**预乘在黑底上**的（黑 = 0，所以 `合成色 = 本色 × alpha`），
所以反过来除一次就还原。不反预乘的话，半透明的辉光边缘会偏暗，
叠到亮背景上会看见一圈脏边。

低于 `FLOOR` 的一律钉成全透明 —— JPEG 的块效应会在纯黑区留下 1–3 的噪声，
不钉死的话整块背景是「几乎透明」而不是「透明」，叠十层就灰了。

## 验收是抽像素量，不是目测

不合格就退出码 1。分两层量，**因为「背景干不干净」和「这一格能不能用」
不是同一件事**：

整张 sheet 的最外一圈（`check_sheet_border`）—— 那里一定是背景

    环的 alpha 中位数        < 10     背景是黑的
    环上 alpha ≥128 的占比   ≤ 2%     没有一整块内容贴着边

每一格（`check`）—— 格子里有主体，不能拿「背景该不该透」去量

    alpha 最大值             ≥ 200    主体真的还在
    中间调（16–239）占比     ≥ 0.5%   辉光过渡还在，不是被抠成硬边二值
    全透（alpha == 0）占比   ≥ 20%    叠加片必须大面积见底
    灰纱（0 < alpha < 40）   ≤ 35%    没有一层半透明的底被烤进图里

**这几条阈值都是拿模拟的坏图验过的**，不是拍脑袋定的：把干净的剑气整体
加 45 和加 15 模拟「垫了石地」，四条里全透和灰纱两条都会响；
只留「背景透了」一条的话，一张**全黑的空图**反而满分通过。

踩过的两个误报，都是**指标用错了地方**，不是阈值太严：

  边框环放到单格上量   `measure_cells` 对亮底图返回的是内容外接框，
                      框紧贴主体，环上 53% 有内容 —— 那是主体占满了框。
                      → 改成只在整张 sheet 的外圈量
  按「有值的占比」量   速度线扫到画幅边上就会顶上去（护盾实测 1.9%，
                      而同一圈中位是 0）。**放宽阈值会把真灰底一起放过**
                      → 改量中位数和实心占比，稀疏内容撑不起来

  .venv/bin/python scripts/vfx_alpha.py --project 漫剧战斗样片
  .venv/bin/python scripts/vfx_alpha.py --project 漫剧战斗样片 --only VFX-剑气
"""
import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FLOOR = 10        # 低于此的亮度当成背景，钉成全透明
RING = 0.006      # 边框环宽度，占短边比例。**只取最外一薄层** ——
                  # 取宽了会伸进模型画的那圈细边框（实测在离边 30–45px 处），
                  # 把「画了个框」误报成「背景没抠干净」。实测最外 8px
                  # 八张 sheet 的中位亮度全是 0，那里才是真背景。
FRAME_MAX = 0.04  # 削边框最多削掉这个比例，超过就停手（宁可留着让质检报出来）
FRAME_HI = 110    # 边框线的 alpha 上限：它是条淡线，不是主体
FRAME_COVER = 0.6 # 一整行里有这么多像素落在淡线区间，才判定它是边框线


def to_rgba(rgb):
    """黑底预乘 → 直通 alpha 的 RGBA。"""
    a = rgb.max(axis=2).astype(np.float32)
    a[a < FLOOR] = 0.0
    # 反预乘：本色 = 合成色 / alpha。alpha 为 0 的地方颜色无意义，填 0。
    scale = np.where(a > 0, 255.0 / np.maximum(a, 1.0), 0.0)[:, :, None]
    col = np.clip(rgb.astype(np.float32) * scale, 0, 255)
    return np.dstack([col, a]).astype(np.uint8)


def trim_frame(rgba):
    """削掉模型给每格画的那圈细边框。

    prompt 里说「panels」，模型就真的给每格描了一道细边。它抠出来是一条
    **淡而均匀、贯穿整条边**的线 —— 叠到镜头上就是画面里凭空多一个矩形框。

    判据不用「离边多少像素」（那是猜），用这条线自己的特征：
    一整行/列里超过 `FRAME_COVER` 的像素落在 `(0, FRAME_HI)` 这个淡区间。
    主体压不中这条：辉光的边缘不会整行均匀，实心处 alpha 远高于 FRAME_HI，
    真背景则是 alpha 0。所以紧贴主体的裁法也不会被误削。
    """
    a = rgba[:, :, 3]
    h, w = a.shape
    t, b, l, r = 0, h, 0, w

    def faint(line):
        return float(((line > 0) & (line < FRAME_HI)).mean()) >= FRAME_COVER

    for _ in range(max(1, int(h * FRAME_MAX))):
        if t < b and faint(a[t]):
            t += 1
        else:
            break
    for _ in range(max(1, int(h * FRAME_MAX))):
        if b - 1 > t and faint(a[b - 1]):
            b -= 1
        else:
            break
    for _ in range(max(1, int(w * FRAME_MAX))):
        if l < r and faint(a[:, l]):
            l += 1
        else:
            break
    for _ in range(max(1, int(w * FRAME_MAX))):
        if r - 1 > l and faint(a[:, r - 1]):
            r -= 1
        else:
            break
    return rgba[t:b, l:r]


def check_sheet_border(rgba, name):
    """整张 sheet 的最外一圈必须透。

    **边框环这个指标只在「这一圈本来就是背景」时才成立。** 放在单格上会误报：
    `measure_cells` 对亮底图返回的是**内容外接框**（紧贴主体），
    冰棱那一格的框就贴着冰棱本身，环上 53% 有内容 —— 那不是背景脏，
    是主体占满了框。跟上一部戏「捏纸的手伸到右上角」是同一种误报。
    所以这条只量整张 sheet 的外圈，那里一定是背景。

    量的是「这一圈是不是一片背景」，不是「这一圈有没有像素」——
    速度线和辉光本来就会扫到画幅边上（护盾那张实测 1.9% 的环上像素有值，
    而同一圈的中位亮度是 0）。按「有值的占比」量，这种正常内容会被判成
    背景没抠干净；**放宽阈值等于把真的灰底也一起放过去**，所以换指标：

      环的 alpha 中位数    背景是黑的，中位就该是 0；铺了一层底，中位会抬起来
      环上实心像素占比     ≥128 的算实心。稀疏的速度线撑不起这个比例，
                          贴着边的一整块内容才撑得起来
    """
    a = rgba[:, :, 3]
    h, w = a.shape
    r = max(2, int(min(h, w) * RING))
    ring = np.concatenate([a[:r].ravel(), a[-r:].ravel(),
                           a[:, :r].ravel(), a[:, -r:].ravel()])
    med = float(np.median(ring))
    solid = float((ring >= 128).mean())
    ok = med < FLOOR and solid <= 0.02
    return ok, (f"{'ok ' if ok else '✗  '} {name} 整张外圈 中位 {med:5.1f}  "
                f"实心 {solid * 100:5.2f}%")


def check(rgba, name):
    """单格 alpha 质检。量的是「这张图能不能当叠加片用」。

    换掉了边框环那条（见 `check_sheet_border`），改量三件跟合成直接相关的事：

      peak   主体真的还在（不是一张空图）
      mid    有中间调 —— 辉光过渡还在，不是被抠成硬边二值
      clear  **全透明像素的占比**。这条抓的是「背景被烤进图里」：
             法阵第一版把发光法阵画在一整块石地上、地裂第一版是满幅石板，
             这种图抠完是一个半透明的灰矩形，clear 会塌到接近 0。
             叠加片必须大面积见底。
      haze   低但非零的 alpha 占比。同一个病的另一面 ——
             石地不会是全黑，它会整片停在 alpha 20–40，形成一层灰纱。
    """
    a = rgba[:, :, 3]
    peak = int(a.max())
    mid = float(((a >= 16) & (a <= 239)).mean())
    clear = float((a == 0).mean())
    haze = float(((a > 0) & (a < 40)).mean())
    ok = peak >= 200 and mid >= 0.005 and clear >= 0.20 and haze <= 0.35
    return ok, (f"{'ok ' if ok else '✗  '} {name}  峰值 {peak:3d}  "
                f"中间调 {mid * 100:5.2f}%  全透 {clear * 100:5.1f}%  "
                f"灰纱 {haze * 100:5.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--only", help="只做这几个，逗号分隔")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    vdir = os.path.join(proj, "assets", "vfx")
    only = {x.strip() for x in a.only.split(",")} if a.only else None

    rows, bad = [], []
    for aid in sorted(os.listdir(vdir)):
        d = os.path.join(vdir, aid)
        if not os.path.isdir(d) or (only and aid not in only):
            continue
        for cj in sorted(f for f in os.listdir(d) if f.startswith("cells_")
                         and f.endswith(".json")):
            meta = json.load(open(os.path.join(d, cj), encoding="utf-8"))
            sheet = os.path.join(d, meta["sheet"])
            if not os.path.exists(sheet):
                bad.append(f"{aid}/{meta['sheet']} 缺图")
                continue
            rgb = np.array(Image.open(sheet).convert("RGB"))
            rgba = to_rgba(rgb)
            stem = cj[len("cells_"):-len(".json")]
            Image.fromarray(rgba, "RGBA").save(
                os.path.join(d, f"sheet_{stem}_rgba.png"))
            # 跟单格同样先削掉那圈细边框再量 —— 否则会因为「模型给整张描了道边」
            # 报「背景没抠干净」，而那道边在成品单格里早就削掉了。
            # 真的垫了一层底照样抓得住：`trim_frame` 最多削 4%，
            # 一整块灰底削不动，环的中位仍然抬着。
            ok, line = check_sheet_border(trim_frame(rgba), f"{aid}/{stem}")
            rows.append(line)
            if not ok:
                bad.append(f"{aid}/{stem} 整张外圈没抠干净")

            missing = [c["key"] for c in meta["cells"] if not c.get("bbox")]
            if missing:
                # **bbox 没实测就不裁。** 理论等分会裁歪，而裁歪了不报错，
                # 只会在成片里少半道剑气。
                bad.append(f"{aid}/{stem} bbox 未实测，跳过裁格：{missing}")
                continue
            cdir = os.path.join(d, "cells")
            os.makedirs(cdir, exist_ok=True)
            H, W = rgba.shape[:2]
            for c in meta["cells"]:
                # measure_cells 写的是 [x, y, w, h]，**不是**两个角点。
                x, y, bw, bh = c["bbox"]
                cut = trim_frame(rgba[max(0, y):min(H, y + bh),
                                      max(0, x):min(W, x + bw)])
                Image.fromarray(cut, "RGBA").save(
                    os.path.join(cdir, f"{c['key']}.png"))
                ok, line = check(cut, f"{aid}/{stem}/{c['key']}")
                rows.append(line)
                if not ok:
                    bad.append(f"{aid}/{stem}/{c['key']} alpha 不合格")

    for r in rows:
        print(r)
    print(f"\n验了 {len(rows)} 格，不合格 {sum(1 for r in rows if r.startswith('✗'))}")
    if bad:
        print("\n要处理的：")
        for b in bad:
            print(f"  {b}")
        sys.exit(1)


if __name__ == "__main__":
    main()
