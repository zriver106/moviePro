#!/usr/bin/env python3
"""30秒段落后期：定稿中文字幕、对白优先混音、候选与交付门禁。"""
import argparse
import difflib
import json
import re
import subprocess
from pathlib import Path
from yichun_video30 import P, K, read, write, sha, require_plan

POST=K/'后期'
FF='/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'


def chars(text):
    return [x for x in text if re.match(r'[\u4e00-\u9fffA-Za-z0-9]',x)]


def timestamp(seconds,ass=False):
    scale=100 if ass else 1000
    total=round(seconds*scale);hours,total=divmod(total,3600*scale);minutes,total=divmod(total,60*scale);sec,part=divmod(total,scale)
    return f'{hours}:{minutes:02}:{sec:02}.{part:02}' if ass else f'{hours:02}:{minutes:02}:{sec:02},{part:03}'


def wrap(text):
    if len(text)<=18:return text
    middle=len(text)//2
    punctuation=[i+1 for i,c in enumerate(text) if c in '，。！？；' and 4<=i<len(text)-4]
    split=min(punctuation,key=lambda i:abs(i-middle)) if punctuation else middle
    return text[:split]+'\n'+text[split:]


def write_subtitles(folder,lines,preview=False,cards=()):
    folder.mkdir(parents=True,exist_ok=True)
    srt='\n\n'.join(f'{i+1}\n{timestamp(l["start"])} --> {timestamp(l["end"])}\n{wrap(l["text"])}' for i,l in enumerate(lines))+'\n'
    (folder/'中文字幕.srt').write_text(srt)
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Heiti SC,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,1,0,1,3,1,2,110,110,66,1
Style: Notice,Heiti SC,28,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,7,38,38,28,1
Style: Time,Heiti SC,42,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,0,0,0,0,100,100,0,0,1,2,1,7,80,80,95,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    for l in lines:
        value=wrap(l['text']).replace('\n',r'\N').replace('{','').replace('}','')
        ass+=f'Dialogue: 0,{timestamp(l["start"],True)},{timestamp(l["end"],True)},Dialogue,,0,0,0,,{value}\n'
    # 用户要求所有导出画面都不带内部验收/试听水印，状态只保存在JSON。
    for card in cards:
        if card['placement']=='左上角时间字幕':
            ass+=f'Dialogue: 0,{timestamp(card["start"],True)},{timestamp(card["end"],True)},Time,,0,0,0,,{card["text"]}\n'
    (folder/'中文字幕.ass').write_text(ass)


def prepare(segment,take=None):
    plan=require_plan();s=next(x for x in plan['segments'] if x['id']==segment)
    raw=[l for b in s['timeline'] for l in b['lines']]
    lines=[{'start':l['at'],'end':l['end'],'text':l['text'],'speaker':l['speaker'],'timing_source':'plan'} for l in raw]
    cards=[dict(c,start=b['start'],end=b['end']) for b in s['timeline'] for c in b.get('on_screen_text',[])]
    metadata={'segment':segment,'plan_sha256':sha(K/'30秒分段方案.json'),'timing_approved':False,'on_screen_text':cards,'onscreen_text_approved':not cards,'status':'planned' if take is None else 'asr_aligned_draft'}
    folder=POST/'字幕'/segment/('计划' if take is None else f'take_{take:02}')
    if take is not None:
        source=K/'视频'/segment/f'take_{take:02d}_480p.mp4';asrfile=source.with_suffix('.scribe.json');asr=read(asrfile)
        if asr.get('source_sha256')!=sha(source):raise ValueError('字幕听写源视频指纹不符')
        words=[]
        for w in asr['result'].get('words',[]):
            if w.get('type')=='word':
                for c in chars(w['text']):words.append({'char':c,'start':w['start'],'end':w['end']})
        canonical=''.join(''.join(chars(l['text'])) for l in lines);recognized=''.join(w['char'] for w in words)
        matched={}
        for block in difflib.SequenceMatcher(None,canonical,recognized,autojunk=False).get_matching_blocks():
            for i in range(block.size):matched[block.a+i]=block.b+i
        offset=0
        for l in lines:
            length=len(chars(l['text']));indices=[matched[i] for i in range(offset,offset+length) if i in matched]
            l['alignment_coverage']=round(len(indices)/max(1,length),3)
            if indices:
                l['start']=max(0,words[min(indices)]['start']-.06);l['end']=min(30,words[max(indices)]['end']+.14);l['timing_source']='asr_matching_characters'
            offset+=length
        for first,second in zip(lines,lines[1:]):first['end']=min(first['end'],second['start']-.04)
        metadata.update(source=str(source.relative_to(P)),video_sha256=sha(source),asr_sha256=sha(asrfile))
    metadata['lines']=lines
    # 已校对字幕不被重复prepare覆盖。
    if (folder/'字幕校对.json').exists() and read(folder/'字幕校对.json').get('timing_approved'):
        raise ValueError('已有确认字幕，需新版本而非覆盖')
    write(folder/'字幕校对.json',metadata);write_subtitles(folder,lines,cards=cards)
    return folder


