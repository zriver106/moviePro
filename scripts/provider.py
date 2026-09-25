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
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys


def arkcli_image(*, project, episodes, endpoint, profile, prompt, inputs,
                 output_dir, record_path, size="1536x2560"):
    """单张 Ark CLI 图片入口；保留评级闸与独占调用记录，未知结果不重提。

    调用者先核对精确模型的参数、参考图及预算。凭证由 Ark CLI 管理。
    此入口不改变历史 fal 路由，也不提供失败后的供应商回落。
    """
    from pathlib import Path
    import rating_gate

    if not episodes or not endpoint.startswith("ep-") or not profile:
        raise ValueError("必须指定评级集数、已核验Endpoint和Profile")
    rating_gate.require(project, episodes, "Ark CLI定妆生成")
    refs = [Path(f).resolve(strict=True) for f in inputs]
    dest = Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    record = Path(record_path)
    record.parent.mkdir(parents=True, exist_ok=True)
    state = {"status": "submitting", "endpoint": endpoint, "profile": profile,
             "prompt": prompt, "inputs": [str(f) for f in refs], "size": size}
    # 独占创建：同一调用即使超时也必须先人工对账，不能再次提交。
    with record.open("x") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    argv = ["arkcli", "+gen", "--model", endpoint, "--profile", profile,
            "--modality", "image", "--size", size, "--output-format", "png",
            "--watermark=false", "--no-open", "--format", "json",
            "--save-to", str(dest)]
    for ref in refs:
        argv.extend(["--input", "@" + str(ref)])
    argv.append(prompt)
    env = dict(os.environ, ARKCLI_NO_UPDATE_NOTIFIER="1",
               ARKCLI_CALLER_TYPE="ai_agent", ARKCLI_CALLER_NAME="codex",
               ARKCLI_SKILL_NAME="arkcli-gen")
    try:
        run = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=600)
        state.update(stdout=run.stdout, stderr=run.stderr, exit_code=run.returncode)
        if run.returncode:
            raise RuntimeError("Ark CLI调用失败，查看调用记录；禁止自动重提")
        result = json.loads(run.stdout)
        if result.get("status") != "succeeded":
            raise RuntimeError("图片未明确成功，需核对原调用")
        paths = result.get("local_paths") or [result.get("local_path")]
        if len(paths) != 1 or not paths[0] or not Path(paths[0]).is_file():
            state["status"] = "generated_delivery_unverified"
            raise RuntimeError("服务端已生成，但单张本地交付未核实；禁止重提")
        state.update(status="succeeded", result=result)
        return result
    except BaseException:
        if state["status"] == "submitting":
            state["status"] = "unknown_requires_reconciliation"
        raise
    finally:
        record.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def arkcli_video_submit(*, project, episode, endpoint, profile, prompt, inputs,
                        duration, record_path):
    """提交已核验的2.0系列视频；独占记录防重提，异步任务立即保存ID。"""
    from pathlib import Path
    import rating_gate
    if not endpoint.startswith("ep-") or not 4 <= duration <= 15:
        raise ValueError("必须指定已核验的2.0系列Endpoint及4至15秒时长")
    rating_gate.require(project, [episode], "Ark CLI视频生成")
    refs = [Path(p).resolve(strict=True) for p in inputs]
    record = Path(record_path)
    record.parent.mkdir(parents=True, exist_ok=True)
    state = dict(status="submitting", endpoint=endpoint, profile=profile,
                 prompt=prompt, inputs=[str(p) for p in refs], duration=duration)
    with record.open("x") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    argv = ["arkcli", "+gen", "--model", endpoint, "--profile", profile,
            "--modality", "video", "--duration", str(duration), "--ratio", "16:9",
            "--resolution", "480p", "--generate-audio=true", "--watermark=false",
            "--no-open", "--format", "json", "--save-to="]
    for ref in refs:
        argv += ["--input", "reference_image:@" + str(ref)]
    argv.append(prompt)
    try:
        result = _arkcli_video_call(argv)
        if not result.get("task_id"):
            raise RuntimeError("提交未返回task_id，须核对原调用，禁止重提")
        state.update(status="submitted", result=result, task_id=result["task_id"])
        return result
    except BaseException as exc:
        state.update(status="unknown_requires_reconciliation", error=str(exc))
        raise
    finally:
        record.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _arkcli_video_call(argv):
    env = dict(os.environ, ARKCLI_NO_UPDATE_NOTIFIER="1", ARKCLI_CALLER_TYPE="ai_agent",
               ARKCLI_CALLER_NAME="codex", ARKCLI_SKILL_NAME="arkcli-gen")
    run = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=180)
    if run.returncode:
        raise RuntimeError(run.stdout + "\n" + run.stderr)
    return json.loads(run.stdout)


def arkcli_video_get(*, task_id, profile, output_dir=""):
    """查询原任务；空目录只查询，成功后指定目录下载，绝不重新生成。"""
    return _arkcli_video_call(["arkcli", "gen", "get", task_id, "--profile", profile,
                              "--format", "json", "--no-open", "--save-to=" + str(output_dir)])


BACKEND = os.environ.get("MOVIEPRO_BACKEND", "fal")

