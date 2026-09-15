#!/usr/bin/env python3
"""57镜新版资源任务：读取已评级规格，按引用指纹生成独立候选，绝不覆盖旧版。"""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from PIL import Image
import provider
import rating_gate
from negwords import NEG_RE

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'projects/一寸活路'
J = P / '制作/前三集_v8_v2_文本定稿'


def read(p):
    return json.loads(Path(p).read_text())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)


def require_spec(spec_name):
    rating_gate.require('一寸活路', what='新版资源生成')
    approval = read(J / '资源外评.json')
    if spec_name not in approval.get('files', {}):
        review = {'结构修图任务.json':'结构修图外评.json',
                  '分镜修图任务.json':'分镜修图外评.json'}.get(spec_name, '修图外评.json')
        approval = read(J / review)
    evidence = J / approval['evidence_path']
    if sha(evidence) != approval['evidence_sha256'] or not approval.get('message_id'):
        raise ValueError('资源独立外评证据缺失或过期')
    if approval['thread_id'] != '01a08ea0-8c4d-74e0-ae4b-95fa647cfb4d':
        raise ValueError('资源评级任务不匹配')
    if approval.get('blocking_issues') != [] or not approval.get('dimensions'):
        raise ValueError('资源外评仍有阻断或缺适用维度')
    if any(x not in ('S', 'S+') for x in approval['dimensions'].values()):
        raise ValueError('资源外评未达S')
    if approval['files'].get(spec_name) != sha(J / spec_name):
        raise ValueError(f'资源规格变更需复评: {spec_name}')
    for name, digest in approval['files'].items():
        if sha(J / name) != digest:
            raise ValueError(f'同一送审包关联文件改变: {name}')
    current = read(P / '评审/当前评级.json')['external_review']['manifest_sha256']
    if approval['source_manifest_sha256'] != current:
        raise ValueError('资源与当前正文版本不符')


def data_uri(path):
    mime = 'image/png' if path.suffix == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()


def resolved_refs(paths, require_visual=False):
    """Text bindings identify assets; a separate hash-bound visual decision picks candidates."""
    review_path = J / '图片采用记录.json'
    decisions = read(review_path) if review_path.exists() else {}
    result = []
    for rel in paths:
        record = decisions.get(rel)
        if require_visual and (not record or record.get('status') != 'accepted_reference'):
            raise ValueError(f'参考图尚未目视采用: {rel}')
        actual = P / (record['selected_path'] if record else rel)
        if record and sha(actual) != record['sha256']:
            raise ValueError(f'参考图在目视采用后已改变: {rel}')
        result.append(actual)
    return result


