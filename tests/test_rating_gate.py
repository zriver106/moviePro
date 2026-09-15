import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import rating_gate


class RatingGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.p = self.root / 'projects/demo'
        self.policy = {'minimum_grade':'S', 'review_thread_id':'reviewer',
                       'episodes':{'EP001':{'target_seconds':60,'tolerance_seconds':0.1}}}
        self.write('评审/评级规则.json', self.policy)
        self.write('剧本/EP001.md', '本版剧本')
        self.write('分镜/EP001_中文.md', '本版中文分镜')
        self.board = {'target_seconds':60,'shots':[{'id':'EP001_SH01','seconds':60,'lines':[]}]}
        self.write('分镜/EP001.json', self.board)
        self.manifest = {'EP001':{f:rating_gate.sha(self.p/f) for f in
                                 ['剧本/EP001.md','分镜/EP001.json','分镜/EP001_中文.md']}}
        self.write('评审/清单.json', self.manifest)
        self.write('评审/回复.json', {'message':'外评本版S/S，文本通过'})
        self.record = {'status':'passed','policy_sha256':rating_gate.sha(self.p/'评审/评级规则.json'),
                       'external_review':{'thread_id':'reviewer','message_id':'real-reply',
                                          'evidence_path':'评审/回复.json','evidence_sha256':rating_gate.sha(self.p/'评审/回复.json'),
                                          'manifest_path':'评审/清单.json','manifest_sha256':rating_gate.sha(self.p/'评审/清单.json')},
                       'episodes':{'EP001':{'script_grade':'S','storyboard_grade':'S','blocking_issues':[]}}}
        self.save_record()

    def write(self, rel, value):
        f = self.p/rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))

    def save_record(self):
        self.write('评审/当前评级.json', self.record)

    def check(self, eps=None):
        return rating_gate.check('demo', eps, root=self.root)

    def test_current_matching_pass(self):
        self.assertEqual(self.check(), [])

    def test_low_grade_cannot_average_with_s_plus(self):
        self.record['episodes']['EP001'].update(script_grade='S+', storyboard_grade='A+')
        self.save_record()
        self.assertTrue(any('storyboard_grade' in s for s in self.check()))

    def test_each_source_edit_invalidates_rating(self):
        for rel in self.manifest['EP001']:
            with self.subTest(rel=rel):
                original = (self.p/rel).read_text()
                self.write(rel, original+'\n')
                self.assertTrue(any('过期' in s for s in self.check()))
                self.write(rel, original)

    def test_blockers_even_with_s_are_rejected(self):
        self.record['episodes']['EP001']['blocking_issues']=['夺刀交接缺一步']
        self.save_record()
        self.assertTrue(any('阻断' in s for s in self.check()))

    def test_missing_evidence_is_rejected(self):
        (self.p/'评审/回复.json').unlink()
        self.assertTrue(self.check())

    def test_evidence_mutation_is_rejected(self):
        self.write('评审/回复.json', {'message':'改成通过'})
        self.assertTrue(any('证据指纹' in s for s in self.check()))

    def test_empty_and_unreviewed_scope_are_rejected(self):
        self.assertTrue(self.check([]))
        self.assertTrue(self.check([2]))

    def test_bad_dimension_is_not_hidden_by_overall_grade(self):
        self.record['episodes']['EP001']['dimensions']={'动作连续性':'A'}
        self.save_record()
        self.assertTrue(any('平均抵消' in s for s in self.check()))

    def test_126_seconds_cannot_pass_60_second_policy(self):
        b = copy.deepcopy(self.board)
        b['shots'][0]['seconds'] = 126.7
        self.write('分镜/EP001.json',b)
        self.assertTrue(any('126.7s' in s for s in self.check()))

    def test_changed_policy_requires_review(self):
        self.policy['episodes']['EP001']['target_seconds'] = 126.7
        self.write('评审/评级规则.json',self.policy)
        self.assertTrue(any('规则已改变' in s for s in self.check()))

    def test_empty_shots_and_nonfinite_duration_fail_closed(self):
        for shots in [[],[{'id':'x','seconds':float('nan')}]]:
            self.write('分镜/EP001.json',{'target_seconds':60,'shots':shots})
            self.assertTrue(any('结构错误' in s for s in self.check()))

    def test_paid_entrypoints_block_before_loading_assets(self):
        root=Path(__file__).resolve().parents[1]
        for script in ['gen_asset','gen_kf','gen_kf_chain','gen_whitemodel']:
            with self.subTest(script=script):
                r=subprocess.run([sys.executable,str(root/'scripts'/f'{script}.py'),'--project','__missing_rating_test__'],capture_output=True,text=True)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('评级门禁拦下',r.stdout+r.stderr)

    def test_force_and_retired_generation_cannot_run(self):
        root=Path(__file__).resolve().parents[1]
        for args,expected in [(['script_lock.py','--project','demo','--lock','--force'],'--force已停用'),
                              (['yichun_prepro.py','assets'],'历史版出图入口已关闭')]:
            r=subprocess.run([sys.executable,str(root/'scripts'/args[0]),*args[1:]],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            self.assertIn(expected,r.stdout+r.stderr)


if __name__ == '__main__':
    unittest.main()
