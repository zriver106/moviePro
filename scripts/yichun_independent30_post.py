#!/usr/bin/env python3
"""ASR and first-version Chinese subtitle exports for the two new fictional clips."""
import argparse,difflib,re,subprocess
import provider
from yichun_independent30 import D
from yichun_landscape98 import P,read,save,sha,probe
FF='/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'
CUES={'TEXT_30_60':(5,9),'TEXT_60_90':(9,11)}
HEADER='''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Unicode MS,36,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,45,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
def asr(name):
 f=D/'视频'/f'{name}.mp4';post=D/'后期';post.mkdir(exist_ok=True)
 log=post/f'{name}_听写.json'
 if log.exists() and read(log).get('result'):print('Existing ASR',name);return
 audio=post/f'{name}_原声.wav'
 subprocess.run([FF,'-v','error','-y','-i',str(f),'-vn','-ac','1','-ar','48000',str(audio)],check=True)
 result,error=provider.transcribe_scribe(str(audio));save(log,{'source_sha256':sha(f),'result':result,'error':error});print(name,error,(result or {}).get('text',''))
def captions(name):
 raw=read(D/'后期'/f'{name}_听写.json');assert raw['source_sha256']==sha(D/'视频'/f'{name}.mp4')
 result=raw['result'];heard=[];times=[]
 for w in result['words']:
  if w.get('type')!='word':continue
  chars=''.join(c for c in w['text'] if c.isalnum())
  for i,c in enumerate(chars):heard.append(c);times.append((w['start']+(w['end']-w['start'])*i/len(chars),w['start']+(w['end']-w['start'])*(i+1)/len(chars)))
 first,last=CUES[name];target='';chunks=[]
 for cue in read(P/'后期/对白时间轴草稿.json')['cues'][first:last]:
  for text in re.findall(r'[^，。！？]+[，。！？]?',cue['text']):
   chars=''.join(c for c in text if c.isalnum());chunks.append((text,len(target),len(chars)));target+=chars
 mapping={}
 for a,b,n in difflib.SequenceMatcher(None,target,''.join(heard),autojunk=False).get_matching_blocks():
  for j in range(n):mapping[a+j]=b+j
 rows=[];missing=[]
 for text,a,n in chunks:
  ids=[mapping[i] for i in range(a,a+n) if i in mapping]
  if len(ids)/n<.6:missing.append(text);continue
  rows.append({'start':times[min(ids)][0],'end':min(30,times[max(ids)][1]),'text':text})
 save(D/'后期'/f'{name}_字幕对齐记录.json',{'heard':result['text'],'missing':missing,'coverage':len(mapping)/len(target)})
 if missing:raise SystemExit('需要人工对齐：'+str(missing))
 save(D/'后期'/f'{name}_字幕.json',rows);print(name,rows)
def ts(t):
 c=round(t*100);return f'{c//360000}:{c//6000%60:02d}:{c//100%60:02d}.{c%100:02d}'
def export(name):
 rows=read(D/'后期'/f'{name}_字幕.json');ass=D/'后期'/f'{name}.ass'
 ass.write_text(HEADER+'\n'.join(f"Dialogue: 0,{ts(r['start'])},{ts(r['end'])},Default,,0,0,0,,{r['text']}" for r in rows if not r.get('native_subtitle_present'))+'\n')
 src=D/'视频'/f'{name}.mp4';info=probe(src);v=next(s for s in info['streams'] if s['codec_type']=='video')
 if abs(v['width']/v['height']-16/9)>.02 or abs(float(info['format']['duration'])-30)>.2:raise SystemExit('实际视频画幅/时长不符')
 out=D/'成片'/f'{name}_横屏30秒_中文字幕.mp4';out.parent.mkdir(exist_ok=True)
 subprocess.run([FF,'-v','error','-y','-i',str(src),'-vf',f'scale=1280:720,setsar=1,fps=24,ass={ass}','-t','30','-c:v','libx264','-crf','18','-preset','slow','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)],check=True)
 save(out.with_suffix('.json'),{'output':str(out),'source_sha256':sha(src),'sha256':sha(out),'probe':probe(out),'first_version':True,'picture_repairs':False,'bgm_added':False});print(out)
def combine(total=90):
 names=list(CUES)[:total//30-1]
 paths=[P/'横屏重制_30秒延长98秒_v01/成片/一寸活路_第一集_横屏前30秒_首版.mp4']+[D/'成片'/f'{n}_横屏30秒_中文字幕.mp4' for n in names]
 inputs=[];filters=[]
 for i,p in enumerate(paths):
  if not p.exists():raise SystemExit('缺少已导出字幕段：'+str(p))
  inputs+=['-i',str(p)];filters += [f'[{i}:v]trim=duration=30,setpts=PTS-STARTPTS,fps=24,setsar=1[v{i}]',f'[{i}:a]atrim=duration=30,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{i}]']
 filters.append(''.join(f'[v{i}][a{i}]' for i in range(len(paths)))+f'concat=n={len(paths)}:v=1:a=1[v][a]')
 out=D/'成片'/f'一寸活路_第一集_横屏前{total}秒_首版.mp4'
 subprocess.run([FF,'-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','18','-preset','slow','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)],check=True)
 info=probe(out);assert abs(float(info['format']['duration'])-total)<.1
 save(D/'交付记录.json',{'output':str(out),'sha256':sha(out),'actual_seconds':total,'episode_target_seconds':98,'remaining_seconds':98-total,'sources':[str(x) for x in paths],'first_version':True,'picture_repairs':False,'bgm_added':False,'probe':info});print(out)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['asr','captions','export','combine']);ap.add_argument('name',nargs='?');ap.add_argument('--through',type=int,choices=[60,90],default=90);a=ap.parse_args();combine(a.through) if a.action=='combine' else globals()[a.action](a.name)
