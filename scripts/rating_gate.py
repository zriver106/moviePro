#!/usr/bin/env python3
"""独立文本评级门禁。缺评、低分、过期、缺证据均阻断付费生成；无force入口。"""
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADES = {'S': 1, 'S+': 2}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def check(project, episodes=None, root=ROOT):
    p = Path(root) / 'projects' / project
    issues = []
    try:
        policy_path = p / '评审/评级规则.json'
        policy = read(policy_path)
        record = read(p / '评审/当前评级.json')
        configured = policy['episodes']
        if not isinstance(configured, dict) or not configured:
            raise ValueError('评级范围为空')
        wanted = list(configured) if episodes is None else [f'EP{x:03d}' if isinstance(x, int) else x for x in episodes]
        if not wanted:
            raise ValueError('请求评级范围为空')
        if record.get('policy_sha256') != sha(policy_path):
            issues.append('评级规则已改变，需重新确认适用标准')
        if record.get('status') != 'passed':
            issues.append('尚无当前版本的外评通过记录')
        review = record['external_review']
        if review.get('thread_id') != policy['review_thread_id'] or not review.get('message_id'):
            issues.append('评级会话或回复标识缺失/不匹配')
        evidence = p / review['evidence_path']
        if sha(evidence) != review['evidence_sha256']:
            issues.append('外评证据指纹不匹配')
        manifest = p / review['manifest_path']
        if sha(manifest) != review['manifest_sha256']:
            issues.append('送审清单指纹不匹配')
        source_map = read(manifest)
        for eid in wanted:
            if eid not in configured:
                issues.append(f'{eid} 不在已评级范围内')
                continue
            rated = record.get('episodes', {}).get(eid, {})
            for key in ('script_grade', 'storyboard_grade'):
                if GRADES.get(rated.get(key), 0) < GRADES.get(policy.get('minimum_grade'), 99):
                    issues.append(f'{eid} {key} 未达到 {policy.get("minimum_grade")}')
            if rated.get('blocking_issues') != []:
                issues.append(f'{eid} 阻断问题未清空或未报告')
            for dimension, grade in rated.get('dimensions', {}).items():
                if GRADES.get(grade, 0) < GRADES.get(policy.get('minimum_grade'), 99):
                    issues.append(f'{eid} {dimension} 未达标，禁止平均抵消')
            required = [f'剧本/{eid}.md', f'分镜/{eid}.json', f'分镜/{eid}_中文.md']
            for rel in required:
                f = p / rel
                if not f.exists() or sha(f) != source_map.get(eid, {}).get(rel):
                    issues.append(f'{eid} 评级已过期或未覆盖：{rel}')
            try:
                board = read(p / f'分镜/{eid}.json')
                shots = board['shots']
                seconds = [s['seconds'] for s in shots]
                if not shots or any(not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t) or t <= 0 for t in seconds):
                    raise ValueError('镜头时长为空或非法')
                target = configured[eid]['target_seconds']
                tolerance = configured[eid].get('tolerance_seconds', 0.1)
                if not math.isfinite(target) or target <= 0 or tolerance < 0 or not math.isfinite(tolerance):
                    raise ValueError('目标时长/容差非法')
                if abs(sum(seconds)-target) > tolerance or abs(board['target_seconds']-target) > tolerance:
                    issues.append(f'{eid} 时长 {sum(seconds):g}s 不符已批准的 {target:g}s 预算')
                ids = [s['id'] for s in shots]
                if len(set(ids)) != len(ids):
                    issues.append(f'{eid} 镜号重复')
                for s in shots:
                    for line in s.get('lines', []):
                        if 'end' in line and not 0 <= line.get('at', 0) < line['end'] <= s['seconds']:
                            issues.append(f"{s['id']} 对白窗口越界")
            except (KeyError, ValueError, TypeError) as exc:
                issues.append(f'{eid} 分镜结构错误：{exc}')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(f'评级门禁资料缺失或损坏：{exc}')
    return issues


def require(project, episodes=None, what='付费生成'):
    issues = check(project, episodes)
    if issues:
        raise SystemExit(f'✗ {what}被评级门禁拦下：\n' + '\n'.join('  - '+s for s in issues) +
                         '\n先送审当前剧本与文字分镜，按低分问题返修并取得真实复评；禁止force绕过。')
    return True


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True)
    ap.add_argument('--ep', type=int, action='append')
    args = ap.parse_args()
    require(args.project, args.ep, '制作准备')
    print('✓ 当前剧本、文字分镜及外评指纹一致，达到文本评级标准；此命令不生成图片。')
