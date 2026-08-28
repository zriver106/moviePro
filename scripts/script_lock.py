#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本定稿闸。**拿到剧本做任何事之前，先过这一步。** 剧目无关。

## 为什么要有

剧本医生只判「有没有逻辑漏洞」，判完没有任何地方声明「这一版定了」。
于是剧本还在改，分镜和资产已经开做 —— 改一句台词，上游全废。

更隐蔽的是**改了剧本但下游没重跑**：分镜、关键帧、成片都还是旧剧本的产物，
每一层单独看都正常，只有并排看才发现对不上。这跟「声景没跟着 action_start
重算」是同一个病 —— 源字段变了，派生的东西不知道。

所以定稿记的是**内容指纹**，不是一句「定了」：剧本一改，指纹就对不上，
下游立刻报错。

## 怎么用

    # 看状态
    .venv/bin/python scripts/script_lock.py --project 漫剧战斗样片 --ep 1

    # 定稿（要求剧本医生判过 PASS）
    .venv/bin/python scripts/script_lock.py --project 漫剧战斗样片 --ep 1 --lock

    # 剧本改了之后重新定稿
    .venv/bin/python scripts/script_lock.py --project 漫剧战斗样片 --ep 1 --relock \\
        --note "补了第二幕的动机"

下游脚本 `import script_lock; script_lock.require(proj, ep)` 一行接进去。
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def paths(project, ep):
    base = os.path.join(ROOT, "projects", project)
    return (os.path.join(base, "剧本", f"EP{ep:03d}.md"),
            os.path.join(base, "剧本", ".lock.json"),
            os.path.join(base, "out", "doctor", f"EP{ep:03d}.json"))


def digest(p):
    """指纹只按**内容**算，不含改动时间 —— 换行改一下不该判成改稿，
    但一个字改了必须判出来。所以先规范化空白再哈希。"""
    txt = io.open(p, encoding="utf-8").read()
    norm = "\n".join(line.rstrip() for line in txt.split("\n")).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def load(lockp):
    if not os.path.exists(lockp):
        return {}
    return json.load(io.open(lockp, encoding="utf-8"))


def state(project, ep):
    """返回 (状态, 说明)。状态是 locked / stale / unlocked / missing。"""
    sp, lockp, docp = paths(project, ep)
    if not os.path.exists(sp):
        return "missing", f"剧本不存在：{sp}"
    rec = load(lockp).get(f"EP{ep:03d}")
    if not rec:
        return "unlocked", "还没定稿"
    now = digest(sp)
    if now != rec["digest"]:
        return "stale", (f"**剧本在定稿之后改过** —— 定稿时 {rec['digest']}，"
                         f"现在 {now}。定稿于 {rec['locked_at']}")
    return "locked", f"定稿于 {rec['locked_at']}　指纹 {now}"


def require(project, ep, what="这一步"):
    """下游的闸。**不通过就退出**，别让半成品往下走。"""
    st, msg = state(project, ep)
    if st == "locked":
        return True
    print(f"\n✗ {what}被拦下：EP{ep:03d} 的剧本没有定稿。\n  {msg}\n")
    if st == "stale":
        print("  剧本改了就意味着下游全部作废 —— 分镜、资产、关键帧、成片都是旧剧本的产物。")
        print(f"  确认改动是对的，就重新定稿：")
        print(f"    .venv/bin/python scripts/script_lock.py --project {project} "
              f"--ep {ep} --relock --note '改了什么'")
    else:
        print(f"    .venv/bin/python scripts/script_doctor.py --project {project} --ep {ep} "
              f"--out projects/{project}/out/doctor")
        print(f"    .venv/bin/python scripts/script_lock.py --project {project} --ep {ep} --lock")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--lock", action="store_true")
    ap.add_argument("--relock", action="store_true", help="剧本改过之后重新定稿")
    ap.add_argument("--note", default="", help="这一稿改了什么")
    ap.add_argument("--force", action="store_true",
                    help="剧本医生没判 PASS 也定稿。**要在 note 里写清楚为什么**")
    a = ap.parse_args()

    sp, lockp, docp = paths(a.project, a.ep)
    st, msg = state(a.project, a.ep)
    if not (a.lock or a.relock):
        icon = {"locked": "✓", "stale": "⚠", "unlocked": "○", "missing": "✗"}[st]
        print(f"{icon} EP{a.ep:03d}  {st}\n  {msg}")
        rec = load(lockp).get(f"EP{a.ep:03d}")
        if rec and rec.get("note"):
            print(f"  备注：{rec['note']}")
        sys.exit(0 if st == "locked" else 1)

    if st == "missing":
        sys.exit(msg)
    if st == "locked" and not a.relock:
        sys.exit(f"EP{a.ep:03d} 已经定稿了（{msg}）。要重新定稿加 --relock")

    # 剧本医生必须判过 PASS —— 定稿是「可以开工」的承诺，不是「我看过了」
    verdict = None
    if os.path.exists(docp):
        verdict = json.load(io.open(docp, encoding="utf-8")).get("verdict")
    if verdict != "PASS" and not a.force:
        print(f"✗ 剧本医生的判决是 {verdict or '（没跑过）'}，不是 PASS。")
        print(f"  先跑：.venv/bin/python scripts/script_doctor.py --project {a.project} "
              f"--ep {a.ep} --out projects/{a.project}/out/doctor")
        print(f"  确实要带着已知问题开工，用 --force 并在 --note 里写清楚为什么。")
        sys.exit(1)
    if a.force and not a.note:
        sys.exit("✗ --force 必须配 --note 写清楚为什么带着问题开工")

    d = load(lockp)
    prev = d.get(f"EP{a.ep:03d}")
    d[f"EP{a.ep:03d}"] = {
        "digest": digest(sp),
        "locked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "doctor_verdict": verdict,
        "note": a.note,
        "forced": bool(a.force),
        "previous_digest": prev["digest"] if prev else None,
    }
    os.makedirs(os.path.dirname(lockp), exist_ok=True)
    json.dump(d, io.open(lockp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✓ EP{a.ep:03d} 已定稿　指纹 {d[f'EP{a.ep:03d}']['digest']}　"
          f"医生判决 {verdict}")
    if prev:
        print(f"  上一稿 {prev['digest']} → 这一稿 {d[f'EP{a.ep:03d}']['digest']}")
        print(f"  **改稿意味着下游全部作废** —— 分镜、资产、关键帧、成片都要重来一遍。")


if __name__ == "__main__":
    main()
