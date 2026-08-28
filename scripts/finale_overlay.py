#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""片尾定格 + 贴图 + 音乐。剧目无关。

剧本写的是「后期给莉莉戴上墨镜、叼上雪茄，震撼的『大佬登场』音乐响起」。
这不是渲染能干的事 —— 让视频模型去长一副墨镜出来，每一帧的形状都会变。
定格一帧再贴静态图，形状 100% 稳定。

**为什么要按锚点贴，不能手动摆**：手动摆每次位置都不一样，改一版就得重摆。
资产的 cells.json 里给了 `anchor_xy`（裁格之后的局部坐标）：墨镜的锚点是
两镜片中心连线的中点，对准鼻梁；雪茄的锚点是圆头茄帽端，对准嘴角。
缩放按两眼间距算，人脸大小变了贴图跟着变。

人脸关键点用 OpenCV 的 Haar 级联找眼睛 —— 装个 dlib/mediapipe 不值当，
这一镜的末帧本来就要求「正面、居中、静止」（分镜 SH21 的验收标准），
正脸检测在这个条件下很稳。检测失败就报错退出，**不猜位置**：
猜歪了的墨镜比没有墨镜难看得多。

  .venv/bin/python scripts/finale_overlay.py --project 搞笑办公室连续剧1 --ep 1
  .venv/bin/python scripts/finale_overlay.py --project 搞笑办公室连续剧1 --ep 1 --preview
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
      if os.path.exists("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg") else "ffmpeg")


def cell(assets, aid, key):
    for sub in ("prop", "char", "wardrobe", "location"):
        d = os.path.join(assets, sub, aid)
        if os.path.isdir(d):
            break
    else:
        sys.exit(f"找不到资产 {aid}")
    cj = json.load(open(os.path.join(d, "cells.json"), encoding="utf-8"))
    c = next((x for x in cj["cells"] if x["key"] == key), None)
    if not c:
        sys.exit(f"{aid} 没有格位 {key}")
    x, y, w, h = c["bbox"]
    im = Image.open(os.path.join(d, "sheet.png")).convert("RGBA").crop((x, y, x + w, y + h))
    ax, ay = c.get("anchor_xy") or (w // 2, h // 2)
    return im, (ax, ay)


def find_eyes(png):
    """返回 (左眼中心, 右眼中心)。找不到就退出 —— 不猜。"""
    try:
        import cv2
    except ImportError:
        sys.exit("需要 opencv：.venv/bin/pip install opencv-python-headless")
    import numpy as np
    img = cv2.imread(png)
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    eyes = casc.detectMultiScale(grey, 1.1, 12, minSize=(img.shape[1] // 40,) * 2)
    # 只保留画面上半部的候选，按面积取最大的两个，再按 x 排序
    eyes = [e for e in eyes if e[1] + e[3] / 2 < img.shape[0] * 0.6]
    if len(eyes) < 2:
        sys.exit(f"末帧上没找到两只眼睛（找到 {len(eyes)} 个候选）。"
                 f"SH21 的验收标准是「正面、居中、静止」，检测不到说明这一镜"
                 f"没达标，先重渲，别硬贴。")
    eyes = sorted(sorted(eyes, key=lambda e: -e[2] * e[3])[:2], key=lambda e: e[0])
    return [(int(e[0] + e[2] / 2), int(e[1] + e[3] / 2)) for e in eyes]


def paste(base, im, anchor, target_xy, scale):
    w, h = int(im.width * scale), int(im.height * scale)
    im = im.resize((w, h), Image.LANCZOS)
    ax, ay = anchor[0] * scale, anchor[1] * scale
    base.alpha_composite(im, (int(target_xy[0] - ax), int(target_xy[1] - ay)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--shot", default=None, help="默认取分镜里带 post 字段的那一镜")
    ap.add_argument("--seconds", type=float, default=2.2, help="定格保持多久")
    ap.add_argument("--preview", action="store_true", help="只出贴好的静帧，不出视频")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    sh = (next((x for x in sb["shots"] if x["id"] == a.shot), None) if a.shot else
          next((x for x in sb["shots"] if x.get("post")), None))
    if not sh:
        sys.exit("分镜里没有带 post 字段的镜头")

    src = os.path.join(proj, "render_api", epid, f"{sh['id']}.mp4")
    if not os.path.exists(src):
        sys.exit(f"缺素材 {src}")
    out = os.path.join(proj, "render_api", epid)
    last = os.path.join(out, f"{sh['id']}_lastframe.png")
    subprocess.run([FF, "-y", "-v", "error", "-sseof", "-0.1", "-i", src,
                    "-update", "1", "-frames:v", "1", last], check=True)

    (lx, ly), (rx, ry) = find_eyes(last)
    eye_gap = rx - lx
    mid = ((lx + rx) // 2, (ly + ry) // 2)
    print(f"末帧眼距 {eye_gap}px，鼻梁位 {mid}")

    assets = os.path.join(proj, "assets")
    base = Image.open(last).convert("RGBA")

    glasses, g_anchor = cell(assets, "PROP-墨镜", "front")
    # 墨镜宽度约等于 2.6 倍眼距（普通墨镜略宽于两眼外眼角）
    paste(base, glasses, g_anchor, mid, eye_gap * 2.6 / glasses.width)

    cigar, c_anchor = cell(assets, "PROP-雪茄", "in-mouth")
    # 嘴角：鼻梁往下约 1.15 倍眼距，往左偏 0.35 倍眼距
    mouth = (int(mid[0] - eye_gap * 0.35), int(mid[1] + eye_gap * 1.15))
    paste(base, cigar, c_anchor, mouth, eye_gap * 1.9 / cigar.width)

    dst_png = os.path.join(out, f"{sh['id']}_finale.png")
    base.convert("RGB").save(dst_png)
    print(f"贴好的定格 → {dst_png}")
    if a.preview:
        return

    dst = os.path.join(out, f"{sh['id']}_finale.mp4")
    subprocess.run([FF, "-y", "-v", "error", "-loop", "1", "-i", dst_png,
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{a.seconds}", "-vf", "scale=1280:720",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", dst], check=True)
    print(f"定格片段 {a.seconds}s → {dst}")


if __name__ == "__main__":
    main()
