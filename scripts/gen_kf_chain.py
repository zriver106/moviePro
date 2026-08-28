#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连续动作的首末帧链：用上一镜的**成片末帧**去生成下一镜的关键帧。剧目无关。

**为什么单独一层**：`gen_kf.py` 每一镜独立合成，跨镜的东西不会传递。
EP001 实测穿帮 —— 领导站起来（SH11 末帧椅子在他左边）→ SH13 椅子又近又大
→ SH14 首帧椅子更远更小 → SH14 末帧他坐下时**椅子瞬移到他身下**，
画面左边还多出一把灰色访客椅。椅子自己在画面里走动。

分镜里本来就有 `continuity_out`（「他站着，椅子空着并往后偏了一点」），
但那是写给人看的，没有任何一步把它变成约束。

这一层做两件事：

  1. 下一镜的关键帧**从上一镜的成片末帧改出来** —— 房间、家具位置、人的站位
     天然继承，只改该改的那一点（手放下、坐下去）
  2. 给动作镜配 `<shot>_last.png`，渲染时走 `end_image_url` ——
     站起来 / 坐下去这种有明确终点的镜头，两端都钉住，中间就没得乱来

配置写在分镜的 `chain` 字段里：

    "chain": {"from": "EP001_SH11", "edit": "他把手放下……（英文）"}
    "chain_last": {"from": "self", "edit": "他坐进椅子里……（英文）"}

  .venv/bin/python scripts/gen_kf_chain.py --project 搞笑办公室连续剧1 --ep 1
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import provider          # 所有出图/出片/ASR 只从这里走
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处


STILL = ("Cinematic film still from a live-action comedy series, photorealistic, "
         "16:9 landscape, fine film grain, natural skin texture, sharp focus. ")
KEEP = ("The room, the wall, the window, the carpet, the desk and every piece of "
        "furniture stay exactly where they are in <Picture 1>, at exactly the same "
        "size and the same position in frame, under exactly the same light. The camera "
        "stays in exactly the same place at the same distance and the same angle. ")


def key():
    return keys.fal()


def data_uri(p):
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


def edit(prompt, uris, seed):
    """出图只从 provider 走 —— 换供应商时业务脚本不用动。"""
    url, err = provider.edit_image(prompt, uris, seed=seed)
    return ({"images": [{"url": url}]}, None) if url else (None, err)


def last_frame(mp4, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", mp4,
                    "-update", "1", "-frames:v", "1", dst], check=True)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--seed", type=int, default=80131)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    kfdir = os.path.join(proj, "keyframes", epid)
    rdir = os.path.join(proj, "render_api", epid)
    tmp = os.path.join(proj, "out", "chain")
    os.makedirs(tmp, exist_ok=True)

    def source_png(ref, sid):
        """`self` 取这一镜自己的关键帧；镜号取那一镜的**成片末帧**。"""
        if ref == "self":
            return os.path.join(kfdir, f"{sid}.png")
        mp4 = os.path.join(rdir, f"{ref}.mp4")
        if os.path.exists(mp4):
            return last_frame(mp4, os.path.join(tmp, f"{ref}_last.png"))
        # 上一镜还没渲，退回它的关键帧 —— 但要说清楚，别当成一回事
        p = os.path.join(kfdir, f"{ref}.png")
        print(f"    （{ref} 还没成片，用它的关键帧代替）")
        return p if os.path.exists(p) else None

    for sh in sb["shots"]:
        sid = sh["id"]
        for field, suffix in (("chain", ""), ("chain_last", "_last")):
            cfg = sh.get(field)
            if not cfg:
                continue
            src = source_png(cfg["from"], sid)
            if not src:
                print(f"  ✗ {sid}{suffix} 找不到来源 {cfg['from']}")
                continue
            prompt = STILL + KEEP + cfg["edit"]
            dst = os.path.join(kfdir, f"{sid}{suffix}.png")
            if a.dry_run:
                print(f"\n{'=' * 70}\n{sid}{suffix}  ← {cfg['from']}  ({src})")
                print(prompt)
                continue
            r, err = edit(prompt, [data_uri(src)], a.seed)
            if err:
                print(f"  ✗ {sid}{suffix} {err}")
                continue
            url = (r.get("images") or [{}])[0].get("url")
            urllib.request.urlretrieve(url, dst)
            print(f"  ✓ {sid}{suffix} ← {cfg['from']} → {dst}")


if __name__ == "__main__":
    main()
