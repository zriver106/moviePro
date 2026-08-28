#!/usr/bin/env python3
"""数成片里切了几次镜。**「一镜到底」这件事之前只能靠人眼数。**

## 为什么要有它

009 实测出一条很值钱的规律：

    25 个时间切片，每片各带一条运镜指令  →  切点 17 个
     7 个时间切片，每片一条连贯路径      →  切点 2 个

也就是说**模型按「运镜指令的条数」理解镜头数，不是按切片数**。
但这条规律当时是人一帧帧数出来的 —— **规律要能被便宜地复测，
否则下次改了 prompt 没人验得起，它就退化成传说。**

## 判据

ffmpeg 的场景变化分数：相邻两帧的差异，0–1。超过阈值算一个切点。

阈值不是常数，按内容定（`video-analyzer-skill` 的经验，我们照用）：

    0.1   静态内容（对话、演示、文档）
    0.3   默认
    0.4   快动作（打斗、游戏、体育）

**打斗片必须用 0.4。** 用 0.3 去数打戏，剑挥过去的那一帧就会被当成切镜 ——
把「动作快」误判成「切镜多」，然后照着一个假数字去改 prompt。

## 它测不出什么

场景分数只看**相邻两帧差多少**，不理解语义。所以：

- 一次硬切和一次极快的甩镜，分数上可能一样 —— 需要人看一眼输出的时间戳
- 同机位换人（克隆事故）分数很低，**这个指标抓不到**，那是关键帧的活
- 淡入淡出的转场分数是分散的小值，可能一个都不超阈值

**它回答的是「画面在第几秒突然变了」，不是「这里该不该切」。**

  python3 scripts/check_cuts.py 成片.mp4
  python3 scripts/check_cuts.py 成片.mp4 --threshold 0.4     # 打戏
  python3 scripts/check_cuts.py a.mp4 b.mp4 --expect 1       # 一镜到底，超了退出码 1
"""
import argparse
import os
import re
import subprocess
import sys


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def cuts(path, thr):
    """返回切点时间戳列表（秒）。

    走 showinfo 而不是 metadata=print —— 后者在有些 ffmpeg 构建上不输出
    pts_time，静默给出空结果，而空结果长得像「零切点」，
    正是我们最怕的那种「看起来合理的错数据」。
    """
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-vf", f"select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True)
    ts = [float(m.group(1)) for m in
          re.finditer(r"pts_time:([0-9.]+)", p.stderr)]
    return sorted(ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.4,
                    help="场景变化阈值。打戏 0.4、默认 0.3、静态内容 0.1。"
                         "默认给 0.4 是因为我们现在做的就是打戏")
    ap.add_argument("--expect", type=int,
                    help="期望的最大切点数。超了退出码 1（一镜到底就填 0 或 1）")
    a = ap.parse_args()

    bad = []
    for v in a.videos:
        if not os.path.exists(v):
            print(f"  ✗ {v} 不存在")
            bad.append(v)
            continue
        d = duration(v)
        ts = cuts(v, a.threshold)
        name = os.path.basename(v)
        rate = f"{len(ts) / d * 60:.1f} 次/分钟" if d else "—"
        print(f"\n{name}  {d:.2f}s  阈值 {a.threshold}")
        print(f"  切点 {len(ts)} 个   {rate}")
        if ts:
            head = "、".join(f"{t:.2f}s" for t in ts[:12])
            print(f"  时间戳: {head}{' …' if len(ts) > 12 else ''}")
            gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
            if gaps:
                print(f"  相邻间隔: 最短 {min(gaps):.2f}s  最长 {max(gaps):.2f}s")
                # 间隔特别短的一批往往不是切镜，是同一次快速运动被拆成几帧
                tight = sum(1 for g in gaps if g < 0.35)
                if tight:
                    print(f"  ⚠ {tight} 处间隔 <0.35s —— 这类多半是一次快速运动"
                          f"被拆成几帧，不是真切镜。要么调高阈值，要么人看一眼")
        if a.expect is not None and len(ts) > a.expect:
            print(f"  ✗ 超出期望 {a.expect}")
            bad.append(name)

    if bad:
        print(f"\n{len(bad)} 条超出期望或缺失")
        sys.exit(1)


if __name__ == "__main__":
    main()
