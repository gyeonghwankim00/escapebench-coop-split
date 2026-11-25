"""Exercise server/setup.sh with fake commands, without GPU or network."""
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
        shutil.copy(ROOT/'server/setup.sh', self.root/'server/setup.sh')
        bin_dir = self.root/'fake-bin'
        bin_dir.mkdir()
        self.write_executable(bin_dir/'nvidia-smi', '#!/bin/bash\nexit 0\n')
        self.write_executable(bin_dir/'conda', '''#!/bin/bash
echo conda >> "$FAKE_LOG"
while [[ "$1" != --prefix ]]; do shift; done
mkdir -p "$2/bin"
cp "$FAKE_PYTHON" "$2/bin/python"
''')
        self.write_executable(bin_dir/'fake-python', '''#!/bin/bash
echo "python $*" >> "$FAKE_LOG"
if [[ "${FAKE_FAIL:-}" = 1 && "$*" = *"pip install torch"* ]]; then exit 1; fi
exit 0
''')
        self.env = dict(os.environ, SLURM_JOB_ID='42', SLURM_SUBMIT_DIR=str(self.root),
                        PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],
                        FAKE_LOG=str(self.root/'calls.log'), FAKE_PYTHON=str(bin_dir/'fake-python'))

    def write_executable(self, path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_setup(self, env=None):
        return subprocess.run(['bash', 'server/setup.sh'], cwd=self.root,
                              env=env or self.env, capture_output=True, text=True)

    def test_first_setup_creates_environment_and_next_reuses_it(self):
        first = self.run_setup()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((self.root/'.conda-env/.escape-setup-complete').exists())
        second = self.run_setup()
        self.assertEqual(second.returncode, 0, second.stderr)
        calls = (self.root/'calls.log').read_text().splitlines()
        self.assertEqual(calls.count('conda'), 1)

    def test_failed_install_never_marks_environment_complete(self):
        result = self.run_setup(dict(self.env, FAKE_FAIL='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'.conda-env/.escape-setup-complete').exists())


if __name__ == '__main__':
    unittest.main()
