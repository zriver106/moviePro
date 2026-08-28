#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐镜关键帧合成器：从资产 sheet 里裁格 → 合成一张 16:9 首帧。剧目无关。

**为什么这一层留着**：渲染器是 Seedance 2.0 i2v，首帧就是这里合出来的图。
2026-08-15 探针实测，Seedance 有三样东西 prompt 管不住，只有首帧图能锁：

    空间关系   说了「椅子在桌子对面」，它把椅子放在人身后同侧
    光位       参考图是白天办公室，它渲成夜景城市灯光 + 台灯
    桌面陈设   桌上凭空多出一台笔记本电脑

所以分工是：**图管空间关系、光位、陈设、构图；字管「中段别引入新东西」
+ 台词 + 声场。**（ref2v 那个端点有参考图通道，身份锁得极牢，但构图完全
听 prompt、空间和光位不可靠 —— 所以它是备用，不是主链路。）

合成用 fal seedream v5 lite edit（image_urls[] 多图合成正是干这个的），
跟出资产同一个模型，脸才连得上。

**家具走底板，不走参考图。** 参考图只锁「长什么样」，锁不住「在哪、多大」——
每一镜独立合成时，模型每次自己决定椅子摆哪，于是椅子在成片里自己走动：
SH11 末帧椅子在他左边、SH13 又近又大、SH14 首帧更远更小、SH14 末帧
直接瞬移到他身下。**同一个资产在同一部戏里必须是同一把椅子在同一个位置。**

所以先出**空场底板**（`--plates`）：房间 + 桌子 + 老板椅 + 访客椅，无人，
每个机位一张。之后该机位的所有关键帧都从这张底板 edit 出来，只往上加人。
家具于是是像素级同一份，不是每次重新想象。

**喂的是从 sheet 里裁出来的格，不是整张 sheet** —— 整张喂进去模型会照着
画一个网格。裁哪一格由分镜的 uses 字段指定，坐标来自各资产的 cells.json。

三条 prompt 铁律，跟视频那边同源：
  一、全英文
  二、一个否定词都不许写（seedream 没有 negative_prompt，只能正向描述）
  三、只写看得见的东西（声音事件、内心活动、创作意图一律不进）

还有一条只在这一步成立：**物理取景必须写死。** 出关键帧时没有参考构图，
文字是构图的唯一来源。到了视频那一步就反过来 —— 那时已有关键帧定构图，
再写景别只会跟图打架（实测把「眉毛到下巴」写死进视频 prompt，
模型 5 秒里强行推焦把人推丢，连性别都换了）。

  .venv/bin/python scripts/gen_kf.py --project 搞笑办公室连续剧1 --ep 1 --dry-run
  .venv/bin/python scripts/gen_kf.py --project 搞笑办公室连续剧1 --ep 1 --only EP001_SH01
