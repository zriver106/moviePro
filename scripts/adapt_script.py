#!/usr/bin/env python3
"""⚠ **设计权归 `/short-drama-write` skill，不归这里。**

2026-08-17 才发现 `.claude/skills/` 里 8 月 14 日就装了 drama-skills，而这个脚本是在不知情的情况下重写的一遍。它有单集卡、因果节拍、去模板感修订，本脚本只有一次性生成。

**保留的理由**：它直接产出我们的 JSON schema，而 skill 产出 markdown，中间还缺一个转换。转换写好之前，没有 skill 产出时用它兜底。
**不要再往这个脚本里加设计能力** —— 加了就是第二次重复造。

改编：原始小说 / 大纲 → 短剧剧本。分镜之前的那一道，之前整条链上是空的。

## 为什么之前没有

15 个脚本里，`script_doctor.py` **审**剧本，其余全是分镜以后的事。
剧本本身一直是手写的（`分镜/EP001.json` 也是，见 `make_board.py`）。
一集手写没问题，100 集不可能。

## 两条入口，同一个出口

    --novel  <文件或目录>   已有小说 → 改编
    --brief  <一句话/梗概>  从头写（没有原著时）

出口都是 `projects/<剧>/剧本/EPxxx.md`，格式跟现有的一致：

    # EP001 标题
    类型 / 时长 / 人物
    ## 1-1 日内 办公室
    △动作描述
    角色：台词

## 一集切多长

**按内容切，不按字数切。** 目标 60 秒左右，不追求精准 ——
判据是「这一集能不能承载一个完整的钩子→翻转→兑现」。
切不动就说明上游的节拍太粗，回去改大纲，不要硬凑。

一集 60 秒的实际容量（EP001 实测）：21 镜、约 8 句台词、总时长 60.0 秒。
所以给模型的锚是**台词句数**而不是字数 —— 短剧的时长由台词量决定，
画面可长可短。

## 剧本是给人看的层，不做语域过滤

剧本里可以写「门外传来通传声」「他在等」这类东西 ——
**过滤发生在喂模型的那一步，不是这一步**。
`make_board.py` 出分镜时才把声音事件归音轨、内心活动改成可见的身体信号。
在这里就过滤掉，人反而看不懂剧本了。

  python3 scripts/adapt_script.py --project 某剧 --novel 素材/原著.txt --ep 1-5
  python3 scripts/adapt_script.py --project 某剧 --brief "外卖员捡到一部能听见人心声的手机" --ep 1
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m3

ROOT = m3.ROOT

SYSTEM = """你是短剧编剧。把素材改编成竖屏短剧剧本，一集约 60 秒。

## 短剧的硬约束

1. **前 3 秒是生死线。** 第一个画面就要有异常、冲突或悬念，
   不能用环境铺垫开场。
2. **一集一个完整的钩子→翻转→兑现**，结尾留一个让人想看下一集的理由。
3. **60 秒约等于 6–10 句台词。** 台词量决定时长，画面可长可短。
   超过 12 句就是塞太多，拆成两集。
4. **信息在本集内自足。** 出场人物在这一集里就要让观众知道他是谁、
   跟主角什么关系、他想要什么。没交代身份的角色，行为对观众就是噪音。
5. **动机要成立。** 特别是：弱势方为什么不揭发？受害者为什么配合？
   如果理由是「被威胁」，要问这个威胁对威胁者自己是不是同样致命。

## 格式（严格照抄，不要加别的）

```
# EP001 本集标题

类型：xx / xx
时长：60 秒以内
人物：角色名（性别，年龄，身份），角色名（性别，年龄，身份）

## 1-1 日内 地点

△动作描述，一句一个动作，写看得见的东西。

角色名：台词。

△动作描述。

角色名（画外）：台词。
```

- 场次号 `1-1`、`1-2`…；`日内/日外/夜内/夜外` + 地点
- `△` 开头是动作行，`角色名：` 开头是台词行
- 台词后面可以用 `（小声）`「（画外）」标注，写在角色名后的括号里
- **动作行只写看得见的**。「他在等」写成「他的视线停在门上不动」
- 心理活动不写进动作行，要么变成动作，要么变成台词
- 不要写运镜、景别、剪辑 —— 那是分镜的事，这一层不碰

