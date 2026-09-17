#!/usr/bin/env python3
"""Align canonical Mandarin captions to the first cut's actual ASR; no media generation."""
import difflib,json,re
from yichun_landscape98 import P,D,read,save
PARTS=[('VIDEO_00_30',0),('EXTEND_30_60',30),('EXTEND_60_90',60),('EXTEND_90_98',90)]
def normalized(s):return ''.join(c for c in s if c.isalnum())
def main():
 heard=[];times=[]
 for name,offset in PARTS:
  f=D/'声音核对'/f'{name}.json'
  if not f.exists():raise SystemExit('缺少原声听写：'+name)
  r=read(f);r=r['result'] if 'result' in r else r
  for w in r.get('words',[]):
   if w.get('type','word')!='word':continue
   chars=normalized(w.get('text',''))
   for i,c in enumerate(chars):
    heard.append(c);dur=w['end']-w['start'];times.append((offset+w['start']+dur*i/len(chars),offset+w['start']+dur*(i+1)/len(chars)))
 cues=read(P/'后期/对白时间轴草稿.json')['cues'];chunks=[];target=''
 for cue in cues:
  for part in re.findall(r'[^，。！？]+[，。！？]?',cue['text']):
   cleaned=normalized(part);start=len(target);target+=cleaned;chunks.append({'text':part,'chars':cleaned,'start_index':start})
 matcher=difflib.SequenceMatcher(None,target,''.join(heard),autojunk=False);mapping={}
 for a,b,n in matcher.get_matching_blocks():
  for j in range(n):mapping[a+j]=b+j
 rows=[];review=[]
 for c in chunks:
  indices=[mapping[i] for i in range(c['start_index'],c['start_index']+len(c['chars'])) if i in mapping]
  coverage=len(indices)/len(c['chars'])
  if not indices or coverage<.6:review.append({'text':c['text'],'matched_fraction':coverage});continue
  rows.append({'start':round(times[min(indices)][0],3),'end':round(times[max(indices)][1],3),'text':c['text']})
 report={'matched_fraction':len(mapping)/len(target),'unmatched_caption_chunks':review,'heard_text':''.join(heard),'canonical_text':target,'note':'首版对齐记录；不代表原声逐字通过，不触发修片或重生'}
 save(D/'后期/字幕对齐报告.json',report)
 if review:raise SystemExit('需人工核对未匹配台词，报告已保存；不自动用计划时间假装原声已说')
 for prev,nxt in zip(rows,rows[1:]):
  if prev['end']>nxt['start']:prev['end']=nxt['start']
 if any(r['start']>=r['end'] for r in rows):raise SystemExit('字幕时间冲突需人工核对')
 save(D/'后期/首版字幕时间轴.json',rows);print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
