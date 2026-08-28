#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按动作峰值算每镜的剪辑入点/出点，写 render_api/EPxxx/cuts.json。

**为什么需要这一步**：MiniMax H3 官方 API 最短只出 6 秒，而分镜里的镜头是
2–5 秒。每镜都会多出一截，拼片的时候必须知道该留哪一段 —— 留错了，动作那
一下（拍键盘、触电、夺簪）就被剪掉了。

怎么定这一段：

  1. **动作峰值**（逐帧差分最大的时刻）是这一镜的重心。把它放在窗口靠后
     一点的位置（默认 55%），因为动作要有前摇、余韵可以短。
  2. **有台词的镜头，窗口必须罩住台词**。台词是 H3 音画一起生的，剪断了
     就是半句话。用 0.1 秒一格的 RMS 找出人声段，再把窗口撑开去包住它。
     台词比目标时长还长时，宁可延长这一镜（记在 note 里），也别切半句。
  3. 窗口夹在 [0, 时长] 里，越界就整体平移。

用法：
  python3 scripts/cut_points.py --ep 1
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT = "搞笑办公室连续剧1"
PROJ = os.path.join(ROOT, "projects", DEFAULT_PROJECT)

PEAK_POS = 0.55        # 峰值落在窗口的哪个位置
PAD = 0.12             # 台词前后各留这么多秒


