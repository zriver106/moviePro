import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import provider
import yichun_post30 as post
import yichun_video_edit30 as repair


def test_editing_uses_source_duration_and_preserves_reference_default():
    with patch.object(provider,'_post',return_value=({'video':{'url':'result'}},None)) as call:
        provider.video('repair',task='editing',video_urls=['source'],seconds=30)
        body=call.call_args.args[1]
        assert body['task']=='editing' and body['duration']=='auto' and body['aspect_ratio']=='auto'
        provider.video('new',seconds=30,image_urls=['image'])
        body=call.call_args.args[1]
        assert body['duration']=='30' and 'task' not in body


def test_editing_missing_video_never_calls_provider():
    with patch.object(provider,'_post') as call:
        _,error=provider.video('repair',task='editing')
        assert error and not call.called


def test_candidate_cannot_be_exported_as_delivery(tmp_path,monkeypatch):
    video=tmp_path/'candidate.mp4';video.write_bytes(b'candidate')
    plan=tmp_path/'30秒分段方案.json';plan.write_text('{}')
    video.with_suffix('.验收.json').write_text(json.dumps({'status':'rejected','video_sha256':post.sha(video)}))
    monkeypatch.setattr(post,'K',tmp_path)
    meta={'video_sha256':post.sha(video),'plan_sha256':post.sha(plan),'timing_approved':True}
    with pytest.raises(ValueError,match='画面未通过'):post.release_gate(video,meta,False)
    post.release_gate(video,meta,True)
    video.write_bytes(b'changed')
    with pytest.raises(ValueError,match='视频已改变'):post.release_gate(video,meta,True)


def test_pair_reference_requires_actual_adoption(tmp_path,monkeypatch):
    (tmp_path/'30秒分段方案.json').write_text('{}')
    (tmp_path/'参考采用.json').write_text('{}')
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'plan_sha256':repair.sha(tmp_path/'30秒分段方案.json'),'scope':'faithful_execution_repair','strategy':'keyframe_pair','first_frame':{'path':'image.jpg','sha256':'missing'},'last_frame':{'path':'end.jpg','sha256':'missing'}}))
    monkeypatch.setattr(repair,'K',tmp_path);monkeypatch.setattr(repair,'require_plan',lambda:None)
    with pytest.raises(ValueError,match='首尾参考未采用'):repair.build(spec)


def test_subtitle_preview_has_chinese_and_unapproved_notice(tmp_path):
    post.write_subtitles(tmp_path,[{'start':1.5,'end':3,'text':'先不借。我们挣。'}],True)
    text=(tmp_path/'中文字幕.ass').read_text()
    assert '先不借。我们挣。' in text and '画面未通过验收' in text
    assert '0:00:01.50,0:00:03.00' in text
