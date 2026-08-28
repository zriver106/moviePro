#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分镜 JSON → 给人看的中文分镜。剧目无关。

## 为什么要有

`分镜/EPxxx.json` 是给 agent 用的：英文渲染文案、时间切片、prompt、门禁字段。
**人读不动，也不该读。** 但导演要验的恰恰是内容 —— 这一秒发生什么、镜头怎么走、
谁说什么、跟下一镜怎么接。

之前这份中文稿是**手写**的，于是 JSON 一改它就过期，两份东西对不上 ——
跟「声景没跟着 action_start 重算」是同一个病。所以它必须是**生成的**。

    JSON 是唯一权威，这份 md/html 是它的中文投影，改分镜重跑即可。

## 两种分镜排布都认

    逐镜   shots[] 各有 action.start/beat/end —— 按镜列表
    逐秒   shots[].render.beats_en 带 at/move/cn —— 按秒列表，🎥 标出有运镜的那几秒

  .venv/bin/python scripts/board_readable.py --project 漫剧战斗样片 --ep 1
  .venv/bin/python scripts/board_readable.py --project 漫剧战斗样片 --ep 1 --html
"""
import argparse
import html
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rows_from_beats(sh):
    """逐秒排布：每个时间切片一行。"""
    out = []
    for b in sh["render"]["beats_en"]:
        a0, a1 = b["at"]
        cn = b.get("cn") or b.get("action", "")[:90]
        out.append({"t": f"{a0:g}–{a1:g}s", "move": bool(b.get("move")),
                    "cn": cn, "form": b.get("form", "")})
    return out


def rows_from_shots(sh):
    """逐镜排布：起/中/末三拍一行。"""
    act = sh.get("action") or {}
    parts = [act.get(k, "") for k in ("start", "beat", "end")]
    cn = " → ".join(x for x in parts if x)
    return [{"t": f"{sh['seconds']:g}s", "move": False,
             "cn": cn or sh.get("intent", ""), "form": ""}]


def lines_of(sh):
    out = []
    for l in (sh.get("lines") or []):
        out.append((l.get("at"), l.get("speaker", ""), l["text"]))
    d = sh.get("dialogue") or {}
    if d.get("text") and not d.get("is_os"):
        out.append((d.get("at"), d.get("speaker", ""), d["text"]))
    return out


def build(sb, epid):
    shots = sb["shots"]
    total = sum(s.get("seconds", 0) for s in shots)
    blocks = []
    for sh in shots:
        rows = (rows_from_beats(sh) if (sh.get("render") or {}).get("beats_en")
                else rows_from_shots(sh))
        blocks.append({
            "id": sh["id"], "seconds": sh.get("seconds", 0),
            "beat": sh.get("beat", ""), "intent": sh.get("intent", ""),
            "cam": sh.get("camera_cn") or (sh.get("location") or {}).get("desc", ""),
            "trans": sh.get("transition_cn", ""),
            "cast": "、".join(c["name"] for c in (sh.get("cast") or [])),
            "fail": (sh.get("qc") or {}).get("fail_if", []),
            "rows": rows, "lines": lines_of(sh),
            "neg": (sh.get("render") or {}).get("negation", []),
        })
    return total, blocks


def to_md(sb, epid, total, blocks):
    L = [f"# {sb.get('title', epid)} · 中文分镜",
         "",
         f"**{len(blocks)} 镜 / {total:g} 秒。** 这份是从 `分镜/{epid}.json` 生成的，"
         f"改分镜重跑 `board_readable.py` 即可 —— 别手改这个文件。",
         ""]
    if sb.get("note"):
        L += ["> " + sb["note"].replace("\n", "\n> "), ""]
    for b in blocks:
        L += [f"## {b['id']}　{b['seconds']:g}s"
              + (f"　【{b['beat']}】" if b["beat"] else "")]
        if b["intent"]:
            L += ["", f"**这一镜要干什么**：{b['intent']}"]
        meta = []
        if b["cast"]:
            meta.append(f"**出场**：{b['cast']}")
        if b["cam"]:
            meta.append(f"**运镜**：{b['cam']}")
        if b["trans"]:
            meta.append(f"**转场**：{b['trans']}")
        if meta:
            L += [""] + meta
        L += ["", "| 时间 | | 内容 |", "|---|---|---|"]
        for r in b["rows"]:
            mv = "🎥" if r["move"] else ""
            form = f"　`{r['form']}`" if r["form"] else ""
            L.append(f"| {r['t']} | {mv} | {r['cn']}{form} |")
        if b["lines"]:
            L += ["", "**台词**"]
            for at, who, txt in b["lines"]:
                at_s = f"{at:g}s " if isinstance(at, (int, float)) else ""
                L.append(f"- {at_s}{who}：「{txt}」")
        if b["fail"]:
            L += ["", "**判废**：" + "、".join(b["fail"])]
        L += [""]
    bad = [b["id"] for b in blocks if b["neg"]]
    L += ["---", "", "## 门禁", "",
          f"- 否定词：{'**' + '、'.join(bad) + ' 有命中**' if bad else '全部为空 ✓'}",
          f"- 合计时长：{total:g} 秒"]
    return "\n".join(L)


def to_html(sb, epid, total, blocks):
    def esc(x):
        return html.escape(str(x))
    rows = []
    for b in blocks:
        head = (f'<div class="shot"><h2>{esc(b["id"])}'
                f'<span class="sec">{b["seconds"]:g}s</span>'
                + (f'<span class="beat">{esc(b["beat"])}</span>' if b["beat"] else "")
                + "</h2>")
        if b["intent"]:
            head += f'<p class="intent">{esc(b["intent"])}</p>'
        meta = ""
        for k, v in (("出场", b["cast"]), ("运镜", b["cam"]), ("转场", b["trans"])):
            if v:
                meta += f'<div class="m"><span>{k}</span>{esc(v)}</div>'
        if meta:
            head += f'<div class="meta">{meta}</div>'
        tr = "".join(
            f'<tr class="{"mv" if r["move"] else ""}"><td class="t">{esc(r["t"])}</td>'
            f'<td class="c">{esc(r["cn"])}'
            + (f'<code>{esc(r["form"])}</code>' if r["form"] else "")
            + "</td></tr>" for r in b["rows"])
        head += f"<table>{tr}</table>"
        for at, who, txt in b["lines"]:
            at_s = f"{at:g}s " if isinstance(at, (int, float)) else ""
            head += (f'<div class="say"><span class="who">{esc(at_s + who)}</span>'
                     f'「{esc(txt)}」</div>')
        if b["fail"]:
            head += ('<div class="fail"><span>判废</span>'
                     + "、".join(esc(x) for x in b["fail"]) + "</div>")
        rows.append(head + "</div>")
    return f"""<title>{esc(sb.get('title', epid))}　中文分镜</title>
