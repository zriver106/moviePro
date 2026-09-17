#!/usr/bin/env python3
"""总包V4独立项目执行器：评级、已验参考、任务留痕、防重复提交。"""
import argparse, hashlib, json, subprocess
from pathlib import Path
from datetime import datetime, timezone
import provider, script_lock, negwords
ROOT=Path(__file__).resolve().parents[1]
PROJECT='一寸活路_总包V4_EP01_国漫v8_20260917'
P=ROOT/'projects'/PROJECT

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def save(p,v):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def submit(name):
    script_lock.require(PROJECT,1,'新总包素材制作')
    spec=read(P/'记录/任务规格.json')[name]
    policy_path=P/'记录/首版制作流程.json'
    policy=read(policy_path) if policy_path.exists() else {}
    if policy.get('status')=='make_first_cut_then_user_review' and spec['body'].get('task')=='editing':
        raise SystemExit('先交完整首版供用户看片；暂停新增画面编辑任务')
    first_cut=False
    if spec.get('first_cut'):
        first_cut=policy.get('status')=='make_first_cut_then_user_review' and name in policy.get('missing_video_jobs',[])
        if not first_cut:raise SystemExit('缺少首版缺失片段制作授权记录')
    log=P/'记录'/f'{name}.json'
    if log.exists():raise SystemExit(f'{name}已有提交记录，禁止重复生成；poll取回原任务')
    approved=read(P/'记录/已验参考.json')
    refs=spec.get('refs',[])
    audio_refs=[r for r in refs if Path(r).suffix.lower() in ('.mp3','.wav')]
    if audio_refs and not (spec['capability']=='video' and spec.get('mode')=='ref'):
        raise SystemExit('配音参考必须使用多模态视频模式')
    if audio_refs:
        durations=[]
        for r in audio_refs:
            duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(P/r)],text=True))
            if not 1.8<=duration<=30.2 or (P/r).stat().st_size>15*1024*1024:
                raise SystemExit(f'配音参考超出官方时长或文件大小限制：{r}')
            durations.append(duration)
        if len(audio_refs)>10 or sum(durations)>30.2:
            raise SystemExit('配音参考总数或总时长超出官方限制')
    for ref in refs:
        entry=approved.get(ref,{})
        cut_ref=policy.get('reference_hashes',{}).get(ref) if first_cut else None
        if entry.get('sha256')!=sha(P/ref) and cut_ref!=sha(P/ref):raise SystemExit(f'参考未验或已改变：{ref}')
        original_for_edit=(spec['body'].get('task')=='editing' and Path(ref).suffix.lower()=='.mp4')
        if spec['capability']=='video' and entry.get('editing_input_only') and not original_for_edit and cut_ref!=sha(P/ref):
            raise SystemExit(f'纠偏输入尚不能作为视频参考：{ref}')
    if spec['capability']=='video' and not first_cut and not spec.get('previs') and spec['body'].get('task')!='editing':
        gate=P/'预演/验收.json'
        if not gate.exists() or any(read(gate).get(f'S{n:02d}',{}).get('status')!='passed' for n in range(10,15)):
            raise SystemExit('S10—S14实际预演未全部通过，禁止铺开整集视频')
    body=spec['body'].copy()
    bad=negwords.scan(body['prompt'])
    if bad:raise SystemExit(f'提示出现否定表达：{bad}')
    record={'state':'submitting','started_at':datetime.now(timezone.utc).isoformat(),'spec':spec,'references':{r:sha(P/r) for r in refs}}
    # O_EXCL语义，崩溃保留不确定提交记录，不重复扣费。
    with log.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
    cachepath=P/'记录/上传缓存.json';cache=read(cachepath) if cachepath.exists() else {}
    urls=[]
    for r in refs:
        digest=sha(P/r)
        if digest not in cache:
            cache[digest]=provider.upload(str(P/r));save(cachepath,cache)
        urls.append(cache[digest])
    if spec['capability']=='edit':body['image_urls']=urls
    elif spec['capability']=='video':
        if spec.get('mode','i2v')=='i2v':
            if len(urls) not in (1,2):raise ValueError('I2V必须有已验SF，可选EF')
            body['image_url']=urls[0]
            if len(urls)==2:body['end_image_url']=urls[1]
        else:
            body['image_urls']=[u for r,u in zip(refs,urls) if Path(r).suffix.lower() in ('.jpg','.jpeg','.png','.webp')]
            body['video_urls']=[u for r,u in zip(refs,urls) if Path(r).suffix.lower() in ('.mp4','.mov')]
            if audio_refs:body['audio_urls']=[u for r,u in zip(refs,urls) if r in audio_refs]
    record['body']=body;save(log,record)
    try:
        handle=provider.queue_submit(spec['capability'],body,model=spec.get('model','2.5'),mode=spec.get('mode','i2v'))
        record.update(state='submitted',handle=handle);save(log,record)
        print(name,handle['request_id'])
    except Exception as exc:
        record.update(state='submission_error_or_unknown',error=str(exc));save(log,record);raise

def poll():
    for log in sorted((P/'记录').glob('*.json')):
        rec=read(log)
        if not isinstance(rec,dict) or rec.get('state') not in ('submitted','IN_QUEUE','IN_PROGRESS','COMPLETED'):continue
        status=provider.queue_read(rec['handle']);rec['status']=status;rec['state']=status['status'];save(log,rec)
        if rec['state']=='COMPLETED':
            try:
                result=provider.queue_read(rec['handle'],result=True);rec['result']=result
                capability=rec['spec']['capability']
                if capability=='video':media=result.get('video',{}).get('url')
                elif capability=='tts':media=result.get('audio',{}).get('url')
                else:media=result.get('images',[{}])[0].get('url')
                if not media:raise RuntimeError('服务完成但缺少素材地址')
                target=P/rec['spec']['output'];target.parent.mkdir(parents=True,exist_ok=True)
                provider.fetch(media,str(target));rec.update(state='downloaded_unreviewed',output_sha256=sha(target))
            except Exception as exc:rec.update(state='result_error',error=str(exc))
            save(log,rec)
        print(log.stem,rec['state'])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['submit','poll']);ap.add_argument('name',nargs='?');a=ap.parse_args()
    if a.action=='submit':submit(a.name)
    else:poll()
