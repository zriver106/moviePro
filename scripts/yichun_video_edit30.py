#!/usr/bin/env python3
"""30秒修正任务：整段编辑或原始资产首尾帧约束，保留每次请求。"""
import argparse
import fcntl
import hashlib
import json
import subprocess
import time
import provider
from yichun_video30 import K, P, read, write, sha, require_plan, uploaded


def build(spec_path):
    require_plan()
    spec = read(spec_path)
    if spec['plan_sha256'] != sha(K/'30秒分段方案.json'):
        raise ValueError('编辑依据的分段方案已变更')
    if spec['scope'] != 'faithful_execution_repair':
        raise ValueError('本工具仅执行已评级动作的忠实纠错')
    strategy=spec.get('strategy','editing')
    if strategy=='keyframe_pair':
        registry=read(K/'参考采用.json')
        for key in ('first_frame','last_frame'):
            ref=spec[key];record=registry.get(ref['path'],{})
            if record.get('status')!='accepted_reference' or record.get('sha256')!=ref['sha256'] or sha(P/ref['path'])!=ref['sha256']:
                raise ValueError('首尾参考未采用或指纹变化')
        task=dict(spec,model='2.5',mode='i2v',seconds=30,api_duration='30',resolution='480p',audio=True)
    elif strategy=='editing':
        source=P/spec['source']
        if sha(source)!=spec['source_sha256']:raise ValueError('源视频已变更')
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(source)]))
        if not 29.8<=float(probe['format']['duration'])<=30.2:raise ValueError('源视频必须为一个完整30秒段落')
        task=dict(spec,model='2.5',mode='ref',task='editing',seconds=30,api_duration='auto_from_30_second_source',resolution='480p',audio=True)
    else:raise ValueError('未知修正策略')
    task['request_sha256'] = hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return task


def run(spec_path):
    task = build(spec_path)
    folder = K/'视频'/task['segment']; folder.mkdir(parents=True,exist_ok=True)
    out = folder/f'take_{task["take"]:02d}_480p.mp4'; log = out.with_suffix('.json')
    with out.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if log.exists():
            old=read(log)
            if old.get('request_sha256')==task['request_sha256'] and out.exists() and old.get('video_sha256')==sha(out):
                return {'status':'existing','path':str(out.relative_to(P))}
            raise ValueError('该take已有请求记录，禁止重复提交')
        write(log,dict(task,status='preparing',started_at=time.time()))
        try:
            if task['mode']=='i2v':
                ref={'first_frame':task['first_frame'],'last_frame':task['last_frame']}
                write(log,dict(task,status='uploading',started_at=time.time()))
                kwargs={'image_url':uploaded(task['first_frame']),'end_image_url':uploaded(task['last_frame']),'aspect':'auto'}
            else:
                # 原片多出的1–2帧仅作容器长度收齐；不拼接不同生成片段。
                source=P/task['source'];trim=K/'参考'/f'{task["segment"]}_edit_source_{task["source_sha256"][:12]}.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-t','30','-c:v','libx264','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',str(trim)],check=True)
                ref={'path':str(trim.relative_to(P)),'sha256':sha(trim)}
                write(log,dict(task,status='uploading',input_video=ref,started_at=time.time()))
                kwargs={'video_urls':[uploaded(ref)],'task':'editing'}
            if build(spec_path)['request_sha256']!=task['request_sha256']:raise ValueError('准备期间输入变更')
            write(log,dict(task,status='submitted',input_video=ref,started_at=time.time()))
            result,error=provider.video(task['prompt'],model='2.5',mode=task['mode'],seconds=30,
                resolution='480p',audio=True,seed=task['seed'],**kwargs)
            if error or not result:raise RuntimeError(error or '空视频响应')
            provider.fetch(result,str(out))
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)]))
            duration=float(probe['format']['duration'])
            if not 29.8<=duration<=30.2:raise ValueError(f'编辑结果时长异常：{duration}')
            if not any(x['codec_type']=='audio' for x in probe['streams']):raise ValueError('编辑结果缺音轨')
            write(log,dict(task,status='generated_pending_visual_and_dialogue_check',input_video=ref,
                video_sha256=sha(out),duration=duration,probe=probe,completed_at=time.time()))
            return {'status':'generated_pending_visual_and_dialogue_check','path':str(out.relative_to(P)),'duration':duration}
        except Exception as exc:
            write(log,dict(task,status='failed_or_uncertain',error=str(exc),completed_at=time.time()))
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('spec',type=__import__('pathlib').Path);parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    print(json.dumps(run(args.spec) if args.run else build(args.spec),ensure_ascii=False))
