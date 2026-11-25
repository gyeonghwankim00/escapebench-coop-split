"""CPU-only known-answer replay and optional local tokenizer preflight; no weights loaded."""
import argparse
from collections import deque
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile

from scripts.adaptive_escape import AdaptiveSolo
from scripts.cohort_policy import load_policy
from scripts.split_metrics import reference

ROOT = Path(__file__).resolve().parents[1]
KNOWN_UNREACHABLE = {'game2-3-easy': [('shelf above food preparation area close-up',
                                     'click(left door of the shelf above food preparation area)')]}


def replay_solo(game, on_prompt=None):
    """Replay reference actions with legal moves; never used by model experiments."""
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        agent = AdaptiveSolo(game, tmp, None, max_steps=600)
        plan = deque(reference(game))
        agent.replay_skipped = []

        def call(step, messages):
            if on_prompt is not None:
                on_prompt(step, messages, agent)
            while plan:
                target = plan[0]['position'].split(' -> ')[-1]
                role = 'A' if target in agent.role_scenes['A'] else 'B'
                if agent.where[role] == target:
                    action = plan.popleft()['action_answer']
                    break
                queue = deque([(agent.where[role], [])])
                seen = {agent.where[role]}
                route = None
                while queue:
                    node, path = queue.popleft()
                    if node == target:
                        route = path
                        break
                    for label, dest in agent.role_relations(role, node).items():
                        if dest not in seen and (agent.graph.scenes[dest].visible or dest == agent.role_starts.get(role)):
                            seen.add(dest)
                            queue.append((dest, path + [label]))
                if route:
                    action = 'move(' + route[0] + ')'
                    break
                # Do not teleport to a reference scene. Record omitted reference steps
                # explicitly; escape after skipping them does not prove full coverage.
                omitted = plan.popleft()
                agent.replay_skipped.append(dict(scene=target, action=omitted['action_answer'],
                                                reason='no legal route at this state'))
            else:
                raise AssertionError(f'{game}: reference exhausted before escape')
            return dict(raw=f'Thought: replay\nRole: {role}\nAction: {action}', messages=messages)

        agent.model_call = call
        iterator = agent.iterate('protocol-check', game)
        try:
            while True:
                next(iterator)
        except StopIteration as final:
            escaped = final.value[0]
    return agent, escaped


def check(tokenizer=None, context_tokens=8192):
    policy, metadata = load_policy()
    games = []
    for game, classification in policy['games'].items():
        if classification['tier'] == 'excluded':
            continue
        stats = dict(game=game, max_prompt_chars=0, max_input_tokens=None,
                     peak_discoveries_omitted=dict(A=0, B=0), reveal_prompts=0)

        def observe(step, messages, agent):
            stats['max_prompt_chars'] = max(stats['max_prompt_chars'], sum(len(m['content']) for m in messages))
            for role in 'AB':
                stats['peak_discoveries_omitted'][role] = max(stats['peak_discoveries_omitted'][role], agent.memory_selection[role]['discoveries']['omitted'])
            if game == 'game2-2-easy' and any(e['action'] == 'apply(entrance guard card, drawer)' for e in agent.discoveries['B']):
                assert '"1040"' in messages[-1]['content'], 'One-time reveal lost'
                stats['reveal_prompts'] += 1
            if tokenizer is not None:
                text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
                size = len(tokenizer(text, add_special_tokens=False).input_ids)
                stats['max_input_tokens'] = max(stats['max_input_tokens'] or 0, size)

        agent, escaped = replay_solo(game, observe)
        stats.update(escaped=escaped, decisions=len(agent.history), environment_actions=agent.cost,
                     skipped_reference_actions=agent.replay_skipped,
                     invalid_actions=sum(r['response'].startswith(('Error', 'Nothing happens')) for r in agent.history))
        stats['expected_skips_only'] = [(r['scene'], r['action']) for r in agent.replay_skipped] == KNOWN_UNREACHABLE.get(game, [])
        stats['context_ok'] = None if tokenizer is None else stats['max_input_tokens'] + 256 <= context_tokens
        games.append(stats)
    return dict(passed=all(g['escaped'] and not g['invalid_actions'] and g['expected_skips_only'] and g['context_ok'] is not False for g in games),
                scope='Known-answer Solo reference replay; not an exhaustive prompt bound or model performance test',
                classification=metadata, context_tokens=context_tokens, reserved_output_tokens=256,
                tokenizer_checked=tokenizer is not None, games=games,
                code_hashes={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                             ('scripts/adaptive_escape.py', 'scripts/check_protocol.py')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer', type=Path, help='Existing local model directory; offline tokenizer only')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--context-tokens', type=int, default=8192)
    args = parser.parse_args()
    tokenizer = None
    if args.tokenizer:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer.resolve()), local_files_only=True)
    result = check(tokenizer, args.context_tokens)
    result['tokenizer_path'] = str(args.tokenizer.resolve()) if args.tokenizer else None
    result['tokenizer_hashes'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in args.tokenizer.glob('*') if p.is_file() and
                                (p.name.startswith(('tokenizer', 'special_tokens', 'vocab', 'merges', 'added_tokens')) or p.name == 'chat_template.jinja')} if args.tokenizer else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(f"Protocol check: {'PASS' if result['passed'] else 'FAIL'}; {len(result['games'])} games; tokenizer={result['tokenizer_checked']}; {args.output}")
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
