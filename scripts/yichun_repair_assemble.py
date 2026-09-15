#!/usr/bin/env python3
"""以逐项验收通过的局部画面及已有素材重剪第一集，保留旧文件。"""
import subprocess,json
import cv2
from yichun_video30 import K,P,read,write,sha,require_plan
from yichun_post30 import FF,POST,write_subtitles
ROOT=K/'延长试验/EP001/统一修复_v1'
BASE=K/'延长试验/EP001/牌面修复_v1/一寸活路_第一集60秒_牌面字放大.mp4'
ALT=K/'视频/EP001_A/take_01_480p.mp4'
B=POST/'完整合剪/段落/EP001_B/take_01/中文字幕_无配乐.mp4'
def frame_count(path):
 c=cv2.VideoCapture(str(path));n=int(c.get(cv2.CAP_PROP_FRAME_COUNT));c.release();return n

def main():
 require_plan();selection=read(ROOT/'剪辑采用.json')
 if sha(BASE)!=read(BASE.parent/'修复记录.json')['output_sha256']:raise ValueError('基底指纹变化')
 info=read(B.with_suffix('.json'))
 if info['output_sha256']!=sha(B) or info['bgm_added']:raise ValueError('救人素材指纹或配乐状态不符')
 replacements=[]
 for item in selection['replacements']:
  path=P/item['path']
  if sha(path)!=item['sha256'] or item['status']!='accepted_for_specific_fix':raise ValueError('局部素材未验收或指纹变更')
  replacements.append((item,path))
 output=ROOT/'一寸活路_第一集60秒_统一修复.mp4'
 if output.exists():raise ValueError('输出已存在，需另存版本')
 inputs=[BASE]+[p for _,p in replacements]+[B]
 command=[FF,'-v','error','-n']
 for p in inputs:command+=['-i',str(p)]
 filters=[];labels=[];pos=0
 for idx,(r,p) in enumerate(replacements,1):
  a,b=r['target_frames'];s,e=r['source_frames']
  if a<pos:raise ValueError('替换范围重叠')
  if a>pos:
   label=f'base{idx}';filters.append(f'[0:v]trim=start_frame={pos}:end_frame={a},setpts=PTS-STARTPTS,setsar=1[{label}]');labels.append(f'[{label}]')
  length=b-a;label=f'edit{idx}'
  filters.append(f'[{idx}:v]trim=start_frame={s}:end_frame={e},setpts=(PTS-STARTPTS)*{length}/{e-s},fps=24,scale=854:480,setsar=1,tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={length}[{label}]');labels.append(f'[{label}]');pos=b
 if pos<720:
  filters.append(f'[0:v]trim=start_frame={pos}:end_frame=720,setpts=PTS-STARTPTS,setsar=1[tail]');labels.append('[tail]')
 filters.append(''.join(labels)+f'concat=n={len(labels)}:v=1:a=0[first]')
 # 新插入的前半画面未烧字幕；只在实际替换段落内补回原声对应的同一套字幕。
 lines=read(POST/'字幕/EP001_A/take_02/字幕校对.json')['lines']
 ranges=[(r['target_frames'][0]/24,r['target_frames'][1]/24) for r,_ in replacements]
 captions=[]
 for l in lines:
  for a,b in ranges:
   s=max(a,l['start']);e=min(b,l['end'])
   if s<e:captions.append(dict(l,start=s,end=e))
 write_subtitles(ROOT/'替换段字幕',captions)
 filters.append('[first]ass=替换段字幕/中文字幕.ass[firstsub]')
 bi=len(inputs)-1
 filters.append(f'[{bi}:v]trim=end_frame=720,setpts=PTS-STARTPTS,setsar=1[last]')
 filters.append('[firstsub][last]concat=n=2:v=1:a=0[v]')
 filters.append('[0:a]asplit=2[originalaudio][roomsource]')
 filters.append('[originalaudio]atrim=end=30,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a0]')
 # 原B素材3.9–5.15秒多出非定稿语音，以现有第一段同室水声覆盖。
 filters.append('[roomsource]atrim=start=15:end=16.25,asetpts=PTS-STARTPTS,volume=0.6,afade=t=in:d=0.04,afade=t=out:st=1.21:d=0.04,adelay=3900|3900[room]')
 filters.append(f'[{bi}:a]atrim=end=30,asetpts=PTS-STARTPTS,volume=0:enable=\'between(t,3.9,5.15)\'[ba]')
 filters.append('[ba][room]amix=inputs=2:duration=first:normalize=0,aresample=48000,aformat=channel_layouts=stereo[a1]')
 filters.append('[a0][a1]concat=n=2:v=0:a=1[a]')
 command+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
 subprocess.run(command,cwd=ROOT,check=True)
 subprocess.run([FF,'-v','error','-i',str(output),'-f','null','-'],check=True)
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
 if abs(float(probe['format']['duration'])-60)>.05 or frame_count(output)!=1440:raise ValueError('输出时长/帧数异常')
 blines=read(POST/'字幕/EP001_B/take_01/字幕校对.json')['lines'];write_subtitles(ROOT/'完整字幕附件',lines+[dict(l,start=l['start']+30,end=l['end']+30) for l in blines])
 write(ROOT/'输出清单.json',dict(output=str(output.relative_to(P)),sha256=sha(output),base_sha256=sha(BASE),existing_rescue_sha256=sha(B),selection=selection,duration=60,frames=1440,bgm_added=False,subtitle_sets=1,administrative_cards=False,method='既有素材重剪及task:editing局部修复；非纯延长版本',status='pending_final_review',probe=probe))
 print(output)
if __name__=='__main__':main()
