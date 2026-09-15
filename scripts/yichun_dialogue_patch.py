#!/usr/bin/env python3
"""一次性四秒原视频编辑修复；保存原片、请求与结果，失败绝不切换生成。"""
import fcntl
import subprocess
import time
import provider
from yichun_video30 import P, K, sha, read, write, require_plan, require_generation_authorization


def run():
    require_plan()
    require_generation_authorization('EP003_B', 1, editing=True)
    source=K/'视频/EP003_B/take_01_480p.mp4'
    folder=K/'后期/对白修复/EP003_B';folder.mkdir(parents=True,exist_ok=True)
    log=folder/'edit_01.json';output=folder/'edit_01.mp4';clip=folder/'source_9_to_13.mp4'
    with (folder/'edit_01.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if log.exists():raise ValueError('本次编辑已有记录，禁止重复提交或自动换模式')
        task={'source':str(source.relative_to(P)),'source_sha256':sha(source),'start':9,'end':13,
              'task':'editing','model':'2.5','resolution':'480p','fallback_to_regeneration':False,
              'prompt':'Edit @Video1, this existing four-second stylized 3D Chinese animation shot. Preserve the shot, characters, wardrobe, camera, dressing action and room ambience. Restore the missing Mandarin dialogue: the woman in pale green speaks clearly from 0.4 to 2.9 seconds, exactly: “能刺，也得躲刀。” Her voice is calm, firm and warm. Keep the injured man silent. Maintain synchronized speech and natural cloth sounds. The frame stays clean for later subtitle compositing. Audio consists of dialogue and diegetic sounds only.'}
        write(log,dict(task,status='preparing',started_at=time.time()))
        try:
            subprocess.run(['ffmpeg','-v','error','-n','-ss','9','-i',str(source),'-t','4','-c:v','libx264','-crf','16','-c:a','aac',str(clip)],check=True)
            url=provider.upload(str(clip))
            write(log,dict(task,status='submitted',input_sha256=sha(clip),started_at=time.time()))
            result,error=provider.video(task['prompt'],model='2.5',mode='ref',task='editing',video_urls=[url],seconds=4,resolution='480p',audio=True)
            if error or not result:raise RuntimeError(error or '空编辑响应')
            provider.fetch(result,str(output))
            write(log,dict(task,status='returned_pending_check',output_sha256=sha(output),completed_at=time.time()))
            print(output)
        except Exception as exc:
            write(log,dict(task,status='failed_no_fallback',error=str(exc),completed_at=time.time()))
            raise

if __name__=='__main__':run()
