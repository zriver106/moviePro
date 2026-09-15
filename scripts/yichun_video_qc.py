#!/usr/bin/env python3
"""Extract actual video frames and expected dialogue for human QA; never auto-pass content."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

def inspect_video(video, plan):
    video=Path(video).resolve()
    output=video.parent/(video.stem+'_qc')
    output.mkdir(exist_ok=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)]))
    duration=float(probe['format']['duration'])
    segment=next(s for s in json.loads(Path(plan).read_text())['segments'] if s['id']==video.parent.name)
    frames=[]
    for n in range(31):
        timestamp=min(float(n),max(0,duration-0.08))
        target=output/f'{n:02d}.jpg'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timestamp),'-i',str(video),'-frames:v','1','-q:v','2',str(target)],check=True)
        frames.append((timestamp,target))
    # Split sheets to retain enough visual detail for identity/action inspection.
    sheets=[]
    for start in (0,16):
        subset=frames[start:start+16]
        sheet=Image.new('RGB',(1280,4*202),'#151515');draw=ImageDraw.Draw(sheet)
        for i,(t,path) in enumerate(subset):
            im=Image.open(path).convert('RGB');im.thumbnail((320,180))
            x=(i%4)*320;y=(i//4)*202
            sheet.paste(im,(x,y));draw.text((x+5,y+182),f'{t:.2f}s',fill='white')
        target=output/f'contact_{start:02d}.jpg';sheet.save(target,quality=92);sheets.append(str(target))
    result={'video':str(video),'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'duration':duration,
            'audio_streams':sum(s['codec_type']=='audio' for s in probe['streams']),
            'technical_duration_pass':29.8<=duration<=30.2,
            'content_status':'pending_human_visual_and_dialogue_review',
            'contact_sheets':sheets,'expected_dialogue':[line for b in segment['timeline'] for line in b['lines']],
            'expected_camera':segment['camera_plan'],'probe':probe}
    (output/'inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return {k:result[k] for k in ('video','duration','audio_streams','contact_sheets','content_status')}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('video');ap.add_argument('--plan',default='projects/一寸活路/制作/前三集_v8_30秒段落/30秒分段方案.json');args=ap.parse_args()
    print(json.dumps(inspect_video(args.video,args.plan),ensure_ascii=False))
