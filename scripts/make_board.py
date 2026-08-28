#!/usr/bin/env python3
"""⚠ **设计权归 `/short-drama-storyboard` skill，不归这里。**

2026-08-17 才发现 `.claude/skills/` 里 8 月 14 日就装了 drama-skills，而这个脚本是在不知情的情况下重写的一遍。它有 Coverage Audition（比较真正不同的导演方案）和轴线/站位/视线/持物连续性检查，本脚本都没有。

**保留的理由**：它直接产出我们的 JSON schema，而 skill 产出 markdown，中间还缺一个转换。转换写好之前，没有 skill 产出时用它兜底。
**不要再往这个脚本里加设计能力** —— 加了就是第二次重复造。

拆解：剧本 → 分镜 JSON。整条链上缺的最后一道，之前分镜全靠手写。

`分镜/EP001.json` 是 2026-08-15 手写进仓库的，15 个脚本没有一个生成它，
全都只是读它。一集手写还行，100 集不可能。

## 两遍，不是一遍

    第一遍  剧本 → 中文分镜（镜号/时长/景别/动作三拍/台词/连续性/qc）
    第二遍  中文分镜 → 英文渲染层（cast_en / loc_en / 每镜 beats_en 时间轴）

**第二遍不是机翻第一遍。** 中文分镜是给人看的，里面混着声音事件
（「门外传来通传声」）、内心活动（「他在等」）、创作意图（「观众要看出来」）。
模型不区分「这句要执行」和「这句是说明」，照单全收 ——
上一个项目就把「门外通传声传入」画成了一个人走进门。
所以第二遍是**带着语域规则重新生成**，不是翻译。

## 分镜驱动资产，不是资产驱动分镜

这一步会同时吐出一份**资产清单**：这一集需要哪些人、哪些道具、哪些场景。
拿它去对现有台账，缺什么就去做什么。

之前的顺序反了 —— 先有资产再写分镜，于是分镜被现有资产限制住。
外部那套（chaoge 的 3+2）也是剧本 → 场景清单 → 资产 → 导演地图。

**模型编出来的资产 ID 一律不进 uses。** 只有在台账里查得到的才绑。
查不到的进 `missing` 报出来，让人决定是去做这个资产还是改分镜。
LLM 编一个 `PROP-咖啡杯` 出来，下游 `crop_cell` 会报「目录不存在」，
但那已经是三步之后的事了 —— 在这里拦掉便宜得多。

  python3 scripts/make_board.py --project 某剧 --ep 1
  python3 scripts/make_board.py --project 某剧 --ep 1 --stage zh    # 只跑第一遍
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m3

ROOT = m3.ROOT

# ── 第一遍：剧本 → 中文分镜 ──────────────────────────────────────────

ZH_SYSTEM = """你是短剧分镜师。把剧本拆成逐镜分镜。

## 拆镜原则

1. **一镜一个动作单元。** 一句台词配一个动作，通常 2–4 秒。
   动作没说完不要切；说完了不要拖。
2. **前 3 秒是生死线**，第一镜必须是钩子，不要用环境铺垫开场。
3. **景别要有节奏。** 连续三镜同一景别就是平的，
   但也不要每镜都换 —— 换景别要有理由（进入冲突、揭示信息、收尾）。
4. **动作分三拍**：start（这一镜开始时的状态）、beat（中间发生了什么）、
   end（结束时的状态）。end 要能接上下一镜的 start。
5. **只写看得见的。** 「他在等」写成「他的视线停在门上不动」。
   声音事件（门外的脚步声）写进 sound 字段，不写进 action。
6. **单人镜的动作，主语和宾语都只能是这个人自己的身体。**
   「他看向对方的脸」在单人镜里会让模型复制出第二个人 ——
   写成「他的视线抬起，落在正前方」。

## 每镜必填字段

- id：EPxxx_SHnn
- seconds：这一镜多长（数字，2.0–6.0）
- intent：这一镜为什么存在（一句话，给人看的，不进 prompt）
- cast：[{name, state}]，state 写这个人在画面里的状态（坐着/站着/只有手入画）
- location：{id, desc}。**id 是稳定的场景标识，同一个地方所有镜头必须用同一个 id**
  （例 LOC-OFFICE），机位不同不算不同场景。desc 写这一镜的机位。
  **场景 id 只能有两三个** —— 一集里换五个地方，资产量就撑不住
- camera：{size: extreme_close|close|medium_close|medium|wide, angle: level|high|low, move: locked|pan|push|pull}
- action：{start, beat, end}
- dialogue：{speaker, text, at, off_screen}，没有台词就写 null。
  at 是台词从第几秒开始（数字）
- sound：这一镜的环境声和音效（中文，给人看的）
- continuity_out：这一镜结束时，什么东西在什么位置/什么状态
  （下一镜要接住它）
- qc：{headcount: 画面里有几个人, fail_if: [什么情况算这一镜废了]}

## 同时给出资产清单

