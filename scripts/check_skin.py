#!/usr/bin/env python3
"""量角色资产的肤色，抓「参考图把环境光烤进皮肤」这类事故。剧目无关。

## 起因

Andy 报「人物皮肤都不一样」。查下来是定妆照在红色环境光里出的，
皮肤被整体染红 —— 模型拿到这种参考图，会把「红」当成这个角色的**固有色**，
场景光一变（蓝光弹、白光柱、暗殿）就冲突，于是每一处肤色都不一样。

跟银簪那条是同一条规律换了个位置：
**参考图带着背景材质 → 被当成物件材质；参考图带着环境光 → 被当成角色肤色。**

## 为什么要脚本，而不是手工取框

第一次量的时候，我和另一个会话**各自手工取了个框，两边都取错了** ——
框横跨了角色那头鲜红竖发，量出来 `RGB(135,26,29)`，那是头发不是脸。
按错数字差点去重出三张定妆照。

正确做法是**用 sheet 里实测过 bbox 的 `face` 格**（`measure_cells.py` 量的），
而不是在定妆照上凭眼睛猜比例。同一个角色的 `face` 格位置是确定的，
换一张图也不会飘。

这跟切点阈值那次是同一类：**代理指标的取样参数选错，会把 A 读成 B。**

## 判据

    R−B      红蓝差。中性光下的皮肤约 +50~+70；超过 +85 就是环境光染进来了
    跨资产   同一个角色的不同形态之间，R−B 差超过 15 就是三档对不上，
             成片里会看到「同一个人每场肤色不同」

**它测不出**：肤色本身对不对（那是审美）、化妆、晒黑。
它只回答「这张参考图里的皮肤有没有被环境光染过，以及几张之间一不一致」。

  python3 scripts/check_skin.py --project 漫剧战斗样片
  python3 scripts/check_skin.py --project 漫剧战斗样片 --max-rb 85
"""
import argparse
import json
import os
import statistics as st
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def face_cell(d):
    """从这个资产的 cells_*.json 里找出 face 格的实测 bbox 和所在 sheet。

    **没有实测 bbox 就返回 None，不退回理论等分** ——
    等分裁出来的框会横跨头发，正是这个脚本存在的原因。
    """
    for f in sorted(os.listdir(d)):
        if not (f.startswith("cells_") and f.endswith(".json")):
            continue
        j = json.load(open(os.path.join(d, f), encoding="utf-8"))
        for c in j.get("cells", []):
            if c.get("key") == "face" and c.get("bbox"):
                sheet = os.path.join(d, j.get("sheet", f.replace("cells_", "sheet_")
                                                       .replace(".json", ".png")))
                if os.path.exists(sheet):
                    return sheet, c["bbox"]
    return None


def skin(sheet, bbox):
    """脸格中央那一小块的中位色，连同裁出来的块一起返回。

    ## 为什么必须把取样块一起返回

    **这个任务里我连着三次猜错取样框**：
      1. 在定妆照上按比例猜 → 框横跨那头鲜红竖发，量出 RGB(135,26,29)
      2. 另一个会话独立猜 → 同样撞上头发，量出 RGB(155,61,51)
      3. 改用 face 格再猜子区域 → 常态那格落在暗部，量出 RGB(37,24,25)

    三次的数字都「看起来是个正常的颜色」，没有一次报错。
    **靠人记得去核对取样位置是靠不住的**，所以脚本每次都把取样块拼成一条
    并排图落盘，看图比看数字快，也比看数字可靠。

    取中央偏上一小块：脸格四周有头发、护颈、背景，还可能有模型自己画的边框
    （实测狂化 H1 那格就带一圈黑边）。
    """
    x, y, w, h = bbox
    im = Image.open(sheet).convert("RGB")
    cx, cy = x + w * 0.38, y + h * 0.30
    c = im.crop((int(cx), int(cy), int(cx + w * 0.24), int(cy + h * 0.16)))
    px = list(c.getdata())
    return [st.median([q[i] for q in px]) for i in range(3)], c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max-rb", type=float, default=85.0,
                    help="R−B 上限。中性光皮肤约 +50~+70，超过就是环境光染进来了")
    ap.add_argument("--max-spread", type=float, default=15.0,
                    help="同一角色不同形态之间 R−B 的最大差")
    a = ap.parse_args()

    base = os.path.join(ROOT, "projects", a.project, "assets", "char")
    if not os.path.isdir(base):
        sys.exit(f"没有 {base}")

    rows, bad, patches = [], [], []
    for aid in sorted(os.listdir(base)):
        d = os.path.join(base, aid)
        if not os.path.isdir(d):
            continue
        fc = face_cell(d)
        if not fc:
            print(f"  {aid:<20} 跳过：没有实测 bbox 的 face 格"
                  f"（先跑 measure_cells.py）")
            continue
        (r, g, b), patch = skin(*fc)
        patches.append((aid, patch))
        rb = r - b
        rows.append((aid, r, g, b, rb))
        flag = "  ← 环境光染进皮肤了" if rb > a.max_rb else ""
        print(f"  {aid:<20} RGB({r:3.0f},{g:3.0f},{b:3.0f})   R−B {rb:+5.0f}{flag}")
        if rb > a.max_rb:
            bad.append(f"{aid} R−B {rb:+.0f} 超过 {a.max_rb:+.0f}")

    # 同一角色的不同形态之间要一致 —— 形态阶梯从同一张母板派生，
    # 肤色理应几乎相同；差得多说明派生时没锁住脸
    fam = {}
    for aid, r, g, b, rb in rows:
        fam.setdefault(aid.split("-")[1] if aid.count("-") >= 2 else aid, []).append((aid, rb))
    for who, xs in fam.items():
        if len(xs) < 2:
            continue
        spread = max(x[1] for x in xs) - min(x[1] for x in xs)
        if spread > a.max_spread:
            detail = "、".join(f"{n.split('-')[-1]} {v:+.0f}" for n, v in xs)
            print(f"\n  ✗ {who} 各形态之间 R−B 差 {spread:.0f}（上限 {a.max_spread:.0f}）：{detail}")
            print(f"    形态阶梯本该从同一张母板派生，肤色差这么多说明派生时没锁住脸")
            bad.append(f"{who} 形态间 R−B 差 {spread:.0f}")

    # 取样块并排落盘。**数字之外必须能看见量的是哪一块** ——
    # 三次量错都是因为没人看过取样位置。
    if patches:
        W = max(p.width for _, p in patches)
        H = max(p.height for _, p in patches)
        strip = Image.new("RGB", (W * len(patches), H), (16, 16, 16))
        for k, (_, p) in enumerate(patches):
            strip.paste(p.resize((W, H)), (k * W, 0))
        out = os.path.join(ROOT, "projects", a.project, "assets", "skin_patches.png")
        strip.save(out)
        print(f"\n取样块并排图 → {out}")
        print(f"  顺序：{'、'.join(n for n, _ in patches)}")
        print(f"  **看一眼再信数字** —— 量到头发或暗部会给出一个看起来正常的错颜色")

    if bad:
        print(f"\n{len(bad)} 项不合格")
        sys.exit(1)
    print("\n全部通过")


if __name__ == "__main__":
    main()
