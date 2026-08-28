#!/usr/bin/env python3
"""资产 sheet 生成器。读 assets/assets.json，一个资产一次 API 调用出整张 sheet。

之前这一步是没有的 —— 现有资产是子代理手工调 API 做的，
`status.json` 里的 `owner` 写着「角色资产代理」。链路上补齐。

## 为什么一张 sheet 一次调用

**分开生成必漂。** 两次出图的光线、材质、比例都会变；
同一个角色的正面和侧面分两次出，会是两个人。
所以全部格位排进一张图**一次生成**，再按格裁。

## 三条硬规矩

1. **纯白底。** 不是浅灰、不是米白 —— 下游要按格裁出来合成关键帧，
   底色不纯就会把一块灰带进镜头。
2. **一个否定词都不写。** Seedream 没有负向通道，写 `no background`
   等于点名 background。提交前正则扫描，扫到就拒绝提交。
3. **prompt 原文落盘。** `prompt.txt` 逐字可复现 ——
   出了问题要能回答「当时到底喂了什么进去」。

  python3 scripts/gen_asset.py --project 漫剧战斗样片            # 全做
  python3 scripts/gen_asset.py --project 漫剧战斗样片 --only CHR-艾琳
  python3 scripts/gen_asset.py --project 漫剧战斗样片 --dry-run  # 只出 prompt 不花钱
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base_lock        # 基础样式没定稿就不许做资产
API = "https://fal.run/fal-ai/bytedance/seedream/v5/lite/text-to-image"
# 派生形态走 edit：**只有换图才换得掉外观，换字换不掉。**
# H1/H2 第一版是 text-to-image 各画各的，出来是三个人（黑短发＋银甲，
# 母板是红尖发＋红黑甲）。形态阶梯的戏剧效果全靠「同一个人变了」。
API_EDIT = "https://fal.run/fal-ai/bytedance/seedream/v5/lite/edit"

# 否定词表在 negwords.py，只有一份 —— 两份表里弱的那份会悄悄放行。
from negwords import NEG_RE


def key():
    return keys.fal()


def positions(cols, rows):
    """格位的方位说法。**不写 Cell 1 / Cell 2** —— 那等于叫模型把编号画进图里，
    第一版的神殿图上真的烧进了 CELL 1、CELL 2 字样。

    旧版是三条写死的分支（3 列 / 2 列 / 其余），**单列会掉进 `["left","right"]`**。
    特效里横幅的东西（剑气、地裂、光矛）必须用 1 列 N 行才有横向空间，
    一掉进这条分支，3 格的 sheet 只拿到 2 个方位词，第三格的描述整条丢掉 ——
    不报错，只是安静地少画一格。按行列算，不写死。
    """
    if cols == 1:
        col_words = [""]
    elif cols == 2:
        col_words = ["left", "right"]
    else:
        col_words = ["left", "middle", "right"][:cols]
    if rows == 1:
        row_words = [""]
    elif rows == 2:
        row_words = ["top", "bottom"]
    else:
        row_words = ["top", "middle", "bottom"][:rows]
    return [" ".join(w for w in (r, c) if w) or "single"
            for r in row_words for c in col_words]


def style_for(a, defs):
    """按类型取风格串。**一份风格串套不住所有类型。**

    全局 `style` 是给角色写的，里面有「ornate layered fantasy armour with
    filigree」「artstation quality character art」—— 拿它去出特效，
    等于明着跟模型要一副盔甲。第一版护盾 sheet 就是这么出的。
    """
    return defs.get("styles", {}).get(a["type"], defs["style"])


def sheet_prompt(a, sh, style, bg):
    """拼一张 sheet 的 prompt。

    **每张最多 6 格。** 质感差的一个真因就是格子太多：24 格挤进一张 2048 的图，
    每格只剩一百多像素，再好的风格词也救不回来。6 格约 680px 一格。

    格位要逐格点名并给编号 —— 只说「出 6 个格」模型会自己决定画什么，
    而下游 `cells.json` 是按 key 取格的，画的内容和 key 对不上就全乱。
    """
    cols, rows = (int(x) for x in sh["grid"].split("x"))
    n = len(sh["cells"])
    # **一致性句只对角色和道具成立。** 第一版把「identical face, identical armour」
    # 无差别套在场景上，等于明着跟模型要一张脸和一副盔甲 ——
    # 神殿那张 4 格里每格都站了个人。空镜进人这条上游能压住，下游压不住。
    same = ("with an identical face, identical armour, identical proportions and "
            "identical lighting in every panel. " if a["type"] == "char" else
            "identical in shape, material and lighting in every panel. "
            if a["type"] == "prop" else
            "the same colour, the same falloff and the same energy signature in "
            "every panel. " if a["type"] == "vfx" else
            "the same architecture, the same columns and the same rubble in every "
            "panel, each panel holding architecture and stone by itself. ")
    POS = positions(cols, rows)
    head = (f"{style}{bg}The image is divided into {n} equal rectangular panels "
            f"arranged in {cols} columns and {rows} rows. Every panel shows "
            f"{a['who']}, {same}")
    body = " ".join(f"The {POS[i]} panel shows {desc}."
                    for i, (_, desc) in enumerate(sh["cells"]))
    return head + body


def hero_prompt(a, style, bg):
    """定妆图：单张全画幅，判质感用的。sheet 是干活用的，两者用途不同。"""
    return (f"{style}{bg}A single full body hero portrait of {a['who']}. "
            f"The whole figure sits inside the frame from head to feet.")


def keep_clause(a):
    """派生形态的「保持不变」清单。

    **逐条重申，不能只说「改成狂化形态」** —— 那样模型会重画整个人。
    清单里的每一项都是第一版实际漂掉过的东西：发色、发型、脸、盔甲、剑。
    """
    return ("Keep every other part of the source picture exactly as it is: "
            "the same face with the same jaw, the same brow, the same nose and "
            "the same diagonal scar across the left cheekbone; the same bright "
            "red upswept spiked hair in the same shape; the same black and "
            "crimson layered plate armour with the same spiked pauldrons and the "
            "same glowing red filigree; the same tattered crimson battle skirt; "
            "the same dark cloth wrapping on the right arm; the same greatsword "
            "with the same geared crossguard and the same red channel down the "
            "blade; the same body proportions and the same lighting. ")


def edit_prompt(a, change, layout):
    return (f"{layout}{change} {keep_clause(a)}"
            f"This is the same man in the same armour, one step further into his "
            f"berserk form.")


def post(prompt, seed, size, src_bytes=None):
    """出图。给了 `src_bytes` 就走 edit 端点，图当唯一输入。

    data URI 直传，**不落公网** —— 资产图不该为了出个图先公开一遍。
    """
    if src_bytes is not None:
        import base64
        body = {"prompt": prompt, "num_images": 1, "seed": seed,
                "image_urls": ["data:image/jpeg;base64,"
                               + base64.b64encode(src_bytes).decode()]}
        url = API_EDIT
    else:
        body = {"prompt": prompt, "image_size": size, "num_images": 1, "seed": seed}
        url = API
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": f"Key {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read()), None
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            detail = e.read().decode("utf-8", "replace")[:300]
        return None, f"{type(e).__name__}: {detail or str(e)[:200]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--only", help="只做这几个，逗号分隔")
    ap.add_argument("--seed", type=int, default=70701)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    # **默认并发 10。** 资产之间互不依赖，串行纯属浪费 ——
    # 上一部戏量过：串行 21 镜 48 分钟，10 路并发 5 分钟。
    # 上限也钉在 10（`render_seedance.py` / `gen_kf.py` 都是这个约定）。
    ap.add_argument("--jobs", type=int, default=10, help="并发路数，默认 10，上限 10")
    a = ap.parse_args()
    jobs_n = max(1, min(10, a.jobs))

    proj = os.path.join(ROOT, "projects", a.project)
    defs = json.load(open(os.path.join(proj, "assets", "assets.json"), encoding="utf-8"))
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    by_id = {x["id"]: x for x in defs["assets"]}

    def path_of(aid, fname):
        return os.path.join(proj, "assets", by_id[aid]["type"], aid, fname)

    # **并发切在「资产」这一层，不是「单张图」这一层。**
    # 派生形态的 sheet 要从**它自己的 hero** 改出来（脸靠这条链传下去），
    # 摊平成图级任务并发就会出现 sheet 先于 hero 跑、母板还不存在。
    # 按资产分工，资产内部保持 hero → sheet 的顺序，资产之间才并发。
    lock = threading.Lock()

    def work(asset):
        """出一个资产的全部图。**异常在这里接住**，不许冒出去带走整批。"""
        aid = asset["id"]
        made, blocked, log = 0, [], []
        d = os.path.join(proj, "assets", asset["type"], aid)
        os.makedirs(d, exist_ok=True)

        style = style_for(asset, defs)
        bg = defs["vfx_bg"] if asset["type"] == "vfx" else defs["sheet_bg"]
        # `edit_from` = 这个资产是从别的资产的图**改**出来的，不是重画。
        # 派生形态的 sheet 再从自己的 hero 改，让脸一路传下去。
        ef = asset.get("edit_from")

        # 要出的东西：一张定妆图（判质感）+ N 张 sheet（干活）
        jobs = []
        if asset.get("hero"):
            if ef:
                jobs.append(("hero.png", edit_prompt(asset, asset["change"], ""),
                             None, None, path_of(ef, "hero.png")))
            else:
                jobs.append(("hero.png", hero_prompt(asset, style, defs["hero_bg"]),
                             {"width": 1152, "height": 2048}, None, None))
        for sh in asset["sheets"]:
            if ef:
                cols, rows = (int(x) for x in sh["grid"].split("x"))
                pos = positions(cols, rows)
                layout = (f"Redraw the man from the source picture as {len(sh['cells'])} "
                          f"separate figures laid out in {cols} columns and {rows} rows "
                          f"on one square canvas over a near black backdrop. "
                          + " ".join(f"The {pos[i]} panel shows him {desc}."
                                     for i, (_, desc) in enumerate(sh["cells"]))
                          + " ")
                jobs.append((f"sheet_{sh['name']}.png",
                             edit_prompt(asset, asset["change"], layout),
                             None, sh, path_of(aid, "hero.png")))
            else:
                jobs.append((f"sheet_{sh['name']}.png",
                             sheet_prompt(asset, sh, style, bg),
                             {"width": 2048, "height": 2048}, sh, None))

        for fname, prompt, size, sh, src in jobs:
            dst = os.path.join(d, fname)
            if os.path.exists(dst) and not a.force:
                log.append(f"  跳过 {aid}/{fname}（已有）")
                continue
            negs = sorted({m.group(0).lower() for m in NEG_RE.finditer(prompt)})
            if negs:
                blocked.append(f"{aid}/{fname} 否定词 {negs}")
                log.append(f"  ✗ {aid}/{fname} 拦下：否定词 {negs}")
                continue
            open(os.path.join(d, fname.replace(".png", ".prompt.txt")),
                 "w", encoding="utf-8").write(prompt)
            if sh:
                json.dump({"sheet": fname, "grid": sh["grid"],
                           "order": "left to right, top to bottom",
                           "note": "bbox 待实测。**别用理论等分** —— 出图模型排的格子不等分。",
                           "cells": [{"key": k, "desc": v, "bbox": None}
                                     for k, v in sh["cells"]]},
                          open(os.path.join(d, f"cells_{sh['name']}.json"),
                               "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if a.dry_run:
                log.append(f"\n{'=' * 70}\n{aid}/{fname}  {len(prompt)} 字符\n{prompt[:360]}…")
                continue
            
            src_bytes = None
            if src:
                if not os.path.exists(src):
                    # **不静默回落到 text-to-image。** 回落回来的是「另一个人」，
                    # 而那正是这次要修的 bug —— 下游看不出它是回落产物。
                    blocked.append(f"{aid}/{fname} 母板缺图 {src}")
                    log.append(f"  ✗ {aid}/{fname} 母板缺图 {src}")
                    continue
                src_bytes = open(src, "rb").read()
            try:
                r, err = post(prompt, a.seed, size, src_bytes)
            except Exception as e:                      # noqa: BLE001
                r, err = None, f"{type(e).__name__}: {str(e)[:120]}"
            if err:
                blocked.append(f"{aid}/{fname} {err}")
                log.append(f"  ✗ {aid}/{fname} {err}")
                continue
            url = (r.get("images") or [{}])[0].get("url")
            if not url:
                blocked.append(f"{aid}/{fname} 返回里没有图")
                continue
            try:
                urllib.request.urlretrieve(url, dst)
            except Exception as e:                      # noqa: BLE001
                blocked.append(f"{aid}/{fname} 下载失败 {type(e).__name__}")
                continue
            made += 1
            log.append(f"  ✓ {aid}/{fname}")

        # **没重新出图就不动 status.json。** 旧版无条件重写，
        # 跑一次 `--only` 之外的资产就会把别人审过的 approved 打回 draft ——
        # 台账被自己的工具改坏，比图坏更难查。
        if not a.dry_run and made:
            json.dump({"id": aid, "type": asset["type"], "status": "draft",
                       "status_note": "刚出图，没人看过。**逐格对完脸再改 ready_for_review**",
                       "hero": asset.get("hero", False),
                       "sheets": [s["name"] for s in asset["sheets"]],
                       "cells": sum(len(s["cells"]) for s in asset["sheets"]),
                       "generation": {"api": API_EDIT if ef else API, "seed": a.seed,
                                      "edit_from": ef,
                                      "negation_scan": "pass（0 个否定词）"},
                       "derives_from": asset.get("derives_from")},
                      open(os.path.join(d, "status.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        # **输出加锁。** 不加锁 10 路的行会交织成一团，看不出谁成了谁没成。
        with lock:
            for line in log:
                print(line)
        return made, blocked

    todo = [x for x in defs["assets"] if x["id"] in only] if only else defs["assets"]
    made, blocked = 0, []
    with cf.ThreadPoolExecutor(max_workers=jobs_n) as ex:
        for m, b in ex.map(work, todo):
            made += m
            blocked += b

    if a.dry_run:
        return
    print(f"\n出图 {made} 个资产")
    if blocked:
        print(f"拦下 {len(blocked)}：")
        for b in blocked:
            print(f"  {b}")
    print("\n**全部是 draft，门禁不会放行。** 逐格对完脸和格位再改 ready_for_review。")


if __name__ == "__main__":
    main()