这一集需要哪些角色、道具、场景。**道具只列出现两次以上的**，
只出现一次的不立资产。

输出严格 JSON，不要解释、不要代码块围栏：
{
 "title": "本集标题",
 "target_seconds": 60,
 "hook_at": 钩子出现在第几秒,
 "assets_needed": {
   "char": [{"name": "角色名", "why": "出现在哪几镜"}],
   "prop": [{"name": "道具名", "why": "出现在哪几镜"}],
   "location": [{"name": "场景名", "why": "哪几镜"}]
 },
 "shots": [ {...如上字段...} ]
}"""

# ── 第二遍：中文分镜 → 英文渲染层 ────────────────────────────────────

EN_SYSTEM = """你把中文分镜转成英文渲染层。**这不是翻译，是带规则重写。**

## 四条硬规则（违反任何一条这一镜就废）

1. **一个否定词都不许写。** 不许出现 no / not / never / without /
   avoid / only / instead of / nothing / don't 等等。
   跟模型说「不要 X」它听见的是「X」。
   要表达「画面里没有别人」，写 "The headcount is exactly 2"，
   不写 "no one else appears"。

2. **不写抽象情绪。** 不许出现 calm / angry / nervous / confident /
   serious / smug 这类词。模型读不懂情绪，只读得懂动作。
   「冷静」写成 "her gaze stays level and her hands stay flat on her knees"。

3. **只写看得见的。** 中文分镜里的声音事件、内心活动、创作意图一律不进
   画面描述。声音归 sound_en。

4. **单人镜的动作，主语和宾语都只能是这个人自己的身体。**
   不许出现 the other person / everyone / his face（当画面里只有一个人时）。

## 时间切片（beats_en）

把这一镜按时间切成 2–4 片，每片承载一个独立的镜头目标。

- at：[起, 止]，单位秒，必须连续覆盖整镜时长
- move：这一片的运镜。镜头不动就写 "static"；
  动了就写具体怎么动（"the camera pushes in toward him"）
- size：**只在 move 不是 static 时才写**，写运镜的落点
  （"ending on a medium shot of him"）。
  镜头不动时构图由关键帧决定，这里再写就是跟图打架。
- action：这一片里人物的具象肢体动作
- says：有台词的那一片带上 {who_en, text}，text 用中文原文

## 另外两样

- sound_en：环境声和音效，英文，一句话
- cast_en：每个角色的英文外形。**写可指认的部件**（脸型、发长落在哪、
  衣服的领型扣数），不写「a man in a dark shirt」这种任何人都符合的描述
- loc_en：**按 location.id 出，不要按镜号出**。同一个 id 只出一份描述 ——
  一个房间出二十份描述，房间就会漂成二十个房间