## 只输出剧本正文，不要任何解释、不要 markdown 代码块围栏"""


def read_source(a):
    """把素材读成一段文本。目录就按文件名排序拼起来。"""
    if a.brief:
        return f"【创作要求】\n{a.brief}", "从头写"
    p = a.novel
    if not os.path.exists(p):
        sys.exit(f"素材不存在：{p}")
    if os.path.isdir(p):
        fs = sorted(f for f in os.listdir(p)
                    if f.lower().endswith((".txt", ".md")))
        if not fs:
            sys.exit(f"{p} 里没有 .txt/.md")
        text = "\n\n".join(open(os.path.join(p, f), encoding="utf-8").read()
                           for f in fs)
        return f"【原著素材】\n{text}", f"{len(fs)} 个文件"
    return ("【原著素材】\n" + open(p, encoding="utf-8").read()), os.path.basename(p)


def canon_context(proj):
    """有 webnovel-writer 的设定集就带上 —— 人物和世界观必须跟 canon 一致，
    不能让改编这一步自己重新发明一个主角。

    **找不到就说明没有，不静默假装有。**
    """
    out = []
    for rel in ("设定集", "大纲"):
        d = os.path.join(proj, rel)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".md"):
                out.append(f"【{rel}/{f}】\n"
                           + open(os.path.join(d, f), encoding="utf-8").read())
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", default="1", help="集数，如 1 或 1-5")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--novel", help="原始小说文件或目录")
    src.add_argument("--brief", help="没有原著时，给一句话梗概从头写")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的剧本")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    if not os.path.isdir(proj):
        sys.exit(f"剧目不存在：{proj}")
    outdir = os.path.join(proj, "剧本")
    os.makedirs(outdir, exist_ok=True)

    eps = ([int(x) for x in range(int(a.ep.split("-")[0]),
                                  int(a.ep.split("-")[1]) + 1)]
           if "-" in a.ep else [int(a.ep)])

    source, label = read_source(a)
    canon = canon_context(proj)
    print(f"素材：{label}｜设定集：{'有' if canon else '无'}｜要写 {len(eps)} 集")

    prev = None
    for ep in eps:
        dst = os.path.join(outdir, f"EP{ep:03d}.md")
        if os.path.exists(dst) and not a.force:
            print(f"  跳过 EP{ep:03d}（已有，--force 覆盖）")
            prev = open(dst, encoding="utf-8").read()
            continue
        # 上一集全文一起喂 —— 跨集断裂单看一集永远发现不了，这条在
        # script_doctor 上已经验过一次，写剧本这一步同样成立：
        # 不给上一集，第 N 集就会重新介绍一遍已经出过场的人。
        ctx = f"【上一集全文，本集必须接得上，不要重复交代已知信息】\n{prev}\n\n" if prev else ""
        want = (f"{ctx}{canon}\n\n{source}\n\n"
                f"【任务】写第 {ep} 集（EP{ep:03d}）。"
                f"{'这是第一集，前 3 秒必须立住钩子。' if ep == 1 else ''}"
                f"按内容切，一集约 60 秒、6–10 句台词，不要凑字数。")
        print(f"  写 EP{ep:03d} …")
        text = m3.ask_text(SYSTEM, want, label=f"EP{ep:03d}")
        # 模型偶尔还是会套一层代码块围栏
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        open(dst, "w", encoding="utf-8").write(text + "\n")
        n_line = sum(1 for l in text.splitlines()
                     if l.strip() and not l.startswith(("#", "△", "类型", "时长", "人物")))
        print(f"  ✓ EP{ep:03d}  {len(text)} 字，约 {n_line} 句台词 → {dst}")
        prev = text

    print(f"\n下一步：script_doctor.py --project {a.project} --ep {a.ep} 过医生，"
          f"过了再 make_board.py 出分镜")


if __name__ == "__main__":
    main()
