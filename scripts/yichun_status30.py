import json,html
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'projects/一寸活路';k=p/'制作/前三集_v8_30秒段落'
read=lambda f:json.loads(f.read_text())
write=lambda f,d:f.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
old=read(p/'制作状态.json')
if old.get('active_version')!='前三集_v8_30秒段落':write(k/'历史逐镜制作状态.json',old)
plan=read(k/'30秒分段方案.json');approved=read(k/'参考采用.json');bind=read(k/'段落引用.json')
segments=[]
for s in plan['segments']:
    logs=sorted((k/'视频'/s['id']).glob('take_*_480p.json'))
    latest=read(logs[-1]) if logs else {}
    qcfile=k/'视频'/s['id']/'验收.json';qc=read(qcfile) if qcfile.exists() else {}
    if not latest.get('video_sha256') or qc.get('video_sha256')!=latest.get('video_sha256'):
        qc={}
    missing=[x['path'] for x in bind[s['id']] if x['path'] not in approved or approved[x['path']].get('status')!='accepted_reference' or not (p/x['path']).exists()]
    v=logs[-1].with_suffix('.mp4') if logs else None
    history=[]
    for log in logs:
        record=read(log);media=log.with_suffix('.mp4');qpath=log.with_suffix('.验收.json')
        check=read(qpath) if qpath.exists() else {}
        if check.get('video_sha256')!=record.get('video_sha256'):check={}
        history.append({'take':record.get('take'),'generation_status':record.get('status'),'visual_status':check.get('status','pending'),'video':str(media.relative_to(p)) if media.exists() else None,'qa':str(qpath.relative_to(p)) if check else None})
    segments.append({'id':s['id'],'seconds_planned':30,'seconds_actual':latest.get('duration'),'generation_status':latest.get('status','not_submitted'),'visual_status':qc.get('status','pending'),'blocking_issues':qc.get('blocking_issues',[]),'history':history,'references_ready':not missing,'missing_references':missing,'video':str(v.relative_to(p)) if v and v.exists() else None})
status={'active_version':'前三集_v8_30秒段落','stage':'30秒段落生成与验收','style':'Seedream立体国漫定妆_v8','video_model':'Seedance 2.5 reference-to-video','initial_resolution':'480p','source_manifest_sha256':plan['source_manifest_sha256'],'episodes':old['episodes'],'segments':segments,'delivery_ready':all(s['visual_status']=='accepted' for s in segments),'rating_scope':'剧本、分镜及直接改变剧情的规划须独立评级；资产ID、技术引用和忠实修正不单独评级','historical_resource_status':'制作/前三集_v8_30秒段落/历史逐镜制作状态.json'}
if not any(s['generation_status'] in ('uploading','submitted') for s in segments) and any(s['visual_status']=='rejected' for s in segments):
    status['stage']='候选未通过，制作待修正'
status['accepted_segments']=sum(s['visual_status']=='accepted' for s in segments)
status['generated_candidates']=sum(bool(h['video']) for s in segments for h in s['history'])
write(p/'制作状态.json',status)
rows=[]
labels={'not_submitted':'未提交','uploading':'参考上传中','submitted':'服务端生成中','generated_pending_visual_and_dialogue_check':'已生成候选','failed_or_uncertain':'请求失败或结果未确认','pending':'待验收','rejected':'退回修正','accepted':'验收通过'}
esc=lambda x:html.escape(str(x))
for s in segments:
    vid=f'<video controls preload="metadata" src="{html.escape(s["video"])}" style="width:100%;max-width:700px"></video>' if s['video'] else ''
    issues=''.join(f'<li>{esc(x.get("time",""))}秒：{esc(x.get("finding",x))}</li>' if isinstance(x,dict) else f'<li>{esc(x)}</li>' for x in s['blocking_issues'])
    history=[]
    for h in s['history']:
        links=(f'<a href="{esc(h["video"])}">播放样片</a>' if h['video'] else '无视频文件')
        if h['qa']:links+=f' · <a href="{esc(h["qa"])}">验收记录</a>'
        history.append(f'<li>第{esc(h["take"])}次请求 · {esc(labels.get(h["generation_status"],h["generation_status"]))} · {esc(labels.get(h["visual_status"],h["visual_status"]))} · {links}</li>')
    details='<details><summary>各次请求与历史样片</summary><ul>'+''.join(history)+'</ul></details>' if history else ''
    rows.append(f'<section><h2>{s["id"]} · 30秒</h2><p>{labels.get(s["generation_status"],esc(s["generation_status"]))} · {labels.get(s["visual_status"],esc(s["visual_status"]))} · 参考：{"就绪" if s["references_ready"] else "等待前段合格接点或首帧修正"}</p>{vid}'+(f'<h3>未通过原因</h3><ul>{issues}</ul>' if issues else '')+details+'</section>')
(p/'制作入口.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>一寸活路 · 30秒段落制作</title><style>body{font:17px/1.8 system-ui;background:#101a20;color:#eee;margin:40px auto;max-width:1000px;padding:24px}a{color:#e0bd83}section{border-top:1px solid #456;margin:24px 0}small{color:#bbc}</style><h1>一寸活路 · 前三集</h1><p>Seedream立体国漫定妆_v8 · Seedance 2.5 · 6段×30秒 · 每集60秒预算</p><p>剧本及原57镜均有真实S评级；30秒重排的四项独立复评均S。源57镜作为动作索引，每30秒只提交一个完整视频请求。战斗及家中长镜按段内摄影计划执行。</p><p><b>生成完成不等于验收通过。以下状态来自实际文件，尚未通过的片段均为候选。</b></p><p><a href="制作/前三集_v8_30秒段落/30秒分段方案.md">30秒分段方案</a> · <a href="制作/前三集_v8_30秒段落/分段外评.json">分段真实外评</a> · <a href="评审/当前评级.json">原稿评级</a> · <a href="制作状态.json">当前状态JSON</a></p>'''+''.join(rows)+'''<section><h2>原稿与历史资源</h2><p><a href="分镜/EP001_中文.html">第一集分镜</a> · <a href="分镜/EP002_中文.html">第二集分镜</a> · <a href="分镜/EP003_中文.html">第三集分镜</a></p><p><a href="制作/前三集_v8_v2_文本定稿/总览.html">原逐镜候选与人物道具参考</a>保留历史检查结果；当前按6个段落及实际采用表制作。</p></section></html>''')
print(json.dumps(segments,ensure_ascii=False))