def generate(spec_name, row, variant=1):
    require_spec(spec_name)
    row = dict(row)
    if variant != 1:
        row['output'] = re.sub(r'_v\d+\.jpg$', f'_v{variant:02d}.jpg', row['output'])
        row['seed'] += 1000 * (variant - 1)
    qa_path = J / '视觉检查.json'
    if spec_name == '出图任务.json' and qa_path.exists():
        rejected = {x['id'] for x in read(qa_path).get('shots', []) if x['status'] == 'rejected'}
        if row['id'] in rejected:
            raise ValueError(f"{row['id']} 首版已被视觉检查退回，须使用已独立评级的纠错任务")
    prompt = row['prompt']
    neg = NEG_RE.findall(prompt)
    if neg:
        raise ValueError(f"{row['id']} 正向提示词含否定词: {neg}")
    is_shot = spec_name in ('出图任务.json', '分镜修图任务.json')
    refs = resolved_refs(row['refs'], require_visual=is_shot)
    if is_shot:
        bindings = read(J / '逐镜绑定.json')
        bound = next(x for x in bindings['shots'] if x['id'] == row['id'])
        all_paths = [x['path'] for x in bound['characters'] + bound['props']] + [bound['location']['path']]
        resolved_refs(all_paths, require_visual=True)
    # Conservative image-job limit; never silently truncate provided references.
    if len(refs) > 9:
        raise ValueError('本制作批次参考图最多9张，须显式调整引用')
    inputs = {str(x.relative_to(P)): sha(x) for x in refs}
    out = J / row['output']
    meta = out.with_suffix('.json')
    signature = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if out.exists():
        if not meta.exists():
            raise ValueError(f'{out} 缺生成记录，不能覆写')
        prior = read(meta)
        if prior['request_sha256'] != signature or prior['refs_sha256'] != inputs or prior['image_sha256'] != sha(out):
            raise ValueError(f'{out} 已有内容与本次请求不符，必须升版本')
        return {'id':row['id'], 'status':'existing', 'path':str(out.relative_to(J))}
    out.parent.mkdir(parents=True, exist_ok=True)
    if refs:
        url, err = provider.edit_image(prompt, [data_uri(x) for x in refs], size=row['size'], seed=row['seed'])
    else:
        url, err = provider.text_to_image(prompt, size=row['size'], seed=row['seed'])
    if err or not url:
        raise RuntimeError(f"{row['id']}: {err or 'empty result'}")
    tmp = out.with_suffix('.download')
    with urllib.request.urlopen(url, timeout=120) as response:
        tmp.write_bytes(response.read())
    with Image.open(tmp) as im:
        im.verify()
    with Image.open(tmp) as im:
        width, height = im.size
    if min(width,height) < 512:
        raise ValueError('生成图尺寸异常')
    require_spec(spec_name)  # Source changes during a paid call invalidate adoption too.
    if {str(x.relative_to(P)): sha(x) for x in refs} != inputs:
        raise ValueError('生成期间参考图改变，候选未采用')
    tmp.replace(out)
    write(meta, {'id':row['id'], 'request_sha256':signature, 'spec_sha256':sha(J/spec_name),
                 'refs_sha256':inputs, 'image_sha256':sha(out), 'dimensions':[width,height],
                 'provider_backend':provider.BACKEND, 'source_spec':spec_name,
                 'visual_status':'pending_inspection'})
    return {'id':row['id'], 'status':'generated', 'path':str(out.relative_to(J))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['assets','shots','repairs','structures','shot_repairs'])
    ap.add_argument('--id', action='append')
    ap.add_argument('--workers',type=int,default=6)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--variant', type=int, default=1)
    args = ap.parse_args()
    if not 1 <= args.workers <= 10:
        ap.error('并发范围1–10')
    if args.variant < 1 or (args.variant > 1 and not args.id):
        ap.error('候选版本须正数，重试必须指定具体资产/镜头')
    spec_name = {'assets':'新增资产规格.json','shots':'出图任务.json','repairs':'修图任务.json','structures':'结构修图任务.json','shot_repairs':'分镜修图任务.json'}[args.stage]
    data = read(J/spec_name)
    rows = data['shots' if args.stage in ('shots','shot_repairs') else 'assets']
    if args.id:
        wanted = set(args.id)
        rows = [x for x in rows if x['id'] in wanted]
        if set(x['id'] for x in rows) != wanted:
            ap.error('镜号/资产ID不存在')
    if not rows:
        ap.error('范围为空')
    if args.dry_run:
        errors=[]
        for r in rows:
            if NEG_RE.search(r['prompt']):errors.append(r['id']+':negative_word')
            if len(r['refs'])>9: errors.append(r['id']+':too_many_refs')
            for rel in r['refs']:
                if not (P/rel).exists():errors.append(r['id']+':missing:'+rel)
        print(json.dumps({'count':len(rows),'issues':errors},ensure_ascii=False))
        return
    require_spec(spec_name)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(generate,spec_name,r,args.variant):r['id'] for r in rows}
        for f in concurrent.futures.as_completed(jobs):
            try:result=f.result()
            except Exception as exc:result={'id':jobs[f], 'status':'failed','error':str(exc)}
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    write(J / f'{args.stage}_最近批次.json', results)
    if any(x['status']=='failed' for x in results):sys.exit(1)

if __name__ == '__main__':main()
