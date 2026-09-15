"""付费调用前的版本、外评和视觉采用闸；测试始终不调用网络。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import yichun_resources as resource


class ResourceGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patcher = patch.multiple(resource, P=self.root, J=self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_missing_external_review_precedes_provider(self):
        with patch.object(resource.rating_gate, 'require'), patch.object(resource.provider, 'text_to_image') as paid:
            with self.assertRaises(FileNotFoundError):
                resource.generate('新增资产规格.json', {})
            paid.assert_not_called()

    def test_unreviewed_image_cannot_enter_shot(self):
        with self.assertRaisesRegex(ValueError, '尚未目视采用'):
            resource.resolved_refs(['missing.jpg'], require_visual=True)

    def test_selected_variant_is_hash_locked(self):
        (self.root / 'v02.jpg').write_bytes(b'checked candidate')
        digest = resource.sha(self.root / 'v02.jpg')
        resource.write(self.root / '图片采用记录.json', {
            'v01.jpg': {'status':'accepted_reference','selected_path':'v02.jpg','sha256':digest}})
        self.assertEqual(resource.resolved_refs(['v01.jpg'], True), [self.root / 'v02.jpg'])
        (self.root / 'v02.jpg').write_bytes(b'changed candidate')
        with self.assertRaisesRegex(ValueError, '已改变'):
            resource.resolved_refs(['v01.jpg'], True)

    def test_changed_request_never_overwrites_candidate(self):
        out = self.root / 'candidate_v01.jpg'
        out.write_bytes(b'existing')
        resource.write(out.with_suffix('.json'), {'request_sha256':'different','refs_sha256':{},'image_sha256':resource.sha(out)})
        row={'id':'case','prompt':'A wooden bowl.','refs':[],'output':out.name,'seed':1,'size':'square'}
        with patch.object(resource, 'require_spec'), patch.object(resource.provider, 'text_to_image') as paid:
            with self.assertRaisesRegex(ValueError, '必须升版本'):
                resource.generate('新增资产规格.json', row)
            paid.assert_not_called()
        self.assertEqual(out.read_bytes(), b'existing')

    def test_rejected_frame_cannot_repeat_original_paid_request(self):
        resource.write(self.root/'视觉检查.json', {'shots':[{'id':'EP001_SH03','status':'rejected'}]})
        with patch.object(resource, 'require_spec'), patch.object(resource.provider, 'edit_image') as paid:
            with self.assertRaisesRegex(ValueError, '须使用已独立评级'):
                resource.generate('出图任务.json', {'id':'EP001_SH03'})
            paid.assert_not_called()

if __name__ == '__main__':
    unittest.main()
