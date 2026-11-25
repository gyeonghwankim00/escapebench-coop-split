"""Download a pinned Qwen3-14B snapshot to the project's personal models directory."""
import os
from pathlib import Path

from huggingface_hub import snapshot_download

from scripts.run_model import ROOT

REPO = 'Qwen/Qwen3-14B'
REVISION = '1ad250734e6f9d33dab640bd4d7af78370042f6a'


def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Submit the download inside a Slurm allocation.')
    target = ROOT / 'models' / 'Qwen3-14B'
    target.mkdir(parents=True, exist_ok=True)
    print(f'Downloading {REPO} revision {REVISION} to {target}', flush=True)
    snapshot_download(repo_id=REPO, revision=REVISION, local_dir=target,
                      allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model', '*.jinja'])
    print('Model download completed.', flush=True)


if __name__ == '__main__':
    main()
