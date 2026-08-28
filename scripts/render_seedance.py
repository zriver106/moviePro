#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 fal 的 Seedance 2.0 渲镜头。剧目无关。

2026-08-15 换掉 MiniMax H3，理由是实测出来的，不是听说的：

  台词    prompt 里写 `She says in Chinese: 不能。`，ASR 回读逐字对上
  口型    音画一起生成，天生同步 —— 这是《太子》最贵的那个 bug 的根治
  时长    4–15 秒精确可控（H3 官方 API 最短 6 秒，每镜都得裁）
  首末帧  i2v 可以同时给 image_url 和 end_image_url（H3 官方只有首帧）
  参考图  ref2v 支持最多 9 张 @ImageN + 3 段 @AudioN —— H3 完全没有这个通道

两个端点，用途不一样：

  fast/image-to-video    首帧=合成好的关键帧。**空间关系、光位、桌面陈设
                         全靠这张图锁死** —— 实测这三样 prompt 管不住：
                         说了「椅子在桌子对面」它放在人身后同侧，
                         参考图是白天办公室它渲成夜景城市灯光，
                         桌上还凭空多出一台笔记本电脑
  reference-to-video     最多 9 张参考图，prompt 里用 @Image1 点名。
                         身份锁得极牢（同一张脸，眉眼鼻唇发际线全对上），
                         **构图完全听 prompt**（喂近景脸、要中景，出来就是中景）
                         —— 这跟出静态图时「参考图控制不了构图」正好相反：
                         那边参考图在抢构图，这边参考图只承担身份

所以默认 i2v；关键帧合不出来、或者要外挂音轨驱动口型时才用 ref2v。

  .venv/bin/python scripts/render_seedance.py --project 搞笑办公室连续剧1 --ep 1 --dry-run
  .venv/bin/python scripts/render_seedance.py --project 搞笑办公室连续剧1 --ep 1 --only EP001_SH08
  .venv/bin/python scripts/render_seedance.py --project 搞笑办公室连续剧1 --ep 1 --mode ref
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import sys
import threading
import urllib.error
import urllib.request

import asset_gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys              # 密钥只此一处
import provider          # 出图/出片/ASR 只从这里走
