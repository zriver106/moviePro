#!/usr/bin/env python3
"""《一寸活路》前三集 v8 的可恢复制作任务；既有其它剧目脚本不变。

prepare 从作者 TSV 投影剧本与分镜，render 通过 provider 出图，report 生成浏览页。
每次请求保留输入哈希和 seed；旧输出存在但输入改变时明确拒绝覆盖。
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

import provider
import script_lock
from negwords import NEG_RE

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'projects/一寸活路'
JOB = P / '制作/前三集_v8_v1'
TEXT_ROOT = JOB / '文字快照' if (JOB / '文字快照').exists() else P
STYLE = ('Sculpted Chinese 3D animated feature aesthetic, coherent sculpted hair locks, '
         'dimensional facial planes, woven cloth, weathered wood and restrained bronze, '
         'soft physically based lighting. ')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def load(path):
    return json.loads(Path(path).read_text())


def rel(path):
    return str(Path(path).relative_to(P))


def parse_design():
    episodes = []
    for line in (JOB / '镜头设计.tsv').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            eid, title = line[1:-1].split(' ', 1)
            episodes.append({'id': eid, 'title': title, 'shots': []})
            continue
        row = [x.strip() for x in line.split('|')]
        if len(row) != 9:
            raise ValueError(f'镜头列数应为9，实际{len(row)}：{line}')
        sec, loc, cast, size, cn, en, dialogue, props, quote = row
        steps = cn.split('→')
        if len(steps) != 3:
            raise ValueError(f'起中末应为三拍：{cn}')
        episode = episodes[-1]
        sid = f"{episode['id']}_SH{len(episode['shots'])+1:02d}"
        people = [c for c in cast.split(',') if c]
        lines = []
        for sentence in dialogue.split('／'):
            if not sentence:
                continue
            speaker, text = sentence.split('：', 1)
            off = speaker.endswith('OS')
            speaker = speaker.removesuffix('OS')
            lines.append({'speaker': speaker, 'text': text, 'off_screen': off})
        durations = [len(re.sub(r'\W', '', x['text'])) / 4 + .4 for x in lines]
        # 台词最低预算按4字/秒+每句停顿；表中不足则公开延长，不截台词。
        seconds = max(float(sec), round(sum(durations) + .7, 1))
        at = .4
        for item, length in zip(lines, durations):
            item['at'] = round(at, 1)
            at += length
        snapshot = en.split(';', 1)[0].strip().rstrip('.') + '.'
        epnum = len(episodes)
        shnum = len(episode['shots']) + 1
        states = {}
        for person in people:
            state = 'dry'
            if person in ('闻溪', '阿砾', '灰胡子工人') and (epnum == 1 or (epnum == 2 and shnum <= 17)):
                state = 'wet'
            if person == '陆照':
                if epnum == 1 and shnum >= 3: state = 'wet_lower_tunic'
                if epnum == 2 and shnum <= 18: state = 'wet_lower_tunic'
                if epnum == 3 and 7 <= shnum <= 18: state = 'left_shoulder_scrape'
                if epnum == 3 and shnum >= 19: state = 'left_shoulder_bandaged'
            states[person] = state
        state_text = []
        names_en = {'陆照':'Lu Zhao', '闻溪':'Wen Xi', '阿砾':'A Li', '灰胡子工人':'the grey-bearded worker'}
        for person, state in states.items():
            who = names_en.get(person, person)
            if state == 'wet': state_text.append(f'{who} has soaked clothing and wet hair.')
            if state == 'wet_lower_tunic': state_text.append(f'{who} has wet boots and a water-darkened lower tunic.')
            if state == 'left_shoulder_scrape': state_text.append('Lu Zhao has a small dark red stain and superficial scrape at his anatomical left shoulder, the right shoulder intact.')
            if state == 'left_shoulder_bandaged': state_text.append('A clean linen dressing covers Lu Zhao\'s anatomical left shoulder beneath the parted collar.')
        frame = {'wide':'Wide shot, 35mm lens.', 'medium':'Medium shot, 50mm lens.',
                 'medium_close':'Medium close shot, 65mm lens.', 'close':'Close shot, 85mm lens.'}[size]
        episode['shots'].append({
            'id': sid, 'seconds': seconds, 'design_seconds': float(sec),
            'source': {'chapter': len(episodes), 'quote': quote},
            'intent': steps[1], 'cast': [{'name': c, 'state': steps[0]} for c in people],
            'location': {'id': loc, 'desc': loc},
            'camera': {'size': size, 'angle': 'level', 'move': 'locked'},
            'camera_cn': {'wide': '全景 / 35mm', 'medium': '中景 / 50mm',
                          'medium_close': '中近景 / 65mm', 'close': '近景 / 85mm'}[size] + ' / 固定机位',
            'action': dict(zip(('start', 'beat', 'end'), steps)),
            'lines': lines, 'dialogue': None,
            'uses': [x for x in props.split(',') if x],
            'character_states': states,
            'continuity_out': steps[-1],
            'transition_cn': '动作承接硬切；保持本场轴线',
            'sound': '闸水、脚步、绳木摩擦；中文对白独立录音' if loc in ('闸舱','北门','梯口') else '港口轻水声与脚步；住屋为灶火、碗筷；中文对白独立录音',
            'render': {'keyframe_prompt': STYLE + frame + ' ' + snapshot + ' ' + ' '.join(state_text), 'action_en': en,
                       'prompt_language': 'en', 'status': 'storyboard_preproduction'},
            'qc': {'headcount': len(people), 'fail_if': ['身份或服装阶段不符', '左右手与伤势侧错误', '道具提前变化']}
        })
    return episodes


def prepare():
    if TEXT_ROOT != P:
        raise ValueError('本版已冻结文字快照；禁止覆盖共享目录中的新版剧本与分镜')
    episodes = parse_design()
    annotations = None
    if (JOB / '制作标注.json').exists():
        annotations = load(JOB / '制作标注.json')
        if annotations['design_sha256'] != digest(JOB / '镜头设计.tsv'):
            raise ValueError('镜头设计已改，制作标注过期；先复核并刷新标注，禁止静默套用旧标注')
    novel = P / '一寸活路_第1—448章_小说阅读版.txt'
    text = novel.read_text()
    chapters = re.split(r'第[一二三四]章[　 ]+[^\n]+\n', text, maxsplit=4)[1:4]
    lock = {'novel': {'path': rel(novel), 'sha256': digest(novel)},
            'design': {'path': rel(JOB / '镜头设计.tsv'), 'sha256': digest(JOB / '镜头设计.tsv')},
            'authorization': '用户指定Seedream立体国漫定妆_v8制作前三集资产与分镜', 'references': []}
    for f in sorted((P / '定稿/Seedream立体国漫定妆_v8').glob('*.jpg')):
        if f.name in ['01_陆照.jpg', '02_闻溪.jpg', '04_阿砾.jpg', '05_陆禾.jpg', '10_岑鹿.jpg']:
            lock['references'].append({'path': rel(f), 'sha256': digest(f)})
    for e, chapter in zip(episodes, chapters):
        e['source_sha256'] = lock['novel']['sha256']
        e['aspect_ratio'] = '16:9'
        e['style'] = STYLE
        e['note'] = 'Seedream立体国漫定妆v8开篇派生；彩色故事板为构图预览，JSON为镜头权威。'
        e['target_seconds'] = round(sum(s['seconds'] for s in e['shots']), 1)
        script = [f"# {e['id']} {e['title']}", '', '画幅16:9。原著对应章逐章改编；画外音为压缩叙述。',
                  '人物：陆照（为姐姐挣饭钱的青年）、陆禾（姐姐）、闻溪（医者）、阿砾（落水青年工人）、岑鹿（救货出资商人）、麻铎（封舱船监）、葛牙（持刀绑人者）、会库守船人。', '']
        coverage = []
        for s in e['shots']:
            if annotations:
                ann = annotations['shots'][s['id']]
                s['on_screen_text'] = ann['on_screen_text']
                s['in_frame'] = ann['in_frame']
                s['render']['keyframe_prompt'] = ann['keyframe_prompt']
            if s['source']['quote'] not in chapter:
                raise ValueError(f"原文锚点不存在：{s['id']} {s['source']['quote']}")
            script += [f"## {s['id']} · {s['location']['id']} · {s['seconds']:g}秒", '',
                       '。'.join(s['action'].values()) + '。']
            for d in s['lines']:
                script += [f"{d['speaker']}{'（画外音）' if d['off_screen'] else ''}：{d['text']}"]
            script += ['']
            coverage.append({'quote': s['source']['quote'], 'shot': s['id'], 'treatment': 'covered'})
        sp = P / f"剧本/{e['id']}.md"
        sp.write_text('\n'.join(script))
        e['script_digest'] = script_lock.digest(sp)
        dump(P / f"分镜/{e['id']}.json", e)
        dump(JOB / f"{e['id']}_原文落实.json", {'source_chapter': int(e['id'][2:]), 'coverage': coverage,
             'compression': '对话与因果见剧本；未逐字复述的内心叙述改为可见反应。EP002老人死亡不另拍遗体，闪回结束表示记忆终止；第三集灶船帮工换铺由制作说明补明。'})
    dump(JOB / '来源锁.json', lock)
    for e in episodes:
        print(e['id'], len(e['shots']), e['target_seconds'], 'seconds', flush=True)


def verify_sources():
    lock = load(JOB / '来源锁.json')
    bad = []
    for item in [lock['novel'], lock['design']] + lock['references']:
        if digest(P / item['path']) != item['sha256']:
            bad.append(item['path'])
    for ep in range(1, 4):
        if TEXT_ROOT == P:
            st, msg = script_lock.state('一寸活路', ep)
            if st != 'locked': bad.append(f'EP{ep:03d} {st}: {msg}')
        else:
            frozen=load(TEXT_ROOT/'剧本/.lock.json')[f'EP{ep:03d}']
            if frozen['digest'] != script_lock.digest(TEXT_ROOT/f'剧本/EP{ep:03d}.md'):
                bad.append(f'EP{ep:03d} 文字快照锁过期')
        sb = load(TEXT_ROOT / f'分镜/EP{ep:03d}.json')
        if sb['script_digest'] != script_lock.digest(TEXT_ROOT / f'剧本/EP{ep:03d}.md'):
            bad.append(f'EP{ep:03d} 分镜剧本指纹过期')
    if bad:
        raise ValueError('来源门禁失败：\n' + '\n'.join(bad))


def make_image(item):
    target = JOB / item['output']
    record = target.with_suffix('.request.json')
    refs = [P / x for x in item.get('refs', [])]
    request = {k: item[k] for k in ('id', 'prompt', 'size', 'seed')}
    request['references'] = [{'path': rel(f), 'sha256': digest(f)} for f in refs]
    request['provider'] = provider.BACKEND
    request['model'] = 'Seedream V5 Lite edit' if refs else 'Seedream V5 Lite text-to-image'
    if target.exists():
        if not record.exists() or load(record) != request:
            raise ValueError(f'拒绝覆盖旧版本/输入改变：{target}')
        print('REUSE', item['id'], flush=True)
        return
    bad = sorted(set(m.group(0) for m in NEG_RE.finditer(item['prompt'])))
    if bad:
        raise ValueError(f"{item['id']} prompt否定词：{bad}")
    target.parent.mkdir(parents=True, exist_ok=True)
    dump(record, request)
    urls = []
    for f in refs:
        mime = 'image/png' if f.suffix.lower() == '.png' else 'image/jpeg'
        urls.append(f'data:{mime};base64,' + base64.b64encode(f.read_bytes()).decode())
    print('START ' + item['id'], flush=True)
    if refs:
        url, err = provider.edit_image(item['prompt'], urls, size=item['size'], seed=item['seed'])
    else:
        url, err = provider.text_to_image(item['prompt'], size=item['size'], seed=item['seed'])
    if err or not url:
        dump(target.with_suffix('.result.json'), {'status': 'failed', 'error': err or 'empty image URL'})
        raise RuntimeError(f"{item['id']}: {err or 'empty URL'}")
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    # 先检验图片，再原子落盘，网络中断的半文件不能被当成完成。
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.verify()
    temp = target.with_suffix('.download.tmp')
    temp.write_bytes(data)
    temp.replace(target)
    dump(target.with_suffix('.result.json'), {'status': 'generated_pending_visual_review',
         'sha256': digest(target), 'dimensions': list(Image.open(target).size), 'bytes': len(data)})
    print('DONE ' + item['id'], flush=True)


def render(kind, jobs, only):
    verify_sources()
    manifest = load(JOB / {'assets':'资产请求.json', 'boards':'故事板请求.json', 'shots':'逐镜请求.json'}[kind])
    items = [x for x in manifest if not only or x['id'] in only.split(',')]
    if not items:
        raise ValueError('没有匹配的生成任务')
    if any('prompt' not in x for x in items):
        raise ValueError('当前页面由单镜排版；先运行 shots，再运行 assemble')
    failures = []
    remaining = list(items)
    while remaining:
        ready = [x for x in remaining if all((P / f).exists() for f in x.get('refs', []))]
        if not ready:
            failures.extend({'id': x['id'], 'error': '上游参考图缺失，未提交请求'} for x in remaining)
            break
        with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {pool.submit(make_image, x): x for x in ready}
            for fut in cf.as_completed(futs):
                try:
                    fut.result()
                except Exception as exc:
                    failures.append({'id': futs[fut]['id'], 'error': str(exc)})
                    print('FAILED', futs[fut]['id'], str(exc)[:400], flush=True)
        remaining = [x for x in remaining if x not in ready]
    dump(JOB / f'{kind}_本次结果.json', {'requested': len(items), 'failures': failures})
    if failures:
        raise SystemExit(1)


def boards():
    verify_sources()
    if (JOB/'逐镜请求.json').exists():
        raise ValueError('已切换单镜流程；用 shots-plan，禁止旧六格流程覆盖当前页面清单')
    assets = {x['id']: x for x in load(JOB / '资产请求.json')}
    requests = []
    for ep in range(1, 4):
        sb = load(TEXT_ROOT / f'分镜/EP{ep:03d}.json')
        for start in range(0, len(sb['shots']), 6):
            shots = sb['shots'][start:start+6]
            names = list(dict.fromkeys([c['name'] for s in shots for c in s['cast']]))
            locations = list(dict.fromkeys(s['location']['id'] for s in shots))
            prop_ids = list(dict.fromkeys(a for s in shots for a in s['uses']))
            priorities = ['铜销','绳轮机关','黑钢锥','双碗','晒网架','湿网','清障图','铜鱼牌','皮鞘','钱袋铜钱']
            prop_ids.sort(key=lambda a: priorities.index(a) if a in priorities else len(priorities))
            # 身份与场景图显式绑定，使用单格参考，不让六宫格成为六个人。
            refs = []
            bindings = []
            for aid in names + locations + prop_ids[:2]:
                if aid not in assets:
                    raise ValueError(f'缺资产定义：{aid}')
                a = assets[aid]
                f = JOB / a.get('binding_ref', a['output'])
                if aid in names:
                    from collections import Counter
                    state = Counter(s['character_states'][aid] for s in shots if aid in s['character_states']).most_common(1)[0][0]
                    index = {'wet':4, 'wet_lower_tunic':4, 'left_shoulder_scrape':5,
                             'left_shoulder_bandaged':6}.get(state)
                    if index and len(a['cells']) >= index:
                        f = (JOB / a['output']).with_name(f'cell_{index:02d}.jpg')
                    if aid == '陆照' and state in ('left_shoulder_scrape','left_shoulder_bandaged'):
                        wound = assets['陆照伤势']
                        f = (JOB / wound['output']).with_name('cell_01.jpg' if state == 'left_shoulder_scrape' else 'cell_02.jpg')
                if aid == '铜销' and (ep == 2 or start >= 18):
                    f = (JOB / a['output']).with_name('cell_03.jpg' if ep == 2 else 'cell_02.jpg')
                if not f.exists():
                    raise ValueError(f'缺已生成资产：{f}')
                refs.append(rel(f))
                bindings.append(f"Reference {len(refs)} establishes {a['label_en']}.")
            prompt = STYLE + ('Create a narrative storyboard contact sheet of six equal 16:9 panels '
                     'in two columns and three rows. Thin dark separators. Each panel is a separate single instant. '
                     'All panels fill their rectangular cells. Clean image surfaces. ')
            prompt += ' '.join(bindings) + ' '
            positions = ['top left', 'top right', 'middle left', 'middle right', 'bottom left', 'bottom right']
            for pos, s in zip(positions, shots):
                prompt += f"The {pos} panel: " + s['render']['keyframe_prompt'].removeprefix(STYLE) + ' '
            if len(shots) < 6:
                prompt += 'Remaining cells show the final location as an empty environment study. '
            requests.append({'id': f'EP{ep:03d}_P{start//6+1:02d}', 'prompt': prompt,
                             'refs': refs, 'size': {'width': 3072, 'height': 2592},
                             'seed': 880000 + ep*100 + start,
                             'output': f'故事板/EP{ep:03d}_P{start//6+1:02d}.jpg',
                             'shots': [s['id'] for s in shots]})
    dump(JOB / '故事板请求.json', requests)


def crops():
    """在实测白底边界内取单格参考；记录cell框与主体框，供人工复核。"""
    from PIL import Image
    import numpy as np
    for item in load(JOB / '资产请求.json'):
        f = JOB / item['output']
        if not f.exists():
            raise ValueError(f'尚无资产图：{f}')
        im = Image.open(f).convert('RGB')
        cols, rows = item['grid']
        # 场景和黑底特效整图绑定；无分格假设。
        if cols == rows == 1:
            im.save(JOB / item['binding_ref'], quality=95)
            dump(f.with_name('cells.json'), {'grid':[1,1], 'cells':[{'bbox':[0,0,*im.size]}]})
            continue
        data = np.array(im)
        white = (data.min(axis=2) > 235)
        def cuts(length, n, whiteness):
            out = [0]
            for i in range(1,n):
                ideal = round(i*length/n)
                lo,hi = max(0,ideal-int(length*.045)),min(length,ideal+int(length*.045))
                scores=whiteness[lo:hi]
                candidates=np.flatnonzero(scores >= max(.92,float(scores.max())-.005))+lo
                cut=int(candidates[np.argmin(abs(candidates-ideal))]) if len(candidates) else ideal
                out.append(cut)
            return out+[length]
        xs=cuts(im.width,cols,white.mean(axis=0))
        ys=cuts(im.height,rows,white.mean(axis=1))
        cells=[]
        for y in range(rows):
            for x in range(cols):
                box=[xs[x]+8,ys[y]+8,xs[x+1]-8,ys[y+1]-8]
                crop=im.crop(box)
                cp=np.array(crop)
                mask=cp.min(axis=2)<220
                yy,xx=np.where(mask)
                subject=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)] if len(xx) else None
                index=y*cols+x
                cpname=f'cell_{index+1:02d}.jpg'
                crop.save(f.with_name(cpname),quality=95)
                cells.append({'index':index+1,'name':item['cells'][index], 'bbox':box,
                              'subject_bbox_in_cell':subject,'path':rel(f.with_name(cpname))})
                if index==0: crop.save(JOB/item['binding_ref'],quality=95)
        dump(f.with_name('cells.json'), {'grid':[cols,rows], 'separator_x':xs,'separator_y':ys,
                                       'method':'near-grid measured white-band maxima; candidate bounds require visual inspection','cells':cells})
    print('单格参考及测量记录已生成',flush=True)


def shots_plan():
    """单镜独立绑定身份和状态，避免六格生成串人；页面仅作本地排版。"""
    verify_sources()
    assets = {x['id']:x for x in load(JOB / '资产请求.json')}
    requests, pages = [], []
    for ep in range(1,4):
        sb = load(TEXT_ROOT / f'分镜/EP{ep:03d}.json')
        for n,s in enumerate(sb['shots'],1):
            refs, bindings = [], []
            names = [c['name'] for c in s['cast']]
            if s.get('in_frame') == 'hands_or_object':
                names = []
            aids = list(dict.fromkeys(names + [s['location']['id']] + s['uses'][:2]))
            for aid in aids:
                a = assets[aid]
                f = JOB / a['binding_ref']
                if aid in names:
                    state=s['character_states'][aid]
                    if state in ('wet','wet_lower_tunic') and len(a['cells'])>=4:
                        f=(JOB/a['output']).with_name('cell_04.jpg')
                    if aid=='陆照' and state in ('left_shoulder_scrape','left_shoulder_bandaged'):
                        f=(JOB/assets['陆照伤势']['output']).with_name('cell_01.jpg' if state=='left_shoulder_scrape' else 'cell_02.jpg')
                if aid=='铜销' and (ep==2 or n>=19):
                    f=(JOB/a['output']).with_name('cell_03.jpg' if ep==2 else 'cell_02.jpg')
                refs.append(rel(f))
                bindings.append(f"Image {len(refs)}: {a['label_en']}.")
            prompt=STYLE+'One cinematic narrative frame. '+ ' '.join(bindings)+' '+s['render']['keyframe_prompt'].removeprefix(STYLE)
            requests.append({'id':s['id'],'prompt':prompt,'refs':refs,'size':{'width':2048,'height':1152},'seed':890000+ep*100+n,'output':f"逐镜/{s['id']}_v01.jpg"})
        for start in range(0,len(sb['shots']),6):
            pages.append({'id':f'EP{ep:03d}_P{start//6+1:02d}','output':f'故事板/EP{ep:03d}_P{start//6+1:02d}_assembled_v01.jpg','shots':[s['id'] for s in sb['shots'][start:start+6]],'method':'locally assembled from individually generated shots'})
    revision_path=JOB/'镜头图修订.json'
    if revision_path.exists():
        revisions=load(revision_path)
        if revisions['design_sha256'] != digest(JOB/'镜头设计.tsv'):
            raise ValueError('镜头图修订与作者源指纹不同，先重新复核')
        for item in requests:
            item.update(revisions['shots'].get(item['id'],{}))
    dump(JOB/'逐镜请求.json',requests)
    dump(JOB/'故事板请求.json',pages)


def assemble():
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    shots={s['id']:s for s in load(JOB/'逐镜请求.json')}
    font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',25)
    for page in load(JOB/'故事板请求.json'):
        canvas=Image.new('RGB',(2080,1880),'#101a20')
        draw=ImageDraw.Draw(canvas)
        for i,sid in enumerate(page['shots']):
            f=JOB/shots[sid]['output']
            if not f.exists():
                raise ValueError(f'缺单镜：{sid}')
            im=Image.open(f).convert('RGB')
            x=16+(i%2)*1032; y=16+(i//2)*622
            fitted=ImageOps.contain(im,(1016,572))
            canvas.paste(fitted,(x+(1016-fitted.width)//2,y+(572-fitted.height)//2))
            draw.text((x,y+578),sid,fill='#ece7db',font=font)
        out=JOB/page['output'];out.parent.mkdir(exist_ok=True,parents=True)
        canvas.save(out,quality=95)
        dump(out.with_suffix('.result.json'),{'status':'assembled_pending_visual_review','sha256':digest(out),'shots':[{'id':sid,'sha256':digest(JOB/shots[sid]['output'])} for sid in page['shots']]})


def report():
    esc = html.escape
    assets = load(JOB / '资产请求.json')
    pages = load(JOB / '故事板请求.json') if (JOB / '故事板请求.json').exists() else []
    shot_images = {s['id']:s for s in load(JOB/'逐镜请求.json')} if (JOB/'逐镜请求.json').exists() else {}
    visual_issues = load(JOB/'待修镜头.json')['shots'] if (JOB/'待修镜头.json').exists() else {}
    css = 'body{background:#101a20;color:#ece7db;font:17px/1.65 system-ui;margin:0}main{max-width:1360px;margin:auto;padding:45px 30px}h1{font-size:42px}h2{margin-top:64px;border-top:1px solid #42515b;padding-top:24px}a{color:#d7b77c}nav{display:flex;gap:25px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:24px}figure{margin:0;background:#1b2932;padding:14px;border-radius:10px}img{width:100%;height:auto}figcaption{padding:12px 0}.page{max-width:1080px;margin:24px auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #43515b;padding:10px;text-align:left;vertical-align:top}.muted{color:#a9b7ba}details{margin:18px 0}summary{cursor:pointer;font-size:21px}@media(max-width:650px){main{padding:20px 12px}h1{font-size:30px}table{font-size:12px}}'
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>一寸活路 · 前三集 v8</title><style>'+css+'</style><main>',
             '<p class="muted">制作版 01 · Seedream 立体国漫 v8 · 16:9</p><h1>一寸活路 / 前三集</h1>',
             '<p style="color:#ffc68a">本页为84镜历史预览版。共享目录已有每集60秒的56镜新版；两版独立保存。当前有5镜待修，详见视觉检查；本页不能用于新版画面验收。</p>' if TEXT_ROOT != P else '',
             '<p>角色与场景资产 · 逐镜设计 · 彩色故事板。图版为构图预览，逐镜生产以 JSON、状态带和视觉问题记录为准。</p>',
             '<nav><a href="#assets">资产</a><a href="#EP001">01 死人领工钱</a><a href="#EP002">02 两只碗</a><a href="#EP003">03 门外三步</a><a href="导演与连续性.md">导演与连续性</a><a href="机关与轴线.svg">机关与轴线</a><a href="视觉检查.md">视觉检查</a></nav>',
             '<h2 id="assets">资产参考板</h2><div class="grid">']
    for a in assets:
        if (JOB / a['output']).exists():
            parts.append(f'<figure><a href="{esc(a["output"])}"><img loading="lazy" src="{esc(a["output"])}"></a><figcaption><b>{esc(a["id"])}</b><br>{esc(a["note"])}</figcaption></figure>')
        else:
            parts.append(f'<figure><b>{esc(a["id"])}</b><p>待生成／失败，见任务记录。</p></figure>')
    parts += ['</div>']
    text_link = '文字快照' if TEXT_ROOT != P else '../..'
    summary = []
    for ep in range(1, 4):
        eid = f'EP{ep:03d}'
        sb = load(TEXT_ROOT / f'分镜/{eid}.json')
        total = round(sum(s['seconds'] for s in sb['shots']), 1)
        summary.append({'episode': eid, 'title': sb['title'], 'shots': len(sb['shots']), 'seconds': total})
        parts.append(f'<h2 id="{eid}">{eid} · {esc(sb["title"])}</h2><p>{len(sb["shots"])} 镜 · {total:g} 秒 · <a href="{text_link}/分镜/{eid}_中文.html">完整中文分镜</a> · <a href="{text_link}/分镜/{eid}.json">JSON</a></p>')
        for page in [x for x in pages if x['id'].startswith(eid)]:
            if (JOB / page['output']).exists():
                warnings='；'.join(sid+'：'+visual_issues[sid] for sid in page['shots'] if sid in visual_issues)
                parts.append(f'<figure class="page"><a href="{page["output"]}"><img loading="lazy" src="{page["output"]}"></a><figcaption>{page["id"]} · 自左至右、从上到下：{", ".join(page["shots"])}<br><span style="color:#ffc68a">{esc(warnings)}</span></figcaption></figure>')
        parts.append('<details open><summary>逐镜时间与内容</summary><table><tr><th>镜号／时间</th><th>画面与衔接</th><th>台词</th><th>资产</th></tr>')
        t = 0
        for s in sb['shots']:
            end = t+s['seconds']
            dialogue = '<br>'.join(esc(d['speaker']+'：'+d['text']) for d in s['lines'])
            picture=shot_images.get(s['id'])
            picture_link=f'<br><a href="{esc(picture["output"])}">单镜原图</a>' if picture and (JOB/picture['output']).exists() else ''
            if s['id'] in visual_issues: picture_link+='<br><b style="color:#ffc68a">待修：'+esc(visual_issues[s['id']])+'</b>'
            parts.append(f'<tr><td>{s["id"]}<br>{t:g}–{end:g}s{picture_link}</td><td>{esc(" → ".join(s["action"].values()))}<br><span class="muted">{esc(s["camera_cn"])}</span></td><td>{dialogue}</td><td>{esc("、".join(s["uses"]))}</td></tr>')
            t = round(end, 1)
        parts.append('</table></details>')
    parts.append('</main></html>')
    (JOB / '总览.html').write_text('\n'.join(parts))
    dump(JOB / '交付统计.json', {'episodes': summary, 'assets': len(assets),
         'assets_generated': sum((JOB / a['output']).exists() for a in assets),
         'shot_images_generated': sum((JOB/s['output']).exists() for s in shot_images.values()),
         'open_visual_issues': len(visual_issues), 'version_status': 'historical_preview_pending_version_choice' if TEXT_ROOT != P else 'preproduction',
         'storyboard_pages': len(pages), 'pages_generated': sum((JOB / a['output']).exists() for a in pages)})
    print(json.dumps(load(JOB / '交付统计.json'), ensure_ascii=False), flush=True)


def audit():
    """交付门禁：完整文件、输入引用、源锁、画幅、对白时长和页面覆盖。"""
    from PIL import Image
    verify_sources()
    assets=load(JOB/'资产请求.json'); shots=load(JOB/'逐镜请求.json'); pages=load(JOB/'故事板请求.json')
    aids={a['id'] for a in assets}
    issues=[]; ids=[]
    for ep in range(1,4):
        sb=load(TEXT_ROOT/f'分镜/EP{ep:03d}.json')
        for s in sb['shots']:
            ids.append(s['id'])
            used={c['name'] for c in s['cast']}|{s['location']['id']}|set(s['uses'])
            if used-aids: issues.append(f"{s['id']} 缺资产 {used-aids}")
            for d in s['lines']:
                length=len(re.sub(r'\W','',d['text']))/4+.4
                if d['at']+length > s['seconds']+.01: issues.append(s['id']+' 台词越界')
    if len(ids)!=84 or len(set(ids))!=84: issues.append('镜号数量/唯一性错误')
    covered=[sid for p in pages for sid in p['shots']]
    if sorted(covered)!=sorted(ids): issues.append('页面覆盖错误')
    if sorted(x['id'] for x in shots)!=sorted(ids): issues.append('单镜请求覆盖错误')
    for item in assets+shots:
        f=JOB/item['output']
        if not f.exists():
            issues.append('缺图 '+item['id']);continue
        if NEG_RE.search(item['prompt']): issues.append('否定词 '+item['id'])
        record=load(f.with_suffix('.request.json'))
        result=load(f.with_suffix('.result.json'))
        if [x['path'] for x in record['references']] != item.get('refs',[]): issues.append('参考列表过期 '+item['id'])
        if result.get('sha256')!=digest(f): issues.append('输出指纹 '+item['id'])
        for ref in record['references']:
            if digest(P/ref['path'])!=ref['sha256']: issues.append('参考指纹 '+item['id'])
        if record['prompt']!=item['prompt'] or record['seed']!=item['seed']: issues.append('请求过期 '+item['id'])
        im=Image.open(f);im.verify()
        if item in shots:
            w,h=Image.open(f).size
            if abs(w/h-16/9)>.02: issues.append('单镜画幅 '+item['id'])
    for page in pages:
        f=JOB/page['output']
        if not f.exists(): issues.append('缺页面 '+page['id']);continue
        result=load(f.with_suffix('.result.json'))
        if result['sha256']!=digest(f): issues.append('页面指纹 '+page['id'])
        lookup={s['id']:s for s in shots}
        for s in result['shots']:
            if digest(JOB/lookup[s['id']]['output'])!=s['sha256']: issues.append('页面引用过期 '+page['id'])
    dump(JOB/'交付检查.json',{'assets':len(assets),'shots':len(shots),'pages':len(pages),'issues':issues,'note':'文件与结构检查；视觉复核另见视觉检查.md，不代替最终关键帧验收'})
    print(json.dumps(load(JOB/'交付检查.json'),ensure_ascii=False))
    if issues: raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['prepare', 'assets', 'crops', 'boards-plan', 'boards', 'shots-plan', 'shots', 'assemble', 'report', 'check', 'audit'])
    ap.add_argument('--jobs', type=int, choices=range(1, 11), default=4)
    ap.add_argument('--only')
    a = ap.parse_args()
    if a.command == 'prepare': prepare()
    elif a.command == 'crops': crops()
    elif a.command == 'boards-plan': boards()
    elif a.command == 'shots-plan': shots_plan()
    elif a.command == 'assemble': assemble()
    elif a.command == 'report': report()
    elif a.command == 'audit': audit()
    elif a.command == 'check': verify_sources()
    else: render(a.command, a.jobs, a.only)


if __name__ == '__main__':
    main()
