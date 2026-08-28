#!/usr/bin/env python3
"""MiniMax-M3 的调用管道。剧本链路上三个脚本共用，不许各抄一份。

抽出来的理由和 `asset_gate.py` 一样：这里每一条都是踩出来的，
散在三个文件里就会有两个文件慢慢忘掉其中一条。

  <think> 要剥      M3 是推理模型，正文前面挂着一大段思考
  max_tokens 给足   <think> 也算 token，给小了正文被截成空字符串
  空返回要重试      空返回是 M3 的常态抖动，重试比报错有用
  裸换行要修        M3 常在 JSON 字符串里留真换行，标准 json 直接拒收
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
API = "https://api.minimaxi.chat/v1/chat/completions"
MODEL = "MiniMax-M3"


def key():
    return keys.minimax()


def chat(messages, max_tokens=32000, timeout=600):
    """max_tokens 默认 32000：<think> 也算在里面，给小了正文会被截空。"""
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens}
    req = urllib.request.Request(
        API, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return (d.get("choices") or [{}])[0].get("message", {}).get("content", "")


def strip_think(s):
    return re.sub(r"<think>.*?</think>", "", s or "", flags=re.S).strip()


def _fix_raw_newlines(js):
    """把 JSON 字符串内部的真换行转义掉。"""
    out, in_str, esc = [], False, False
    for ch in js:
        if esc:
            out.append(ch); esc = False; continue
        if ch == "\\":
            out.append(ch); esc = True; continue
        if ch == '"':
            in_str = not in_str
        if in_str and ch in "\n\r":
            out.append("\\n" if ch == "\n" else "")
            continue
        out.append(ch)
    return "".join(out)


def parse_json(s):
    s = strip_think(s)
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    m = re.search(r"[\[{].*[\]}]", s, re.S)
    if not m:
        return None
    for cand in (m.group(0), _fix_raw_newlines(m.group(0))):
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def ask_json(system, user, tries=3, max_tokens=32000, label=""):
    """要 JSON 的调用。三次拿不到就 exit —— **不返回半成品**。

    半成品往下游走，就是我们记过无数次的静默兜底：不报错，
    只是产出一份看起来合理的错数据。
    """
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    last = ""
    for i in range(tries):
        last = chat(msgs, max_tokens=max_tokens)
        r = parse_json(last)
        if r:
            return r
        print(f"  第 {i+1} 次{('（' + label + '）') if label else ''}"
              f"返回空或非 JSON，重试")
    sys.exit(f"{label or 'M3'}：{tries} 次都没拿到合法 JSON。"
             f"最后一次原文前 800 字：\n{strip_think(last)[:800]}")


def ask_text(system, user, tries=3, max_tokens=32000, label=""):
    """要纯文本的调用（剧本正文）。空返回重试，三次全空就 exit。"""
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    for i in range(tries):
        t = strip_think(chat(msgs, max_tokens=max_tokens))
        if t:
            return t
        print(f"  第 {i+1} 次{('（' + label + '）') if label else ''}返回为空，重试")
    sys.exit(f"{label or 'M3'}：{tries} 次都是空返回")
