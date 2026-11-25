from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from scripts.run_state_probes import probe
from scripts.download_32b import download, storage_error

ROOT = Path(__file__).resolve().parents[1]


class StateProbeTests(unittest.TestCase):
    def case(self, name):
        return json.loads((ROOT/'data/state_probes'/f'{name}.json').read_text())

    def test_same_state_across_interfaces_and_legal_collection(self):
        case = self.case('collect_hammer')
        results, calls = [], []
        for interface in ('original', 'move_labels', 'action_labels'):
            def request(messages):
                calls.append(messages)
                return dict(raw='Action: click(hammer)', messages=messages)
            results.append(probe(case, interface, request))
        self.assertEqual(len(calls), 3)  # no model calls to replay the prefix
        self.assertTrue(all(r['evaluation'] == results[0]['evaluation'] for r in results))
        self.assertTrue(all('hammer' in r['bags']['B'] for r in results))
        self.assertNotIn('Action-format reference', calls[0][-1]['content'])
        self.assertIn('Action-format reference', calls[2][-1]['content'])

    def test_replay_mismatch_is_rejected(self):
        case = self.case('collect_key')
        case['rows'][0]['bags']['A'] = ['invented']
        with self.assertRaisesRegex(ValueError, 'State replay mismatch'):
            probe(case, 'original', lambda _: self.fail('must not call model'))

    def test_recipient_cannot_give_partners_tool(self):
        case = self.case('request_not_give')
        row = probe(case, 'action_labels', lambda m: dict(raw='Action: give(iron hoop)', messages=m))
        self.assertEqual(row['role'], 'A')
        self.assertIn('not a tool in your bag', row['upstream']['response'])


class DownloadTests(unittest.TestCase):
    def test_complete_shards_are_reused_and_partial_cache_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/'complete.safetensors').write_bytes(b'123')
            cache = path/'.cache/huggingface/download'
            cache.mkdir(parents=True)
            (cache/'partial.incomplete').write_bytes(b'12')
            def fetch(**kwargs):
                self.assertEqual(kwargs['allow_patterns'], ['pending.safetensors'])
                self.assertEqual((cache/'partial.incomplete').read_bytes(), b'12')
                (path/'pending.safetensors').write_bytes(b'1234')
            files = {'complete.safetensors': 3, 'pending.safetensors': 4}
            with patch('scripts.download_32b.shutil.disk_usage') as usage:
                usage.return_value.free = 100 * 1024**3
                download(path, files, fetch)
                usage.return_value.free = 1  # no free-space reserve needed to reuse all shards
                download(path, files, lambda **_: self.fail('all files already present'))

    def test_only_confirmed_space_errors_trigger_fallback(self):
        self.assertTrue(storage_error(OSError(errno.EDQUOT, 'quota')))
        outer = RuntimeError('wrapped download failure')
        outer.__cause__ = OSError(errno.ENOSPC, 'full')
        self.assertTrue(storage_error(outer))
        self.assertFalse(storage_error(TimeoutError('network timeout')))
        self.assertFalse(storage_error(PermissionError('permission denied')))

    def test_incomplete_snapshot_rejected_and_pinned_revision_used(self):
        from scripts.download_32b import REVISION
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            def fetch(**kwargs):
                self.assertEqual(kwargs['revision'], REVISION)
                (path/'config.json').write_bytes(b'{}')
            with patch('scripts.download_32b.shutil.disk_usage') as usage:
                usage.return_value.free = 100 * 1024**3
                self.assertEqual(download(path, {'config.json': 2}, fetch), path)
                with self.assertRaisesRegex(ValueError, 'Incomplete model'):
                    download(path, {'config.json': 3}, fetch)

    def test_insufficient_space_prevents_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.download_32b.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(OSError) as error:
                download(Path(tmp), {'file': 10}, lambda **_: self.fail('must not download'))
            self.assertTrue(storage_error(error.exception))


class CleanupTests(unittest.TestCase):
    def run_cleanup(self, home, *args):
        return subprocess.run(['bash', '-s', '--', *args],
            input=(ROOT/'server/cleanup-personal-32b.sh').read_text(), text=True,
            capture_output=True, env={**os.environ, 'HOME': str(home)})

    def test_preview_and_delete_only_personal_32b(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            models = home/'escape-lab/models'
            target = models/'Qwen3-32B'
            target.mkdir(parents=True)
            (target/'.incomplete').write_text('partial')
            (models/'Qwen3-14B').mkdir()
            (home/'shared').mkdir()
            result = self.run_cleanup(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.exists())
            result = self.run_cleanup(home, '--delete')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())
            self.assertTrue((models/'Qwen3-14B').exists())
            self.assertTrue((home/'shared').exists())

    def test_refuse_link_to_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            models = home/'escape-lab/models'
            models.mkdir(parents=True)
            shared = home/'shared'
            shared.mkdir()
            (models/'Qwen3-32B').symlink_to(shared, target_is_directory=True)
            result = self.run_cleanup(home, '--delete')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(shared.exists())


if __name__ == '__main__':
    unittest.main()
