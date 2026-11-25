"""Adapter around the pinned, byte-unmodified EscapeBench BaseAgent and engine.

Only I/O, model transport, and a yield at each completed step are adapted.
The original prompt builder, parser, engine, progress, and helper policy execute
directly from the vendored source. No credentials or upstream call_LLM stub run.
"""
import ast
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor/escapebench'


def verify_upstream():
    manifest = json.loads((UPSTREAM/'UPSTREAM.json').read_text())
    for name, expected in manifest['files'].items():
        if hashlib.sha256((UPSTREAM/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Upstream snapshot changed: {name}')
    return manifest


verify_upstream()
sys.path.insert(0, str(UPSTREAM/'src'))
env = importlib.import_module('env')
Graph = importlib.import_module('env.graph').Graph
gv = importlib.import_module('env.global_vars')
instruction = importlib.import_module('instruction')
SYS_PROMPT = instruction.BASE_SYS_PROMPT
SYS_PROMPT_COT = instruction.BASE_SYS_PROMPT_COT
HELPER_PROMPT = instruction.HELPER_PROMPT
# Terminal color is irrelevant to evaluation; do not require cprint.
cprint = SimpleNamespace(**{name: lambda *a, **kw: None for name in ('ok', 'info', 'warn', 'err')})


def load_definitions(path, names):
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise ValueError(f'Missing upstream definitions: {names}')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), globals())
    return selected


# These exact helpers are used by BaseAgent. Avoid module-level OpenAI/secret.json
# setup and the unconditional return "click(door)" in the upstream transport.
load_definitions(UPSTREAM/'src/utils.py', ['read_jsonl_multiline', 'find_last_function_call', 'count_gobal'])
original_class = load_definitions(UPSTREAM/'src/agent_base.py', ['BaseAgent'])[0]
original_run = next(n for n in original_class.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
iter_run = deepcopy(original_run)
iter_run.name = 'iterate'
loops = [n for n in iter_run.body if isinstance(n, ast.For)]
assert len(loops) == 1
# The original loop body is unchanged, including order and off-by-one semantics
# of the 50-step stagnation test. A yield only exposes a completed step for saving.
loops[0].body.append(ast.Expr(value=ast.Yield(value=ast.Constant(None))))
ast.fix_missing_locations(iter_run)
exec(compile(ast.Module(body=[iter_run], type_ignores=[]), '<upstream run + step yield>', 'exec'), globals())


class Agent(BaseAgent):
    iterate = iterate

    def __init__(self, game, scratch, model_call, max_steps=4000):
        args = SimpleNamespace(max_steps=max_steps, memory=10, use_cot=True, stuck_steps=50,
                               stuck_behavior='help', is_api=False, port='unused', overwrite=False,
                               output_suffix='original')
        super().__init__(args)
        self.game = game
        self.scratch = Path(scratch)
        self.model_call = model_call
        self.pending_generation = None
        self.help_before = False
        self.forced_before = False
        self.first_hint_progress = None

    def setup(self, controller, game_name):
        # Same initialization as upstream, but explicit paths and no rmtree.
        game_path = UPSTREAM/'data'/f'{game_name}.yaml'
        self.graph = Graph(str(game_path), use_index=False)
        self.controller = controller
        self.history = []
        self.scene_stack = []
        self.stuck = False
        self.stuck_in_help = 0
        self.helper = read_jsonl_multiline(str(UPSTREAM/'data/reference'/
            f'key_log_{game_name.replace("-easy", "").replace("-hard", "").replace("game", "")}.txt'))
        self.help_cnt = 0
        gv.reset_global_vars()
        self.key_step_num, self.tool_num = count_gobal(str(game_path))
        self.output_dir = str(self.scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        (self.scratch/'progress.csv').write_text('step\tckpts\ttools\tprogress\thelp\n')
        self.setup_done = True

    def act(self, step):
        global call_LLM
        self.pending_generation = None
        self.help_before = self.stuck
        self.forced_before = self.stuck and self.stuck_in_help + 1 >= 10
        if self.stuck and self.first_hint_progress is None:
            self.first_hint_progress = self.history[-1]['tracking']['progress']
        def transport(model, system, user, *unused):
            self.pending_generation = self.model_call(step, [{'role': 'system', 'content': system},
                                                            {'role': 'user', 'content': user}])
            return self.pending_generation['raw']
        call_LLM = transport
        return super().act(step)

    def record(self):
        return deepcopy(dict(upstream=self.history[-1], generation=self.pending_generation,
                             helper_active=self.help_before, forced_action=self.forced_before,
                             hints_used=self.help_cnt, first_hint_progress=self.first_hint_progress))


def initial_messages(game):
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        captured = []
        def collect(step, messages):
            captured.extend(messages)
            return {'raw': 'Thought: Preview only.\nAction: click(nonexistent)'}
        agent = Agent(game, scratch, collect)
        agent.setup('preview', game)
        agent.act(0)
        return captured
