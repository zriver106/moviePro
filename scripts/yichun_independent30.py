#!/usr/bin/env python3
"""Two newly authorized fictional text-only clips. Does not resubmit rejected media."""
import argparse,json
from datetime import datetime,timezone
import provider,script_lock,negwords
from yichun_landscape98 import P,PROJECT,sha,probe,save,read
D=P/'横屏独立两段30秒_v01'
def submit(name):
 script_lock.require(PROJECT,1,'用户要求独立新增两个30秒')
 plan=read(D/'制作计划.json');s=read(D/'任务规格.json')[name]
 if name not in plan['jobs'] or len(plan['jobs'])!=2:raise SystemExit('本轮限两条独立首版任务')
 body=s['body'];log=D/'记录'/f'{name}.json'
 if log.exists():raise SystemExit('已有提交记录，禁止重复生成')
 if s.get('refs') or any(k in body for k in ('image_url','image_urls','video_urls','audio_urls','task')):raise SystemExit('本轮为新虚构文本创作，不接收参考媒体')
 if body.get('duration')!='30' or body.get('aspect_ratio')!='16:9':raise SystemExit('必须30秒16:9')
 if negwords.scan(body['prompt']):raise SystemExit(str(negwords.scan(body['prompt'])))
 r={'state':'submitting','started_at':datetime.now(timezone.utc).isoformat(),'spec':s,'source_sha256':sha(P/'来源/视频制作总包.txt')}
 log.parent.mkdir(exist_ok=True,parents=True)
 with log.open('x') as f:json.dump(r,f,ensure_ascii=False,indent=2)
 try:r.update(state='submitted',handle=provider.queue_submit('video',body,model='2.5',mode='t2v'));save(log,r);print(name,r['handle']['request_id'])
 except Exception as e:r.update(state='submission_error_or_unknown',error=str(e));save(log,r);raise

def poll():
 for log in sorted((D/'记录').glob('*.json')):
  r=read(log)
  if r.get('state') not in ('submitted','IN_PROGRESS','IN_QUEUE','COMPLETED'):continue
  status=provider.queue_read(r['handle']);r.update(state=status['status'],status=status);save(log,r)
  if r['state']=='COMPLETED':
   try:
    result=provider.queue_read(r['handle'],result=True);out=D/r['spec']['output'];out.parent.mkdir(exist_ok=True,parents=True);provider.fetch(result['video']['url'],str(out));r.update(state='downloaded_first_version',result=result,sha256=sha(out),probe=probe(out))
   except Exception as e:r.update(state='result_error',error=str(e))
   save(log,r)
  print(log.stem,r['state'])
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['submit','poll']);ap.add_argument('name',nargs='?');a=ap.parse_args();submit(a.name) if a.action=='submit' else poll()
