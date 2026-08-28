#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染前的关键帧质检：出总览图 + 逐镜清单，让人看图对分镜。剧目无关。

**脚本判断不了「这张图对不对」，但能保证看之前不开渲。** 踩过两次同样的坑：
关键帧尺寸对、机制通、渲染忠实，但**内容不符合分镜** —— 两次都是渲完才发现。

这一版实际抓到过的（都是肉眼对着清单看出来的，机器判不了）：

    SH03  凭空长出一块黑色显示器 —— 根因是首帧描述里写了「视线朝桌面落一下」，
          桌面在近景里根本不入画，模型就在她面前放了台屏幕
    SH17  分镜写 medium 渲成了 wide，脸只剩一点点
    SH19  两人渲到了桌子同一侧，指的还是人不是椅子
    全局  11 个近景里一半渲成暗调夜景，跟中景的白天办公室剪在一起会闪
          —— 这条只有把 21 张并排铺开才看得见，逐张看永远发现不了

最后一条是这个脚本存在的主要理由：**并排看和逐张看，能发现的问题不是一类。**

  .venv/bin/python scripts/check_keyframes.py --project 搞笑办公室连续剧1 --ep 1
"""
import argparse
import json
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--width", type=int, default=430, help="总览图里每格的宽")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    kfdir = os.path.join(proj, "keyframes", epid)
    outdir = os.path.join(proj, "out")
    os.makedirs(outdir, exist_ok=True)

    shots, missing = [], []
    for sh in sb["shots"]:
        p = os.path.join(kfdir, f"{sh['id']}.png")
        (shots if os.path.exists(p) else missing).append((sh, p))

    # 逐镜清单：人 / 景别 / 地点 / 首帧该是什么 / 这一镜判废的条件
    print(f"{epid}  关键帧 {len(shots)}/{len(sb['shots'])}\n")
    for sh, _ in shots:
        cam = sh.get("camera") or {}
        who = "、".join(c["name"] for c in (sh.get("cast") or [])) or "无人"
        loc = (sh.get("location") or {}).get("id", "—")
        d = (sh.get("dialogue") or {}).get("text", "")
        print(f"{sh['id']}  {sh['seconds']}s  {cam.get('size','?'):12s} "
              f"{cam.get('angle','?'):6s} {who:8s} {loc}")
        print(f"    首帧应是：{(sh.get('action') or {}).get('start','')}")
        if d:
            print(f"    台词：{d}")
        for f in (sh.get("qc") or {}).get("fail_if", []):
            print(f"    判废：{f}")
        print()

    if missing:
        print("缺关键帧：")
        for sh, p in missing:
            print(f"  ✗ {sh['id']}")

    # 总览图。一屏放不下就分几张 —— **必须并排看**，逐张看发现不了明暗不一致
    per = a.cols * 4
    th = int(a.width * 9 / 16)
    n = 0
    for start in range(0, len(shots), per):
        chunk = shots[start:start + per]
        rows = (len(chunk) + a.cols - 1) // a.cols
        out = Image.new("RGB", (a.width * a.cols, (th + 16) * rows), "white")
        for i, (sh, p) in enumerate(chunk):
            out.paste(Image.open(p).convert("RGB").resize((a.width, th)),
                      (a.width * (i % a.cols), (th + 16) * (i // a.cols)))
        n += 1
        dst = os.path.join(outdir, f"{epid}_关键帧总览_{n}.png")
        out.save(dst)
        print(f"总览图 {n}：{dst}")

    print("\n**人看图对上面的清单。** 脚本判断不了「这张图对不对」，"
          "只保证看之前不开渲。")
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
