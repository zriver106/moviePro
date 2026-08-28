#!/usr/bin/env python3
"""按剪辑点拼片 + 烧中文字幕。第一集重做后的成片装配。

为什么需要剪辑点：MiniMax H3 官方 API 最短出 6 秒，而分镜是 2–5 秒，
每镜都多出一截。cuts.json 里逐镜给了 in/out/speed，算法是**滑窗取动作
总量最大的一段**，不是把峰值居中 —— SH04 的三拍是「电弧→颤抖→仰倒」，
差分最高点落在最后的仰倒，峰值居中会把 3.3 秒的电弧整个剪掉，
而电弧是这一集穿越的唯一因果。

字幕用本机 ffmpeg-full（带 libass）。系统自带的 ffmpeg 没编 subtitles 滤镜，
之前一直得传到 GPU 节点上烧，机器停掉之后那条路就断了。

  python3 scripts/assemble.py --ep 1
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT = "搞笑办公室连续剧1"
PROJ = os.path.join(ROOT, "projects", DEFAULT_PROJECT)
# 系统 ffmpeg 没有 subtitles 滤镜，拼片和烧字幕都走 full 版
FF = ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
      if os.path.exists("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg") else "ffmpeg")


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def ts(v):
    return (f"{int(v//3600):02d}:{int(v%3600//60):02d}:"
            f"{int(v%60):02d},{int(round((v-int(v))*1000)):03d}")


def voice_segs(video, thr=-34):
    """检出这条片子里真正有人在说话的时间段。

    字幕必须跟实际人声对齐，不能按 `dialogue.at` 估 —— 官方 H3 决定台词在
    第几秒开口，我们说了不算。而且**没有声音的镜头不该有字幕**：
    SH09/SH11 是内心独白，我们没让模型念，音轨是全静音的，
    给它们配字幕就是有字无声。

    带通到 200–3400Hz（人声主频）再测，否则电流声、水声、脚步声都会被
    当成人声 —— 实测 SH03（泼水，无台词）不带通时会检出 6 秒「人声」。
    """
    import re as _re
    r = subprocess.run([FF, "-i", video, "-af",
                        f"highpass=f=200,lowpass=f=3400,silencedetect=n={thr}dB:d=0.20",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    st = [float(x) for x in _re.findall(r"silence_start: ([\d.]+)", r)]
    en = [float(x) for x in _re.findall(r"silence_end: ([\d.]+)", r)]
    total = dur(video)
    segs, cur = [], 0.0
    for a, b in zip(st, en + [total]):
        if a - cur > 0.25:
            segs.append((cur, a))
        cur = b
    if total - cur > 0.25:
        segs.append((cur, total))
    return segs


def split_cue(text, start, span, cps=7.0, max_chars=18):
    """一句台词默认就是一条字幕，只有长到一屏放不下才切。

    上一版切得太碎：「妈的！天天催，天天熬——」被拆成三条，每条 0.3–0.8 秒，
    42 条字幕配 48 秒的片子。字幕不是逐词打拍子，它是给人读的 ——
    **一条字幕至少要挂够 1.2 秒，短句宁可整句显示。**
    """
    import re
    if len(text) <= max_chars:
        yield text.strip("，。；、 "), start, start + span
        return
    parts = [x.strip("，。；、！？ ") for x in re.split(r"(?<=[，。！？；])", text)]
    parts = [x for x in parts if x] or [text]
    # 先按「一屏装得下」合并，再看时间够不够
    merged, buf = [], ""
    for x in parts:
        cand = buf + ("，" if buf else "") + x
        if buf and (len(cand) > max_chars or
                    span * len(cand) / max(1, len(text)) < len(cand) / cps * 0.75):
            merged.append(buf)
            buf = x
        else:
            buf = cand
    if buf:
        merged.append(buf)
    # 合并后如果还有条目分不到 1.2 秒，继续两两并
    while len(merged) > 1 and span / len(merged) < 1.2:
        merged = [merged[0] + "，" + merged[1]] + merged[2:]
    tot = sum(len(x) for x in merged) or 1
    # 末段太短就并回前一条 ——「是不是」挂 0.48 秒是闪一下就没
    if len(merged) > 1 and span * len(merged[-1]) / tot < 1.0:
        merged[-2] = merged[-2] + "，" + merged[-1]
        merged.pop()
        tot = sum(len(x) for x in merged) or 1
    cur = start
    for i, x in enumerate(merged):
        end = start + span if i == len(merged) - 1 else cur + span * len(x) / tot
        if end > cur:
            yield x, cur, end
        cur = end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--project", default=DEFAULT_PROJECT,
                    help="剧目目录名，一套流水线跑多个剧目，路径不能写死")
    ap.add_argument("--no-subs", action="store_true")
    a = ap.parse_args()

    global PROJ
    PROJ = os.path.join(ROOT, "projects", a.project)

    epn = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(PROJ, "分镜", f"{epn}.json")))
    src = os.path.join(PROJ, "render_api", epn)
    cuts = json.load(open(os.path.join(src, "cuts.json")))
    if isinstance(cuts, list):
        cuts = {c.get("shot") or c.get("id"): c for c in cuts}

    tmp = os.path.join(PROJ, ".asm", epn)
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(os.path.join(PROJ, "交付"), exist_ok=True)

    parts, cues, clock = [], [], 0.0
    for sh in sb["shots"]:
        sid = sh["id"]
        v = os.path.join(src, f"{sid}.mp4")
        if not os.path.exists(v):
            print(f"  {sid} 缺素材，跳过")
            continue
        c = cuts.get(sid) or {}
        t_in = float(c.get("in", 0.0))
        t_out = float(c.get("out", min(dur(v), t_in + sh["seconds"])))
        speed = float(c.get("speed", 1.0) or 1.0)
        seg = (t_out - t_in) / speed
        out = os.path.join(tmp, f"{sid}.mp4")

        # 变速要同时处理画面和声音；setpts 用倒数，atempo 用原值
        vf = f"setpts=PTS/{speed}" if speed != 1.0 else "null"
        af = f"atempo={speed}" if speed != 1.0 else "anull"
        subprocess.run([FF, "-y", "-v", "error", "-ss", f"{t_in:.3f}",
                        "-i", v, "-t", f"{t_out - t_in:.3f}",
                        "-vf", vf, "-af", af,
                        "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                        out], check=True)
        parts.append(out)
        mark = f"  ×{speed:g}" if speed != 1.0 else ""
        print(f"  {sid}  {t_in:.2f}→{t_out:.2f}  →{seg:.2f}s{mark}")

        # 字幕：OS 和画外音也要出字幕（观众听得见就该看得见），
        # 但字幕卡是另一回事，单独排
        # 只给「真有人在说话」的镜头配字幕，起止点用实测人声段。
        # 内心独白（is_os）音轨是静音的，配了就是有字无声。
        d = sh.get("dialogue") or {}
        if d.get("text") and not d.get("is_os"):
            vs = [(a, b) for a, b in voice_segs(v) if t_in - 0.15 < b and a < t_out + 0.15]
            if vs:
                a0 = max(t_in, min(x[0] for x in vs))
                b0 = min(t_out, max(x[1] for x in vs))
                st = clock + max(0.0, (a0 - t_in) / speed)
                span = max(1.0, (b0 - a0) / speed)
                for x, s0, s1 in split_cue(d["text"], st, span):
                    cues.append((x, s0, min(s1, clock + seg)))
            else:
                print(f"    {sid} 标了台词但音轨里没有人声，跳过字幕")
        sc = sh.get("subtitle_card")
        if sc:
            st = clock + float(sc.get("at", 0)) / speed
            cues.append((sc["text"], st, min(st + float(sc.get("seconds", 1.2)),
                                             clock + seg)))
        clock += seg

    if not parts:
        sys.exit("没有可用素材")

    lst = os.path.join(tmp, "concat.txt")
    open(lst, "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in parts))
    final = os.path.join(PROJ, "交付", f"{epn}.mp4")
    subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-af", "aresample=48000,alimiter=limit=0.95,"
                           "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                    "-c:a", "aac", "-b:a", "192k", final], check=True)
    total = dur(final)
    print(f"\n成片 {final}  {total:.1f}s（{len(parts)} 镜）")

    srt = os.path.join(PROJ, "交付", f"{epn}.srt")
    cues.sort(key=lambda x: x[1])
    open(srt, "w").write("".join(
        f"{i}\n{ts(s0)} --> {ts(s1)}\n{t}\n\n"
        for i, (t, s0, s1) in enumerate(cues, 1)))
    print(f"字幕 {len(cues)} 条 → {srt}（末条 {cues[-1][2]:.1f}s / 片长 {total:.1f}s）")
    if cues[-1][2] > total + 0.5:
        print("  ⚠ 字幕越界，拒绝烧录"); return

    if a.no_subs:
        return
    # 字号取画面高度 3.3%，再大就抢画面；描边保证浅背景上也读得清
    h = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v",
                            "-show_entries", "stream=height", "-of", "csv=p=0", final],
                           capture_output=True, text=True).stdout.strip() or 768)
    style = (f"FontName=Songti SC,FontSize={max(16, int(h*0.033))},"
             f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
             f"Outline=2,Shadow=1,Alignment=2,MarginV={int(h*0.045)}")
    burned = os.path.join(PROJ, "交付", f"{epn}_字幕版.mp4")
    r = subprocess.run([FF, "-y", "-v", "error", "-i", final,
                        "-vf", f"subtitles={srt}:force_style='{style}'",
                        "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-c:a", "copy", burned], capture_output=True, text=True)
    if r.returncode:
        print(f"  烧字幕失败：{r.stderr[-200:]}")
    else:
        print(f"字幕版 {burned}")


if __name__ == "__main__":
    main()
