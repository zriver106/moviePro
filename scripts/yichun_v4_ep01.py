#!/usr/bin/env python3
"""总包V4独立项目执行器：评级、已验参考、任务留痕、防重复提交。"""
import argparse, hashlib, json
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
    log=P/'记录'/f'{name}.json'
    if log.exists():raise SystemExit(f'{name}已有提交记录，禁止重复生成；poll取回原任务')
    approved=read(P/'记录/已验参考.json')
    refs=spec.get('refs',[])
    for ref in refs:
        if approved.get(ref,{}).get('sha256')!=sha(P/ref):raise SystemExit(f'参考未验或已改变：{ref}')
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
            body['image_urls']=[u for r,u in zip(refs,urls) if not r.endswith('.mp4')]
            body['video_urls']=[u for r,u in zip(refs,urls) if r.endswith('.mp4')]
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
