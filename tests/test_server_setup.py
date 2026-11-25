"""Exercise the batch setup flow with fake commands, without GPU or network."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'server').mkdir()
        for name in ('setup.sh', 'solo-sequential.sbatch', 'experiment.sbatch', 'experiment-two-models.sbatch',
                     'original.sbatch', 'run-original.sh'):
            shutil.copy(ROOT/'server'/name, self.root/'server'/name)
        bin_dir = self.root/'fake-bin'
        bin_dir.mkdir()
        self.write_executable(bin_dir/'nvidia-smi', '#!/bin/bash\nexit 0\n')
        self.write_executable(bin_dir/'srun', '#!/bin/bash\nif [[ "$1" = --ntasks=1 ]]; then shift; fi\nexec "$@"\n')
        self.write_executable(bin_dir/'timeout', '#!/bin/bash\nshift\nexec "$@"\n')
        self.write_executable(bin_dir/'conda', '''#!/bin/bash
echo conda >> "$FAKE_LOG"
while [[ "$1" != --prefix ]]; do shift; done
mkdir -p "$2/bin"
cp "$FAKE_PYTHON" "$2/bin/python"
''')
        self.write_executable(bin_dir/'fake-python', '''#!/bin/bash
echo "python $*" >> "$FAKE_LOG"
if [[ "${FAKE_FAIL:-}" = 1 && "$*" = *"pip install torch"* ]]; then exit 1; fi
if [[ "${FAKE_STAGE_FAIL:-}" = 1 && "$*" = *"scripts.run_experiment"* ]]; then exit 1; fi
exit 0
''')
        self.env = dict(os.environ, SLURM_JOB_ID='42', SLURM_SUBMIT_DIR=str(self.root),
                        PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],
                        FAKE_LOG=str(self.root/'calls.log'), FAKE_PYTHON=str(bin_dir/'fake-python'))

    def write_executable(self, path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_batch(self, env=None):
        return subprocess.run(['bash', 'server/solo-sequential.sbatch'], cwd=self.root,
                              env=env or self.env, capture_output=True, text=True)

    def test_first_batch_creates_environment_and_next_reuses_it(self):
        first = self.run_batch()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((self.root/'.conda-env/.escape-setup-complete').exists())
        second = self.run_batch()
        self.assertEqual(second.returncode, 0, second.stderr)
        calls = (self.root/'calls.log').read_text().splitlines()
        self.assertEqual(calls.count('conda'), 1)
        self.assertEqual(sum('scripts.run_solo_suite' in x for x in calls), 2)

    def test_failed_install_never_marks_environment_complete_or_starts_model(self):
        result = self.run_batch(dict(self.env, FAKE_FAIL='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'.conda-env/.escape-setup-complete').exists())
        self.assertNotIn('scripts.run_solo_suite', (self.root/'calls.log').read_text())

    def test_experiment_reuses_environment_and_forwards_model_and_seeds(self):
        self.assertEqual(self.run_batch().returncode, 0)
        result = subprocess.run(['bash', 'server/experiment.sbatch', '--model', '/shared/test-model',
                                 '--seeds', '42', '43'], cwd=self.root, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root/'calls.log').read_text().splitlines()
        self.assertEqual(calls.count('conda'), 1)
        self.assertTrue(any('scripts.run_experiment' in x and '--model /shared/test-model --seeds 42 43' in x
                            for x in calls))

    def test_two_models_run_in_order_and_stop_on_failure(self):
        self.assertEqual(self.run_batch().returncode, 0)
        batch = ['bash', 'server/experiment-two-models.sbatch']
        result = subprocess.run(batch, cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root/'calls.log').read_text().splitlines()
        experiment_calls = [x for x in calls if 'scripts.run_experiment' in x or 'scripts.download_14b' in x]
        self.assertEqual(len(experiment_calls), 3)
        self.assertIn('models/Qwen3-8B', experiment_calls[0])
        self.assertIn('scripts.download_14b', experiment_calls[1])
        self.assertIn('models/Qwen3-14B', experiment_calls[2])
        (self.root/'calls.log').unlink()
        retry = subprocess.run(batch + ['--14b-only'], cwd=self.root, env=self.env,
                               capture_output=True, text=True)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        calls = (self.root/'calls.log').read_text()
        self.assertNotIn('models/Qwen3-8B', calls)
        self.assertIn('scripts.download_14b', calls)
        self.assertIn('models/Qwen3-14B', calls)
        (self.root/'calls.log').unlink()
        result = subprocess.run(batch, cwd=self.root, env=dict(self.env, FAKE_STAGE_FAIL='1'),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('scripts.download_14b', (self.root/'calls.log').read_text())

    def test_original_batch_runs_inference_with_existing_env_and_resume_argument(self):
        self.assertEqual(self.run_batch().returncode, 0)
        result = subprocess.run(['bash', 'server/original.sbatch', '--resume', 'outputs/original-existing'],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root/'calls.log').read_text()
        self.assertIn('scripts.run_original --model', calls)
        self.assertIn('models/Qwen3-14B --resume outputs/original-existing', calls)


if __name__ == '__main__':
    unittest.main()
