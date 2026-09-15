import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import yichun_extend30 as e

def test_extension_failure_does_not_retry_or_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'ROOT',tmp_path)
    task={'source':'existing.mp4','source_sha256':'sourcehash','references':[],'prompt':'continue'}
    monkeypatch.setattr(e,'build',lambda:task)
    monkeypatch.setattr(e,'uploaded',lambda ref:'https://example.invalid/source')
    calls=[]
    def video(prompt,**kwargs):
        calls.append(kwargs);return None,'422 rejected'
    monkeypatch.setattr(e.provider,'video',video)
    with pytest.raises(RuntimeError,match='422'):e.run()
    assert calls[0]['task']=='extension'
    assert calls[0]['seconds']==30
    assert calls[0]['video_urls']==['https://example.invalid/source']
    with pytest.raises(ValueError,match='禁止'):e.run()
    assert len(calls)==1
    assert e.read(tmp_path/'extension_01.json')['status']=='failed_no_retry_no_fallback'
