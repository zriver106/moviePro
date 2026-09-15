#!/usr/bin/env python3
"""一寸活路：每次请求一个完整30秒段落，保留正文/分段外评及实际图片门禁。"""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
import provider
import rating_gate
from negwords import NEG_RE

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'projects/一寸活路'
K=P/'制作/前三集_v8_30秒段落'
UPLOAD_LOCK=threading.Lock()

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def require_generation_authorization(segment,take,*,editing=False):
    policy_path=K/'视频生成授权.json'
    if not policy_path.exists():return
    policy=read(policy_path)
    if editing and policy.get('allow_existing_video_editing'):
        return
    if not policy.get('repeat_generation_requires_explicit_user_approval'):return
    prior=[p for p in (K/'视频'/segment).glob('take_*.json') if re.fullmatch(r'take_\d+_(480p|720p|1080p)\.json',p.name)]
    if segment not in policy.get('authorized_first_generation',[]) or take!=policy.get('authorized_take') or prior:
        raise ValueError('用户要求重复生成先获同意；本次仅授权缺段首次请求，禁止付费重试')

def require_plan():
    rating_gate.require('一寸活路',what='30秒视频制作')
    plan=read(K/'30秒分段方案.json');approval=read(K/'分段外评.json')
    if approval.get('thread_id')!='01a08ea0-8c4d-74e0-ae4b-95fa647cfb4d' or not approval.get('message_id'):
        raise ValueError('分段真实外评来源缺失')
    if approval.get('blocking_issues')!=[] or not approval.get('dimensions') or any(x not in ('S','S+') for x in approval['dimensions'].values()):
        raise ValueError('30秒分段外评未全S')
    if sha(K/approval['evidence_path'])!=approval['evidence_sha256'] or sha(K/'30秒分段方案.json')!=approval['plan_sha256']:
        raise ValueError('30秒分段或外评证据已变更')
    current=read(P/'评审/当前评级.json')['external_review']['manifest_sha256']
    if plan['source_manifest_sha256']!=current:raise ValueError('分段所据原稿已过期')
    for rel,digest in plan['source_files_sha256'].items():
        if sha(P/rel)!=digest:raise ValueError('源分镜已变更')
    ids=[]
    for s in plan['segments']:
        if s['seconds']!=30:raise ValueError('每段必须30秒')
        pos=0
        for beat in s['timeline']:
            if beat['start']!=pos or beat['end']<=pos:raise ValueError('时间轴断裂')
            pos=beat['end'];ids.append(beat['source_shot'])
            if any(l['at']<beat['start'] or l['end']>beat['end'] for l in beat['lines']):raise ValueError('对白越界')
        if pos!=30:raise ValueError('段内时长不为30秒')
    if len(ids)!=57 or len(set(ids))!=57:raise ValueError('原57镜动作覆盖缺漏或重复')
    return plan

def references(segment_id):
    registry=read(K/'参考采用.json');binding=read(K/'段落引用.json')[segment_id]
    out=[]
    for item in binding:
        a=registry.get(item['path'])
        if not a or a.get('status')!='accepted_reference':raise ValueError('参考尚未采用: '+item['path'])
        f=P/item['path']
        if sha(f)!=a['sha256']:raise ValueError('参考指纹变更: '+item['path'])
        if a.get('video_source') and sha(P/a['video_source'])!=a['video_sha256']:raise ValueError('接点所据前段视频改变')
        out.append(dict(item,sha256=a['sha256']))
    if not out or out[0].get('kind')!='opening':raise ValueError('缺经过检查的开场图')
    if len(out)>provider.capabilities('2.5')['max_refs']:raise ValueError('参考超过模型上限')
    return out

