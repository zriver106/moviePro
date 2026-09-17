#!/usr/bin/env python3
"""Assemble the complete V4 first cut from existing footage; performs no API calls."""
import json, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'projects/一寸活路_总包V4_EP01_国漫v8_20260917'
FF='/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'
PARTS=[
 ('视频/首版素材/FIRSTCUT_A_S01_S04_v01.mp4',27),
 ('视频/首版素材/FIRSTCUT_B_S05_S09_v01.mp4',23),
 ('预演/PREVIS_S10_v01.mp4',3),
 ('视频/已验/EP001_S11.mp4',2),
 ('视频/已验/EP001_S12.mp4',3),
 ('预演/PREVIS_S13_v01.mp4',4),
 ('预演/S14双腕已修_踢叉待修.mp4',10),
 ('视频/首版素材/FIRSTCUT_C_S15_S19_v01.mp4',26),
]
def probe(path):
 return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))
def stamp(t):
 cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
def subtitles():
 cues=json.loads((P/'后期/对白时间轴草稿.json').read_text())['cues']
 head='''[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Unicode MS,36,&H00FFFFFF,&H00FFFFFF,&H00141414,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
 lines=[]
 for cue in cues:
  parts=re.findall(r'[^，。！？]+[，。！？]?',cue['text']);total=sum(map(len,parts));start=cue['start']
  for part in parts:
   end=start+(cue['end']-cue['start'])*len(part)/total
   lines.append(f'Dialogue: 0,{stamp(start)},{stamp(end)},Default,,0,0,0,,{part}')
   start=end
 out=P/'后期/EP001_首版中文字幕.ass';out.write_text(head+'\n'.join(lines)+'\n');return out

def main():
 ass=subtitles()
 manifest={'seconds':98,'bgm':False,'subtitle_layers':1,'parts':[], 'status':'awaiting_source_videos'}
 cursor=0
 for source,duration in PARTS:
  manifest['parts'].append({'source':source,'start':cursor,'end':cursor+duration,'available':(P/source).exists()});cursor+=duration
 assert cursor==98
 manifest_path=P/'后期/首版剪辑清单.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 missing=[x['source'] for x in manifest['parts'] if not x['available']]
 if missing:raise SystemExit('完整首版等待真实视频素材：\n'+'\n'.join(missing))
 temp=P/'后期/首版中间素材';temp.mkdir(exist_ok=True)
 for i,(source,duration) in enumerate(PARTS):
  info=probe(P/source);actual=float(info['format']['duration'])
  if actual+0.08<duration:raise SystemExit(f'素材不足目标时长，禁止定格或循环填充：{source} {actual} < {duration}')
  subprocess.run([FF,'-v','error','-y','-i',str(P/source),'-an','-vf','scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=24','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','18',str(temp/f'{i:02d}.mp4')],check=True)
 concat=temp/'concat.txt';concat.write_text(''.join(f"file '{i:02d}.mp4'\n" for i in range(len(PARTS))))
 clean=temp/'画面拼接.mp4'
 subprocess.run([FF,'-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(clean)],check=True)
 out=P/'成片/一寸活路_第一集_98秒_首版.mp4';out.parent.mkdir(exist_ok=True)
 subprocess.run([FF,'-v','error','-y','-i',str(clean),'-i',str(P/'后期/EP001_对白时间轴草稿.wav'),'-map','0:v:0','-map','1:a:0','-vf',f'ass={ass}','-t','98','-c:v','libx264','-preset','slow','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)],check=True)
 info=probe(out);assert abs(float(info['format']['duration'])-98)<.1
 assert sum(x['codec_type']=='video' for x in info['streams'])==1
 assert sum(x['codec_type']=='audio' for x in info['streams'])==1
 manifest.update(status='first_cut_exported_pending_user_review',output=str(out),probe=info)
 manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(out)
if __name__=='__main__':main()
