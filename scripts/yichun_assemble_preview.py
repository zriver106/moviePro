#!/usr/bin/env python3
"""现有前三集片段合剪；缺段用短提示卡标记，保留原字幕与预览身份。"""
import json
import subprocess
from yichun_post30 import POST, FF, write_subtitles, timestamp
from yichun_video30 import P, read, write, sha, require_plan


def assemble():
    require_plan()
    outdir=POST/'合剪预览';outdir.mkdir(parents=True,exist_ok=True)
    sequence=[('card',2,'一寸活路 · 第一集'),('clip',30,('EP001_A',2)),
              ('card',3,'第一集后半段尚未生成'),('card',2,'一寸活路 · 第二集'),
              ('clip',30,('EP002_A',2)),('clip',30,('EP002_B',7)),
              ('card',2,'一寸活路 · 第三集'),('clip',30,('EP003_A',2)),
              ('card',3,'第三集后半段尚未生成')]
    inputs=[];timeline=[];subtitles=[];position=0
    for i,(kind,duration,value) in enumerate(sequence):
        if kind=='card':
            folder=outdir/f'card_{i:02}';folder.mkdir(exist_ok=True)
            write_subtitles(folder,[])
            ass=folder/'中文字幕.ass'
            ass.write_text(ass.read_text()+f'Dialogue: 0,0:00:00.00,{timestamp(duration,True)},Dialogue,,0,0,0,,{{\\an5\\fs58}}{value}\\N{{\\fs30}}现有素材合剪预览 · 非完整定版\n')
            source=folder/'card.mp4'
            subprocess.run([FF,'-v','error','-y','-f','lavfi','-i','color=c=0x10151c:s=854x480:r=24',
                '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-vf','ass=中文字幕.ass','-t',str(duration),
                '-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac',str(source)],cwd=folder,check=True)
            subtitles.append({'start':position,'end':position+duration,'text':value})
            item={'type':'status_card','text':value}
        else:
            segment,take=value
            folder=POST/'试听样片'/segment/f'take_{take:02}'
            source=folder/'中文字幕_低音量配乐.mp4'
            meta=read(source.with_suffix('.json'))
            if sha(source)!=meta['output_sha256'] or not meta['preview']:
                raise ValueError('合剪输入必须是指纹一致的预览文件')
            subtitle_meta=POST/'字幕'/segment/f'take_{take:02}'/'字幕校对.json'
            if sha(subtitle_meta)!=meta['subtitle_metadata_sha256']:
                raise ValueError('字幕在导出后发生变化')
            for line in read(subtitle_meta)['lines']:
                subtitles.append(dict(line,start=line['start']+position,end=line['end']+position))
            item={'type':'clip','segment':segment,'take':take}
        inputs.append(source)
        timeline.append(dict(item,start=position,end=position+duration,source=str(source.relative_to(P)),sha256=sha(source)))
        position+=duration
    command=[FF,'-v','error','-y']
    for source in inputs:command+=['-i',str(source)]
    filters=[];streams=[]
    for i,(_,duration,_) in enumerate(sequence):
        filters += [f'[{i}:v]trim=duration={duration},setpts=PTS-STARTPTS,fps=24,scale=854:480,setsar=1[v{i}]',
                    f'[{i}:a]atrim=duration={duration},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={duration}[a{i}]']
        streams += [f'[v{i}][a{i}]']
    filters.append(''.join(streams)+f'concat=n={len(inputs)}:v=1:a=1[v][a]')
    output=outdir/'一寸活路_前三集现有素材合剪_中文字幕.mp4'
    command+=['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','18',
              '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    subprocess.run(command,check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
    if abs(float(probe['format']['duration'])-position)>.1:raise ValueError('合剪时长不符')
    write_subtitles(outdir,subtitles)
    write(outdir/'合剪清单.json',{'output':str(output.relative_to(P)),'sha256':sha(output),'duration':position,
        'footage_seconds':120,'missing_segments':['EP001_B','EP003_B'],'preview':True,'delivery_ready':False,
        'timeline':timeline,'probe':probe})
    print(output)


if __name__=='__main__':assemble()
