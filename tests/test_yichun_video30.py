"""30秒付费入口：版本、视觉参考及防重复扣费保护；全部离线。"""
import json
import fcntl
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import yichun_video30 as v

class Video30Gates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.patch=patch.multiple(v,P=self.root,K=self.root);self.patch.start();self.addCleanup(self.patch.stop)
    def test_missing_plan_rating_blocks_before_upload(self):
        with patch.object(v.rating_gate,'require'),patch.object(v.provider,'upload') as upload:
            with self.assertRaises(FileNotFoundError):v.run('EP002_B')
            upload.assert_not_called()
    def test_missing_visual_acceptance_blocks_reference(self):
        v.write(self.root/'参考采用.json',{})
        v.write(self.root/'段落引用.json',{'EP001_A':[{'path':'opening.png','kind':'opening','role':'opening'}]})
        with self.assertRaisesRegex(ValueError,'尚未采用'):v.references('EP001_A')
    def test_changed_picture_cannot_keep_visual_acceptance(self):
        p=self.root/'opening.png';p.write_bytes(b'new pixels')
        v.write(self.root/'参考采用.json',{'opening.png':{'status':'accepted_reference','sha256':'old'}})
        v.write(self.root/'段落引用.json',{'EP001_A':[{'path':'opening.png','kind':'opening','role':'opening'}]})
        with self.assertRaisesRegex(ValueError,'指纹变更'):v.references('EP001_A')
    def test_prior_submitted_request_never_automatically_retries(self):
        v.write(self.root/'视频/EP002_B/take_01_480p.json',{'request_sha256':'same','status':'submitted'})
        with patch.object(v,'build',return_value={'request_sha256':'same'}),patch.object(v.provider,'video') as paid:
            with self.assertRaisesRegex(ValueError,'禁止自动重复扣费'):v.run('EP002_B')
            paid.assert_not_called()
    def test_parallel_process_lock_blocks_before_paid_call(self):
        folder=self.root/'视频/EP002_B';folder.mkdir(parents=True)
        with (folder/'take_01_480p.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(v,'build') as build,patch.object(v.provider,'video') as paid:
                with self.assertRaisesRegex(ValueError,'另一进程'):v.run('EP002_B')
                build.assert_not_called();paid.assert_not_called()
    def test_stale_asr_cannot_be_reused_for_changed_video(self):
        folder=self.root/'视频/EP002_B';folder.mkdir(parents=True)
        (folder/'take_01_480p.mp4').write_bytes(b'changed video')
        v.write(folder/'take_01_480p.asr.json',{'source_sha256':'old'})
        with patch.object(sys,'argv',['video30','asr','--segment','EP002_B']),patch.object(v.provider,'transcribe') as paid:
            with self.assertRaisesRegex(ValueError,'听写所据视频已变更'):v.main()
            paid.assert_not_called()
    def test_exact_plan_source_gate_passes_on_real_files(self):
        self.patch.stop()
        try:
            p=v.require_plan()
            self.assertEqual([s['seconds'] for s in p['segments']],[30]*6)
        finally:self.patch.start()

    def test_preflight_preserves_prior_request(self):
        path=self.root/'请求/EP002_B_take01.json'
        v.write(path,{'request_sha256':'historic'})
        before=path.read_bytes()
        task={'references':[{}],'prompt':'new draft','seconds':30}
        with patch.object(sys,'argv',['video30','preflight','--segment','EP002_B']),patch.object(v,'build',return_value=task),patch.object(v.provider,'video') as paid:
            v.main()
            self.assertEqual(path.read_bytes(),before)
            paid.assert_not_called()

if __name__=='__main__':unittest.main()
