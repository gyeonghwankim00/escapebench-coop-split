"""Pinned official weights; personal storage first, own lab subdir only on space/quota failure."""
import argparse
import errno
import fnmatch
import json
import os
from pathlib import Path
import pwd
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = 'Qwen/Qwen3-32B'
REVISION = '9216db5781bf21249d130ec9da846c4624c16137'
PATTERNS = ['*.json', '*.safetensors', '*.txt', '*.model', '*.jinja']


def storage_error(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, 'errno', None) in (errno.ENOSPC, errno.EDQUOT): return True
        if any(s in str(exc).lower() for s in ('no space left on device', 'disk quota exceeded')): return True
        exc = exc.__cause__ or exc.__context__
    return False


def download(target, files, fetch, *, repo=REPO, revision=REVISION):
    target.mkdir(parents=True, exist_ok=True)
    marker = target/'.escape-download.json'
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous['repo'] != repo or previous['revision'] != revision:
            raise ValueError(f'Different model/revision already recorded at {target}')
    pending = [name for name, size in files.items()
               if not (target/name).is_file() or (target/name).stat().st_size != size]
    missing = sum(files[name] for name in pending)
    # Filesystem free space is NOT a measurement of personal quota.
    free = shutil.disk_usage(target).free
    if pending and free < missing + 5 * 1024**3:
        raise OSError(errno.ENOSPC, f'Filesystem free={free}; remaining download={missing}, plus 5 GiB reserve')
    print(f'Download {repo}@{revision} -> {target}; reusing {len(files)-len(pending)}/{len(files)} '
          f'complete files; pending file sizes {missing/1e9:.1f} GB; quota unknown', file=sys.stderr, flush=True)
    # Keep local_dir/.cache: the Hub downloader can resume incomplete shards there.
    # Complete files from this pinned download do not need to be fetched again.
    if pending:
        fetch(repo_id=repo, revision=revision, local_dir=str(target),
              allow_patterns=pending, max_workers=1)
    for name, size in files.items():
        if not (target/name).is_file() or (target/name).stat().st_size != size:
            raise ValueError(f'Incomplete model file: {name}')
    metadata = json.dumps(dict(repo=repo, revision=revision, files=files), indent=2)+'\n'
    if not marker.exists() or marker.read_text() != metadata:
        marker.write_text(metadata)  # keep model identity stable across repeated preparation
    return target


def shared_target():
    lab = Path('/shared/s2/lab04')
    if not lab.is_dir() or not os.access(lab, os.W_OK | os.X_OK):
        raise RuntimeError('lab04 is not writable')
    return lab/pwd.getpwuid(os.getuid()).pw_name/'escape-lab/models/Qwen3-32B'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', choices=('auto', 'shared'), default='auto',
                        help='shared resumes directly in your lab folder without writing personal storage')
    args = parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Run inside a Slurm allocation (GSDS manual).')
    from huggingface_hub import HfApi, snapshot_download
    info = HfApi().model_info(REPO, revision=REVISION, files_metadata=True)
    files = {f.rfilename: f.size for f in info.siblings if any(fnmatch.fnmatch(f.rfilename,p) for p in PATTERNS)}
    if not files or any(size is None for size in files.values()):
        raise RuntimeError('Cannot verify expected model file sizes')
    personal = ROOT/'models/Qwen3-32B'
    if args.storage == 'shared':
        target = download(shared_target(), files, snapshot_download)
        print(target.resolve())
        return
    try:
        target = download(personal, files, snapshot_download)
    except Exception as exc:
        if not storage_error(exc): raise
        target = shared_target()
        print(f'Confirmed storage exhaustion: {exc}. Falling back to {target}. '
              f'Partial personal files at {personal} are retained, not deleted.', file=sys.stderr, flush=True)
        target = download(target, files, snapshot_download)
    # Only the selected path goes to stdout, for the batch script to capture.
    print(target.resolve())


if __name__ == '__main__':
    main()