"""
import argparse
import base64
import concurrent.futures as cf
import io
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

from PIL import Image

import asset_gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import provider          # 所有出图/出片/ASR 只从这里走
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处


TIGHT = {"extreme_close", "close", "medium_close"}
MAX_JOBS = 10        # 并发上限。每镜的合成互不依赖，串行纯粹是浪费

NEG_RE = re.compile(
    r"\b(no|not|none|never|without|avoid|avoiding|don't|doesn't|didn't|isn't|aren't|"
    r"won't|can't|cannot|nothing|nobody|nowhere|neither|nor|lack|lacking|free of|"
    r"instead of|rather than|absent|omit|exclude|refrain)\b", re.I)

STILL = ("Cinematic film still from a live-action comedy series, photorealistic, "
         "16:9 landscape, fine film grain, natural skin texture, sharp focus. ")

# 物理取景。这一步必须写死 —— 出图时没有参考构图，文字是唯一来源。
#
# 近景**不喂场景图**（喂了会跟「只有一张脸」打架），但那样背景的明暗就由模型
# 自由发挥 —— 实测 11 个近景镜里一半渲成了暗调夜景，跟中景的白天办公室剪在
# 一起会闪。所以近景要**锁背景的明暗色温、不锁背景的内容**：只说「浅灰蓝墙面
# 被窗户的白天光照亮」，不说墙上有什么。锁内容才会抢构图，锁色温不会。
BG = ("Behind the subject the background is a smooth wash of pale grey-blue office wall "
      "lit by bright even daylight coming from a window, thrown far out of focus into "
      "soft light shapes, bright and cool and airy in tone.")
FRAMING = {
    "close": ("Close shot: the head and shoulders fill the frame. " + BG),
    "medium_close": ("Medium close shot: the frame holds the body from the chest up. "
                     + BG),
    "medium": ("Medium shot: the frame holds the body from the waist up, with the desk "
               "edge across the lower part of frame and the room readable behind."),
    "wide": ("Wide shot: the camera sits back far enough to hold the whole desk, both "
             "chairs and the people at full length, with the room around them in view."),
}
ANGLE = {
    "level": "The camera is at eye level, square to the scene.",
    "low": "The camera sits a little below eye level and looks slightly upward.",
    "high": "The camera sits above the scene and looks down onto it.",
}


def key():
    return keys.fal()


def data_uri(im):
    b = io.BytesIO()
    im.convert("RGB").save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def crop_cell(assets, aid, cell_key, blocked):
    """按 cells.json 从 sheet 里裁一格。

    **裁不出来就进 blocked，绝不静默回落到整张 sheet。** 回落的后果是
    模型照着网格画一张九宫格出来，而这个错误在成片里才看得见。
    这一类静默兜底是这个项目目前最贵的 bug 类型。
    """
    for sub in ("char", "wardrobe", "prop", "location"):
        d = os.path.join(assets, sub, aid)
        if os.path.isdir(d):
            break
    else:
        blocked.append(f"{aid} 目录不存在")
        return None
    cj, sp = os.path.join(d, "cells.json"), os.path.join(d, "sheet.png")
    if not os.path.exists(cj):
        blocked.append(f"{aid} 缺 cells.json")
        return None
    if not os.path.exists(sp):
        blocked.append(f"{aid} 缺 sheet.png")
        return None
    cells = {c["key"]: c for c in json.load(open(cj, encoding="utf-8"))["cells"]}
    c = cells.get(cell_key)
    if not c:
        blocked.append(f"{aid} 的 cells.json 里没有格位 {cell_key}（有的是 "
                       f"{sorted(cells)[:8]}…）")
        return None
    x, y, w, h = c["bbox"]
    im = Image.open(sp).crop((x, y, x + w, y + h))
    # mirror：出图模型把两个侧面格渲成了同一朝向，资产方没有另开一次生成去补
    # （分开生成必漂），而是标记「这一格裁出来要水平翻转」。
    # **忽略这个字段不会报错**，只会得到两个同向侧面还挂着不同的 key ——
    # 正是那种「产出看起来合理的错数据」，所以这里必须认。
    if c.get("mirror"):
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    return im


def collect(sh, assets, blocked, plate=None):
    """按 uses 收齐这一镜要喂的图，并记下每张图是什么（prompt 里要逐张点名）。

    **必须逐张点名**：只把图扔进去不说它是谁，模型会把白底棚拍的背景
    一起搬进镜头。
    """
    u = sh.get("uses") or {}
    ims, notes = [], []
    tight = (sh.get("camera") or {}).get("size") in TIGHT
    if plate:
        # 底板必须是 <Picture 1> —— FROM_PLATE 那段是按这个编号写的
        ims.append(Image.open(plate))
        notes.append("plate")
    for c in u.get("char", []):
        for k in c["cells"]:
            im = crop_cell(assets, c["id"], k, blocked)
            if im:
                ims.append(im)
                notes.append(f"the person in <Picture {len(ims)}>")
    SET_PIECE = {"PROP-办公桌", "PROP-老板椅", "PROP-访客椅"}
    for p in u.get("prop", []):
        if plate and p["id"] in SET_PIECE:
            continue                     # 已经在底板里，再喂一份只会打架
        for k in p["cells"]:
            im = crop_cell(assets, p["id"], k, blocked)
            if im:
                ims.append(im)
                notes.append(f"the object in <Picture {len(ims)}>")
    loc = u.get("location")
    # 走底板时房间和家具都在底板里了，不再单独喂 —— 喂了等于同一件家具给两份
    # 参考，模型会在两者之间折中，位置照样漂
    if plate:
        for pr in u.get("prop", []):
            pass
        return ims, notes
    # 近景一张场景图都不喂 —— 近景背景本该完全虚化，喂全景只会跟「只有一张脸」
    # 打架（上个项目实测首帧偏离 23788）
    if loc and not tight:
        for k in loc["cells"]:
            im = crop_cell(assets, loc["id"], k, blocked)
            if im:
                ims.append(im)
                notes.append(f"the room in <Picture {len(ims)}>")
    return ims, notes


PLATE = ("Cinematic film still from a live-action comedy series, photorealistic, "
         "16:9 landscape, fine film grain, sharp focus. An empty modern private office "
         "with the room, wall, window, blinds, carpet and corner plant of the room "
         "picture, furnished with the dark walnut desk, the tall black leather "
         "executive chair standing behind that desk, and the low grey armless guest "
         "chair standing in front of it on the near side. The furniture sits squarely "
         "in the room with clear floor around it. The room holds furniture alone. ")

# 底板上「加人」时必须逐字重申的一句。家具是这一步唯一不许动的东西 ——
# 只说「保持不变」不够，要把「同样的位置、同样的大小、同样的机位」说满。
FROM_PLATE = ("The room, the wall, the window, the carpet, the desk, the tall black "
              "leather executive chair and the low grey guest chair all stay exactly "
              "where they are in <Picture 1>, at exactly the same size and the same "
              "position in frame, under exactly the same light, and the camera stays "
              "in exactly the same place at the same distance and the same angle. ")


def build_plates(sb, assets, proj, epid, seed, jobs, dry=False):
    """每个用到的机位出一张空场底板：房间 + 全部家具，无人。

    `dry=True` 时只返回底板路径不生成 —— 这个函数会真的花钱，
    必须能被 --dry-run 挡住。
    """
    views = {}
    for sh in sb["shots"]:
        u = sh.get("uses") or {}
        loc = u.get("location")
        if not loc or (sh.get("camera") or {}).get("size") in TIGHT:
            continue
        for k in loc["cells"]:
            views.setdefault((loc["id"], k), []).append(sh["id"])
    outdir = os.path.join(proj, "keyframes", epid, "plates")
    os.makedirs(outdir, exist_ok=True)
    made = {}
    for (lid, k), users in views.items():
        dst = os.path.join(outdir, f"{lid}__{k}.png")
        made[(lid, k)] = dst
        if os.path.exists(dst):
            print(f"  跳过底板 {lid}/{k}（已有，{len(users)} 镜共用）")
            continue
        if dry:
            print(f"  [dry] 底板 {lid}/{k} 待生成（{len(users)} 镜共用）")
            continue
        blocked = []
        # 底板是几十镜共用的地基，它比单镜更需要门禁：这里放行一个没审过的
        # 场景资产，错误会分摊到每一镜上，而且看起来「所有镜头一致」。
        furniture = (("PROP-办公桌", "side"), ("PROP-老板椅", "front"),
                     ("PROP-访客椅", "side"))
        for aid in (lid,) + tuple(p for p, _ in furniture):
            asset_gate.check(assets, aid, blocked)
        ims = [crop_cell(assets, lid, k, blocked)]
        for pid, ck in furniture:
            ims.append(crop_cell(assets, pid, ck, blocked))
        ims = [x for x in ims if x]
        if blocked:
            print(f"  ✗ 底板 {lid}/{k}：{'；'.join(blocked)}")
            continue
        r, err = edit(PLATE + f"The camera view is the one shown in <Picture 1>.",
                      [data_uri(x) for x in ims], seed)
        if err:
            print(f"  ✗ 底板 {lid}/{k} {err}")
            continue
        urllib.request.urlretrieve((r.get("images") or [{}])[0].get("url"), dst)
        print(f"  ✓ 底板 {lid}/{k}（{len(users)} 镜共用）→ {dst}")
    return made


def build_prompt(sh, sb, notes):
    """两个逐镜覆盖口子，都是被实际错误逼出来的：

      cast[].partial_en   这一镜只有身体的一部分入画。SH01 要的是「只有手和
                          小臂伸进画面」的桌面俯视，但整段人物外形描述会把
                          整个人招进来 —— 实测第一版就渲成了他的脸和上半身
      render.framing_en   景别表按人像写的（「头和肩占满画面」），物件特写
                          套不上，硬套就是跟画面内容打架
    """
    cast_en = sb.get("cast_en", {})
    cam = sh.get("camera") or {}
    cast = sh.get("cast") or []
    who, partial = [], []
    for c in cast:
        if c.get("partial_en"):
            partial.append(c["partial_en"])
            continue
        d = cast_en.get(c["name"])
        if d:
            who.append(d)
    n = len(who)
    if n:
        head = (f"The frame holds exactly {n} "
                f"{'person' if n == 1 else 'people'}: {'; and '.join(who)}. ")
    elif partial:
        head = ""
    else:
        head = "The frame holds the objects and the room alone. "
    if partial:
        head += ("The frame holds " + "; and ".join(partial)
                 + ", and that is all of any person that reaches into frame. ")

    bind = ""
    if notes and notes[0] == "plate":
        bind = FROM_PLATE
        notes = notes[1:]
    if notes:
        kinds = []
        for x in notes:
            if x.startswith("the person"):
                kinds.append(f"{x} keeps that exact face, that exact hair and that "
                             f"exact clothing")
            elif x.startswith("the object"):
                kinds.append(f"{x} appears here as the same object, same shape, "
                             f"same colour, same proportions")
            else:
                kinds.append(f"{x} is this same room, same architecture, same "
                             f"furniture layout, same light direction")
        bind += ("; ".join(kinds) + ". These pictures fix identity and objects; "
                 "the framing and the moment are as described here. ")

    r = sh.get("render") or {}
    if r.get("framing_en"):
        frame, angle = r["framing_en"], ""
    else:
        frame = FRAMING.get(cam.get("size"), FRAMING["medium"])
        angle = ANGLE.get(cam.get("angle"), ANGLE["level"])
    ff = r.get("first_frame_en", "")
    return " ".join(x for x in (f"{STILL}{head}{bind}".strip(), frame, angle, ff) if x)


def edit(prompt, uris, seed):
    """出图只从 provider 走 —— 换供应商时业务脚本不用动。"""
    url, err = provider.edit_image(prompt, uris, seed=seed)
    return ({"images": [{"url": url}]}, None) if url else (None, err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--only", help="只做这几镜，逗号分隔")
    ap.add_argument("--seed", type=int, default=80101)
    ap.add_argument("--dry-run", action="store_true", help="只打印 prompt 和用图清单")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=MAX_JOBS,
                    help="并发数，上限 10")
    ap.add_argument("--plates", action="store_true",
                    help="只出空场底板（房间+全部家具，无人），每个机位一张")
    ap.add_argument("--no-plate", action="store_true",
                    help="不走底板，回到每镜独立合成（家具位置会漂，仅调试用）")
    a = ap.parse_args()
    a.jobs = max(1, min(MAX_JOBS, a.jobs))

    proj = os.path.join(ROOT, "projects", a.project)
    epid = f"EP{a.ep:03d}"
    sb = json.load(open(os.path.join(proj, "分镜", f"{epid}.json"), encoding="utf-8"))
    assets = os.path.join(proj, "assets")
    outdir = os.path.join(proj, "keyframes", epid)
    os.makedirs(outdir, exist_ok=True)
    only = {x.strip() for x in a.only.split(",")} if a.only else None

    # --dry-run 必须挡住 build_plates。它在 dry-run 分支之前跑，而且会真的调
    # 出图接口 —— 「只想看看 prompt」结果扣了钱，是最不该有的那种意外。
    # dry-run 时只算出底板路径，不生成。
    plates = ({} if a.no_plate else
              build_plates(sb, assets, proj, epid, a.seed, a.jobs,
                           dry=a.dry_run))
    if a.plates:
        return

    blocked_all, made, jobs = [], 0, []
    for sh in sb["shots"]:
        sid = sh["id"]
        if only and sid not in only:
            continue
        dst = os.path.join(outdir, f"{sid}.png")
        if os.path.exists(dst) and not a.force:
            print(f"  跳过 {sid}（已有）")
            continue

        blocked = []
        # 状态门禁在收图之前跑：先问「这些资产能不能用」，再问「图裁不裁得出来」。
        # 反过来的话，一个没审过的资产只要图是好的就照样进渲染。
        asset_gate.check_shot(assets, sh, blocked)
        u = sh.get("uses") or {}
        loc = u.get("location")
        pl = None
        if loc and (sh.get("camera") or {}).get("size") not in TIGHT:
            pl = plates.get((loc["id"], loc["cells"][0]))
        ims, notes = collect(sh, assets, blocked, pl)
        prompt = build_prompt(sh, sb, notes)
        negs = sorted({m.group(0).lower() for m in NEG_RE.finditer(prompt)})
        if negs:
            blocked.append(f"prompt 里有否定词 {negs}")
        if not ims:
            blocked.append("一张参考图都没收到")
        if blocked:
            blocked_all.append((sid, blocked))
            print(f"  ✗ {sid} 拦下：{'；'.join(blocked)}")
            continue

        if a.dry_run:
            print(f"\n{'=' * 70}\n{sid}  {len(ims)} 张参考图")
            for i, im in enumerate(ims, 1):
                print(f"  <Picture {i}>  {im.size[0]}×{im.size[1]}")
            print(prompt)
            continue
        jobs.append((sid, dst, prompt, ims))

    if a.dry_run:
        return

    lock = threading.Lock()

    def work(j):
        """一镜的合成往返。每镜互不依赖，串行纯粹是浪费。"""
        sid, dst, prompt, ims = j
        try:
            r, err = edit(prompt, [data_uri(x) for x in ims], a.seed)
            if err:
                return sid, err
            url = (r.get("images") or [{}])[0].get("url")
            if not url:
                return sid, "返回里没有图"
            urllib.request.urlretrieve(url, dst)
        except Exception as e:                    # 一镜挂掉不能带走整批
            return sid, f"{type(e).__name__}: {str(e)[:120]}"
        with lock:
            print(f"  ✓ {sid}  {len(ims)} 图合成")
        return sid, None

    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for sid, err in ex.map(work, jobs):
            if err:
                print(f"  ✗ {sid} {err}")
            else:
                made += 1

    if not a.dry_run:
        print(f"\n出图 {made} 张 → {outdir}")
    if blocked_all:
        print(f"\n拦下 {len(blocked_all)} 镜：")
        for sid, b in blocked_all:
            print(f"  {sid}: {'；'.join(b)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
