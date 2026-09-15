#!/usr/bin/env python3
"""全片检查后的两项定点编辑；复用现有较好镜头，每项目单次请求。"""
import argparse, fcntl, subprocess, time
import provider
from yichun_video30 import K,P,sha,read,write,require_plan,require_generation_authorization
ROOT=K/'延长试验/EP001/统一修复_v1'
S=K/'视频/EP001_A/take_01_480p.mp4'
SPECS={
 'flood':dict(start=191/24,end=254/24,prompt='Edit the existing shot in @Video1. The trapped compartment is filled with opaque dark floodwater up to the three people\'s upper chests. Their heads, shoulders and raised hands remain visible above the rippling water surface. The woman in pale green holds the lamp at the high inspection opening. The grey-haired worker and blue-clad youth stand together inside the same closed timber compartment. Preserve the original three faces, costumes, camera movement, closed wooden walls, inspection opening and lantern position. The water surface intersects their upper chests throughout this shot, reflecting the lamp. Preserve the original dialogue and shot timing.'),
 'copper':dict(start=254/24,end=350/24,prompt='Edit the existing action in @Video1. @Image1 shows the copper latch plate and wooden door used later in this same scene. Match that exact copper plate, latch and door here. The young man plants both bare heels against two fixed wooden floor stops. He grips the same thin steel awl with both hands and pushes its point straight horizontally into the LEFT side of this intact copper plate, at chest height on the closed door. The plate dents slightly and remains intact; he withdraws the awl straight back and looks at the shallow dent. His elbows extend in line with the awl during the push. Preserve his face, teal costume, camera motion, lighting, water level and shot duration. The original inspection opening stays above the copper plate.')
}
SPECS['rope']=dict(start=0,end=5.5,seconds=5.5,source='EP001_B',prompt="Edit the existing action in @Video1. Preserve the same people and winch. As the young man pulls the existing wedge out with both hands, the wooden drum turns, the suspended stone descends a short distance and lands on its timber catch frame. The rope visibly uncoils from this drum and tightens an already-laid low loop around the brown-clad antagonist's ankles. Show the taut rope connecting drum to ankles as his feet are pulled together and he falls backward. The young man stays beside the winch. Keep the original camera sequence, identities, costumes and room geometry. Finish with the antagonist on the same floor, ready for the existing next shot of his wrists being bound.")
SPECS['rescue']=dict(start=401/24,end=30,seconds=30-401/24,source='EP001_B',prompt="Edit the existing rescue shot in @Video1. Preserve the identities of the teal-clad young man, pale-green woman, grey-haired grey-bearded elderly worker, blue-clad young man, and bound brown-clad antagonist. The teal-clad young man stands on the raised wooden repair ledge beside the door throughout the rescue. Water pours from inside the newly opened door down into the lower floor channel. The woman emerges through that opened doorway and crawls onto the raised ledge first. The grey-bearded worker follows from the same doorway; the teal-clad young man and woman each hold one of his upper arms and help him kneel onto the ledge. The blue-clad youth emerges last through the same doorway. The teal-clad man grips his forearm and lifts his knee onto the ledge while the woman anchors the rescuer's waist belt. Finish with all four rescued characters sitting on that dry raised ledge as in the original ending. The bound brown-clad antagonist remains beside his low post in the foreground. Preserve the original duration, animation style and single continuous camera movement. Preserve the spoken Mandarin call exactly: 阿砾！")
def run(name):
 require_plan();require_generation_authorization('EP001_A',1,editing=True)
 spec=SPECS[name];source=K/f"视频/{spec.get('source','EP001_A')}/take_01_480p.mp4";seconds=spec.get('seconds',4);root=ROOT/name;root.mkdir(parents=True,exist_ok=True);log=root/'request.json'
 with (root/'request.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if log.exists():raise ValueError('已有请求记录，禁止重复提交')
  task=dict(spec,source=str(source.relative_to(P)),source_sha256=sha(source),task='editing',model='2.5',scope='faithful_execution_repair',plan_sha256=sha(K/'30秒分段方案.json'),fallback_to_regeneration=False)
  write(log,dict(task,status='preparing',started_at=time.time()))
  try:
   clip=root/'input.mp4';dur=spec['end']-spec['start'];ratio=seconds/dur;frames=round(seconds*24)
   subprocess.run(['ffmpeg','-v','error','-n','-ss',str(spec['start']),'-t',str(dur),'-i',str(source),'-vf',f'setpts=(PTS-STARTPTS)*{ratio},fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame={frames}','-af',f'atempo={dur/seconds},apad,atrim=duration={seconds}','-c:v','libx264','-crf','16','-c:a','aac',str(clip)],check=True)
   images=[]
   if name=='copper':
    ref=root/'copper_reference.png';b=K/'视频/EP001_B/take_01_480p.mp4'
    subprocess.run(['ffmpeg','-v','error','-n','-ss','16','-i',str(b),'-frames:v','1',str(ref)],check=True)
    task['reference']=dict(source=str(b.relative_to(P)),source_sha256=sha(b),time=16,frame_sha256=sha(ref));images=[provider.upload(str(ref))]
   url=provider.upload(str(clip));write(log,dict(task,status='submitted',input_sha256=sha(clip),started_at=time.time()))
   result,error=provider.video(spec['prompt'],model='2.5',mode='ref',task='editing',video_urls=[url],image_urls=images or None,seconds=seconds,resolution='480p',audio=True)
   if error or not result:raise RuntimeError(error or '空结果')
   out=root/'edited.mp4';provider.fetch(result,str(out));write(log,dict(task,status='returned_pending_check',output_sha256=sha(out),completed_at=time.time()));print(out)
  except Exception as exc:
   write(log,dict(task,status='failed_no_fallback',error=str(exc),completed_at=time.time()));raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('name',choices=SPECS);run(p.parse_args().name)
