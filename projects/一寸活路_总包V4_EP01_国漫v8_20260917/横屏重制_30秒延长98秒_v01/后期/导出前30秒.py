import sys,re,json,difflib,subprocess
sys.path.insert(0,'scripts');from yichun_landscape98 import P,D,read,save,sha,probe
asr=read(D/'声音核对/VIDEO_00_30.json')['result'];heard=[];times=[]
for w in asr['words']:
 if w.get('type')!='word':continue
 chars=''.join(c for c in w['text'] if c.isalnum())
 for i,c in enumerate(chars):heard.append(c);times.append((w['start']+(w['end']-w['start'])*i/len(chars),w['start']+(w['end']-w['start'])*(i+1)/len(chars)))
cues=read(P/'后期/对白时间轴草稿.json')['cues'][:5];target='';chunks=[]
for cue in cues:
 for text in re.findall(r'[^，。！？]+[，。！？]?',cue['text']):
  chars=''.join(c for c in text if c.isalnum());chunks.append((text,len(target),len(chars)));target+=chars
mapping={}
for a,b,n in difflib.SequenceMatcher(None,target,''.join(heard),autojunk=False).get_matching_blocks():
 for j in range(n):mapping[a+j]=b+j
rows=[]
for text,a,n in chunks:
 ids=[mapping[i] for i in range(a,a+n) if i in mapping];assert len(ids)/n>=.6,(text,ids)
 rows.append({'start':times[min(ids)][0],'end':min(30,times[max(ids)][1]),'text':text})
post=D/'后期';post.mkdir(exist_ok=True);save(post/'前30秒字幕时间轴.json',rows)
def ts(t):
 c=round(t*100);return f'{c//360000}:{c//6000%60:02d}:{c//100%60:02d}.{c%100:02d}'
head='''[Script Info]
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
ass=post/'前30秒中文字幕.ass';ass.write_text(head+'\n'.join(f"Dialogue: 0,{ts(r['start'])},{ts(r['end'])},Default,,0,0,0,,{r['text']}" for r in rows)+'\n')
out=D/'成片/一寸活路_第一集_横屏前30秒_首版.mp4';out.parent.mkdir(exist_ok=True)
subprocess.run(['/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg','-v','error','-y','-i',str(D/'视频/VIDEO_00_30.mp4'),'-vf',f'ass={ass}','-t','30','-c:v','libx264','-preset','slow','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(out)],check=True)
info=probe(out);assert abs(float(info['format']['duration'])-30)<.1
save(D/'交付记录.json',{'state':'partial_first_version_extension_blocked','target_seconds':98,'actual_seconds':30,'output':str(out),'sha256':sha(out),'aspect':'16:9','resolution':[1280,720],'subtitle_layers_added':1,'bgm_added':False,'video_repairs':False,'audio':'original generated soundtrack','source_sha256':sha(D/'视频/VIDEO_00_30.mp4'),'blocker':'EXTEND_30_60_COMPAT returned 422 content_policy_violation / partner_validation_failed: images or videos may contain likenesses of real people or private information','extension_output_received':False,'further_generation_paused':True,'probe':info})
print(out)