def compile_prompt(s,refs):
    lines=['A complete 30-second narrative segment, 16:9, sculpted Chinese 3D animated feature style. Woven cloth, dimensional faces, cohesive sculpted hair, restrained wood and bronze. Natural Mandarin dialogue with lip synchronization, footsteps, water and cloth sounds. Each timeline interval is an action beat. Camera cuts follow the CAMERA PLAN; continuous takes carry successive beats through one moving camera. Begin by matching the opening composition in @Image1. Reference portraits define identity and clothing; the current action defines pose and placement. Technical diagrams define mechanical connections translated into the scene materials. Paper surfaces stay suitable for later Chinese typography.',
           'REFERENCE ROLES:']
    lines += [f'@Image{i+1}: {r["role"]}.' for i,r in enumerate(refs)]
    if s['id']=='EP002_B':
        lines.append('摄影约束：全段恰好三个摄影镜头。第一镜0–3秒收锥，第二镜3–10秒废船闪回，第三镜10–30秒屋内一镜到底。第三镜是同一摄影机持续20秒的真实连续运动，钱袋、换碗、分肉、船纸和说话全部在同一镜内依次发生；摄影机随动作缓慢后拉、侧移、俯仰，人物和桌面之间保持连续空间视差。Three camera shots total. The third shot is one uninterrupted 20-second take inside the home from 10s through 30s; every subsequent action unfolds within that continuous camera move. During 13–18s the sister lifts the old chipped bowl away with her left hand and gives the intact full bowl from her right hand into Lu Zhao bandaged palm. The old chipped bowl is set aside at the edge shelf. Both bowls used for eating from 18s onward have complete intact rims.')
    if s['id']=='EP003_A':
        lines.append('摄影约束：全片恰好三个摄影镜头：0–2秒铜塞局部，2–4秒付钱，4–30秒为同一台摄影机连续拍完的26秒长镜。战斗中的每一个时间段都是这一条长镜里的连续动作。摄影机依次横移、前移、稍降及小幅绕行，保持真实连续的空间视差和运动。Three camera shots total; the third is one uninterrupted 26-second take from 4s through 30s. Within that take, close observations happen through a continuous camera glide.')
    if s['id']=='EP002_A':
        lines.append('道具连续性：0–7秒同一把约20厘米的L形铜轮柄，短金属臂一端有方孔，另一端是垂直的深色握把。陆照从麻铎腰钩摘下它，随后把方孔端套到底在裸方轴上，再握住深色握把下压至止点，水才停，L形铜柄留在轴上。摄影约束：13–20秒守卫横棍、岑鹿递保单、指签责栏及守卫收棍是同一条7秒连续侧移镜头，16秒仍在该同机运动中。The small L-shaped bronze crank preserves its exact silhouette across 0–7s. From 13s to 20s one uninterrupted camera move carries the guard confrontation into the cargo-bond exchange.')
    if s['id']=='EP001_A':
        lines.append('执行要点：10–12.5秒的侧景距陆照约两米，清楚看见双脚抵住固定木榫、两手握原锥、锥尖顶在掌大铜片左半面，铜片材质清楚；推锥失败回弹在12.5秒前完成。12.5–30秒是一条17.5秒连续跟拍长镜，麻铎保持画左，陆照画右，随着退到轮架，摄影机连续前移、缓降、横移，让索圈至卷筒、滑轮、坠石的同一根绳和石下承台同时可见。最后0.5秒，原锥已经横放并停稳在陆照旁边台面，陆照两手紧扣轮下突出的三角木楔，楔保持插入，绳圈仍松，石尚悬在承台上方，叉卡独立固定梁。The final frame is a ready-to-pull wooden-wedge state: original awl resting horizontally on the ledge, both young hands gripping the protruding wooden brake wedge, slack foot loop and suspended stone unchanged.')
    camera=s['camera_plan']['en']
    if s['id']=='EP002_B':
        camera=camera.replace('cooler light and the clear time caption three months earlier','cooler light and clean plain upper-left space for later typography')
    lines += ['CAMERA PLAN: '+camera,'TIMELINE:']
    for b in s['timeline']:
        action=re.sub(r'\bonly\b','just',b['action_en'],flags=re.I)
        if s['id']=='EP002_B':
            action=action.replace('with a post-composited three-months-earlier caption','with clean plain upper-left space')
            action=action.replace('a familiar repaired bow and the post-composited three-thousand-copper price are visible','a familiar repair patch on the forward hull of the small wooden boat is visible, with plain paper space for later typography')
        if s['id']=='EP003_A':
            action=action.replace('Next-day caption.','Clean plain upper-left space for later typography.')
            action=action.replace('Close detail shows','The same continuously moving camera glides nearer to reveal')
            action=action.replace('A side view includes','The same camera continuously eases to a three-quarter side angle that includes')
            action=re.sub(r'\bknife\b','wood-handled short knife',action)
            action=re.sub(r'\bawl\b','slender hemp-handled awl',action)
        if s['id']=='EP002_A':
            action=re.sub(r'\bcrank\b','small L-shaped bronze crank',action)
            if b['start']==16:action='Within the same continuously gliding camera take, '+action
        if s['id']=='EP001_A':
            action=action.replace('A low wide side angle clearly shows','The same continuous camera take lowers smoothly into a low side angle that clearly shows')
        lines.append(f'[{b["start"]:g}–{b["end"]:g}s] '+action)
        if b.get('bridge_action_en'):lines.append(b['bridge_action_en'])
        for l in b['lines']:
            voice='off-screen voice' if l['off_screen'] else 'visible speaker with synchronized lips'
            lines.append(f'[{l["at"]:g}–{l["end"]:g}s] {l["speaker"]}, {voice}, says exactly in Mandarin: “{l["text"]}”')
    states={
        'EP001_A':'Lu Zhao palms remain bare and his shoulder cloth intact. Original short awl at waist or in hands as specified.',
        'EP001_B':'Lu Zhao palms remain bare and shoulder cloth intact. Original short awl moves from ledge to hands to waist in the specified order.',
        'EP002_A':'Lu Zhao starts with bare palms. The RIGHT palm receives medicinal cloth at 28s. The new leather sheath is purchased in the following segment.',
        'EP002_B':'RIGHT palm is bandaged in the present at 0–3s and 10–30s. At 3–10s the flashback has bare palms and the old chest wound. In the present the original awl and its palm-sized sheath stay at the waist.',
        'EP003_A':'RIGHT palm is bandaged throughout. LEFT shoulder cloth begins intact, gets cut during 10–13.5s and retains that small wound afterward. The uninjured RIGHT shoulder performs the final body pin. Awl sheath is palm-sized at waist.',
        'EP003_B':'RIGHT palm remains bandaged. The anatomical LEFT shoulder wound receives a dressing at 9–13s and retains it afterward. The uninjured RIGHT shoulder performs the opening body pin. The original awl is retrieved at 7–9s and then stays sheathed at waist.'}
    lines.append(states[s['id']])
    if s['id']=='EP002_B':
        lines.append('VISIBLE CONTINUITY: During the flashback both young palms and wrists show uncovered natural skin. The elder red wrist strip belongs to the elder. Lu Zhao holds the one original awl and the elder rests his hand upon that awl hand. In the dusk home, the RIGHT palm cloth visibly wraps the palm and wrist. The chipped bowl has a large visible missing-rim notch. Lu He lifts that chipped bowl away before handing over the intact full bowl; show these two separate bowls exchanging places clearly in the existing 13–18s continuous action. The boat notice lies flat on the table as specified, showing a wooden boat hull and its repair patch. Keep all picture lettering areas plain. Each spoken line begins and finishes inside its specified time window, at a natural brisk Mandarin pace. The elder articulates 痕永不消，能一直添 clearly; the final 陆照 word is 挣, pronounced zhèng. Finish that final word by 29s and hold the final action state through 30s.')
    if s['id']=='EP003_A':
        lines.append('动作连续性：陆照左肩衣料在10秒前完整，挨刀后才出现同一处小伤。短刀是葛牙手里的木柄宽刃，原锥是陆照的一支麻绳柄细尖工具，两个器型严格区分。原锥离开腰鞘后，鞘口保持空；20–23秒双手将原锥直刺穿折起网角和木栏后，原锥固定留在木栏内，双手放开它再夺刀。23–27秒左掌压葛牙右肘、右手折右腕，接刀、回送松网、顺刃退出、落右下石沟依次连续发生。最后两人保持相向：葛牙背部贴立柱，陆照用自己的右肩抵葛牙胸前，把他压实在柱上；左掌仍控其右肘，右手抓其左腕折在胸前。双人的手臂控制点保持在胸口以下，右肩抵胸是明确的最终接触点。The final continuous camera view shows Ge Ya back against the post and Lu Zhao facing him, Lu Zhao RIGHT shoulder pressing Ge Ya upper chest into the post, hands maintaining the stated elbow and wrist control. All contact positions remain visible through the final frame.')
    lines.append('The original awl stays a single small hemp-handled tool. All characters preserve their reference identities across camera movements. End at the last specified action state at 30 seconds.')
    prompt='\n'.join(lines)
    if NEG_RE.search(prompt):raise ValueError('提示词含否定词: '+str(NEG_RE.findall(prompt)))
    return prompt