输出严格 JSON，不要解释、不要代码块围栏：
{
 "cast_en": {"角色名": "英文外形描述（可指认部件）"},
 "loc_en": {"LOC-XXX": "英文地点描述，键必须是 location.id"},
 "shots": {
   "EPxxx_SHnn": {
     "sound_en": "...",
     "beats_en": [{"at":[0,2], "move":"static", "action":"...",
                   "says":{"who_en":"...","text":"中文台词"}}]
   }
 }
}"""


def registry_ids(proj):
    """现有资产 ID。**台账是唯一权威** —— 模型说需要什么不算数，
    这里查得到才算数。"""
    ids = set()
    ad = os.path.join(proj, "assets")
    for sub in ("char", "wardrobe", "prop", "location"):
        d = os.path.join(ad, sub)
        if os.path.isdir(d):
            ids |= {x for x in os.listdir(d) if not x.startswith(".")}
    return ids


def bind_assets(sb, have):
    """把分镜里的资产名对到台账 ID 上。

    对不上的**不绑**，进 missing 报出来。
    绑一个不存在的 ID 下去，三步之后 crop_cell 才会报「目录不存在」——
    在这里拦掉便宜得多，而且能说清楚是哪一镜要用它。
    """
    missing = {}
    for sh in sb["shots"]:
        u = {"char": [], "prop": []}
        for c in sh.get("cast") or []:
            for pre in ("CHAR-",):
                aid = pre + c["name"]
                if aid in have:
                    u["char"].append({"id": aid, "cells": []})
                else:
                    missing.setdefault(aid, []).append(sh["id"])
        sh["uses"] = {k: v for k, v in u.items() if v}
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--stage", default="all", choices=["all", "zh", "en"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--batch", type=int, default=5,
                    help="第二遍每批几镜。一次要 20 镜实测 10 分钟不返回")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    src = os.path.join(proj, "剧本", f"{epid}.md")
    if not os.path.exists(src):
        sys.exit(f"剧本不存在：{src}\n先跑 adapt_script.py")
    dst = os.path.join(proj, "分镜", f"{epid}.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and not a.force and a.stage != "en":
        sys.exit(f"{dst} 已存在。--force 覆盖，或 --stage en 只补英文层。\n"
                 f"**默认不覆盖**：分镜可能已经被人手改过，"
                 f"重跑一遍会把手改的东西冲掉。")

    script = open(src, encoding="utf-8").read()

    # ── 第一遍 ──
    if a.stage in ("all", "zh"):
        print(f"第一遍：{epid} 剧本 → 中文分镜 …")
        sb = m3.ask_json(ZH_SYSTEM, f"【剧本】\n{script}", label=f"{epid} 中文分镜")
        sb["ep"] = a.ep
        for i, sh in enumerate(sb.get("shots", []), 1):
            sh.setdefault("id", f"{epid}_SH{i:02d}")
        tot = sum(float(s.get("seconds") or 0) for s in sb["shots"])
        print(f"  ✓ {len(sb['shots'])} 镜 / {tot:.1f}s"
              f"（目标 {sb.get('target_seconds', 60)}s）")

        have = registry_ids(proj)
        missing = bind_assets(sb, have)
        json.dump(sb, io.open(dst, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  写入 {dst}")

        need = sb.get("assets_needed") or {}
        for kind in ("char", "prop", "location"):
            items = need.get(kind) or []
            if items:
                print(f"  资产清单·{kind}：" +
                      "、".join(x.get("name", "?") for x in items))
        if missing:
            print(f"\n  ⚠ {len(missing)} 个资产台账里没有，**没有绑进 uses**：")
            for aid, shots in missing.items():
                print(f"      {aid}  用在 {'、'.join(shots[:5])}"
                      f"{'…' if len(shots) > 5 else ''}")
            print("    去做这些资产，或改分镜避开它们。做完重跑本脚本绑定。")
        if a.stage == "zh":
            return
    else:
        sb = json.load(io.open(dst, encoding="utf-8"))

    # ── 第二遍：分批 ──
    #
    # **一次要 20 镜的英文层是不行的**（实测：单次调用 10 分钟没返回）。
    # 一份 20 镜的 JSON 又大又脆 —— 慢、容易截断、而且一次失败整集重来。
    # 分批之后：单批快、失败只丢一批、批次之间可以看进度。
    #
    # 批大小 5 是权衡：太小则 cast_en 在每批里重复生成、批间不一致；
    # 太大则回到上面那个问题。cast_en/loc_en 只认第一批的，后面批次的丢弃 ——
    # 全集共用的东西必须只有一个来源，否则同一个角色在第二批里长得不一样。
    print(f"\n第二遍：{epid} 中文分镜 → 英文渲染层（分批，每批 {a.batch} 镜）…")
    KEEP = ("id", "seconds", "cast", "location", "camera",
            "action", "dialogue", "sound")
    got, cast_en, loc_en = {}, {}, {}
    shots = sb["shots"]
    for i in range(0, len(shots), a.batch):
        chunk = shots[i:i + a.batch]
        tag = f"{chunk[0]['id']}–{chunk[-1]['id']}"
        # 已经定下来的英文外形要带进后面每一批，否则第二批会重新发明一次外形
        fixed = (f"【已确定的角色英文外形，必须原样沿用，不要改写】\n"
                 f"{json.dumps(cast_en, ensure_ascii=False)}\n"
                 f"【已确定的地点英文描述，必须原样沿用】\n"
                 f"{json.dumps(loc_en, ensure_ascii=False)}\n\n") if cast_en else ""
        lean = {"shots": [{k: sh.get(k) for k in KEEP} for sh in chunk]}
        print(f"  批 {i // a.batch + 1}/{-(-len(shots) // a.batch)}  {tag} …")
        en = m3.ask_json(EN_SYSTEM,
                         fixed + "【中文分镜】\n"
                         + json.dumps(lean, ensure_ascii=False, indent=1),
                         label=f"{epid} 英文层 {tag}")
        for k, v in (en.get("cast_en") or {}).items():
            cast_en.setdefault(k, v)      # 第一次出现的说了算
        for k, v in (en.get("loc_en") or {}).items():
            loc_en.setdefault(k, v)
        got.update(en.get("shots") or {})
    sb["cast_en"], sb["loc_en"] = cast_en, loc_en
    miss_en = []
    for sh in sb["shots"]:
        e = got.get(sh["id"])
        if not e:
            miss_en.append(sh["id"])
            continue
        r = sh.setdefault("render", {})
        r["beats_en"] = e.get("beats_en") or []
        r["sound_en"] = e.get("sound_en") or ""
    json.dump(sb, io.open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  ✓ 英文层写回 {dst}")
    if miss_en:
        # 不静默：漏掉的镜头在 compile_prompts 那一步才会暴露，
        # 而那时候只会看到「beats_en 没有」，不知道是这一步漏的
        print(f"  ⚠ {len(miss_en)} 镜没拿到英文层：{'、'.join(miss_en)}")
        print("    重跑 --stage en 补，或手写这几镜的 render.beats_en")

    print(f"\n下一步：compile_prompts.py --project {a.project} --ep {a.ep}")


if __name__ == "__main__":
    main()
