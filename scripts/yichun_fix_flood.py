#!/usr/bin/env python3
"""第8秒进水房间局部原视频编辑；一次请求，失败不重生。"""
import fcntl
import json
import subprocess
import time
import provider
from yichun_video30 import P,K,sha,write,read,require_plan,require_generation_authorization

ROOT=K/'延长试验/EP001/进水房间修复_v4'
SOURCE=K/'延长试验/EP001/进水房间修复_v3/edited_shot.mp4'
BASE=K/'延长试验/EP001/牌面修复_v1/一寸活路_第一集60秒_牌面字放大.mp4'
START=0
END=4

def run():
    require_plan();require_generation_authorization('EP001_A',2,editing=True)
    if read(SOURCE.parent/'edit_01.json')['output_sha256']!=sha(SOURCE):raise ValueError('原片指纹变化')
    if read(BASE.parent/'修复记录.json')['output_sha256']!=sha(BASE):raise ValueError('牌面修复版指纹变化')
    ROOT.mkdir(parents=True,exist_ok=True);log=ROOT/'edit_01.json';clip=ROOT/'original_shot.mp4';output=ROOT/'edited_shot.mp4'
    with (ROOT/'edit_01.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if log.exists():raise ValueError('此次编辑已有记录，禁止自动重复或切换生成')
        task={'source':str(SOURCE.relative_to(P)),'source_sha256':sha(SOURCE),'base':str(BASE.relative_to(P)),'base_sha256':sha(BASE),'start':START,'end':END,'frames':96,'task':'editing','model':'2.5','resolution':'480p','plan_sha256':sha(K/'30秒分段方案.json'),'fallback_to_regeneration':False,
        'prompt':'Edit @Video1, this single existing interior shot. Make the trapped compartment deeply flooded. Raise opaque water to the SHOULDERS of all three people: show their heads, necks, shoulders and raised forearms above the water; their chests and entire lower bodies are submerged. The surface fills the lower half of the image, clearly touching shoulder-height clothing, with reflected lantern light. The blue-clad young man keeps pounding the CLOSED wooden door from inside. The elderly worker is also inside, in front of continuous closed wood planks, gripping the fixed jamb. The woman in pale green lifts the lantern and places it on a small narrow ledge attached directly to the inspection-hatch frame at head height, above the flood. Her hands support the lantern at that height. The original isolated wooden block is completely submerged. Preserve the three characters, their faces, costumes, visual style and the single camera shot. Her Mandarin line is exactly “三个人！开门！” followed by her turning toward the older worker. All lettering is handled afterward by local typography compositing.' }
        write(log,dict(task,status='preparing',started_at=time.time()))
        try:
            subprocess.run(['ffmpeg','-v','error','-n','-i',str(SOURCE),'-vf','trim=start_frame=4:end_frame=67,setpts=(PTS-STARTPTS)*96/63,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame=96','-af','atrim=start=0.1666666667:end=2.7916666667,asetpts=PTS-STARTPTS,atempo=0.65625,apad,atrim=duration=4','-c:a','aac','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',str(clip)],check=True)
            url=provider.upload(str(clip));write(log,dict(task,status='submitted',input_sha256=sha(clip),started_at=time.time()))
            result,error=provider.video(task['prompt'],model='2.5',mode='ref',task='editing',video_urls=[url],seconds=4,resolution='480p',audio=True)
            if error or not result:raise RuntimeError(error or '空编辑结果')
            provider.fetch(result,str(output))
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(output)]))
            write(log,dict(task,status='returned_pending_check',output_sha256=sha(output),probe=probe,completed_at=time.time()))
            print(output)
        except Exception as exc:
            write(log,dict(task,status='failed_no_fallback',error=str(exc),completed_at=time.time()))
            raise

if __name__=='__main__':run()