def build(segment_id,take=1,resolution='480p'):
    plan=require_plan();s=next(x for x in plan['segments'] if x['id']==segment_id);refs=references(segment_id)
    if resolution not in provider.capabilities('2.5')['resolutions']:raise ValueError('分辨率不支持')
    task={'segment':segment_id,'plan_sha256':sha(K/'30秒分段方案.json'),'model':'2.5','mode':'ref','seconds':30,'resolution':resolution,'aspect':'16:9','audio':True,'seed':961000+['EP001_A','EP001_B','EP002_A','EP002_B','EP003_A','EP003_B'].index(segment_id)*100+take,'take':take,'references':refs,'prompt':compile_prompt(s,refs)}
    task['request_sha256']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return task

def uploaded(ref):
    # One shared cache: serialized uploads prevent duplicate copies of common references.
    with UPLOAD_LOCK, (K/'上传缓存.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        cachefile=K/'上传缓存.json';cache=read(cachefile) if cachefile.exists() else {}
        digest=ref['sha256']
        if digest not in cache:
            cache[digest]=provider.upload(str(P/ref['path']));write(cachefile,cache)
        return cache[digest]

def run(segment_id,take=1,resolution='480p'):
    folder=K/'视频'/segment_id;folder.mkdir(parents=True,exist_ok=True)
    with (folder/f'take_{take:02d}_{resolution}.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('同一take正在另一进程执行，禁止重复扣费')
        return _run(segment_id,take,resolution)

def _run(segment_id,take=1,resolution='480p'):
    task=build(segment_id,take,resolution);folder=K/'视频'/segment_id;folder.mkdir(parents=True,exist_ok=True)
    out=folder/f'take_{take:02d}_{resolution}.mp4';log=out.with_suffix('.json')
    if log.exists():
        old=read(log)
        if old['request_sha256']!=task['request_sha256']:raise ValueError('同版本请求已改变，须新take')
        if out.exists() and old.get('video_sha256')==sha(out):return {'segment':segment_id,'status':'existing','path':str(out.relative_to(P))}
        raise ValueError('已有未完成/失败请求，请检查记录后决定新take，禁止自动重复扣费')
    require_generation_authorization(segment_id,take)
    write(log,dict(task,status='uploading',started_at=time.time()))
    try:
        urls=[uploaded(r) for r in task['references']]
        if build(segment_id,take,resolution)['request_sha256']!=task['request_sha256']:raise ValueError('上传期间输入变更')
        write(log,dict(task,status='submitted',started_at=time.time()))
        url,err=provider.video(task['prompt'],model='2.5',mode='ref',seconds=30,resolution=resolution,aspect='16:9',audio=True,seed=task['seed'],image_urls=urls)
        if err or not url:raise RuntimeError(err or '空视频响应')
        provider.fetch(url,str(out))
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)]))
        duration=float(probe['format']['duration'])
        if not 29.8<=duration<=30.2:raise ValueError(f'实际时长异常: {duration}')
        if not any(x['codec_type']=='audio' for x in probe['streams']):raise ValueError('缺原生音轨')
        status='generated_pending_visual_and_dialogue_check'
        write(log,dict(task,status=status,video_sha256=sha(out),duration=duration,probe=probe,completed_at=time.time()))
        return {'segment':segment_id,'status':status,'path':str(out.relative_to(P)),'duration':duration}
    except Exception as exc:
        write(log,dict(task,status='failed_or_uncertain',error=str(exc),completed_at=time.time()))
        raise