def duration_of(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", mp4], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def motion_curve(mp4):
    """逐帧差分曲线（24fps 一格一个值）。跟 render_api_ep.qc 同口径。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", mp4, "-vf",
         "scale=64:36,format=gray,tblend=all_mode=difference,signalstats,"
         "metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
        capture_output=True, text=True)
    return [float(m.group(1)) for m in
            re.finditer(r"lavfi\.signalstats\.YAVG=([\d.]+)", r.stdout)]


def best_window(vals, target, fps=24.0):
    """滑窗求**动作总量最大**的一段，返回 (起点秒, 窗内动作占全片比例)。

    为什么不是「把峰值摆到窗口中间」：一镜往往有好几拍。SH04 是
    「电弧 → 颤抖 → 仰倒」三拍，逐帧差分的最高点落在最后的仰倒（6.04s），
    按峰值居中会把 3.3s 的电弧整个剪掉 —— 而电弧才是这一集穿越的因果。
    取动作总量最大的窗口，多拍的镜头才不会只保住最后一拍。
    """
    n = int(round(target * fps))
    if not vals or n >= len(vals):
        return 0.0, 1.0
    pre = [0.0]
    for v in vals:
        pre.append(pre[-1] + v)
    total = pre[-1] or 1.0
    best_i, best_s = 0, -1.0
    for i in range(len(vals) - n + 1):
        s = pre[i + n] - pre[i]
        if s > best_s:
            best_i, best_s = i, s
    return round(best_i / fps, 2), round(best_s / total, 3)


def loud_span(mp4, drop_db=10.0, step=0.1):
    """0.1 秒一格量 RMS，返回 (起, 止)：响度在峰值 drop_db 以内的第一格和最后一格。

    只用来找**人声段的大致范围**，不做 VAD —— 台词镜里最响的就是台词，
    环境音（布料、呼吸）比它低十几个 dB，这个粗判够用了。
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", mp4, "-af",
         "aresample=16000,asetnsamples=1600,astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(m.group(1)) for m in
            re.finditer(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+)", r.stdout)]
    if not vals:
        return None
    peak = max(vals)
    hot = [i for i, v in enumerate(vals) if v >= peak - drop_db]
    if not hot:
        return None
    return round(hot[0] * step, 2), round((hot[-1] + 1) * step, 2)


def spoken_line(sh):
    """真台词才算。is_os 是内心独白（嘴不动，后期配），off_screen 是画外音，
    两种都可以在剪辑时自由摆位，不该绑住窗口。"""
    d = sh.get("dialogue")
    if not d or not (d.get("text") or "").strip():
        return None
    if d.get("is_os") or d.get("off_screen"):
        return None
    return d


# ── 人工覆盖 ────────────────────────────────────────────────────────────
# 差分只知道「哪里在动」，不知道「哪一下是这场戏的意思」。个别镜头看图之后
# 手工定入出点，每条都要写清楚为什么，以后重跑不会又被算回去。
#
# **覆盖表放在剧目里，不放在脚本里**（`projects/<剧名>/分镜/cut_override.json`）。
# 血的教训：这张表原来写死在脚本里、按镜号索引，换了一部剧之后
# `EP001_SH03` / `EP001_SH05` 的镜号正好撞上，《太子》的「水柱砸键帽」
# 和「闪回碎片 2 倍速」两条覆盖就套到了办公室戏上 —— SH05 直接被判 2 倍速。
# **脚本接了 --project 不等于它通用了**，里面埋的剧目数据也得跟着搬走。
#
# 格式：{"EP001_SH03": {"t_in": 0.5, "reason": "为什么"}}
# 可用字段 t_in / t_out / speed / reason，reason 必填。


def load_override(proj, epid):
    p = os.path.join(proj, "分镜", "cut_override.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    for k, v in d.items():
        if not v.get("reason"):
            sys.exit(f"{p} 里 {k} 没写 reason —— 人工覆盖必须写清楚为什么")
    return d


def plan(sh, mp4, OVERRIDE=None):
    OVERRIDE = OVERRIDE or {}
    dur = duration_of(mp4)
    target = float(sh["seconds"])
    vals = motion_curve(mp4)
    notes = []

    if vals:
        i = max(range(len(vals)), key=lambda k: vals[k])
        pt, pv = round((i + 1) / 24.0, 2), round(vals[i], 2)
    else:
        pt, pv = round(dur / 2.0, 2), None
        notes.append("差分算不出运动曲线，按中点取")
    start, share = best_window(vals, target)
    notes.append(f"取动作总量最大的一段，占全片动作的 {share * 100:.0f}%")

    line = spoken_line(sh)
    span = loud_span(mp4) if line else None
    if span:
        s0, s1 = span
        need = (s1 - s0) + 2 * PAD
        if need > target:
            # 罩不住。多半是这一镜的环境音／音效跟台词一样响，RMS 粗判分不开
            # （SH01 的键盘声就把整段 6 秒都算成「响」）。这时候拿它去撑窗口
            # 只会把镜头拉长、把动作挤到边上，不如老老实实按峰值取。
            notes.append(f"响度段 {s0:.2f}–{s1:.2f}s 比目标 {target:.2f}s 还长，"
                         f"判为音效而非台词，按峰值取；拼片时人耳复核一下句尾")
            span = None
        else:
            if start > s0 - PAD:
                start = s0 - PAD
            if start + target < s1 + PAD:
                start = s1 + PAD - target
            notes.append(f"窗口已罩住人声段 {s0:.2f}–{s1:.2f}s")

    start = max(0.0, min(start, dur - target))
    end = min(dur, start + target)
    speed = 1.0

    ov = OVERRIDE.get(sh["id"])
    if ov:
        start = ov.get("t_in", start)
        end = ov.get("t_out", start + target)
        speed = ov.get("speed", 1.0)
        target = round((end - start) / speed, 2)
        notes.append(f"人工覆盖：{ov['reason']}")

    return {
        "duration": round(dur, 2),
        "target_seconds": round(target, 2),
        "peak_t": pt, "peak_v": pv,
        "in": round(start, 2), "out": round(end, 2),
        "speed": speed,
        "peak_in_window": round(pt - start, 2),
        "motion_share": share,
        "loud_span": list(span) if span else None,
        "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--project", default=DEFAULT_PROJECT,
                    help="剧目目录名，一套流水线跑多个剧目，路径不能写死")
    ap.add_argument("--only")
    a = ap.parse_args()

    global PROJ
    PROJ = os.path.join(ROOT, "projects", a.project)
    ov_table = load_override(PROJ, f"EP{a.ep:03d}")
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(PROJ, "分镜", f"{epid}.json"), encoding="utf-8"))
    outdir = os.path.join(PROJ, "render_api", epid)
    only = {x.strip() for x in a.only.split(",")} if a.only else None

    cuts = {}
    p = os.path.join(outdir, "cuts.json")
    if os.path.exists(p):
        try:
            cuts = json.load(open(p, encoding="utf-8"))
        except Exception:
            cuts = {}

    total = 0.0
    for sh in sb["shots"]:
        mp4 = os.path.join(outdir, f"{sh['id']}.mp4")
        if not os.path.exists(mp4):
            print(f"  — {sh['id']} 还没有成片")
            continue
        if only and sh["id"] not in only:
            total += cuts.get(sh["id"], {}).get("target_seconds", 0)
            continue
        c = plan(sh, mp4, ov_table)
        cuts[sh["id"]] = c
        total += c["target_seconds"]
        print(f"  {sh['id']}  in={c['in']:.2f} out={c['out']:.2f} "
              f"（成片 {c['target_seconds']:.2f}s ×{c['speed']}，峰值@{c['peak_t']}s 落在窗口内 "
              f"{c['peak_in_window']:.2f}s）  {'；'.join(c['notes'])}")

    json.dump(cuts, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{p}\n合计 {total:.2f}s（分镜目标 {sb['target_seconds']}s）")


if __name__ == "__main__":
    main()
