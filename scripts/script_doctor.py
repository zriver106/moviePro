#!/usr/bin/env python3
"""剧本医生：查主线逻辑漏洞，给修订方案。分镜之前的第一步。

为什么要有这一步：之前整条流水线的输入是没审过的剧本，
下游做得再细也是把坏输入渲得更清楚。实际查出来的问题包括

  第一集缺「触电→失去意识→眼前一黑」三拍，穿越没有因果
  女主到第二集才交代身份，第一集里她只是「床上一个尖叫的女人」
  第一集结尾强吻，第二集开头在扭打，中间断了
  女主被下药用强，却因为一句软弱的威胁替施暴者圆谎，动机不成立

这些都不是画面问题，是叙事问题，只能在文字阶段解决。

审查维度取自四处，各补各的缺：
  AI-Storyboard 的 Director   —— PASS/FAIL 判决 + 常见失败模式
  Seamless 的连续性规则       —— 跨镜状态继承、场景元素锁
  ViMax 的一致性验证          —— 角色/场景跨集追踪
  我们自己踩出来的            —— 因果链完整性、动机成立性、穿帮台词

用 MiniMax-M3（推理模型）做理解，不用本地小模型：这一层是全流程里
最需要智力的地方，省在这里等于把错误往下游传。

  python3 scripts/script_doctor.py --ep 1
  python3 scripts/script_doctor.py --ep 1-3 --out out/doctor
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m3

# API 调用、<think> 剥离、裸换行修复、空返回重试全在 m3.py ——
# 剧本链路三个脚本共用一份，不许各抄一份（抄了就会有一份慢慢忘掉其中一条）。
ROOT = m3.ROOT
DEFAULT_PROJECT = "回到古代当太子"
PROJ = os.path.join(ROOT, "projects", DEFAULT_PROJECT)

RUBRIC = """你是短剧的剧本医生兼导演。审查下面的剧本，只找**真问题**，不做文学点评。

按这些维度逐条查，每条给出「原文引用 + 问题 + 修订方案」：

1. 因果链断裂
   关键转折有没有交代过程？（例：人物死亡/穿越/受伤，中间的动作有没有写出来）
   观众能不能只看画面就明白发生了什么？

2. 人物身份与利害
   每个出场人物，观众在**这一集之内**知不知道他是谁、跟主角什么关系、他想要什么？
   没交代身份的角色，他的行为对观众就是噪音。

3. 动机成立性
   每个人物的每个选择，有没有足够的理由？特别注意：
   受害者为什么配合加害者？弱势方为什么不揭发？
   如果理由只是「被威胁了」，要问这个威胁对威胁者自己是不是同样致命。

4. 时间线与场景衔接
   上一集结尾和这一集开头之间发生了什么？画面能不能接上？
   同一场戏里，人物位置、衣着、手里拿什么，前后一致吗？

5. 穿帮与设定冲突
   穿越者说了现代词汇（报警、警察、手机），周围人有没有反应？
   没人接就是 bug，有人接才是笑点。
   古代设定里出现现代物件/概念，合不合理？

6. 短剧节奏
   这一集的钩子在第几秒？前 3 秒有没有抓人的东西？
   结尾有没有让观众想看下一集的理由？
   有没有大段铺垫可以压缩？

输出严格用 JSON，不要任何解释文字，不要 markdown 代码块：
{
 "ep": 集数,
 "hook_seconds": 钩子出现在第几秒（估算），
 "issues": [
   {"severity": "致命|严重|一般",
    "dimension": "因果链|身份|动机|时间线|穿帮|节奏",
    "quote": "原文引用（20字以内）",
    "problem": "问题是什么（一句话）",
    "fix": "具体怎么改（给出可直接替换的文字）"}
 ],
 "verdict": "PASS 或 FAIL",
 "summary": "一句话总结这一集能不能用"
}"""







def review(ep, prev_text=None):
    p = os.path.join(PROJ, "剧本", f"EP{ep:03d}.md")
    if not os.path.exists(p):
        return None
    text = open(p).read()
    # 带上一集，才查得出跨集断裂 —— 这类问题单看一集永远发现不了
    ctx = f"【上一集全文，用于检查衔接】\n{prev_text}\n\n" if prev_text else ""
    msgs = [{"role": "system", "content": RUBRIC},
            {"role": "user", "content": f"{ctx}【本集剧本】\n{text}"}]
    for attempt in range(3):        # 空返回是 M3 的常态抖动，重试比报错有用
        out = m3.chat(msgs)
        r = m3.parse_json(out)
        if r:
            return r
        print(f"  第 {attempt+1} 次返回为空或非 JSON，重试")
    return {"ep": ep, "raw": m3.strip_think(out)[:1500]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", required=True, help="集数，如 1 或 1-3")
    ap.add_argument("--project", default=DEFAULT_PROJECT,
                    help="剧目目录名，默认 " + DEFAULT_PROJECT)
    ap.add_argument("--out", help="结果写到这个目录")
    a = ap.parse_args()

    global PROJ                     # 一套流水线跑多个剧目，路径不能写死
    PROJ = os.path.join(ROOT, "projects", a.project)

    if "-" in a.ep:
        s, e = a.ep.split("-")
        eps = list(range(int(s), int(e) + 1))
    else:
        eps = [int(a.ep)]

    prev = None
    for ep in eps:
        print(f"\n{'='*72}\n审查 EP{ep:03d}")
        r = review(ep, prev)
        if not r:
            print("  剧本不存在"); continue
        if "raw" in r:
            print("  ⚠ 返回不是合法 JSON，原文：\n", r["raw"][:800]); continue
        print(f"  判决 {r.get('verdict')}  钩子在第 {r.get('hook_seconds')} 秒")
        print(f"  {r.get('summary','')}")
        for i in r.get("issues", []):
            print(f"\n  [{i.get('severity')}] {i.get('dimension')}  「{i.get('quote')}」")
            print(f"    问题：{i.get('problem')}")
            print(f"    修订：{i.get('fix')}")
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            json.dump(r, open(f"{a.out}/EP{ep:03d}.json", "w"),
                      ensure_ascii=False, indent=1)
        prev = open(os.path.join(PROJ, "剧本", f"EP{ep:03d}.md")).read()


if __name__ == "__main__":
    main()