def main():
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['preflight','run','asr']);ap.add_argument('--segment',action='append',required=True);ap.add_argument('--take',type=int,default=1);ap.add_argument('--resolution',default='480p');ap.add_argument('--workers',type=int,default=2);ap.add_argument('--decoder',choices=['whisper','scribe'],default='whisper');a=ap.parse_args()
    if not 1<=a.workers<=6 or a.take<1:ap.error('并发1–6，take为正数')
    if a.command=='preflight':
        for ident in a.segment:
            # 预检只读；新版绑定不能覆写已提交take的历史请求档案。
            t=build(ident,a.take,a.resolution);print(json.dumps({'segment':ident,'refs':len(t['references']),'prompt_chars':len(t['prompt']),'seconds':t['seconds']},ensure_ascii=False))
    elif a.command=='asr':
        for ident in a.segment:
            f=K/'视频'/ident/f'take_{a.take:02d}_{a.resolution}.mp4';out=f.with_suffix('.scribe.json' if a.decoder=='scribe' else '.asr.json')
            digest=sha(f)
            if out.exists():
                if read(out).get('source_sha256')!=digest:raise ValueError('听写所据视频已变更或缺来源指纹')
                print(ident,'ASR existing');continue
            if a.decoder=='scribe':
                wav=f.with_suffix('.wav')
                subprocess.run(['ffmpeg','-v','error','-y','-i',str(f),'-vn','-ac','1','-ar','48000',str(wav)],check=True)
                d,e=provider.transcribe_scribe(str(wav))
            else:d,e=provider.transcribe(str(f),language='zh',chunk_level='segment')
            if e:raise RuntimeError(e)
            if sha(f)!=digest:raise ValueError('听写期间源视频变更')
            write(out,{'source_sha256':digest,'decoder':a.decoder,'text_hints':False,'result':d});print(ident,'ASR saved')
    else:
        failed=False
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
            jobs={pool.submit(run,i,a.take,a.resolution):i for i in a.segment}
            for f in concurrent.futures.as_completed(jobs):
                try:print(json.dumps(f.result(),ensure_ascii=False),flush=True)
                except Exception as e:
                    failed=True
                    print(json.dumps({'segment':jobs[f],'error':str(e)},ensure_ascii=False),flush=True)
        if failed:raise SystemExit(1)
if __name__=='__main__':main()
