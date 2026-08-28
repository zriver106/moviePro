#!/usr/bin/env python3
"""从分镜 JSON 编译渲染 prompt，写回同一份 JSON。剧目无关，多剧共用。

默认出 **Seedance 2.0** 的一整段 prompt（`--target h3` 出 H3 三段式，
H3 已于 2026-08-15 停用，留着只为读旧数据）。

**只读分镜 JSON** —— 英文动作就写在分镜里，不像旧版躺在渲染脚本的字典里
（那正是「分镜里看不到 prompt」的根因）。

  分镜 JSON 是唯一权威：
    cast_en          角色的英文外形（顶层，全集共用）
    loc_en           地点的英文描述（顶层）
    shots[].render.action_en / sound_en    逐镜手写的英文
  编译出来的 shots[].render.prompt 就是提交给 API 的原文。

为什么英文要手写、不机翻中文分镜：中文分镜里混着声音事件（「门外通传声」）、
内心活动（「他在等」）、创作意图（「观众要看出来」）。模型不区分「这句要执行」
和「这句是说明」，照单全收 —— 上一版就把「门外通传声传入」画成了一个人走进门。

  python3 scripts/compile_prompts.py --project 搞笑办公室连续剧1 --ep 1
  python3 scripts/compile_prompts.py --project 搞笑办公室连续剧1 --ep 1 --show EP001_SH11
"""
import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_lock          # 剧本没定稿就不许往下编译

# 近景一个字地点都不写 —— 近景背景就是一面虚化的墙，写全景细节等于跟关键帧
# 抢方向盘（《太子》实测首帧偏离 23788）。
TIGHT = {"extreme_close", "close", "medium_close"}

# 否定词表在 negwords.py，只有一份 —— 两份表里弱的那份会悄悄放行。
from negwords import NEG_RE


def cast_line(sh, cast_en):
    """人数写死 + 每个人的外形。不写人数就会多出人；两人镜不分开描述就会克隆
    （《太子》渲出过三个同脸主角并排）。"""
    cast = sh.get("cast") or []
    n = len(cast)
    if not n:
        return ("The headcount is exactly 0 for every frame of this shot: the frame holds "
                "objects and the room alone, and it stays that way from the first frame "
                "to the last. ")
    who = []
    for c in cast:
        d = cast_en.get(c["name"])
        if not d:
            sys.exit(f"{sh['id']}: cast_en 里缺 {c['name']} 的英文外形")
        who.append(d)
    joined = who[0] if n == 1 else "; and ".join(who)
    # **别写 the only person who appears** —— only 是排除式表达，排除即点名。
    # 正面写法：直接声明人数在整镜里保持不变。
    return (f"The headcount is exactly {n} for every frame of this shot: {joined}. "
            f"The headcount stays exactly {n} from the first frame to the last. ")


def setting_line(sh, loc_en):
    if (sh.get("camera") or {}).get("size") in TIGHT:
        return ""
    loc = loc_en.get((sh.get("location") or {}).get("id", ""))
    return f"The whole shot takes place in {loc}. Every frame shows that same place. " if loc else ""


def dialogue_line(sh):
    """三种台词三种去处：

      正常台词    → <d>[Chinese] …</d>，官方 API 音画一起出，嘴型才对得上
      is_os       → 内心独白，嘴不能动，一个字都不进 prompt
      off_screen  → 画外音，只留在 sound_en 里描述成「画外传来的说话声」
    """
    d = sh.get("dialogue")
    if not d or not (d.get("text") or "").strip():
        return ""
    if d.get("is_os") or d.get("off_screen"):
        return ""
    txt = re.sub(r"[（(][^）)]*[）)]", "", d["text"]).strip("，。、 ")
    cast = sh.get("cast") or []
    if len(cast) <= 1:
        lead = "The person in frame speaks these words: "
    else:
        # 多人镜必须点明谁在说，否则口型落到错的人身上。
        # who_en 由分镜直接写（过肩镜里说话人在「前景」不在「左边」，
        # 按 cast 顺序猜左右会指错人）；没写才退回按顺序猜。
        who = d.get("who_en")
        if not who:
            names = [c["name"] for c in cast]
            idx = names.index(d.get("speaker")) if d.get("speaker") in names else 0
            who = "The person on the left" if idx == 0 else "The person on the right"
        lead = f"{who} speaks these words while the others listen in silence: "
    return f" {lead}<d>[Chinese] {txt}</d>"


def _moves(sh):
    """这一镜的时间切片里有没有真的在运镜。"""
    return any((b.get("move") or "static") != "static"
               for b in ((sh.get("render") or {}).get("beats_en") or []))


