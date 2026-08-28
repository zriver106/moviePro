#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定妆定稿：给常驻角色、高频道具、高频场景各定一张**基础样式图**。剧目无关。

## 这一步在干什么

剧本定稿（`script_lock.py`）冻的是**文字**。这一步冻的是**样子**：

    反复出现的东西，先定一张基础样式图，人确认，锁住指纹。
    之后所有资产 —— 多面 sheet、表情格、动作格、派生形态 ——
    **全部从这张基础图 edit 出来**，不许另起炉灶重画。

**基础样式图是单张，不要多面。** 多面和细节是资产阶段的事，这一步只回答
「这个人／这件道具／这个地方长什么样」。

## 为什么必须有

没有被锁住的母板，同一个东西每次生成都会漂：

    《漫剧》的狂化 H1/H2 一开始各画各的 —— 常态红色尖发，H1/H2 黑色短发，
    三档看起来是三个人。狂化的戏剧效果全靠「同一个人变了」，换了张脸就归零。
    改成从常态母板 edit 派生之后才对上。

    《搞笑办公室》的桌子在两个资产里木色不同（139,94,66 vs 100,70,62），
    SH01 切 SH02 就是两块木头。

## 基础样式图的三条硬要求

1. **中性光。** 环境光归场景管。踩过：三张定妆照都在红光里出的，
   脸部 R−B 高到 +150，模型把「红」当成了角色的固有色，
   场景光一变就冲突，成片里每处肤色都不一样。
2. **单张、正面、全身（道具/场景取最能说明它的那个角度）。**
   多面留给资产阶段。
3. **写可指认的部件，不写抽象词。**「一支精致的细银簪」三次画成
   银球/宽刃剑/巨型簪；写成「锥形细杆＋扁平五瓣梅花＋花心珍珠＋针尖」一次就对。

## 怎么用

    # ① 扫剧本，按出现频次排出该定稿的清单
    .venv/bin/python scripts/base_lock.py --project 漫剧战斗样片 --scan

    # ② 人过一遍清单（改 定稿/清单.json），然后出图
    .venv/bin/python scripts/base_lock.py --project 漫剧战斗样片 --gen --jobs 10

    # ③ 人看图，确认了再锁
    .venv/bin/python scripts/base_lock.py --project 漫剧战斗样片 --lock

下游 `gen_asset.py` 查这道闸：没锁的基础样式不许开始做资产。
"""
import argparse
import concurrent.futures as cf
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
import provider          # 出图/出片/ASR 只从这里走
