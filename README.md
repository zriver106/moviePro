# moviePro

短剧自动化制作流水线。剧本进，成片出。

```
立项 → 剧本 → 剧本医生 → 定稿 → 分镜 → 资产 → 关键帧 → 出片 → 验收纠错 → 成片
                          ↑                                        ↓
                    冻文字 + 冻样子                          小问题当场改，
                    改了下游全废                              别重渲整条
```

## 四层

| 层 | 目录 | 碰不碰 API |
|---|---|---|
| 规格 | `.claude/skills/` | **不碰**。产出文字规格，刻意不生成媒体 |
| 执行 | `scripts/` | **只有这一层**，且统一走 `provider.py` |
| 剧目 | `projects/<剧名>/` | 每部戏的剧本、分镜、资产 |
| 方法 | `docs/` | — |

**判据：产出文字规格 → skill；产出图和视频 → `scripts/`。**

## 从这里读起

| 文档 | 管什么 |
|---|---|
| [`工作流.md`](工作流.md) | **一集从头到尾**，每步花不花钱、过哪几道门禁 |
| [`CLAUDE.md`](CLAUDE.md) | 五条跨环节铁律 |
| [`docs/打斗分镜制作.md`](docs/打斗分镜制作.md) | 打戏：牌面、密度、运镜、特效、形态切换 |
| [`docs/验收与纠错.md`](docs/验收与纠错.md) | 成片怎么验、发现问题选哪条修法 |
| [`docs/asset-management.md`](docs/asset-management.md) | 资产铁律 |

## 五条铁律（详见 CLAUDE.md）

```
否定即点名        写 no cut，硬切率 43% → 86%
图字冲突时图赢     想换造型必须换图，不能只换字
语域铁律          给人看的文本不能直接喂模型
静默兜底最贵       回落值错了下游发现不了，就不许静默回落
派生跟着源头       改了源字段就问一句「谁是从它推出来的」
```

## 供应商可替换

所有出图/出片/ASR 只从 `scripts/provider.py` 走，业务脚本里不出现服务商域名。

```bash
MOVIEPRO_BACKEND=fal        # 中介
MOVIEPRO_BACKEND=official   # 官方直连
```

上限查 `provider.capabilities(model)`，超限在调用前报错 —— **不静默截断**。

## 跑起来

```bash
python3 -m venv .venv && .venv/bin/pip install Pillow opencv-python-headless zhconv
mkdir key    # 放 API 密钥，已 gitignore
```

`ffmpeg-full` 用于烧字幕（系统自带的 ffmpeg 没编 `subtitles` 滤镜）。

## 不在版本控制里

`key/`（密钥）、`render_api/` `keyframes/` `交付/`（生成物，源头是分镜和 prompt）、
`cells_debug` `sheet.raw`（可再生的中间图）。
