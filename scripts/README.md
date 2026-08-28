# scripts/ —— 执行层

## 先看这条边界，否则会重复造轮子

2026-08-17 翻出来：`.claude/skills/` 里 8 月 14 日就装了 9 个 `drama-skills`，
覆盖小说 → 剧本 → 分镜 → 资产 → 提示词全链路。**而我在不知情的情况下
又写了一遍 `adapt_script.py` 和 `make_board.py`**，且 skill 那版更细
（它有 Coverage Audition、轴线/站位/视线/持物连续性检查）。

边界从此写死：

| 层 | 谁做 | 碰不碰 API |
|---|---|---|
| **规格与方法** | `drama-skills` 9 个 skill | **不碰**。它刻意不生成媒体，防止未确认的提示词烧钱 |
| **蒸馏** | `cangjie-skill` | 不碰 |
| **看片 / 量片** | `claude-video` `/watch`、`video-analyzer` | 不碰 |
| **执行** | 本目录 | **只有这一层调外部 API**（统一走 `provider.py`） |

**判据一句话：产出的是文字规格 → skill；产出的是图和视频 → 这里。**

剧目无关是第二条判据：这里每个脚本都接 `--project`。写死了某部剧的角色名、
场次号、资产 id 的，放 `projects/<剧名>/scripts/`；停用的时代放 `legacy_h3/`。

---

## 跑一集的顺序

```bash
P=漫剧战斗样片
V=.venv/bin/python

# ① 文本层 —— 优先用 skill，下面两个脚本是没有 skill 产出时的兜底
#    /short-drama-novel-analyze → develop → write        剧本
#    /short-drama-storyboard                             分镜
$V scripts/script_doctor.py    --project $P --ep 1
                               # 剧本医生：因果链/身份/动机/时间线/穿帮/节奏
                               # 判 FAIL 就先改剧本，别往下走

# ② 编译 —— 分镜 JSON → API 载荷
$V scripts/compile_prompts.py  --project $P --ep 1
                               # 顺带扫否定词和抽象情绪词，有一个就报

# ③ 资产
$V scripts/gen_asset.py        --project $P
$V scripts/measure_cells.py    --project $P            # bbox 实测，别用理论等分
$V scripts/vfx_alpha.py        --project $P            # 特效黑底 → RGBA
$V scripts/check_assets_bg.py  --project $P
                               # **门禁在 asset_gate.py，只有 approved 放行**

# ④ 关键帧
$V scripts/gen_kf.py           --project $P --ep 1
$V scripts/check_keyframes.py  --project $P --ep 1
                               # **人看图对清单再开渲。** 出总览图是为了并排看

# ⑤ 出片
$V scripts/render_seedance.py  --project $P --ep 1 --model 2.5
                               # 时长上限按端点分：2.0=15s，2.5=30s

# ⑥ 验收与后期
$V scripts/check_cuts.py       成片.mp4 --threshold 0.4
$V scripts/check_dialogue.py   --project $P --ep 1
$V scripts/cut_points.py       --project $P --ep 1
$V scripts/assemble.py         --project $P --ep 1
```

---

## 各脚本一句话（按层归位）

### 文本层兜底 —— 设计权归 skill，这两个只在没有 skill 产出时用

| 脚本 | 干什么 | 被谁取代 |
|---|---|---|
| `adapt_script.py` | 小说/梗概 → 剧本 md | `short-drama-write`（更细） |
| `make_board.py` | 剧本 → 分镜 JSON（中文层 + 英文渲染层两遍） | `short-drama-storyboard`（有 Coverage Audition 和连续性检查） |

**别删它们**：它们直接产出我们的 JSON schema。skill 产出的是**它自己的 JSON**
（`剧集/<EP>/storyboard/*.jsonl`，不是 markdown —— 这一句我先前写错过），
中间缺一个转换。等转换写好再决定是退休还是留作执行壳。

接缝的对照见 `docs/工作安排.md` 的「T4 补充」。

### 审查与门禁

| 脚本 | 干什么 |
|---|---|
| `script_doctor.py` | 剧本医生，MiniMax-M3 查逻辑漏洞，出 PASS/FAIL |
| `asset_gate.py` | **资产状态门禁，唯一一处定义什么能进渲染**。只有 `approved` 放行 |
| `negwords.py` | **否定词表，唯一一份**。两份表里弱的那份会悄悄放行，吃过亏 |
| `check_assets_bg.py` | 资产背景门禁：量边框环上的中灰平台，不是四角 |
| `check_keyframes.py` | 关键帧总览图 + 逐镜清单，人看图对分镜 |
| `check_cuts.py` | 数成片切了几次镜。打戏阈值 0.4，静态 0.1 |
| `check_dialogue.py` | 逐镜 ASR 回读，比对分镜里的台词原文 |

### 编译与生成（只有这几个花钱）

| 脚本 | 干什么 | 花钱 |
|---|---|---|
| `compile_prompts.py` | 分镜 JSON → prompt，写回同一份 JSON；扫否定词和情绪词 | 否 |
| `gen_asset.py` | 资产 sheet + 定妆图，一资产一次调用 | **出图/出片** |
| `gen_kf.py` | 资产 sheet 裁格 → 多图合成 16:9 首帧 | **出图/出片** |
| `gen_kf_chain.py` | 用上一镜的成片末帧生成下一镜的关键帧 | **出图/出片** |
| `render_seedance.py` | Seedance 出片，i2v / ref 双模式，`--model 2.0\|2.5` | **出片** |
| `m3.py` | MiniMax-M3 调用管道，剧本链路共用 | **MiniMax** |

### 资产加工（本机，不花钱）

| 脚本 | 干什么 |
|---|---|
| `measure_cells.py` | 实测 sheet 格位坐标写回 `cells_*.json`。**别用理论等分，模型排的格子不等分** |
| `vfx_alpha.py` | 黑底特效 sheet → RGBA 透明底，按格裁单格 PNG |
| `whiten_bg.py` | sheet 的浅灰影棚底提成纯白，不碰皮肤和深色 |

### 后期（本机 ffmpeg）

| 脚本 | 干什么 |
|---|---|
| `cut_points.py` | 每镜的剪辑入出点（渲染最短 4 秒，分镜可能 2–4 秒，都要裁） |
| `assemble.py` | 拼片 + 排字幕轴 + 烧字幕 |
| `assemble_takes.py` | 长镜版装配：拼片 + ASR 时间戳排字幕 |
| `finale_overlay.py` | 片尾定格 + 按锚点贴图 + 保持 N 秒 |
| `add_subtitle.py` | 单独烧字幕（字幕文本取自分镜原文，不取自音频转录） |

---

## 环境

系统 Python 是 PEP 668 externally-managed，装不了包。用项目自带 venv：

```bash
.venv/bin/python ...          # 已装 Pillow、opencv-python-headless
```

字幕烧录要 `ffmpeg-full`（系统自带的 ffmpeg 没编 `subtitles` 滤镜），
脚本会自动找 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`。

**`whisper` 是垫片**（`~/.local/bin/whisper`），把 openai-whisper 风格的参数
翻译成 `mlx_whisper`（Apple Silicon 原生，150 秒音轨 5 秒转完）。
装它是为了让 `video-analyzer` 这类写死了 `whisper` CLI 的 skill 直接能用，
而不用改 vendor 里的代码 —— 改 vendor 会在下次 `git pull` 时被冲掉。

## 密钥

```
key/fal.ai     当前供应商的密钥。**端点写在 provider.py，业务脚本里不出现域名**
sk-api     MiniMax-M3，剧本链路
```

都是读文件取，**别打印、别写进日志**。