def release_gate(source,meta,preview):
    if sha(source)!=meta.get('video_sha256'):raise ValueError('字幕所据视频已改变')
    if sha(K/'30秒分段方案.json')!=meta.get('plan_sha256'):raise ValueError('字幕所据定稿已改变')
    if not preview:
        qa=read(source.with_suffix('.验收.json'))
        if qa.get('status')!='accepted' or qa.get('video_sha256')!=sha(source):raise ValueError('画面未通过，不能导出交付成片')
        if not meta.get('timing_approved'):raise ValueError('字幕时点未校对通过')
        if meta.get('on_screen_text') and not meta.get('onscreen_text_approved'):raise ValueError('画内中文尚未合成验收')


def render(segment,take,preview=False,output_root=None,cleanup=None,add_bgm=False):
    require_plan()
    folder=POST/'字幕'/segment/f'take_{take:02}';meta=read(folder/'字幕校对.json');source=P/meta['source']
    release_gate(source,meta,preview)
    config=read(POST/'配乐方案.json');cues=config['segments'][segment]['cues'] if add_bgm else [];lines=meta['lines']
    if any(l['start']<0 or l['end']>30 or l['end']<=l['start'] for l in lines):raise ValueError('字幕时间异常')
    output_dir=(output_root or POST/('试听样片' if preview else '交付'))/segment/f'take_{take:02}';output_dir.mkdir(parents=True,exist_ok=True)
    write_subtitles(output_dir,lines,preview,meta.get('on_screen_text',[]))
    output=output_dir/('中文字幕_低音量配乐.mp4' if add_bgm else '中文字幕_无配乐.mp4')
    command=[FF,'-v','error','-y','-i',str(source)];filters=['[0:a]atrim=0:30,asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=9,aresample=48000[dialogue]'];inputs=['[dialogue]']
    for i,cue in enumerate(cues,1):
        music=P/cue['source']
        if sha(music)!=cue['source_sha256']:raise ValueError('音乐源文件已变更')
        command+=['-i',str(music)]
        start=cue['start'];length=cue['end']-start
        if start<0 or cue['end']>30 or length<=0:raise ValueError('配乐区间错误')
        # 先统一音乐响度，再在对白区额外压低6dB，避免“音量百分比”忽略源响度。
        chain=f'[{i}:a]atrim=start={cue["source_in"]}:duration={length},asetpts=PTS-STARTPTS,loudnorm=I=-30:TP=-2:LRA=7,aresample=48000,volume=0.631'
        for l in lines:
            a=max(0,l['start']-.15-start);b=min(length,l['end']+.25-start)
            if b>a:chain+=f",volume=0.501:enable='between(t,{a:.3f},{b:.3f})'"
        chain+=f',afade=t=in:d={min(1.2,length/3)},afade=t=out:st={max(0,length-1.2)}:d={min(1.2,length)},adelay={round(start*1000)}:all=1,apad,atrim=0:30[m{i}]'
        filters.append(chain);inputs.append(f'[m{i}]')
    # 预留AAC编码后的真峰值余量，交付复测目标仍为不高于-1.5dBTP。
    filters.append(''.join(inputs)+f'amix=inputs={len(inputs)}:normalize=0:duration=first,alimiter=limit=0.794328:level=false,atrim=0:30[aout]')
    # 固定的本地字幕文件名，从输出目录启动ffmpeg，避免路径转义破坏滤镜。
    vf=[]
    if cleanup:
        if cleanup['source_sha256']!=sha(source):raise ValueError('字幕清理所据原片变更')
        for box in cleanup['regions']:
            x,y,w,h=box['rect'];start,end=box['start'],box['end']
            if min(x,y)<1 or min(w,h)<1 or not 0<=start<end<=30:raise ValueError('字幕清理区域异常')
            vf.append(f"delogo=x={x}:y={y}:w={w}:h={h}:enable='between(t,{start},{end})'")
    vf.append('ass=中文字幕.ass')
    command+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[aout]','-vf',','.join(vf),'-t','30','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    subprocess.run(command,cwd=output_dir,check=True)
    measured=subprocess.run([FF,'-hide_banner','-i',str(output),'-af','loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,check=True).stderr
    stats=json.JSONDecoder().raw_decode(measured[measured.rfind('{'):])[0]
    write(output.with_suffix('.json'),{'segment':segment,'source':str(source.relative_to(P)),'source_sha256':sha(source),'output_sha256':sha(output),'preview':preview,'delivery_ready':False,'visible_review_watermark':False,'caption_cleanup':cleanup,'hard_chinese_subtitles':True,'subtitle_metadata_sha256':sha(folder/'字幕校对.json'),'music_plan_sha256':sha(POST/'配乐方案.json'),'bgm_added':bool(cues),'music_target_lufs_between_dialogue':-34 if cues else None,'music_target_lufs_under_dialogue':-40 if cues else None,'mix_loudness':stats,'status':'rendered_pending_listening_and_visual_check'})
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','render']);parser.add_argument('--segment',required=True);parser.add_argument('--take',type=int);parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    if args.command=='render' and args.take is None:parser.error('render需要take')
    print(prepare(args.segment,args.take) if args.command=='prepare' else render(args.segment,args.take,args.preview))