def say_text(t):
    """台词清洗 + 收尾标点。

    去掉圆括号里的表演提示（那是给演员看的，不是要念的），
    收尾补句号 —— **但原本就以 ？！ 收尾的不补**，否则出现「？。」，
    而台词是真的会被念出来的，标点错了断句就错了。
    """
    t = re.sub(r"[（(][^）)]*[）)]", "", t).strip("，、 ").rstrip("。")
    return t if t and t[-1] in "？！?!" else t + "。"


def lock_line(has_ref, moving=False):
    """收尾的连续性锁。

    **`moving=True` 时不能写「locked on a tripod」** —— 切片里刚说完
    「the camera pulls out」，末尾又说「机位钉死不动」，是两条互斥的硬约束。
    我们已经吃过一次这个亏：prompt 写死的景别和关键帧的景别互斥，模型在
    5 秒里强行折中，把人推出画还换了性别。**写得越具体，矛盾越致命。**

    所以运镜镜头锁的是「一镜到底、不换地方、不换人」，不锁机位；
    固定镜头才锁机位。
    """
    if moving:
        # 运镜镜头：锁连续性和空间，不锁机位。
        # 机位怎么走已经在各个时间切片里逐段说过了。
        # **别写 moves only as described** —— only 是排除式表达，排除即点名，
        # 而「机位乱飘」恰恰是模型本来就想做的事，点名等于批准。
        # 正面写法：直接说机位照着上面那条路径走。
        base = ("The whole thing is one single unbroken take: the camera follows exactly "
                "the path described above, in one continuous move, and stays inside that "
                "same room the entire time.")
        if has_ref:
            return ("The take starts exactly at the reference image. " + base)
        return base
    if has_ref:
        return ("The camera is locked on a tripod at a fixed distance and a fixed focal "
                "length for the whole take, so the framing stays identical to the "
                "reference image throughout. The shot starts exactly at the reference "
                "image and continues as one single unbroken take from there, staying in "
                "that same moment, that same place, at that same camera distance.")
    return ("The camera is locked on a tripod at a fixed distance and a fixed focal "
            "length for the whole take, so the framing holds steady as one single "
            "unbroken take from the first frame to the last.")


# 抽象情绪词。**模型读不懂情绪，只读得懂动作。**
# 写「凶狠」「冷静」它无从下手，写「抽刀向前突袭」「视线停在一处不动」它照做。
# 情绪在视频里是靠动作烘托出来的，不是靠形容词声明的 ——
# 这条和「动作描述必须是可见的」同源，只是那条管的是声音事件和内心活动，
# 这条管的是形容词。
EMO_RE = re.compile(
    r"\b(angry|angrily|furious|calm(?:ly)?|nervous(?:ly)?|anxious|happy|happily|sad(?:ly)?|"
    r"confident(?:ly)?|smug(?:ly)?|arrogant(?:ly)?|fierce(?:ly)?|menacing(?:ly)?|"
    r"excited(?:ly)?|scared|afraid|proud(?:ly)?|shy(?:ly)?|awkward(?:ly)?|"
    r"embarrassed|annoyed|irritated|serious(?:ly)?|thoughtful(?:ly)?|"
    r"emotion(?:al|ally)?|mood|feels?|feeling)\b", re.I)


# 身体动词表。**每一个时间切片都必须有至少一个动词落在人身上。**
# 实测：EP001 第 23 秒我写的是「从光柱背面走出，剑上带着火星流，身后弹坑还在发亮」
# —— 三句全是状态不是动作，模型照着执行，给了一个站着的人和一些飘着的火星。
# 那一秒的画面变动量 15.6，是全片最低（结尾定格除外），Andy 一眼看出「有个镜头人站着不动」。
BODY_VERBS = re.compile(
    r"\b(swing|swings|swung|cut|cuts|slash|slashes|thrust|thrusts|stab|stabs|"
    r"strike|strikes|chop|chops|drive|drives|drove|lift|lifts|raise|raises|"
    r"bring|brings|brought|throw|throws|threw|hurl|hurls|push|pushes|pull|pulls|"
    r"spin|spins|turn|turns|twist|twists|duck|ducks|roll|rolls|leap|leaps|"
    r"jump|jumps|dive|dives|dash|dashes|charge|charges|run|runs|ran|step|steps|"
    r"stamp|stamps|kick|kicks|block|blocks|parry|parries|deflect|deflects|"
    r"catch|catches|grip|grips|plant|plants|sink|sinks|sag|sags|snap|snaps|"
    r"lower|lowers|reach|reaches|sweep|sweeps|swept|shove|shoves|brace|braces|"
    r"stagger|staggers|drag|drags|crosses|closes|lands|opens)\b", re.I)


def scan_body_verbs(text):
    return sorted({m.group(0).lower() for m in BODY_VERBS.finditer(text)})


def scan_emotion(text):
    return sorted({m.group(0).lower() for m in EMO_RE.finditer(text)})


