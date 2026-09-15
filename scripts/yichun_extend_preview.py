#!/usr/bin/env python3
"""将实测新增30秒接到原30秒，输出独立对照文件；不替换现有成片。"""
import json
import subprocess
from yichun_video30 import P,K,sha,read,write,require_plan
from yichun_post30 import FF,POST,write_subtitles


def main():
    require_plan();root=K/'延长试验/EP001';extension=root/'extension_01.mp4';record=read(root/'extension_01.json')
    if record['status']!='returned_pending_continuation_check' or sha(extension)!=record['output_sha256']:
        raise ValueError('缺少可追溯的延长结果')
    if sha(P/record['source'])!=record['source_sha256']:raise ValueError('原片已变更')
    if abs(float(record['probe']['format']['duration'])-30)>.1:raise ValueError('本次实测接续必须为新增30秒')
    original=POST/'完整合剪/段落/EP001_A/take_02/中文字幕_无配乐.mp4';info=read(original.with_suffix('.json'))
    if info['source_sha256']!=record['source_sha256'] or info['output_sha256']!=sha(original) or info['bgm_added']:
        raise ValueError('前30秒来源或无配乐状态不符')
    asr=read(extension.with_suffix('.scribe.json'))
    if asr['source_sha256']!=sha(extension):raise ValueError('听写来源变化')
    # 此次实际Scribe完整词边界经人工核对，字幕仍取定稿原文。
    segment=next(s for s in require_plan()['segments'] if s['id']=='EP001_B')
    canonical=[l for b in segment['timeline'] for l in b['lines']]
    lines=[dict(l,start=a,end=b) for l,(a,b) in zip(canonical,[(10.08,12.42),(23.34,24.52)])]
    write_subtitles(root/'续段字幕',lines)
    output=root/'一寸活路_第一集_30秒延长至60秒_中文字幕.mp4'
    filters='[0:v]trim=duration=30,setpts=PTS-STARTPTS,fps=24,setsar=1[v0];[1:v]trim=duration=30,setpts=PTS-STARTPTS,fps=24,scale=854:480,setsar=1,ass=续段字幕/中文字幕.ass[v1];[0:a]atrim=duration=30,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a0];[1:a]atrim=duration=30,asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-2:LRA=9,aresample=48000,aformat=channel_layouts=stereo[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]'
    subprocess.run([FF,'-v','error','-y','-i',str(original),'-i',str(extension),'-filter_complex',filters,'-map','[v]','-map','[a]','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)],cwd=root,check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
    if abs(float(probe['format']['duration'])-60)>.1:raise ValueError('成片并非60秒')
    first=read(POST/'字幕/EP001_A/take_02/字幕校对.json')['lines']
    write_subtitles(root/'完整字幕附件',first+[dict(l,start=l['start']+30,end=l['end']+30) for l in lines])
    write(root/'输出清单.json',{'output':str(output.relative_to(P)),'sha256':sha(output),'duration':60,'original_source_sha256':record['source_sha256'],'extension_sha256':sha(extension),'added_bgm':False,'subtitle_sets':1,'administrative_cards':False,'quality_status':'rejected_see_验收.json','probe':probe})
    print(output)

if __name__=='__main__':main()
