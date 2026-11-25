import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
from scripts import run_nightly as nightly
from scripts.download_32b import download
from scripts.download_phi import REPO, REVISION

ROOT = Path(__file__).resolve().parents[1]


class NightlyTests(unittest.TestCase):
    def test_balanced_48_episodes_and_identical_settings(self):
        self.assertEqual(len(nightly.TASKS), 48)
        self.assertEqual(len(set(nightly.TASKS)), 48)
        for key in nightly.MODELS:
            for condition in ('solo', 'coop'):
                self.assertEqual(sum(m == key and c == condition for m,c,g in nightly.TASKS),12)
            for index in range(24):
                cmd = nightly.command(key,index,Path('/tmp/out'))
                for flag,value in [('--max-steps','500'),('--max-batch','1'),('--interface','original'),('--context-tokens','8192')]:
                    self.assertEqual(cmd[cmd.index(flag)+1],value)
                self.assertEqual(Path(cmd[cmd.index('--model')+1]).name,nightly.MODELS[key])

    def test_phi_download_pin_and_stable_marker(self):
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.download_32b.shutil.disk_usage') as usage:
            usage.return_value.free = 100*1024**3
            target=Path(tmp)
            def fetch(**kw):
                self.assertEqual(kw['repo_id'],REPO)
                self.assertEqual(kw['revision'],REVISION)
                (target/'config.json').write_text('{}')
            download(target,{'config.json':2},fetch,repo=REPO,revision=REVISION)
            marker=target/'.escape-download.json'; stamp=marker.stat().st_mtime_ns
            download(target,{'config.json':2},lambda **_: self.fail('already downloaded'),repo=REPO,revision=REVISION)
            self.assertEqual(stamp,marker.stat().st_mtime_ns)
            with self.assertRaisesRegex(ValueError,'Different model'):
                download(target,{'config.json':2},fetch,repo=REPO,revision='wrong')

    def test_submission_dependency_and_model_order(self):
        run=subprocess.run(['bash','server/submit-nightly.sh','--dry-run'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('afterok:DRYRUN',run.stderr)
        self.assertIn('--kill-on-invalid-dep=yes',run.stderr)
        self.assertEqual(sum(line.startswith('sbatch ') for line in run.stderr.splitlines()),3)
        for script in ['server/nightly.sbatch','server/phi-prepare.sbatch']:
            self.assertIn('#SBATCH --gres=gpu:1',(ROOT/script).read_text())
        self.assertIn('#SBATCH --array=0-23%1',(ROOT/'server/nightly.sbatch').read_text())

    def test_missing_results_are_reported_not_scored(self):
        with tempfile.TemporaryDirectory() as tmp, patch('builtins.print'):
            from scripts.run_cohort import report
            report(Path(tmp),tasks=nightly.TASKS,max_steps=500,prefix=nightly.PREFIX,
                   model_names=nightly.MODELS,budgets=(50,200,500))
            rows=json.loads((Path(tmp)/'cohort-results.json').read_text())
            self.assertEqual(len(rows),48)
            self.assertTrue(all(r['state']==('excluded' if r['game']=='game1-4-easy' else 'missing') and r['budgets']['500'] is None for r in rows))
            self.assertEqual(sum(r['state']=='excluded' for r in rows),4)


class PhiGateTests(unittest.TestCase):
    def make_run(self, folder, bad_role=None, bad_audit=False):
        from scripts.greedy_generation import POLICY, GENERATION_VERSION
        from scripts.run_matrix import PROTOCOL
        manifest = dict(protocol=PROTOCOL,dry_run=False,generation_version=GENERATION_VERSION,
                        conditions=['solo','coop'],games=['one','two'],settings=dict(max_steps=70))
        (folder/'experiment.json').write_text(json.dumps(manifest))
        (folder/'timing.jsonl').write_text('{}\n')
        for condition in manifest['conditions']:
            for game in manifest['games']:
                path=folder/condition/game; path.mkdir(parents=True)
                (path/'summary.json').write_text(json.dumps(dict(stop_reason='step_budget',steps=70)))
                (path/'collaboration.json').write_text('{}')
                rows=[]
                for i in range(70):
                    actor='AB'[i%2]
                    audit=dict(version=GENERATION_VERSION, mode='greedy_search',use_model_defaults=False,config=POLICY)
                    if bad_audit: audit['mode']='sample'
                    rows.append(dict(role=actor,evaluation={},generation=dict(effective_generation=audit,output_limit_hit=False),
                        upstream=dict(action_answer='No action' if condition=='coop' and actor==bad_role else 'click(door)')))
                (path/'turns.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def test_valid_pipeline_passes_without_task_success(self):
        from scripts.check_matrix_smoke import check
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.make_run(folder)
            self.assertTrue(check(folder,require_action_output=True)['passed'])

    def test_missing_b_action_blocks_release(self):
        from scripts.check_matrix_smoke import check
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.make_run(folder,bad_role='B')
            with self.assertRaisesRegex(ValueError,'no complete parsed action'):
                check(folder,require_action_output=True)
            self.assertFalse((folder/'smoke-check.json').exists())

    def test_sampling_blocks_release(self):
        from scripts.check_matrix_smoke import check
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.make_run(folder,bad_audit=True)
            with self.assertRaisesRegex(ValueError,'generation audit'):
                check(folder,require_action_output=True)


if __name__ == '__main__':
    unittest.main()
