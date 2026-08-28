#!/usr/bin/env python3
"""资产状态门禁：唯一一处定义「什么状态的资产可以进渲染」。

## 为什么单独开一个模块

这条规则**早就写在文档里了**。`docs/asset-management.md`：

    分镜引用的资产没 locked，分镜进不了队列。硬拦，不是警告。

然后 `grep -rn "status" scripts/*.py` **零命中** —— 没有任何脚本读它。
13 个资产处在三种状态里（draft / ready_for_review / approved），
char 上还多挂一个 `ready_to_render` 布尔，全部形同虚设，
什么状态都能进渲染。

**规则写在文档里而没有代码执行，等于没有规则。**
这和我们记过的另一条是同一个病：「规律只写在代码注释里，等于只对
那一个文件生效」。所以门禁不放在任何一个调用方里，单独一个模块，
两边 import 同一份。

## 状态机

    draft             刚出图，没人看过
    ready_for_review  出图方认为可用，等审
    approved          审过，可进渲染 —— **只有这一档放行**
    blocked           有已知问题，禁止进渲染，`status_reason` 必填

缺 `status.json`、状态值不在表内、状态是 `blocked` 却没写原因 ——
**三种都拦**。不是「读不到就放行」：读不到恰恰说明这个资产没人管过，
而我们所有最贵的 bug 都在「主路径失败后用最不设防的取值方式」上。

## 拦法

走各脚本**已有的** `blocked` 列表，不新开报错出口。
一个大家都认的闸门，比五个各自为政的 raise 有用。
"""
import json
import os

PASS = "approved"
KNOWN = ("draft", "ready_for_review", "approved", "blocked")
SUBDIRS = ("char", "wardrobe", "prop", "location")

_cache = {}


def _read(assets, aid):
    """返回 (status, reason)。读不到时 status 为 None，reason 说明为什么读不到。"""
    if (assets, aid) in _cache:
        return _cache[(assets, aid)]
    d = None
    for sub in SUBDIRS:
        p = os.path.join(assets, sub, aid)
        if os.path.isdir(p):
            d = p
            break
    if d is None:
        r = (None, "目录不存在")
    else:
        sp = os.path.join(d, "status.json")
        if not os.path.exists(sp):
            r = (None, "缺 status.json")
        else:
            try:
                j = json.load(open(sp, encoding="utf-8")) or {}
                r = (j.get("status"), j.get("status_reason"))
            except Exception as e:
                r = (None, f"status.json 读不动（{type(e).__name__}）")
    _cache[(assets, aid)] = r
    return r


def why_blocked(assets, aid):
    """不放行的理由；放行则返回 None。"""
    st, reason = _read(assets, aid)
    if st is None:
        return f"{aid} {reason}"
    if st not in KNOWN:
        return f"{aid} 状态 {st!r} 不在状态机里（合法值 {'/'.join(KNOWN)}）"
    if st == "blocked":
        return f"{aid} 是 blocked：{reason or '**没写原因** —— blocked 必须写明原因'}"
    if st != PASS:
        return f"{aid} 状态是 {st}，不是 {PASS}"
    return None


def check(assets, aid, blocked):
    """不放行就往 blocked 里追加一条（同一资产只记一次），返回是否放行。

    同一个资产在一镜里可能被裁多格，逐格追加会把 blocked 刷成一片重复。
    """
    w = why_blocked(assets, aid)
    if w is None:
        return True
    if w not in blocked:
        blocked.append(w)
    return False


def shot_assets(sh):
    """一镜声明依赖的全部资产 id。

    两个来源，都要认：
      uses.char / uses.prop / uses.location  —— 会变成像素的
      cast[].look                            —— 造型资产，决定 char sheet 穿什么
    """
    out = []
    u = sh.get("uses") or {}
    for c in u.get("char", []) or []:
        out.append(c["id"])
    for p in u.get("prop", []) or []:
        out.append(p["id"])
    loc = u.get("location")
    if loc:
        out.append(loc["id"])
    for c in sh.get("cast", []) or []:
        if c.get("look"):
            out.append(c["look"])
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def check_shot(assets, sh, blocked):
    """把一镜依赖的资产全过一遍门禁。返回是否全部放行。"""
    return all([check(assets, aid, blocked) for aid in shot_assets(sh)])
    # 注意这里是先算完整个列表再 all() —— 不能写成生成器。
    # all(生成器) 会在第一个 False 处短路，后面的资产就不进 blocked 了，
    # 人看到的报告只有第一个问题，修完再跑又冒出下一个。
    # （另：all([]) 是 True，空依赖的镜头放行，这是对的 —— 但同样这个
    # 「空列表返回 True」在别处坑过我们，见 CLAUDE.md 的静默兜底那节。）