NO_VERB = []


def beats_line(sh, has_ref):
    """把 render.beats_en 编成时间切片。没有这个字段返回 None。

    ## 为什么要时间切片

    Seedance 2.5 有时序叙事能力，看重「空间叙事＋时间叙事」。堆一大段笼统
    文案的结果是镜头随意切换、动作前后没有逻辑。正确做法是把剧情拆成
    **带时间戳的分镜脚本，每一段时间切片承载一个独立的镜头目标**。

    我们的分镜本来就有这个结构 —— `action.start / beat / end` 是三拍，
    v3 的长镜单元 `transitions` 是五个运镜 —— 但编译时全被揉成了一段散文，
    时间信息在编译这一步丢掉了。

    ## 每一片写什么、不写什么

      写：运镜（转场）、人物的具象肢体动作、台词
      不写：光影 —— **只在开头的全局段说一次**。每片重复只会让模型
            在同一件事上反复调整；实测的写法也是光影只出现在第一段
      不写：景别 —— **除非这一片的镜头真的在动**。有关键帧时构图归图管，
            prompt 再写景别就是跟图抢方向盘（实测写死物理景别是唯一
            会换掉人物身份的改动：5 秒里强行推焦，把人推丢，连性别都换了）

    所以 `size` 只在 `move` 不是 static 时才进 prompt —— 镜头在动的时候，
    景别是运镜的终点而不是对构图的重复声明。
    """
    beats = (sh.get("render") or {}).get("beats_en")
    if not beats:
        return None
    out = []
    for b in beats:
        at = b.get("at") or []
        if len(at) != 2:
            sys.exit(f"{sh['id']}: beats_en 的 at 必须是 [起, 止] 两个数，"
                     f"拿到 {at!r}")
        head = f"{at[0]:g}–{at[1]:g}s"
        seg = [head]
        mv = (b.get("move") or "").strip()
        if mv and mv != "static":
            seg.append(mv.rstrip(".,"))
            # 景别只在镜头动的时候写：它是这一段运镜的落点
            if b.get("size"):
                seg.append(f"ending on {b['size'].strip().rstrip('.,')}")
        act = (b.get("action") or "").strip()
        if not act:
            sys.exit(f"{sh['id']}: beats_en 里 {head} 这一片没有 action")
        # **每一片都要有身体动词**，写状态会得到静止画面。
        # 收集不退出 —— 撞到第一个就退会让人「改一个→重跑→又发现一个」跑很多遍。
        if not scan_body_verbs(act):
            NO_VERB.append((sh["id"], head, act[:100]))
        line = ", ".join(seg) + ", " + act.rstrip(".") + "."
        says = b.get("says")
        if says and says.get("text"):
            who = says.get("who_en") or "The person in frame"
            line += f" {who} says in Chinese: {say_text(says['text'])}"
        out.append(line)
    return " ".join(out)


def build_seedance(sh, cast_en, loc_en, era_en, has_ref=True):
    """Seedance 2.0 的 prompt 是一整段，没有 H3 那套三段式表头。

    内容跟 H3 版同源 —— 2026-08-15 四组受控对照里「写死人物+人数+地点」是
    唯一全面为正的改动（漂门 −18pp、人数错 −27pp、推焦 −36pp），换个模型
    这条照样成立，所以人数锁和地点锁都留着。

    台词写法实测有效：`She says in Chinese: 不能。`
    ASR 回读确认逐字念对，而且音画一起生成、口型天生同步。

    **画外音也必须写进 prompt。** 这条是踩出来的：off_screen 原来直接跳过
    （H3 时代画外音归 soundscape 描述），换到 Seedance 就错了 ——
    它 generate_audio=true 一定会出声，不给台词它就自己编。
    EP001 第一句「为什么你的简历会比别人小一号呢」被编成了「你有什么办法」，
    而那是全集的钩子。不报错，产出一句听起来挺合理的错台词。
    """
    r = sh.get("render") or {}
    body = beats_line(sh, has_ref)
    if body is None and not r.get("action_en"):
        sys.exit(f"{sh['id']}: render 里既没有 beats_en 也没有 action_en")

    # 全局段只说一次：画风、人数锁、人物外形、地点、光影。
    # 时间切片里只放会变的东西（运镜、动作、台词）—— 不变的东西每片重复一遍，
    # 等于让模型在同一件事上反复调整。
    parts = [f"{era_en}, photorealistic cinematic footage, fine film grain, 16:9 landscape.",
             cast_line(sh, cast_en).strip(),
             setting_line(sh, loc_en).strip(),
             (body or r["action_en"].strip()),
             lock_line(has_ref, moving=bool(body and _moves(sh))).strip()]
    d = sh.get("dialogue") or {}
    # 走时间切片时台词已经落在各自的切片上了，不再在末尾统一补一句 ——
    # 补了就是同一句台词说两遍，模型会真的念两遍。
    if body:
        d = {}
    if d.get("text") and not d.get("is_os"):
        txt = say_text(d["text"])
        if d.get("off_screen"):
            # 画外音：要有声，但说话的人不在画面里，所以不点画面里的谁在说
            who = "A voice speaks from just outside the frame and"
        else:
            who = d.get("who_en") or ("The person in frame"
                                      if len(sh.get("cast") or []) <= 1 else "The speaker")
        parts.append(f"{who} says in Chinese: {txt}")
    parts.append(f"Sound: {r['sound_en'].strip()}.")
    return " ".join(x for x in parts if x)


