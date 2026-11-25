"""Fail closed before releasing full GPU jobs after a smoke run."""
import argparse
import json
from pathlib import Path

from scripts.greedy_generation import GENERATION_VERSION, POLICY
from scripts.run_matrix import PROTOCOL


def check(run, require_action_output=False):
    run = Path(run)
    m = json.loads((run/'experiment.json').read_text())
    if m.get('protocol') != PROTOCOL:
        raise ValueError('Smoke uses the old Solo definition; rerun with the split controller')
    if m.get('dry_run') or m.get('generation_version') != GENERATION_VERSION:
        raise ValueError('Smoke must be a real run with the current generation version')
    if m['conditions'] != ['solo', 'coop'] or len(m['games']) != 2 or m['settings']['max_steps'] < 70:
        raise ValueError('Smoke requires Solo/Coop, two games, and at least 70 steps')
    calls, episodes = 0, 0
    for condition in m['conditions']:
        for game in m['games']:
            directory = run/condition/game
            summary = json.loads((directory/'summary.json').read_text())
            if summary['stop_reason'] not in ('success', 'step_budget', 'decision_budget'):
                raise ValueError(f'{condition}/{game}: {summary["stop_reason"]}')
            if summary['stop_reason'] == 'step_budget' and summary.get('environment_actions',summary['steps']) < m['settings']['max_steps']:
                raise ValueError(f'{condition}/{game}: incomplete smoke')
            rows = [json.loads(x) for x in (directory/'turns.jsonl').read_text().splitlines()]
            if len(rows) != summary['steps']:
                raise ValueError(f'{condition}/{game}: trace/summary length mismatch')
            generated = [r['generation'] for r in rows if r['generation']]
            if not generated:
                raise ValueError(f'{condition}/{game}: no real generation')
            if require_action_output:
                actors = ('A', 'B') if condition == 'coop' else (None,)
                for actor in actors:
                    if not any(r.get('generation') and not r['generation'].get('output_limit_hit')
                               and r['upstream']['action_answer'] != 'No action'
                               and (actor is None or r.get('role') == actor) for r in rows):
                        raise ValueError(f'{condition}/{game}/{actor}: no complete parsed action')
            for generation in generated:
                audit = generation.get('effective_generation', {})
                if (audit.get('version') != GENERATION_VERSION or audit.get('mode') != 'greedy_search'
                        or audit.get('use_model_defaults') is not False
                        or any(audit.get('config', {}).get(k) != v for k, v in POLICY.items())):
                    raise ValueError(f'{condition}/{game}: missing/incorrect effective generation audit')
            if condition == 'coop':
                if {r['role'] for r in rows[:8]} != {'A', 'B'}:
                    raise ValueError('Both roles must act from the start')
                if not all('evaluation' in r for r in rows):
                    raise ValueError('Missing evaluator telemetry')
                if not (directory/'collaboration.json').exists():
                    raise ValueError('Missing collaboration analysis')
            calls += len(generated)
            episodes += 1
    timing = [json.loads(x) for x in (run/'timing.jsonl').read_text().splitlines()][-1]
    result = dict(passed=True, episodes=episodes, checked_model_calls=calls,
                  generation_version=GENERATION_VERSION, timing=timing,
                  note='Pipeline/decoding check, not task success or a guarantee of 12-hour completion.')
    (run/'smoke-check.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--require-action-output', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.run, args.require_action_output), indent=2))
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(f'Smoke rejected; full jobs must not start: {exc}')


if __name__ == '__main__':
    main()
