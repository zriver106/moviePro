#!/usr/bin/env python3
"""从冻结57镜与真实图片采用记录派生浏览页、分镜板和交付审计。"""
import csv
import html
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import yichun_resources as r

P,J=r.P,r.J
FONT='/System/Library/Fonts/STHeiti Medium.ttc'

def wrapped(draw,text,xy,font,width,fill):
    x,y=xy;line=''
    for ch in text:
        if ch=='\n' or draw.textlength(line+ch,font=font)>width:
            draw.text((x,y),line,font=font,fill=fill);y+=font.size+7;line='' if ch=='\n' else ch
        else:line+=ch
    if line:draw.text((x,y),line,font=font,fill=fill)
    return y+font.size+7


def main():
    r.require_spec('出图任务.json')
    binding=r.read(J/'逐镜绑定.json')['shots'];specs=r.read(J/'逐镜资源规格.json')['shots']
    decisions=r.read(J/'图片采用记录.json');shots_review=r.read(J/'分镜图片采用记录.json') if (J/'分镜图片采用记录.json').exists() else {}
    tasks={x['id']:x for x in r.read(J/'出图任务.json')['shots']}
    composites=r.read(J/'文字合成记录.json') if (J/'文字合成记录.json').exists() else {}
    visual=r.read(J/'视觉检查.json') if (J/'视觉检查.json').exists() else {'shots':[]}
    visual_by_id={x['id']:x for x in visual['shots']}
    dependencies=sorted(set(x['path'] for s in binding for x in s['characters']+s['props']+[s['location']]))
    issues=[]
    for rel in dependencies:
        try:r.resolved_refs([rel],True)
        except (ValueError,OSError) as e:issues.append(str(e))
    frames={}
    for s in binding:
        a=shots_review.get(s['id'])
        if not a or a.get('status')!='accepted_storyboard':issues.append(s['id']+':分镜图片待验');continue
        p=P/a['selected_path']
        if not p.exists() or r.sha(p)!=a['sha256']:issues.append(s['id']+':分镜图指纹不符');continue
        original=P/composites[s['id']]['source'] if s['id'] in composites else p
        try:
            meta=r.read(original.with_suffix('.json'))
            source_spec=meta.get('source_spec','出图任务.json')
            if source_spec!='出图任务.json':
                r.require_spec(source_spec)
                if meta['spec_sha256']!=r.sha(J/source_spec):
                    raise ValueError('纠错文字已改变，原图片不能继续采用')
            expected={str(x.relative_to(P)):r.sha(x) for x in r.resolved_refs(tasks[s['id']]['refs'],True)}
            if meta['refs_sha256']!=expected:
                issues.append(s['id']+':参考图采用版本已更新，需重验派生帧');continue
        except (OSError,ValueError,KeyError) as exc:
            issues.append(s['id']+':生成来源记录不可核验:'+str(exc));continue
        frames[s['id']]=p
    board_dir=J/'故事板';board_dir.mkdir(exist_ok=True)
    titlefont=ImageFont.truetype(FONT,34);font=ImageFont.truetype(FONT,22);small=ImageFont.truetype(FONT,20)
    pages=[]
    for ep in ['EP001','EP002','EP003']:
        batch=[s for s in specs if s['id'].startswith(ep)]
        for start in range(0,len(batch),6):
            page=Image.new('RGB',(1960,2300),'#eeede6');draw=ImageDraw.Draw(page)
            draw.text((35,24),f'一寸活路  {ep}  /  {start//6+1:02d}   Seedream v8',font=titlefont,fill='#172a2e')
            for i,s in enumerate(batch[start:start+6]):
                x=30+(i%2)*970;y=100+(i//2)*720
                if s['id'] in frames:
                    im=Image.open(frames[s['id']]).convert('RGB');im.thumbnail((940,529));page.paste(im,(x+(940-im.width)//2,y))
                else:draw.rectangle((x,y,x+940,y+529),fill='#bec5c3');draw.text((x+30,y+200),'待验收图片',font=titlefont,fill='#3c4e50')
                draw.text((x,y+539),f"{s['id']}  ·  {s['seconds']:g}秒",font=font,fill='#172a2e')
                wrapped(draw,s['action_cn']['beat'],(x,y+574),font,935,'#273638')
                if s['on_screen_text']:
                    texts=' / '.join(t['text'].replace('\n',' · ') for t in s['on_screen_text'])
                    wrapped(draw,'画内文字：'+texts,(x,y+652),small,935,'#6a4c27')
            draw.text((35,2270),'当前57镜文本外评S；静态制作分镜。动作时长、配音与视频另行验证。',font=small,fill='#455b60')
            name=f'{ep}_P{start//6+1:02d}.jpg';page.save(board_dir/name,quality=94);pages.append(name)
    rows=[]
    for s in binding:
        for kind,entries in [('人物',s['characters']),('场景',[s['location']]),('道具',s['props'])]:
            for a in entries:
                d=decisions.get(a['path'],{});rows.append([s['id'],kind,a['name'],a.get('state',''),a['path'],d.get('selected_path','待验'),d.get('sha256','待验')])
    with (J/'逐镜资源调用.tsv').open('w') as f:
        writer=csv.writer(f,delimiter='\t',lineterminator='\n');writer.writerow(['镜号','类别','资源','镜末状态','逻辑引用','实际采用','SHA256']);writer.writerows(rows)
    css='body{margin:0;background:#111e23;color:#eee9dc;font:16px/1.7 system-ui}main{max-width:1280px;margin:auto;padding:36px}h1{font-size:42px}a{color:#debd83}nav{display:flex;gap:20px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{background:#1b3037;padding:18px;border-radius:10px}img{width:100%;height:auto}small{color:#b7c4c5}.asset{height:360px;object-fit:contain;background:#e6e5dc}h2{margin-top:55px}.pill{color:#d9b579} @media(max-width:800px){.grid{grid-template-columns:1fr}}'
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>一寸活路｜新版资源与57镜分镜</title><style>'+css+'</style><main><p class="pill">SEEDREAM · 立体国漫定妆 v8</p><h1>一寸活路 · 前三集</h1><p>22 / 17 / 18镜 · 每集60秒剪辑预算 · 剧本、文字分镜及资源规格独立外评S</p>',f'<p>已验资源引用 {len(dependencies)-sum(1 for x in dependencies if x not in decisions)} / {len(dependencies)}；已验分镜 {len(frames)} / 57。</p><nav><a href="#assets">资源</a><a href="#EP001">第一集</a><a href="#EP002">第二集</a><a href="#EP003">第三集</a><a href="交付审计.json">审计</a><a href="资源外评.json">独立外评</a><a href="逐镜资源调用.tsv">调用表</a></nav>']
    h.append('<h2 id="assets">新版采用资源</h2><div class="grid">')
    for rel in dependencies:
        a=decisions.get(rel)
        if not a:continue
        target=Path(a['selected_path']).relative_to(J.relative_to(P));label=Path(rel).parent.name if Path(rel).parent.name!='复用' else Path(rel).stem
        h.append(f'<article><h3>{html.escape(label)}</h3><a href="{html.escape(str(target))}"><img class="asset" loading="lazy" src="{html.escape(str(target))}"></a><small>{html.escape(a.get("scope",""))}</small></article>')
    h.append('</div>')
    for ep in ['EP001','EP002','EP003']:
        h.append(f'<h2 id="{ep}">{ep}</h2><p><a href="../../分镜/{ep}_中文.html">已评级中文分镜</a> · <a href="../../剧本/{ep}.md">剧本</a></p><div class="grid">')
        for s in [x for x in specs if x['id'].startswith(ep)]:
            h.append(f'<article><h3>{s["id"]} · {s["seconds"]:g}秒</h3>')
            if s['id'] in frames:
                target=frames[s['id']].relative_to(J);h.append(f'<a href="{target}"><img loading="lazy" src="{target}"></a>')
            else:
                state=visual_by_id.get(s['id'],{})
                h.append('<p>图片尚未验收：'+html.escape(state.get('reason','待制作'))+'</p>')
                if state.get('candidate_path'):
                    candidate=(P/state['candidate_path']).relative_to(J)
                    h.append(f'<details><summary>查看未采用候选（不可交付）</summary><img loading="lazy" src="{candidate}"></details>')
            h.append(f'<p>{html.escape(s["action_cn"]["beat"])}</p><small>起始：{html.escape(s["action_cn"]["start"])}<br>结束：{html.escape(s["action_cn"]["end"])}</small></article>')
        h.append('</div>')
    h.append('<h2>整页故事板</h2>'+''.join(f'<p><a href="故事板/{n}">{n}</a></p>' for n in pages))
    h.append('<p><a href="../前三集_v8_v1/总览.html">旧84镜历史资料（已退役）</a></p></main></html>')
    (J/'总览.html').write_text(''.join(h))
    r.write(J/'交付审计.json',{'source_manifest_sha256':r.read(J/'资源外评.json')['source_manifest_sha256'],'text_gate':'passed','resource_file_sync':'complete','image_delivery_ready':not issues,'expected_shots':57,'accepted_frames':len(frames),'unique_dependency_refs':len(dependencies),'storyboard_pages':len(pages),'issues':issues,'status':'complete' if not issues else 'not_ready','video_duration_verified':False})
    print(json.dumps({'frames':len(frames),'dependencies':len(dependencies),'issues':issues},ensure_ascii=False))

if __name__=='__main__':main()
