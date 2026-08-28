#!/usr/bin/env python3
"""否定词表。**只能有这一份。**

之前有两份：`gen_asset.py` 的表里有 `only`，`compile_prompts.py` 的没有 ——
而跑主链路的恰恰是弱的那一份。结果分镜 prompt 里躺着 37 处 `only`，
其中「These 2 are the only people who appear」来自 `cast_line()`，
是从上一部戏就带着的老 bug，一直没人发现。

CLAUDE.md 里早就写着「`the only person visible`、`at any moment` 都中招」，
但规则写在文档里、表分散在两个文件里，等于没有规则。
和 `asset_gate.py` 是同一个教训：**同一条规则不许有两份实现。**

## 为什么 only 也算否定词

「只有 X」在语义上等于「除了 X 都没有」—— 模型收到的是一份排除清单，
而排除即点名。正面写法是直接说要什么：

    ✗ These 2 are the only people who appear
    ✓ The headcount stays exactly 2 from the first frame to the last
    ✗ the camera moves only as described above
    ✓ the camera follows exactly the path described above
    ✗ drawn only as three crimson trails
    ✓ drawn as three crimson trails
"""
import re

WORDS = (r"no|not|none|never|without|avoid|avoiding|don't|doesn't|didn't|isn't|"
         r"aren't|won't|can't|cannot|nothing|nobody|nowhere|neither|nor|lack|"
         r"lacking|free of|instead of|rather than|absent|omit|exclude|refrain|only")

NEG_RE = re.compile(r"\b(" + WORDS + r")\b", re.I)


def scan(text):
    return sorted({m.group(0).lower() for m in NEG_RE.finditer(text)})
