#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型供应商抽象层。**所有出图/出片/ASR 的网络调用只从这里走。**

## 为什么要有这一层

fal.ai 是中介。正式做项目会直接对接官方 API（火山引擎 / 即梦开放平台）。
如果各脚本里散着 `https://fal.run/...`，换供应商就要改八个文件，
**漏一处就是跑到一半才炸，而且炸出来看起来像 API 出问题**。

抽出来之后换供应商只改这一个文件：把 `BACKENDS` 里加一个 `official` 条目，
再把 `BACKEND` 环境变量指过去。业务脚本一行都不用动。

    MOVIEPRO_BACKEND=fal        默认，中介
    MOVIEPRO_BACKEND=official   官方直连（待接）

## 五个能力

    upload(path)                 传文件拿 URL（视频端点不吃 data URI）
    text_to_image(prompt, ...)   出图
    edit_image(prompt, imgs, ..) 多图合成 / 改图
    video(prompt, ...)           出片。mode=i2v|ref，model=2.0|2.5
    transcribe(path)             ASR 回读

**能力名是我们自己的词，不是某一家的端点名。** 换供应商时改的是映射，
不是调用点 —— 这是这一层唯一的价值。

## 换供应商时要重新验的事（跟端点绑死的，不是抽象层能吸收的）

    data URI 支不支持        fal 出图吃、视频不吃
    时长/分辨率上限          2.0 是 15s/720p，2.5 是 30s/1080p
    参考图张数上限           9 / 30
    内容策略                 2.5 拒收写实真人参考图和含人视频
    参数名与枚举值           duration 是字符串还是整数、resolution 的写法

这些差异在 `capabilities()` 里声明，业务脚本查它做决策，别自己写死。
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys

BACKEND = os.environ.get("MOVIEPRO_BACKEND", "fal")

BACKENDS = {
    "fal": {
        "auth": lambda: f"Key {keys.fal()}",
        "upload_init": "https://rest.alpha.fal.ai/storage/upload/initiate",
        "t2i": "https://fal.run/fal-ai/bytedance/seedream/v5/lite/text-to-image",
        "edit": "https://fal.run/fal-ai/bytedance/seedream/v5/lite/edit",
        "asr": "https://fal.run/fal-ai/whisper",
        "video": {
            ("2.0", "i2v"): "https://fal.run/bytedance/seedance-2.0/fast/image-to-video",
            ("2.0", "ref"): "https://fal.run/bytedance/seedance-2.0/reference-to-video",
            ("2.5", "i2v"): "https://fal.run/bytedance/seedance-2.5/image-to-video",
            ("2.5", "ref"): "https://fal.run/bytedance/seedance-2.5/reference-to-video",
        },
    },
    # official: 官方直连待接。加一个同构的条目即可，业务脚本不用动。
}

CAPS = {
    "2.0": {"max_seconds": 15, "resolutions": ("480p", "720p"), "max_refs": 9,
            "accepts_photoreal_people": True, "accepts_video_with_people": True},
    "2.5": {"max_seconds": 30, "resolutions": ("480p", "720p", "1080p"), "max_refs": 30,
            "accepts_photoreal_people": False, "accepts_video_with_people": False},
}


def capabilities(model="2.5"):
    """业务脚本查这个做决策，别自己写死上限。"""
    return CAPS[model]


def _cfg():
    if BACKEND not in BACKENDS:
        sys.exit(f"✗ 未知后端 {BACKEND}（有 {sorted(BACKENDS)}）")
    return BACKENDS[BACKEND]


def _post(url, body, timeout=1800):
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": _cfg()["auth"](),
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        d = e.read().decode("utf-8", "replace")
        # 内容策略是最常见的一类拒绝，单独点出来 —— 否则看起来像鉴权或参数错
        if "likenesses" in d:
            return None, f"{e.code} 内容策略：疑似真人肖像（换 2.0，或换非写实素材）"
        return None, f"{e.code} {d[:300]}"


def upload(path, content_type=None):
    """传文件拿 URL。视频端点不吃 data URI，只能先传。"""
    ext = os.path.splitext(path)[1].lower()
    ct = content_type or {".png": "image/png", ".jpg": "image/jpeg",
                          ".jpeg": "image/jpeg", ".mp4": "video/mp4",
                          ".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(ext,
                                                                         "application/octet-stream")
    c = _cfg()
    r = json.loads(urllib.request.urlopen(urllib.request.Request(
        c["upload_init"], method="POST",
        data=json.dumps({"content_type": ct,
                         "file_name": os.path.basename(path)}).encode(),
        headers={"Authorization": c["auth"](),
                 "Content-Type": "application/json"}), timeout=60).read())
    urllib.request.urlopen(urllib.request.Request(
        r["upload_url"], method="PUT", data=open(path, "rb").read(),
        headers={"Content-Type": ct}), timeout=900)
    return r["file_url"]


def text_to_image(prompt, size="landscape_16_9", seed=None, n=1):
    body = {"prompt": prompt, "image_size": size, "num_images": n}
    if seed is not None:
        body["seed"] = seed
    r, err = _post(_cfg()["t2i"], body, timeout=300)
    return (None, err) if err else ((r.get("images") or [{}])[0].get("url"), None)


def edit_image(prompt, image_urls, size="landscape_16_9", seed=None, n=1):
    body = {"prompt": prompt, "image_urls": image_urls, "image_size": size,
            "num_images": n}
    if seed is not None:
        body["seed"] = seed
    r, err = _post(_cfg()["edit"], body, timeout=300)
    return (None, err) if err else ((r.get("images") or [{}])[0].get("url"), None)


def video(prompt, *, model="2.5", mode="ref", seconds=None, resolution="720p",
          aspect="16:9", audio=True, seed=None, image_url=None, end_image_url=None,
          image_urls=None, video_urls=None, audio_urls=None):
    """出片。**上限查 capabilities()，超了直接报错，不静默截断。**"""
    caps = capabilities(model)
    if seconds is not None and seconds > caps["max_seconds"]:
        return None, (f"{model} 单段上限 {caps['max_seconds']} 秒（要 {seconds} 秒）。"
                      f"分段或换模型 —— 别让端点静默截断")
    if resolution not in caps["resolutions"]:
        return None, f"{model} 不支持 {resolution}（有 {caps['resolutions']}）"
    if image_urls and len(image_urls) > caps["max_refs"]:
        return None, f"{model} 参考图上限 {caps['max_refs']} 张（给了 {len(image_urls)}）"

    url = _cfg()["video"].get((model, mode))
    if not url:
        return None, f"后端 {BACKEND} 没有 {model}/{mode} 这个组合"
    body = {"prompt": prompt, "resolution": resolution, "aspect_ratio": aspect,
            "generate_audio": audio}
    if seconds is not None:
        body["duration"] = str(int(round(seconds)))
    if seed is not None:
        body["seed"] = seed
    for k, v in (("image_url", image_url), ("end_image_url", end_image_url),
                 ("image_urls", image_urls), ("video_urls", video_urls),
                 ("audio_urls", audio_urls)):
        if v:
            body[k] = v
    r, err = _post(url, body)
    return (None, err) if err else ((r.get("video") or {}).get("url"), None)


def transcribe(path, language="zh", chunk_level=None):
    """ASR 回读。传本地文件，内部先上传。"""
    body = {"audio_url": upload(path), "task": "transcribe", "language": language}
    if chunk_level:
        body["chunk_level"] = chunk_level
    r, err = _post(_cfg()["asr"], body, timeout=900)
    return (None, err) if err else (r, None)


def fetch(url, dst):
    urllib.request.urlretrieve(url, dst)
    return dst