BACKENDS = {
    "fal": {
        "auth": lambda: f"Key {keys.fal()}",
        "upload_init": "https://rest.alpha.fal.ai/storage/upload/initiate",
        "t2i": "https://fal.run/fal-ai/bytedance/seedream/v5/lite/text-to-image",
        "edit": "https://fal.run/fal-ai/bytedance/seedream/v5/lite/edit",
        "edit_pro": "https://fal.run/bytedance/seedream/v5/pro/edit",
        "asr": "https://fal.run/fal-ai/whisper",
        "asr_scribe": "https://fal.run/fal-ai/elevenlabs/speech-to-text/scribe-v2",
        "tts": "https://fal.run/fal-ai/minimax/speech-2.8-hd",
        "video": {
            ("2.0", "i2v"): "https://fal.run/bytedance/seedance-2.0/fast/image-to-video",
            ("2.0", "ref"): "https://fal.run/bytedance/seedance-2.0/reference-to-video",
            ("2.5", "i2v"): "https://fal.run/bytedance/seedance-2.5/image-to-video",
            ("2.5", "ref"): "https://fal.run/bytedance/seedance-2.5/reference-to-video",
            ("2.5", "t2v"): "https://fal.run/bytedance/seedance-2.5/text-to-video",
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
          image_urls=None, video_urls=None, audio_urls=None, task=None):
    """出片。**上限查 capabilities()，超了直接报错，不静默截断。**"""
    caps = capabilities(model)
    if task is not None:
        if model != '2.5' or mode != 'ref' or task not in ('reference','editing','extension'):
            return None, 'task仅适用于2.5/ref的reference、editing或extension'
        if task in ('editing','extension') and not video_urls:
            return None, '编辑或延展任务需要源视频'
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
    if task is not None:
        body['task'] = task
        if task in ('editing','extension'):body['aspect_ratio']='auto'
        if task == 'editing':body['duration']='auto'
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


def transcribe_scribe(path, language="zho"):
    """独立音轨复核：Scribe V2，不提供原台词或偏置词。"""
    body = {"audio_url": upload(path), "language_code": language,
            "tag_audio_events": False, "diarize": True}
    result, err = _post(_cfg()["asr_scribe"], body, timeout=900)
    return (None, err) if err else (result, None)


def fetch(url, dst):
    urllib.request.urlretrieve(url, dst)
    return dst


def queue_submit(capability, body, *, model="2.5", mode="i2v"):
    """显式提交一次并返回真实任务ID；调用端先落锁，失败不自动重投。"""
    if BACKEND != "fal":
        raise ValueError("当前队列适配仅支持fal")
    if capability == "video":
        if mode == "t2v" and any(k in body for k in ('image_url', 'image_urls', 'video_urls', 'audio_urls', 'end_image_url', 'task')):
            raise ValueError("纯文字视频请求不得携带素材或reference/editing/extension任务参数")
        endpoint = _cfg()["video"][(model, mode)]
        if body.get("resolution") not in capabilities(model)["resolutions"]:
            raise ValueError("视频分辨率不支持")
        duration = body.get("duration", "auto")
        if duration != "auto" and not 4 <= int(duration) <= capabilities(model)["max_seconds"]:
            raise ValueError("视频素材必须在接口时长范围内；短镜通过剪辑取完整动作")
        if body.get("task") in ("editing", "extension") and not body.get("video_urls"):
            raise ValueError("编辑/延展必须提供原视频")
    elif capability in ("edit", "t2i"):
        use_pro = capability == "edit" and model == "seedream-5-pro"
        endpoint = _cfg()["edit_pro" if use_pro else capability]
        size = body.get("image_size", "auto_2K")
        if len(body.get("image_urls", [])) > 10:
            raise ValueError("Seedream最多10张参考，禁止供应商静默截断")
        if use_pro:
            if isinstance(size, dict):
                width, height = size["width"], size["height"]
                if not 1024**2 <= width*height <= 2048**2 or not 1/16 <= width/height <= 16:
                    raise ValueError("Seedream Pro尺寸超出官方像素或比例范围")
            elif size not in ("square_hd", "square", "portrait_4_3", "portrait_16_9", "landscape_4_3", "landscape_16_9", "auto_1K", "auto_2K"):
                raise ValueError("Seedream Pro尺寸枚举无效")
        if isinstance(size, str) and size not in (
                "square_hd", "square", "portrait_4_3", "portrait_16_9",
                "landscape_4_3", "landscape_16_9", "auto_1K", "auto_2K", "auto_3K", "auto_4K"):
            raise ValueError("Seedream尺寸枚举无效，请使用官方枚举或width/height对象")
    elif capability == "tts":
        endpoint = _cfg()["tts"]
        if not body.get("voice_setting", {}).get("voice_id"):
            raise ValueError("配音必须指定固定voice_id")
    else:
        raise ValueError("不支持的队列能力")
    result, error = _post(endpoint.replace("https://fal.run/", "https://queue.fal.run/"), body, timeout=60)
    if error:
        raise RuntimeError(error)
    if not result.get("request_id"):
        raise RuntimeError("服务未返回任务ID；禁止盲目重投")
    return result


def queue_read(handle, *, result=False):
    """读取已提交任务，限制鉴权请求到供应商队列域名。"""
    url = handle["response_url" if result else "status_url"]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "queue.fal.run":
        raise ValueError("非法队列地址")
    req = urllib.request.Request(url, headers={"Authorization": _cfg()["auth"]()})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', 'replace')
        # Validation errors echo the entire prompt/input before useful context.
        # Keep diagnostic fields, rather than truncating inside that large echo.
        try:
            detail = json.loads(raw).get('detail')
            if isinstance(detail, list):
                detail = [{k: item[k] for k in ('loc', 'msg', 'type', 'ctx') if k in item}
                          if isinstance(item, dict) else item for item in detail]
            diagnostic = json.dumps(detail, ensure_ascii=False) if detail is not None else raw
        except (ValueError, AttributeError):
            diagnostic = raw
        raise RuntimeError(f"队列读取 {exc.code}: {diagnostic[:2000]}") from exc
