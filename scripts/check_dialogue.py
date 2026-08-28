#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐镜 ASR 回读，比对分镜里的台词原文。剧目无关。

**为什么必须机器验**：Seedance 的 `generate_audio=true` 一定会出声，
prompt 里没给台词它就自己编，而且编得挺像那么回事 —— 光听不对着文本看
根本发现不了。EP001 第一句「为什么你的简历会比别人小一号呢」被编成了
「你有什么办法」，那是全集的钩子，是 ASR 回读才抓出来的。

比对用「去标点后的字符集重合度」，不做精确匹配 —— ASR 的同音字选择
（坐/做、的/得）不是错误。低于阈值才报。**先繁转简**：whisper 时不时
整句输出繁体，内容一字不差却会被字符比对判成 57% 重合。

无台词的镜头**不能直接信 ASR**。whisper 在近似静音的音轨上会幻听出
「谢谢大家」「请点赞订阅」这类字幕组套话 —— EP001_SH09 就报过一次，
一量语音频段 mean −52.7dB，跟判为干净的 SH02（−48.0dB）一个量级，
音轨里根本没人说话。所以先量能量，够响才去看 ASR 说了什么。

笑声、喘息这类非语言发声不算「冒出人声」：分镜的 sound_en 里写了
laugh/breath/gasp 的，ASR 转出「哈哈哈」是对的，不是事故。

  .venv/bin/python scripts/check_dialogue.py --project 搞笑办公室连续剧1 --ep 1
"""
import argparse
import concurrent.futures as cf
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
MAX_JOBS = 10
PASS = 0.75          # 字符重合度及格线
QUIET_DB = -45.0     # 语音频段 mean 低于这个值就当静音，不信 ASR 的幻听
NONVERBAL = ("laugh", "laughter", "breath", "gasp", "sigh", "chuckle", "exhale")


def key():
    return keys.fal()


def clean(s):
    # 先繁转简：whisper 有时整句输出繁体，内容对但字符比对会判不及格
    return re.sub(r"[^一-鿿]", "", convert(s or "", "zh-cn"))


def voice_db(mp4):
    """语音频段（200–3400Hz）的平均电平。用来判「这一镜到底有没有人在说话」。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", mp4, "-af",
         "highpass=f=200,lowpass=f=3400,volumedetect", "-f", "null", os.devnull],
        capture_output=True, text=True).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r)
    return float(m.group(1)) if m else -99.0


def overlap(want, got):
    """字符集重合度。同音字（坐/做）会扣分但不致命，整句跑偏才会掉到线下。"""
    w, g = clean(want), clean(got)
    if not w:
        return 1.0
    hit = sum(1 for c in w if c in g)
    return hit / len(w)


def asr(mp4):
    """抽音轨 → ASR。网络部分走 provider，换供应商时这里不用动。"""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vn",
                    "-ac", "1", "-ar", "16000", wav], check=True)
    try:
        t, err = provider.transcribe(wav)
        if err:
            raise RuntimeError(err)
        return (t.get("text") or "").strip()
    finally:
        os.unlink(wav)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=MAX_JOBS)
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    src = os.path.join(proj, "render_api", epid)
    sb_by_id = {x["id"]: x for x in sb["shots"]}

    jobs = []
    for sh in sb["shots"]:
        d = sh.get("dialogue") or {}
        mp4 = os.path.join(src, f"{sh['id']}.mp4")
        if not os.path.exists(mp4):
            continue
        # 无台词的镜也要验 —— 该静音的地方冒出人声同样是事故
        jobs.append((sh["id"], d.get("text", "") if not d.get("is_os") else "", mp4))

    def work(j):
        sid, want, mp4 = j
        try:
            return sid, want, asr(mp4), voice_db(mp4), None
        except Exception as e:
            return sid, want, "", -99.0, f"{type(e).__name__}: {str(e)[:80]}"

    bad = []
    with cf.ThreadPoolExecutor(max_workers=max(1, min(MAX_JOBS, a.jobs))) as ex:
        for sid, want, got, db, err in ex.map(work, jobs):
            if err:
                print(f"  ? {sid} ASR 失败：{err}")
                continue
            if not want:
                snd = ((sb_by_id[sid].get("render") or {}).get("sound_en") or "").lower()
                nonverbal = any(w in snd for w in NONVERBAL)
                if db < QUIET_DB:
                    print(f"  ✓ {sid} 无台词，音轨干净（{db:.1f}dB）")
                elif nonverbal:
                    print(f"  ✓ {sid} 无台词，是分镜里写的笑声/呼吸（{db:.1f}dB）")
                elif len(clean(got)) >= 4:
                    bad.append((sid, "（这一镜没有台词）", got))
                    print(f"  ✗ {sid} 无台词镜里冒出人声（{db:.1f}dB）：「{got}」")
                else:
                    print(f"  ✓ {sid} 无台词，音轨干净（{db:.1f}dB）")
                continue
            r = overlap(want, got)
            if r < PASS:
                bad.append((sid, want, got))
                print(f"  ✗ {sid} 重合 {r * 100:.0f}%\n      要求「{want}」\n      听到「{got}」")
            else:
                print(f"  ✓ {sid} 重合 {r * 100:.0f}%  「{got}」")

    print()
    if bad:
        print(f"{len(bad)} 镜台词对不上，重渲这几镜：")
        print("  --only " + ",".join(x[0] for x in bad))
        sys.exit(1)
    print("全部对上")


if __name__ == "__main__":
    main()