<style>
:root{{--ink:#15181d;--ink2:#4b5563;--ink3:#8b95a3;--bg:#f4f5f7;--panel:#fff;
 --line:#e2e5ea;--mv:#eef4ff;--accent:#2f5fb8;--warn:#b3402f;
 --sans:"PingFang SC","Hiragino Sans GB",system-ui,sans-serif;
 --mono:"SF Mono",ui-monospace,Menlo,monospace}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{
 --ink:#e7eaee;--ink2:#a6b0be;--ink3:#6b7583;--bg:#0f1216;--panel:#171b21;
 --line:#272d36;--mv:#182234;--accent:#7aa5e8;--warn:#e07a68}}}}
:root[data-theme=dark]{{--ink:#e7eaee;--ink2:#a6b0be;--ink3:#6b7583;--bg:#0f1216;
 --panel:#171b21;--line:#272d36;--mv:#182234;--accent:#7aa5e8;--warn:#e07a68}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.7}}
.wrap{{max-width:900px;margin:0 auto;padding:48px 22px 80px;display:flex;
 flex-direction:column;gap:26px}}
h1{{margin:0;font-size:30px;letter-spacing:.03em}}
.lead{{color:var(--ink2);margin:8px 0 0}}
.shot{{background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:18px 20px}}
h2{{margin:0;font-size:16px;display:flex;align-items:baseline;gap:10px;
 font-family:var(--mono);letter-spacing:.02em}}
.sec{{color:var(--ink3);font-size:13px}}
.beat{{background:var(--mv);color:var(--accent);font-size:12px;padding:1px 8px;
 border-radius:2px;font-family:var(--sans)}}
.intent{{color:var(--ink2);font-size:14px;margin:10px 0 0}}
.meta{{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;font-size:13.5px;
 color:var(--ink2)}}
.m span{{color:var(--ink3);font-size:11.5px;letter-spacing:.1em;margin-right:6px}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:14.5px}}
td{{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}}
tr.mv td{{background:var(--mv)}}
.t{{font-family:var(--mono);color:var(--ink3);white-space:nowrap;width:76px;
 font-variant-numeric:tabular-nums}}
code{{font-family:var(--mono);font-size:12px;color:var(--accent);margin-left:8px}}
.say{{margin-top:10px;font-size:14.5px;background:var(--mv);padding:6px 12px;
 border-radius:2px;display:inline-block;margin-right:8px}}
.who{{color:var(--ink3);font-size:12px;margin-right:8px;font-family:var(--mono)}}
.fail{{margin-top:12px;font-size:13px;color:var(--warn)}}
.fail span{{font-size:11.5px;letter-spacing:.1em;margin-right:8px;opacity:.8}}
footer{{color:var(--ink3);font-size:13px;border-top:1px solid var(--line);padding-top:16px}}
</style>
<div class="wrap">
<header><h1>{esc(sb.get('title', epid))}</h1>
<p class="lead">{len(blocks)} 镜 / {total:g} 秒　·　灰底行 = 这一秒有新的运镜路径</p></header>
{''.join(rows)}
<footer>由 <code>分镜/{epid}.json</code> 生成 —— 改分镜重跑 <code>board_readable.py</code>，别手改这一页。</footer>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--sb", default=None, help="分镜文件名，默认 EPxxx.json")
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()

    epid = f"EP{a.ep:03d}"
    d = os.path.join(ROOT, "projects", a.project, "分镜")
    src = os.path.join(d, a.sb or f"{epid}.json")
    if not os.path.exists(src):
        sys.exit(f"找不到 {src}")
    sb = json.load(io.open(src, encoding="utf-8"))
    total, blocks = build(sb, epid)
    stem = os.path.splitext(os.path.basename(src))[0]

    md = os.path.join(d, f"{stem}_中文.md")
    io.open(md, "w", encoding="utf-8").write(to_md(sb, epid, total, blocks))
    print(f"✓ {md}")
    if a.html:
        hp = os.path.join(d, f"{stem}_中文.html")
        io.open(hp, "w", encoding="utf-8").write(to_html(sb, epid, total, blocks))
        print(f"✓ {hp}")
    print(f"  {len(blocks)} 镜 / {total:g} 秒")


if __name__ == "__main__":
    main()
