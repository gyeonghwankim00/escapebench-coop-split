# Pinned upstream snapshot

Repository: https://github.com/qiancheng0/EscapeBench
Commit: `2d42347446a8e9ed4f058fa415d40afa194166a5` (retrieved 2026-11-13).
`UPSTREAM.json` records SHA-256 for every copied upstream file. Files listed there
are byte-unmodified. Assets were omitted; all 36 game YAMLs, references, source
and launch scripts are included. The source archive has no top-level LICENSE;
no new license is asserted over these upstream files.

The runtime adapter is `scripts/original_escape.py` outside this snapshot.
It compiles the original BaseAgent class and three utility definitions directly
from their source AST; it does not import `utils.py`'s API client/secret.json setup.
The unconditional `return "click(door)"` debug stub in `call_LLM` is bypassed by
an injected HF transport. `instruction.py` and the entire `env` package execute
unchanged. Terminal coloring is replaced by no-op printers.

BaseAgent.setup is adapted for explicit paths and safe output creation. An
`iterate` method is mechanically made from the original run method with ONE
yield appended at the bottom of the outer action loop. No original statement
in that loop is replaced. Original `act`, `take_action`, `add_history`, response
parser, action semantics, progress counting, helper selection, relocation,
history omission while helping, forced answer after helping, and even the
original zero-based stagnation test remain unchanged.

The original Graph engine owns ALL state. The cooperative JSON engine is not
used by the Solo baseline. Tests compare prompts and per-step logs against
stock BaseAgent.run, including the first helper cycle and forced action.

Resumption re-executes the deterministic engine with stored responses. It checks
every reconstructed prompt and step against saved records before any new model
call. No pickle or untrusted executable checkpoint is loaded. Forced actions
are tagged separately and have generation=null; they are never counted as LLM
calls or presented as independent model success.

Hardware adaptation is explicit: HF/SDPA rather than vLLM, one GPU and optional
NF4 rather than the upstream BF16 example. Qwen3 native thinking is disabled;
the upstream short Thought/Action instruction is unchanged. Greedy decoding,
one output, max 256 generated tokens and default 2400 total context follow the
public deployment example. Context overflow is an infrastructure error (saved
checkpoint), never silent truncation. Increasing --context-tokens defines a
different configuration and cannot resume the previous run.
