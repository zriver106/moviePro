#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密钥读取。**只此一处** —— 别在各个脚本里各写各的路径。

2026-08-25 Andy 把密钥收进 `key/`。收之前十个脚本各自写着
`os.path.join(ROOT, "fal.ai")`，改一个位置要改十处，**漏一处就是跑到一半才炸**，
而且炸的时候看起来像 API 出问题。跟否定词表那次是同一个教训：
**同一条规则不许有两份实现。**

    key/fal.ai      出图（Seedream）+ 出片（Seedance）+ ASR（whisper）
    key/sk-api      MiniMax-M3，剧本链路
    key/tg-token    Telegram 发片

老位置（仓库根目录）留作兼容，读到了会提示挪走。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYDIR = os.path.join(ROOT, "key")


def read(name):
    """按名字取密钥。找不到就退出并说清楚该放哪 —— 别返回空串让下游拿去请求。"""
    new = os.path.join(KEYDIR, name)
    old = os.path.join(ROOT, name)
    if os.path.exists(new):
        v = open(new).read().strip()
        if not v:
            sys.exit(f"✗ {new} 是空的")
        return v
    if os.path.exists(old):
        print(f"⚠ {name} 还在仓库根目录，请挪进 key/：mv {name} key/", file=sys.stderr)
        return open(old).read().strip()
    sys.exit(f"✗ 找不到密钥 {name}。放到 {new}")


def fal():
    return read("fal.ai")


def minimax():
    return read("sk-api")


def telegram():
    return read("tg-token")
