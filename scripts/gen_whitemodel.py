#!/usr/bin/env python3
"""白模故事板：分镜 → 一张多格白模预演图。资产之后、关键帧之前的那一道。

方法论出处和完整模板见 `docs/白模故事板.md`。这里只讲工程。

## 为什么要这一道

我们记了很久的硬伤：**Seedance / Seedream 的 prompt 管不住空间关系**
（说了「椅子在桌子对面」，它放在人身后同侧）、光位、桌面陈设。
只有图锁得住。

白模板是**模型自己生成的控制图**：一张图里 P00 是俯视站位布局，
P01…P0N 是逐镜取景。站位错了在这一层重出一张几分钱；
到关键帧才发现要重出整张图；到成片才发现要重渲。
**把「空间关系对不对」挪到最便宜的那一层判断。**

## 为什么不画箭头

第一版方法（手绘线稿板）用红蓝绿橙紫五色箭头标运动，**实测会翻车**——
箭头被模型当成画面内容画进成片，加限制词也照样中招。

所以白模板**一个箭头都不画**，改用本来就属于画面的白色中性标记：
短拖影、接触爆点、地面擦痕、尘土环、冲击波环。
即使渲进成片，看起来是动态模糊和扬尘，不是 UI 箭头。
**把标注做成 diegetic 的。**

这是语域铁律的又一次换位：给人看的标注不能直接进控制图。
**控制图上的每一样东西，模型都可能照着画。**

## 两个待验的东西（`--refs` 开关就是为了做 A/B）

1. 白模板 + 我们已有的角色定妆图同时喂会不会打架 ——
   我们的角色带完整重铠和红发，白模是无贴图块面，
   **两张图在「这个人长什么样」上直接冲突**。谁赢没验过。
2. 白模的块面质感会不会渗进成片。

**先一镜对照，别直接上全片。**

  python3 scripts/gen_whitemodel.py --project 漫剧战斗样片 --ep 1
  python3 scripts/gen_whitemodel.py --project 漫剧战斗样片 --ep 1 --shot EP001_ONE
  python3 scripts/gen_whitemodel.py --project 漫剧战斗样片 --ep 1 --refs   # 带角色图
  python3 scripts/gen_whitemodel.py --project 漫剧战斗样片 --ep 1 --dry-run
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
T2I = "https://fal.run/fal-ai/bytedance/seedream/v5/lite/text-to-image"
EDIT = "https://fal.run/fal-ai/bytedance/seedream/v5/lite/edit"

# [STYLE] 白模预演的质感规格。**这一段一个字都别省** ——
# 模板原文反复强调「不是成片、不是插画、不是精雕塑成品」，
# 说明模型确实有把预演质感往成品方向拉的倾向，说轻了就拉不住。
STYLE = (
    "【画面风格】明亮黏土模型 3D 预演故事板。整体保持统一的白模预演质感："
    "所有角色、场景和特效都使用未贴图的块面模型、哑光浅陶土材质，"
    "只用柔和白色、浅暖灰和少量中性灰。"
    "画面是电影动作预演，是块面模型摆出来的走位示意，"
    "角色保留清晰剪影、身体比例、发型轮廓、服装体积和动作姿态，表面简洁光滑。"
    "特效只能是附着在动作来源上的中性白标记：短拖影、接触爆点、地面擦痕、"
    "尘土环、水波飞溅、撞击碎屑、冲击波环，全部灰白、半透明、低饱和、贴近接触点。"
)

# 这几条是「不许出现」，按我们收窄过的否定即点名规则解释得通：
# STYLE 已经把画风钉成白模之后，「画彩色皮肤纹理」是弱先验，点名就是禁止。
# 而「箭头/UI」正是第一版方法翻车的东西，必须点名。
FORBID = (
    "彩色材质、真实皮肤纹理、布料纹理、混凝土纹理和完成度很高的特效都不要出现；"
    "彩色法术、图标、UI、箭头、引导线和漂浮装饰物都不要出现。"
    "不要把方括号标题模块渲染成画面文字。"
)

HEADER_RULE = (
    "【顶部标题区】排版具有电影制作板质感，使用细线分隔，层级清晰。"
    "图形处理只能出现在分镜格之外。标题区只允许出现下面这两行文字：「{loc}」「{one}」"
)


def board_rule(cols, rows, n):
    return (f"【网格】严格 {cols} 列 × {rows} 行，按 P## 顺序从左到右、从上到下填满 {n} 格。"
            f"每个分镜格都是严格的 16:9 横向矩形，宽度是高度的 1.78 倍，"
            f"全部 {n} 格比例和大小完全一致。整张画布保持 16:9，"
            f"多余空间用于标题区和页边距。"
            f"每个分镜格的标题格式必须是 P## /景别 /动作名，写在格子上沿。")


SIZE_CN = {"extreme_close": "大特写", "close": "特写", "medium_close": "中近景",
           "medium": "中景", "wide": "全景", "moving": "运动镜头"}


def panels_from_shots(sb, only=None):
    """一镜一格。适合 SH 这种 3–5 秒的短镜。"""
    out = []
    for s in sb["shots"]:
        if only and s["id"] not in only:
            continue
        a = s.get("action") or {}
        act = (a.get("beat") or a.get("start") or s.get("beat") or "").strip()
        out.append((SIZE_CN.get((s.get("camera") or {}).get("size", ""), "中景"),
                    s.get("beat") or s["id"], act, s["seconds"]))
    return out


def panels_from_beats(sh, want):
    """一个长镜内部按时间切片取格。30 秒 30 片塞不进 9 格，等距抽样。

    **抽样不是随便丢**：等距取能保住首尾和中段的节奏，
    随机丢会让相邻两格的动作接不上，人审的时候看不出走位是否连贯。
    """
    bs = (sh.get("render") or {}).get("beats_en") or []
    if not bs:
        return []
    step = max(1, len(bs) / want)
    picked = [bs[min(len(bs) - 1, int(i * step))] for i in range(want)]
    out = []
    for b in picked:
        t0, t1 = b["at"]
        mv = (b.get("move") or "static")
        out.append(("运动镜头" if mv != "static" else "固定",
                    f"{t0:g}-{t1:g}s", (b.get("action") or "")[:110], t1 - t0))
    return out


def build_prompt(loc, one, panels, layout):
    cols, rows = layout
    n = len(panels) + 1                      # +1 是 P00 俯视布局格
    lines = [
        f"创建一张 16:9 的电影动作预演故事板分镜图，共 {n} 个分镜格。"
        f"通过镜头角度、景别、姿态、画面方向和空间地理关系，"
        f"传达人物在场景中的站位、走位路线、动作接触点和力量方向。",
        HEADER_RULE.format(loc=loc, one=one),
        board_rule(cols, rows, n),
        STYLE, FORBID,
        "【逐格内容】",
        # P00 是这套方法最要紧的一格：俯视布局。空间关系锁在这里，
        # 后面每一格的取景都要跟它对得上。
        f"P00 /俯视布局 /空间站位：从正上方俯视{loc}，"
        f"用块面模型标出场地边界、主要陈设和两名角色各自的站位与移动路线。",
    ]
    for i, (size, name, act, sec) in enumerate(panels, 1):
        lines.append(f"P{i:02d} /{size} /{name}：{act}")
    return "\n".join(lines)


def build_prompt_nolayout(loc, one, panels, layout):
    """第二块板之后不再重复 P00 俯视布局格 —— 空间关系第一块已经锁了，
    省下的格位画内容。重复画反而可能画成第二个不一样的场地。"""
    cols, rows = layout
    n = len(panels)
    lines = [
        f"创建一张 16:9 的电影动作预演故事板分镜图，共 {n} 个分镜格。"
        f"通过镜头角度、景别、姿态、画面方向和空间地理关系，"
        f"传达人物在场景中的站位、走位路线、动作接触点和力量方向。",
        HEADER_RULE.format(loc=loc, one=one),
        board_rule(cols, rows, n),
        STYLE, FORBID, "【逐格内容】",
    ]
    for i, (size, name, act, sec) in enumerate(panels, 1):
        lines.append(f"P{i:02d} /{size} /{name}：{act}")
    return "\n".join(lines)


def key():
    return keys.fal()


def post(prompt, refs, seed):
    if refs:
        body, url = {"prompt": prompt, "image_urls": refs,
                     "num_images": 1, "seed": seed}, EDIT
    else:
        body, url = {"prompt": prompt, "image_size": {"width": 2048, "height": 1152},
                     "num_images": 1, "seed": seed}, T2I
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": f"Key {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read()), None
    except Exception as e:
        d = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else str(e)[:200]
        return None, f"{type(e).__name__}: {d}"


def char_refs(proj, sb):
    """角色定妆图当参考。**这是待验项** —— 我们的角色带完整重铠和红发，
    白模是无贴图块面，两张图在「这个人长什么样」上直接冲突。"""
    out = []
    for aid in sorted({c["id"] for s in sb["shots"]
                       for c in ((s.get("uses") or {}).get("char") or [])}):
        p = os.path.join(proj, "assets", "char", aid, "hero.png")
        if os.path.exists(p):
            b = io.BytesIO()
            Image.open(p).convert("RGB").save(b, "PNG")
            out.append("data:image/png;base64," + base64.b64encode(b.getvalue()).decode())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--shot", help="只做这一镜，按它内部的时间切片分格（长镜用）")
    ap.add_argument("--panels", help="从 JSON 读面板清单（中文分镜 md 手工挑格用）。"
                                     "格式 {loc, one, panels:[{size,name,action}]}")
    ap.add_argument("--md", help="直接解析逐秒中文分镜 md 的表格，一秒一格")
    ap.add_argument("--sec", help="只取这个秒区间，如 0-8。**一块板最多 9 格** ——"
                                  "格子越多每格分辨率越低，质感必然差")
    ap.add_argument("--loc", default="废弃神殿")
    ap.add_argument("--layout", default="3x3", choices=["3x3", "2x2"],
                    help="3x3 九视图配 ~15 秒，2x2 四视图配 ~8 秒")
    ap.add_argument("--refs", action="store_true",
                    help="把角色定妆图一起喂（待验：会不会和白模质感打架）")
    ap.add_argument("--seed", type=int, default=70701)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    cols, rows = (int(x) for x in a.layout.split("x"))
    cap = cols * rows - 1                    # 留一格给 P00

    if a.md:
        # 逐秒表一秒一格。**不抽样、不合并** —— 30 秒就是 30 格。
        #
        # **运镜按段说，不是按秒说。** 🎥 标记的是「这一秒开始一条新的运镜路径」，
        # 后面没有标记的秒**继承同一段运镜**，直到下一个 🎥。
        # 第一版把非 🎥 的秒标成「固定机位」——那等于把一条一镜到底
        # 切成 30 个机位，正好是这份分镜自己要避免的事
        #（「切片各带一条运镜指令 → 模型把每条当成一个新镜头」）。
        import re as _re
        txt = open(a.md, encoding="utf-8").read()

        # 台词按时间戳挂到对应的秒上。台词是这一秒在发生的事的一部分，
        # 分开列在文档末尾是给人读的，喂模型时要合回去。
        says = {}
        for m in _re.finditer(r"\*\*(\d+(?:\.\d+)?)s\*\*\s*([^：:]+)[：:]\s*「([^」]+)」", txt):
            says.setdefault(int(float(m.group(1))), []).append(
                f"{m.group(2).strip()}说「{m.group(3)}」")

        rows, seg = [], "一镜到底"
        for ln in txt.splitlines():
            m = _re.match(r"\|\s*(\d+)[–-](\d+)\s*s?\s*\|(.+)\|\s*$", ln.strip())
            if not m:
                continue
            t0, t1, body = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            body = body.replace("　", "").strip()
            if "🎥" in body:
                body = body.replace("🎥", "").strip()
                # 🎥 那一秒的格式是「运镜名｜内容」，前半段是这一段运镜的名字
                if "｜" in body:
                    seg, body = (x.strip() for x in body.split("｜", 1))
                else:
                    seg = body
            body = _re.sub(r"\*\*|`", "", body).replace("｜", "；同时 ")
            if t0 in says:
                body += "；" + "、".join(says[t0])
            rows.append((t0, t1, seg, body))

        if a.sec:
            lo, hi = (int(x) for x in a.sec.split("-"))
            rows = [r for r in rows if lo <= r[0] < hi]
        if not rows:
            sys.exit("这个区间没有内容")
        if len(rows) > 9:
            sys.exit(f"{len(rows)} 格超过一块板的上限 9 —— 用 --sec 拆开。"
                     f"格子越多每格分辨率越低，质感必然差")

        panels = [(seg_, f"{t0}-{t1}s", body, 1) for t0, t1, seg_, body in rows]
        loc_cn = a.loc
        segs = []
        for _, _, sg, _ in rows:
            if sg not in segs:
                segs.append(sg)
        one = f"{rows[0][0]}-{rows[-1][1]} 秒 · 一镜到底 · {'／'.join(segs)}"
        tag = f"EP{a.ep:03d}_{rows[0][0]:02d}-{rows[-1][1]:02d}s"
        cols, rows_n = (int(x) for x in a.layout.split("x"))
        head = (a.sec or "").startswith("0-")
        prompt = (build_prompt if head else build_prompt_nolayout)(
            loc_cn, one, panels, (cols, rows_n))
        # 一镜到底：整块板是同一条镜头运动的连续取样，不是九个独立机位
        prompt += ("\n【全板一致】这 %d 格是同一条不间断长镜头在连续时间上的取样，"
                   "同一个场地、同一套光、同一组角色，格与格之间是镜头连续移动过去的，"
                   "空间关系必须前后对得上。" % len(panels))
        outdir = os.path.join(proj, "白模")
        os.makedirs(outdir, exist_ok=True)
        base = os.path.join(outdir, tag)
        open(base + ".prompt.txt", "w", encoding="utf-8").write(prompt)
        print(f"{tag}  {len(panels)}{'+1' if head else ''} 格  运镜段：{'／'.join(segs)}")
        if a.dry_run:
            print("\n" + prompt); return
        r, err = post(prompt, None, a.seed)
        if err:
            sys.exit(f"✗ {err}")
        urllib.request.urlretrieve((r.get("images") or [{}])[0].get("url"), base + ".png")
        print(f"✓ → {base}.png")
        return

    if a.panels:
        # 从文件读面板。**中文分镜 md 是给人看的**，逐秒 30 条塞不进 9 格，
        # 哪几秒该成为一格是导演判断，不是脚本能算的 —— 所以让人挑好了给进来。
        j = json.load(open(a.panels, encoding="utf-8"))
        panels = [(x["size"], x["name"], x["action"], 0) for x in j["panels"]]
        loc_cn, one = j["loc"], j["one"]
        tag = j.get("tag") or os.path.splitext(os.path.basename(a.panels))[0]
        cols, rows = (int(x) for x in a.layout.split("x"))
        prompt = build_prompt(loc_cn, one, panels, (cols, rows))
        outdir = os.path.join(proj, "白模")
        os.makedirs(outdir, exist_ok=True)
        base = os.path.join(outdir, f"{tag}{'_refs' if a.refs else ''}")
        open(base + ".prompt.txt", "w", encoding="utf-8").write(prompt)
        print(f"{tag}  {len(panels)}+1 格  {a.layout}")
        if a.dry_run:
            print("\n" + prompt); return
        refs = char_refs(proj, sb) if a.refs else None
        r, err = post(prompt, refs, a.seed)
        if err:
            sys.exit(f"✗ {err}")
        url = (r.get("images") or [{}])[0].get("url")
        urllib.request.urlretrieve(url, base + ".png")
        print(f"✓ → {base}.png")
        return

    if a.shot:
        sh = next((s for s in sb["shots"] if s["id"] == a.shot), None)
        if not sh:
            sys.exit(f"没有 {a.shot}")
        panels = panels_from_beats(sh, cap)
        tag = a.shot
    else:
        panels = panels_from_shots(sb)[:cap]
        tag = f"{epid}_all"

    if not panels:
        sys.exit("没有可用的分镜格")

    loc = (sb.get("loc_en") and list(sb["loc_en"])[0]) or "场景"
    loc_cn = {"LOC-神殿": "废弃神殿"}.get(loc, loc)
    one = f"{len(panels)} 个连续动作阶段"

    prompt = build_prompt(loc_cn, one, panels, (cols, rows))
    outdir = os.path.join(proj, "白模")
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, f"{tag}_{a.layout}{'_refs' if a.refs else ''}")
    open(base + ".prompt.txt", "w", encoding="utf-8").write(prompt)

    print(f"{tag}  {len(panels)}+1 格  {a.layout}  "
          f"参考图 {'带' if a.refs else '不带'}")
    if a.dry_run:
        print("\n" + prompt)
        return

    refs = char_refs(proj, sb) if a.refs else None
    if a.refs and not refs:
        # 不静默：要了参考图却一张都没找到，等于悄悄退回不带参考图那条路
        sys.exit("要了 --refs 但一张 hero.png 都没找到")
    r, err = post(prompt, refs, a.seed)
    if err:
        sys.exit(f"✗ {err}")
    url = (r.get("images") or [{}])[0].get("url")
    if not url:
        sys.exit("✗ 返回里没有图")
    urllib.request.urlretrieve(url, base + ".png")
    print(f"✓ → {base}.png")
    print("\n**人看图对分镜**：P00 的站位和走位对不对，"
          "各格取景跟 P00 是不是同一个空间。错了在这一层重出，别带到关键帧。")


if __name__ == "__main__":
    main()
