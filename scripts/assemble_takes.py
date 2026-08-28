#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长镜版装配：拼片 + 用 ASR 时间戳排字幕 + 烧字幕。剧目无关。

**字幕轴取自成片的 ASR 时间戳，文本取自分镜原文。** 两边各取所长：
时间戳只有真实音频知道，文本只有分镜知道（ASR 会写错字、会输出繁体）。

上一版靠 `silencedetect` 找人声段来定轴，三种病：
  掌声、笑声是宽带瞬态，落在 200–3400Hz 里被当成人声 → 字幕比台词早 0.9 秒
  一句台词被剪辑点切掉开头，字幕却还是整句 → 字幕说了音频里没有的话
  长句按字数硬拆两条 → 一句话闪两下

  .venv/bin/python scripts/assemble_takes.py --project 搞笑办公室连续剧1 --ep 1
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

from zhconv import convert

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
FF = ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
      if os.path.exists("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg") else "ffmpeg")


def key():
    return keys.fal()


def han(s):
    return re.sub(r"[^一-鿿]", "", convert(s or "", "zh-cn"))


def ts(v):
    return (f"{int(v//3600):02d}:{int(v%3600//60):02d}:"
            f"{int(v%60):02d},{int(round((v-int(v))*1000)):03d}")


def asr_chunks(mp4):
    """取带时间戳的语音段。网络部分走 provider。"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    subprocess.run([FF, "-v", "error", "-y", "-i", mp4, "-vn", "-ac", "1",
                    "-ar", "16000", wav], check=True)
    t, err = provider.transcribe(wav, chunk_level="segment")
    os.unlink(wav)
    if err:
        sys.exit(f"ASR 失败：{err}")
    out = []
    for c in t.get("chunks", []):
        a, b = (c.get("timestamp") or [None, None])[:2]
        if a is None:
            continue
        out.append([float(a), float(b if b else a + 1.0), han(c.get("text", ""))])
    return out


def align(lines, chunks):
    """把分镜台词按顺序贴到 ASR 段上。

    **按顺序贪心，不做全局最优** —— 台词顺序是确定的，一句一句往下走就行。
    一句台词可能被 ASR 切成几段（它按停顿切），所以要允许一句吃掉连续多段。
    """
    cues, ci = [], 0
    for text in lines:
        want = han(text)
        if not want:
            continue
        best = None
        # 从当前位置起，试着用 1..3 段拼出这句话
        for span in (1, 2, 3):
            if ci + span > len(chunks):
                break
            got = "".join(c[2] for c in chunks[ci:ci + span])
            hit = sum(1 for ch in want if ch in got) / len(want)
            if best is None or hit > best[0]:
                best = (hit, span)
        if not best or best[0] < 0.5:
            print(f"    对不上，跳过字幕：「{text}」")
            continue
        span = best[1]
        a, b = chunks[ci][0], chunks[ci + span - 1][1]
        cues.append((text.strip("（）() "), a, b))
        ci += span
    return cues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--sb", default=None)
    ap.add_argument("--no-subs", action="store_true")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sbname = a.sb or f"{epid}_v2.json"
    sb = json.load(open(os.path.join(proj, "分镜", sbname), encoding="utf-8"))
    src = os.path.join(proj, "render_api", os.path.splitext(sbname)[0])
    out = os.path.join(proj, "交付")
    os.makedirs(out, exist_ok=True)
    tag = os.path.splitext(sbname)[0]

    parts = []
    for sh in sb["shots"]:
        p = os.path.join(src, f"{sh['id']}.mp4")
        if not os.path.exists(p):
            sys.exit(f"缺素材 {p}")
        parts.append(p)

    tmp = os.path.join(proj, ".asm", tag)
    os.makedirs(tmp, exist_ok=True)
    lst = os.path.join(tmp, "concat.txt")
    # 逐段统一采样率和画幅再拼 —— 直接 concat 不同参数的流会炸
    norm = []
    for i, p in enumerate(parts):
        d = os.path.join(tmp, f"{i:02d}.mp4")
        subprocess.run([FF, "-y", "-v", "error", "-i", p,
                        "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-vf", "scale=1280:720", "-r", "24",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", d],
                       check=True)
        norm.append(d)
    open(lst, "w").write("".join(f"file '{os.path.abspath(x)}'\n" for x in norm))
    final = os.path.join(out, f"{epid}_长镜版.mp4")
    subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-af", "aresample=48000,alimiter=limit=0.95,"
                           "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                    "-c:a", "aac", "-b:a", "192k", final], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0", final],
                               capture_output=True, text=True).stdout.strip())
    print(f"成片 {final}  {dur:.1f}s（{len(parts)} 段）")
    if a.no_subs:
        return

    print("跑 ASR 取时间戳…")
    chunks = asr_chunks(final)
    lines = []
    for sh in sb["shots"]:
        for ln in (sh.get("lines") or []):
            lines.append(ln["text"])
        if not sh.get("lines"):
            d = sh.get("dialogue") or {}
            if d.get("text") and not d.get("is_os"):
                lines.append(d["text"])
    if not lines:
        # 兜底才从 prompt 里抠，而且只抠中文段 —— 英文里没有句号，
        # 用 [^。]* 会一路吞掉整段提示词，字幕里就印出英文（踩过）
        for sh in sb["shots"]:
            lines += re.findall(
                r"says in Chinese: ([\u4e00-\u9fff0-9，、；：！？…—·「」（）]+[。！？]?)",
                sh["render"]["prompt"])
    cues = align(lines, chunks)

    # 字幕卡不跟人声走，单独按分镜给的时间放
    clock = 0.0
    for sh in sb["shots"]:
        sc = sh.get("subtitle_card")
        if sc:
            st = clock + float(sc.get("at", 0))
            cues.append((sc["text"], st, min(st + float(sc.get("seconds", 1.2)), dur)))
        clock += float(sh["seconds"])

    cues.sort(key=lambda x: x[1])
    srt = os.path.join(out, f"{epid}_长镜版.srt")
    open(srt, "w").write("".join(
        f"{i}\n{ts(s0)} --> {ts(s1)}\n{t}\n\n"
        for i, (t, s0, s1) in enumerate(cues, 1)))
    print(f"字幕 {len(cues)} 条 → {srt}")

    h = 720
    style = (f"FontName=Songti SC,FontSize={int(h*0.033)},"
             f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
             f"Outline=2,Shadow=1,Alignment=2,MarginV={int(h*0.045)}")
    burned = os.path.join(out, f"{epid}_长镜版_字幕.mp4")
    r = subprocess.run([FF, "-y", "-v", "error", "-i", final,
                        "-vf", f"subtitles={srt}:force_style='{style}'",
                        "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-c:a", "copy", burned], capture_output=True, text=True)
    print(f"字幕版 {burned}" if not r.returncode else f"烧字幕失败 {r.stderr[-200:]}")


if __name__ == "__main__":
    main()
