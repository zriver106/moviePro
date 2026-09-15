#!/usr/bin/env python3
"""六段齐备后连续合剪180秒：无提示卡、无行政水印、不添加BGM。"""
import json
import subprocess
from yichun_video30 import P, K, require_plan, read, write, sha
from yichun_post30 import FF, POST, write_subtitles


def assemble():
    require_plan()
    folder=POST/'完整合剪';folder.mkdir(parents=True,exist_ok=True)
    selected=[('EP001_A',2),('EP001_B',1),('EP002_A',2),('EP002_B',7),('EP003_A',2),('EP003_B',1)]
    timeline=[];lines=[];command=[FF,'-v','error','-y'];filters=[];streams=[]
    for i,(segment,take) in enumerate(selected):
        source=folder/'段落'/segment/f'take_{take:02}'/'中文字幕_无配乐.mp4'
        if not source.exists():raise ValueError(f'{segment}视频尚缺失，禁止以提示卡代替')
        info=read(source.with_suffix('.json'))
        if sha(source)!=info['output_sha256'] or info.get('bgm_added') is not False or info.get('visible_review_watermark') is not False:
            raise ValueError('输入指纹、无配乐或无水印状态不符')
        if sha(P/info['source'])!=info['source_sha256']:raise ValueError('原始视频被更改')
        subtitles=POST/'字幕'/segment/f'take_{take:02}'/'字幕校对.json'
        if sha(subtitles)!=info['subtitle_metadata_sha256']:raise ValueError('字幕版本已变更')
        for line in read(subtitles)['lines']:
            lines.append(dict(line,start=line['start']+30*i,end=line['end']+30*i))
        timeline.append({'segment':segment,'take':take,'start':30*i,'end':30*(i+1),
                         'source':str(source.relative_to(P)),'sha256':sha(source),'original_sha256':info['source_sha256']})
        command+=['-i',str(source)]
        filters += [f'[{i}:v]trim=duration=30,setpts=PTS-STARTPTS,fps=24,scale=854:480,setsar=1[v{i}]',
                    f'[{i}:a]atrim=duration=30,asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration=30[a{i}]']
        streams.append(f'[v{i}][a{i}]')
    filters.append(''.join(streams)+'concat=n=6:v=1:a=1[v][a]')
    output=folder/'一寸活路_前三集完整合剪_无BGM.mp4'
    command+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','18',
              '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    subprocess.run(command,check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
    if abs(float(probe['format']['duration'])-180)>.1:raise ValueError('完整合剪必须180秒')
    if [s['codec_type'] for s in probe['streams']]!=['video','audio']:raise ValueError('应只有一条视频和一条音轨，避免叠加字幕轨')
    # 字幕附件分目录保存，成片只烧录一套，播放器不需再外挂同名字幕。
    write_subtitles(folder/'字幕附件',lines)
    write(folder/'完整合剪清单.json',{'output':str(output.relative_to(P)),'sha256':sha(output),'duration':180,
          'content_complete':False,'segment_coverage_complete':True,'missing_segments':[],
          'unresolved_dialogue':[{'segment':'EP003_B','start':159.4,'end':162.1,'text':'能刺，也得躲刀。','status':'原音轨缺句；4秒原片editing被服务端422拒绝，未重试或回退生成'}],
          'title_or_missing_cards':False,'visible_review_watermark':False,
          'bgm_added':False,'hard_chinese_subtitle_sets':1,'quality_approval':'独立保留各原片验收记录，合剪不改变质量评级',
          'timeline':timeline,'probe':probe})
    print(output)


if __name__=='__main__':assemble()
