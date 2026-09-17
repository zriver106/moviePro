#!/usr/bin/env python3
"""横屏30+30+30+8首版合片：真实视频、原声、单层中文字幕；不生成/修复画面。"""
import json,subprocess
from pathlib import Path
from yichun_landscape98 import P,D,probe,save,sha
FF='/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'
PARTS=[('VIDEO_00_30',30),('EXTEND_30_60',30),('EXTEND_60_90',30),('EXTEND_90_98',8)]
def main():
 inputs=[];filters=[]
 for i,(name,seconds) in enumerate(PARTS):
  f=D/'视频'/f'{name}.mp4'
  if not f.exists():raise SystemExit('等待真实素材：'+str(f))
  info=probe(f);vs=next(x for x in info['streams'] if x['codec_type']=='video')
  if abs(vs['width']/vs['height']-16/9)>.02:raise SystemExit('源片画幅错误，暂停交付：'+name)
  if abs(float(info['format']['duration'])-seconds)>.2:raise SystemExit('需核实延长返回的是新增段还是包含原片，禁止盲拼：'+name)
  if not any(x['codec_type']=='audio' for x in info['streams']):raise SystemExit('原声缺失：'+name)
  inputs+=['-i',str(f)]
  filters.append(f'[{i}:v]trim=duration={seconds},setpts=PTS-STARTPTS,scale=1280:720,setsar=1,fps=24[v{i}]')
  filters.append(f'[{i}:a]atrim=duration={seconds},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{i}]')
 filters.append(''.join(f'[v{i}][a{i}]' for i in range(4))+'concat=n=4:v=1:a=1[v][a]')
 post=D/'后期';post.mkdir(exist_ok=True);clean=post/'98秒首版_原声无后期字幕.mp4'
 subprocess.run([FF,'-v','error','-y',*inputs,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','18','-preset','slow','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(clean)],check=True)
 # Subtitle text remains the package's original dialogue; times follow checked native speech.
 cues_path=post/'首版字幕时间轴.json'
 if not cues_path.exists():raise SystemExit('无字幕原声合片已导出，等待原声字幕时间轴核对：'+str(clean))
 cues=json.loads(cues_path.read_text())
 def ts(t):
  cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
 ass=post/'中文字幕.ass'
 header='''[Script Info]
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
 rows=[]
 for c in cues:
  assert 0<=c['start']<c['end']<=98
  rows.append(f"Dialogue: 0,{ts(c['start'])},{ts(c['end'])},Default,,0,0,0,,{c['text']}")
 ass.write_text(header+'\n'.join(rows)+'\n')
 out=D/'成片/一寸活路_第一集_横屏98秒_首版.mp4';out.parent.mkdir(exist_ok=True)
 subprocess.run([FF,'-v','error','-y','-i',str(clean),'-vf',f'ass={ass}','-c:v','libx264','-crf','18','-preset','slow','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(out)],check=True)
 info=probe(out)
 if abs(float(info['format']['duration'])-98)>.1:raise SystemExit('导出时长不符98秒')
 save(D/'交付记录.json',{'state':'first_version_waiting_user_review','output':str(out),'sha256':sha(out),'seconds':98,'aspect':'16:9','bgm_added':False,'subtitle_layers_added':1,'source_parts':[{'job':n,'seconds':t,'sha256':sha(D/'视频'/f'{n}.mp4')} for n,t in PARTS],'repairs_performed':False,'probe':info})
 print(out)
if __name__=='__main__':main()