def build(sh, cast_en, loc_en, era_en, has_ref=True):
    r = sh.get("render") or {}
    if not r.get("action_en"):
        sys.exit(f"{sh['id']}: render.action_en 是空的，先把英文动作写进分镜")
    visual = (f"integrated_multimodal_description: [Shot 1] {era_en}, photorealistic "
              f"cinematic footage, fine film grain, 16:9 landscape. "
              f"{cast_line(sh, cast_en)}{setting_line(sh, loc_en)}"
              f"Within the shot: {r['action_en']} {lock_line(has_ref)}"
              f"{dialogue_line(sh)}")
    sound = ("overall_soundscape: Natural production sound at a normal, balanced level, "
             f"continuously present through the whole shot: {r['sound_en']}. Room reverb "
             "matching the space shown in frame.")
    return "\n\n".join([visual, sound, "non_diegetic_music: N/A"])


def scan_negation(text):
    """把 <d> 里的中文台词摘掉再扫 —— 台词里的「不能」是演员要说的话，
    不是给模型的指令。"""
    return sorted({m.group(0).lower()
                   for m in NEG_RE.finditer(re.sub(r"<d>.*?</d>", " ", text, flags=re.S))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--era", default="contemporary drama, present-day setting")
    ap.add_argument("--target", default="seedance", choices=["seedance", "h3"],
                    help="渲染后端。seedance 出一整段，h3 出三段式")
    ap.add_argument("--show")
    a = ap.parse_args()

    # **剧本定稿是所有下游工作的前置。** 剧本还在改就做分镜/资产/关键帧，
    # 改一句台词上游全废；更隐蔽的是改了剧本下游没重跑，每一层单独看都正常。
    script_lock.require(a.project, a.ep, "编译 prompt")

    path = os.path.join(ROOT, "projects", a.project, "分镜", f"EP{a.ep:03d}.json")
    sb = json.load(io.open(path, encoding="utf-8"))
    cast_en, loc_en = sb.get("cast_en", {}), sb.get("loc_en", {})

    fn = build_seedance if a.target == "seedance" else build
    field = "prompt" if a.target == "seedance" else "prompt_h3"
    bad, flat = [], []
    for sh in sb["shots"]:
        p = fn(sh, cast_en, loc_en, sb.get("era_en", a.era))
        neg = scan_negation(p)
        sh["render"][field] = p
        sh["render"]["negation"] = neg
        if neg:
            bad.append(f"{sh['id']} prompt 里有否定词 {neg}")
        emo = scan_emotion(p)
        sh["render"]["emotion_words"] = emo
        if emo:
            bad.append(f"{sh['id']} prompt 里有抽象情绪词 {emo} —— 换成具象肢体动作")
        # 还在用平铺 action_en 的镜头要数出来。**不静默** ——
        # 「有 prompt」和「prompt 带时间轴」是两回事，不报出来就看不见差别。
        if not (sh.get("render") or {}).get("beats_en"):
            flat.append(sh["id"])
        if a.show and sh["id"] == a.show:
            print(p)
            return
    if a.show:
        sys.exit(f"没有 {a.show}")

    if NO_VERB:
        print(f"\n✗ {len(NO_VERB)} 个时间切片没有身体动词 —— 写的全是状态，"
              f"模型会给你站着不动的人：")
        for sid, head, act in NO_VERB:
            print(f"    {sid} {head}\n      {act}…")

    json.dump(sb, io.open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = sum(s["seconds"] for s in sb["shots"])
    print(f"EP{a.ep:03d}: {len(sb['shots'])} 镜 / {tot:.1f}s，prompt 已写回 {path}")
    if flat:
        print(f"  ⚠ {len(flat)}/{len(sb['shots'])} 镜还在用平铺 action_en，没有时间轴："
              f"{'、'.join(flat[:6])}{'…' if len(flat) > 6 else ''}")
        print(f"    时间轴要写进 render.beats_en：[{{at:[起,止], move, size, action, says}}]")
    for x in bad:
        print(f"  ✗ {x}")
    if bad or NO_VERB:
        sys.exit(1)


if __name__ == "__main__":
    main()
