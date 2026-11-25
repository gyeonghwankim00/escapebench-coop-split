"""Exercise shell submission wiring with fake sbatch, no cluster access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PilotSubmissionTests(unittest.TestCase):
    def run_submit(self, fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'server').mkdir()
            shutil.copy(ROOT/'server/submit-pilot.sh', root/'server/submit-pilot.sh')
            (root/'models/Qwen3-14B').mkdir(parents=True)
            (root/'models/Qwen3-14B/config.json').write_text('{}')
            (root/'.conda-env').mkdir()
            (root/'.conda-env/.escape-setup-complete').touch()
            (root/'bin').mkdir()
            stub = root/'bin/sbatch'
            stub.write_text('#!' + sys.executable + '\n' + '''import os,sys,json
from pathlib import Path
p=Path(os.environ['SUBMISSION_LOG'])
rows=json.loads(p.read_text()) if p.exists() else []
rows.append(dict(args=sys.argv[1:],out=os.environ.get('ESCAPE_OUT')))
p.write_text(json.dumps(rows))
if os.environ.get('FAIL_SUBMIT'): sys.exit(1)
print(str(1000+len(rows))+';cluster')
''')
            stub.chmod(0o755)
            env = dict(os.environ, PATH=str(root/'bin') + ':' + os.environ['PATH'],
                       SUBMISSION_LOG=str(root/'calls.json'))
            env.pop('RUN_TAG', None)
            if fail:
                env['FAIL_SUBMIT'] = '1'
            result = subprocess.run(['bash', str(root/'server/submit-pilot.sh')],
                                    env=env, capture_output=True, text=True)
            return result, json.loads((root/'calls.json').read_text())

    def test_14b_smoke_gates_both_batches_and_exports_unique_paths(self):
        result, calls = self.run_submit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]['args'][-2:], ['server/matrix-smoke.sbatch', '14B'])
        for call in calls[1:]:
            self.assertIn('--dependency=afterok:1001', call['args'])
            self.assertIn('--kill-on-invalid-dep=yes', call['args'])
            self.assertIn('both', call['args'])
        self.assertTrue(calls[1]['out'].endswith('-main'))
        self.assertTrue(calls[2]['out'].endswith('-control'))
        self.assertEqual(calls[1]['args'][-1], '4')
        self.assertEqual(calls[2]['args'][-1], '2')

    def test_failed_smoke_submission_does_not_submit_full_jobs(self):
        result, calls = self.run_submit(fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
