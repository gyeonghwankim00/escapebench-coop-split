"""Versioned evaluator policy; independent of inference state and resume."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEFAULT_POLICY=ROOT/'data/cohort_policy_v1.json'

def load_policy(path=DEFAULT_POLICY):
    path=Path(path);raw=path.read_bytes();policy=json.loads(raw)
    games=policy['games']
    allowed={'core','extended','negative_control','excluded'}
    if len(games)!=12 or any(g['tier'] not in allowed for g in games.values()):
        raise ValueError('Invalid cohort policy')
    return policy,dict(version=policy['version'],sha256=hashlib.sha256(raw).hexdigest(),path=str(path.resolve()))
