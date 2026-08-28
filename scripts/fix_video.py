#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照着原片修片：把成片当 @Video1 喂回去，只改指定的那一样。剧目无关。

**发现小问题不要重渲整条。** 重渲是换一个种子重掷所有东西 —— 修好了这一处，
别处可能塌了，而且前面所有通过验收的镜头都要重验一遍。

## 它到底是什么

fal 上**没有独立的 video-edit 端点**。修片走的是 `reference-to-video` 的
`video_urls[]`（prompt 里用 `@Video1` 点名）。

**注意：它不是像素级的「改」，是「照着原片重做」。** 实测（2026-08-25）：
镜头结构和时序保住了（四个节拍落在同样的时间点），但细节会重掷 ——
原片一个法阵，修完成了两个；盾的位置镜像了。

所以判据是：

    能修   全局性的东西 —— 色调、肤色、背景替换、天气氛围、删掉画面里的某样东西
    不能修 只想动一帧、或要求其余像素完全不变

后者只能本机做（ffmpeg 调色、抠图叠加、裁掉那一段）。

## 端点差异（实测）

    2.5 ref2v + video_urls   **拒收含人的视频**（content_policy_violation）
    2.0 ref2v + video_urls   收，通过

所以修片一律走 2.0：上限 15 秒、720p。30 秒的片子要分段修再拼。

  .venv/bin/python scripts/fix_video.py 成片.mp4 --fix "把他的肤色改成中性日光" --seconds 6
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
import provider          # 出图/出片/ASR 只从这里走
MAX_SEC = 15          # 2.0 的上限；修片只能走 2.0

KEEP = ("Edit @Video1. Keep the camera move, the framing, the timing and the cut points "
        "of @Video1 exactly as they are. Keep every person in it exactly as they are: "
        "the same faces, the same hair, the same clothing, the same weapons and the same "
        "actions at the same moments. ")


def key():
    return keys.fal()


def upload(path, ctype="video/mp4"):
    return provider.upload(path)


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fix", required=True,
                    help="要改的那一样，英文，只写一件事")
    ap.add_argument("--start", type=float, default=0.0, help="从第几秒开始修")
    ap.add_argument("--seconds", type=float, default=None,
                    help="修多长，上限 15；不给就用整条")
    ap.add_argument("--resolution", default="720p", choices=["480p", "720p"])
    ap.add_argument("--seed", type=int, default=91101)
    ap.add_argument("--keep-audio", action="store_true",
                    help="保留原音轨（默认让模型重新生成，多半更差）")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if not os.path.exists(a.video):
        sys.exit(f"找不到 {a.video}")
    total = dur(a.video)
    seg = a.seconds or min(MAX_SEC, total - a.start)
    if seg > MAX_SEC:
        sys.exit(f"修片走 2.0，单段上限 {MAX_SEC} 秒（要修 {seg:.1f} 秒）。"
                 f"分段修再拼：--start / --seconds")

    work = a.video
    if a.start > 0 or abs(seg - total) > 0.05:
        work = os.path.join(os.path.dirname(a.video) or ".", "_fix_src.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a.start}",
                        "-t", f"{seg}", "-i", a.video, "-c:v", "libx264",
                        "-crf", "18", "-c:a", "aac", work], check=True)
        print(f"截出 {a.start:.1f}–{a.start + seg:.1f}s")

    print("上传原片…")
    src_url = upload(work)
    prompt = KEEP + f"Change one thing: {a.fix.rstrip('.')}."
    body = {"prompt": prompt, "video_urls": [url], "resolution": a.resolution,
            "duration": str(int(round(seg))), "aspect_ratio": "16:9",
            "generate_audio": False, "seed": a.seed}
    print(f"修片中（{seg:.0f}s，{a.resolution}）…")
    # 修片走 2.0 —— 2.5 拒收含人的视频
    url, err = provider.video(prompt, model="2.0", mode="ref", seconds=seg,
                              resolution=a.resolution, audio=False, seed=a.seed,
                              video_urls=[src_url])
    if err:
        sys.exit(f"✗ {err}")
    dst = a.out or a.video.replace(".mp4", "_fixed.mp4")
    provider.fetch(url, dst)

    if a.keep_audio:
        tmp = dst.replace(".mp4", "_a.mp4")
        # 修出来的片子没有音轨，把原片那一段的声音贴回去
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-i", work,
                        "-map", "0:v", "-map", "1:a?", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", tmp], check=True)
        os.replace(tmp, dst)
    print(f"✓ {dst}")
    print("\n**修完要重跑验收** —— 它是照着原片重做，细节会重掷，"
          "可能修好这处、碰坏别处。")


if __name__ == "__main__":
    main()
