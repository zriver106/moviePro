#!/usr/bin/env python3
"""已评级30秒剧情的显式extension试验，保留原片，禁止重试和生成回退。"""
import argparse
import fcntl
import json
import subprocess
import time
import provider
from yichun_video30 import P,K,read,write,sha,require_plan,uploaded

ROOT=K/'延长试验/EP001'

def build():
    plan=require_plan();auth=read(ROOT/'授权.json')
    source=P/auth['source']
    if auth.get('task')!='extension' or auth.get('max_requests')!=1 or auth.get('episode')!='EP001':
        raise ValueError('本试验只授权第一集一次显式extension')
    if sha(source)!=auth['source_sha256']:raise ValueError('原片指纹变化')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(source)]))
    if not 29.8<=float(probe['format']['duration'])<=30.2 or source.stat().st_size>200_000_000:
        raise ValueError('输入必须为已有30秒原片且小于200MB')
    segment=next(s for s in plan['segments'] if s['id']=='EP001_B')
    old=read(K/'修正请求/EP001_B_first_completion.json');registry=read(K/'参考采用.json')
    refs=[dict(r) for r in old['references'][3:6]]
    roles=['Wen Xi, woman wearing pale mint green, wet clothes','the grey-bearded older worker, wet clothes','Ali, young man wearing blue, wet clothes']
    for ref,role in zip(refs,roles):
        ref['role']=role
        if sha(P/ref['path'])!=ref['sha256'] or registry[ref['path']]['status']!='accepted_reference' or registry[ref['path']]['sha256']!=ref['sha256']:
            raise ValueError('身份参考尚未采用或已变化')
    lines=['Continue @Video1 from its final instant with the next 30 seconds of this same stylized 3D Chinese animation. The following timeline starts at 0 seconds of the new continuation, corresponding to 30 seconds in the episode. Preserve the existing camera position, characters, wet costumes, props, lighting and spatial layout at the join. Lu Zhao starts with both bare hands gripping the wooden wedge beneath the drum, with his original short hemp-handled awl resting on the ledge. His palms stay bare and shoulder cloth intact. The soundtrack consists of synchronized Mandarin dialogue, water, breathing, cloth and wooden mechanism sounds. Keep the picture clean for later Chinese subtitle compositing.']
    lines += [f'@Image{i+1}: {ref["role"]}.' for i,ref in enumerate(refs)]
    lines += ['CAMERA: '+segment['camera_plan']['en'],'CONTINUATION TIMELINE:']
    for beat in segment['timeline']:
        lines.append(f'[{beat["start"]}–{beat["end"]}s] '+beat['action_en'])
        for line in beat['lines']:
            speaker='remembered elderly male voice off screen' if line['off_screen'] else 'Wen Xi with synchronized lips'
            lines.append(f'[{line["at"]}–{line["end"]}s] {speaker} says in Mandarin: “{line["text"]}”')
    return {'episode':'EP001','source':auth['source'],'source_sha256':auth['source_sha256'],
            'plan_sha256':sha(K/'30秒分段方案.json'),'authorization_sha256':sha(ROOT/'授权.json'),
            'task':'extension','model':'2.5','mode':'ref','seconds':30,'resolution':'480p',
            'references':refs,'prompt':'\n'.join(lines),'fallback_to_regeneration':False}

def run():
    task=build();ROOT.mkdir(parents=True,exist_ok=True);log=ROOT/'extension_01.json';output=ROOT/'extension_01.mp4'
    with (ROOT/'extension_01.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if log.exists() or output.exists():raise ValueError('试验已有请求或结果，禁止自动重复付费')
        write(log,dict(task,status='preparing',started_at=time.time()))
        try:
            video=uploaded({'path':task['source'],'sha256':task['source_sha256']})
            images=[uploaded(r) for r in task['references']]
            if build()!=task:raise ValueError('上传期间输入或授权变化')
            write(log,dict(task,status='submitted',started_at=time.time()))
            result,error=provider.video(task['prompt'],model='2.5',mode='ref',task='extension',video_urls=[video],image_urls=images,seconds=30,resolution='480p',audio=True)
            if error or not result:raise RuntimeError(error or '空延长响应')
            provider.fetch(result,str(output))
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
            write(log,dict(task,status='returned_pending_continuation_check',output_sha256=sha(output),probe=probe,completed_at=time.time()))
            print(json.dumps({'output':str(output),'duration':probe['format']['duration']},ensure_ascii=False))
        except Exception as exc:
            write(log,dict(task,status='failed_no_retry_no_fallback',error=str(exc),completed_at=time.time()))
            raise

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',action='store_true');a=ap.parse_args()
    if a.run:run()
    else:
        t=build();print(json.dumps({k:t[k] for k in ('episode','task','seconds','resolution','source')},ensure_ascii=False))
