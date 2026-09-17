#!/usr/bin/env python3
"""V4横屏首版：一次30秒首生，三次真实extension，原任务取回，禁止自动返修。"""
import argparse,hashlib,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
import provider,script_lock,negwords
ROOT=Path(__file__).resolve().parents[1]
PROJECT='一寸活路_总包V4_EP01_国漫v8_20260917'
P=ROOT/'projects'/PROJECT
D=P/'横屏重制_30秒延长98秒_v01'
def read(p):return json.loads(p.read_text())
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(p)]))
def submit(name):
 script_lock.require(PROJECT,1,'用户授权横屏重制30秒再延长98秒')
 plan=read(D/'制作计划.json');spec=read(D/'任务规格.json')[name]
 if name not in plan['authorized_jobs']:raise SystemExit('任务不在本轮授权名单')
 body=spec['body'].copy();log=D/'记录'/f'{name}.json'
 if log.exists():raise SystemExit('已有任务记录，禁止重复提交；查询原任务')
 if body.get('task')=='editing':raise SystemExit('本轮先交首版，禁止自行修复')
 if negwords.scan(body['prompt']):raise SystemExit(str(negwords.scan(body['prompt'])))
 refs=spec['refs'];registry=read(D/'参考登记.json')
 for ref in refs:
  if registry.get(ref,{}).get('sha256')!=sha(P/ref):raise SystemExit('参考尚未核对或字节变化：'+ref)
 if spec['capability']=='video':
  if body.get('task')=='extension':
   videos=[r for r in refs if Path(r).suffix=='.mp4'];assert len(videos)==1
   source=P/videos[0];info=probe(source);v=next(s for s in info['streams'] if s['codec_type']=='video')
   if not 1.8<=float(info['format']['duration'])<=30.2 or source.stat().st_size>200_000_000 or abs(v['width']/v['height']-16/9)>.02:raise SystemExit('延长输入必须横屏且1.8—30.2秒/200MB内')
   if not spec.get('actual_join_record') or not (D/spec['actual_join_record']).exists():raise SystemExit('缺少实际末态接续记录')
   body['aspect_ratio']='auto'
  elif name!='VIDEO_00_30' or body.get('aspect_ratio')!='16:9':raise SystemExit('仅首段可首生，后续必须延长')
 record={'state':'preparing_upload','started_at':datetime.now(timezone.utc).isoformat(),'spec':spec,'references':{r:sha(P/r) for r in refs}}
 log.parent.mkdir(exist_ok=True,parents=True)
 with log.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
 cachepath=P/'记录/上传缓存.json';cache=read(cachepath);urls=[]
 for r in refs:
  h=sha(P/r)
  if h not in cache:cache[h]=provider.upload(str(P/r));save(cachepath,cache)
  urls.append(cache[h])
 body['image_urls']=[u for r,u in zip(refs,urls) if Path(r).suffix.lower() in ('.png','.jpg','.jpeg')]
 if spec['capability']=='video':
  body['video_urls']=[u for r,u in zip(refs,urls) if Path(r).suffix.lower()=='.mp4']
  body['audio_urls']=[u for r,u in zip(refs,urls) if Path(r).suffix.lower() in ('.wav','.mp3')]
 record.update(state='submitting',body=body);save(log,record)
 try:
  handle=provider.queue_submit(spec['capability'],body,model=spec['model'],mode='ref')
  record.update(state='submitted',handle=handle);save(log,record);print(name,handle['request_id'])
 except Exception as e:record.update(state='submission_error_or_unknown',error=str(e));save(log,record);raise

def poll():
 for log in sorted((D/'记录').glob('*.json')):
  r=read(log)
  if r.get('state') not in ('submitted','IN_QUEUE','IN_PROGRESS','COMPLETED'):continue
  s=provider.queue_read(r['handle']);r.update(state=s['status'],status=s);save(log,r)
  if s['status']=='COMPLETED':
   try:
    result=provider.queue_read(r['handle'],result=True);r['result']=result
    media=result['video']['url'] if r['spec']['capability']=='video' else result['images'][0]['url']
    out=D/r['spec']['output'];out.parent.mkdir(exist_ok=True,parents=True);provider.fetch(media,str(out))
    r.update(state='downloaded_first_version',output_sha256=sha(out))
    if r['spec']['capability']=='video':r['probe']=probe(out)
    cachepath=P/'记录/上传缓存.json';cache=read(cachepath);cache[sha(out)]=media;save(cachepath,cache)
   except Exception as e:r.update(state='result_error',error=str(e))
   save(log,r)
  print(log.stem,r['state'])
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['submit','poll']);ap.add_argument('name',nargs='?');a=ap.parse_args();submit(a.name) if a.action=='submit' else poll()
