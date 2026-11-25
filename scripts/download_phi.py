"""Download the pinned official Phi-4 snapshot directly into personal lab storage."""
import fnmatch
import os
import sys
import time
from scripts.download_32b import download, shared_target, PATTERNS
from scripts.download_32b import storage_error

REPO = 'microsoft/phi-4'
REVISION = '2db69c1c3e91a05d2c64a3185acfbaf36f744e25'


def retryable(exc):
    from requests.exceptions import ConnectionError, Timeout, ChunkedEncodingError, HTTPError
    if storage_error(exc):
        return False
    if isinstance(exc, HTTPError):
        response = exc.response
        return response is not None and (response.status_code == 429 or 500 <= response.status_code < 600)
    return isinstance(exc, (ConnectionError, Timeout, ChunkedEncodingError))


def network_retry(operation, sleep=time.sleep):
    for attempt in range(4):
        try:
            return operation()
        except Exception as exc:
            if attempt == 3 or not retryable(exc):
                raise
            delay = (5, 15, 30)[attempt]
            print(f'Transient download error ({type(exc).__name__}); retry {attempt+2}/4 '
                  f'in {delay}s; existing files/cache retained.', file=sys.stderr, flush=True)
            sleep(delay)


def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Download inside a Slurm allocation')
    from huggingface_hub import HfApi, snapshot_download
    info = network_retry(lambda: HfApi().model_info(REPO, revision=REVISION, files_metadata=True))
    files = {f.rfilename: f.size for f in info.siblings
             if any(fnmatch.fnmatch(f.rfilename, p) for p in PATTERNS)}
    if not files or any(s is None for s in files.values()):
        raise RuntimeError('Cannot verify snapshot sizes')
    target = shared_target().parent/'phi-4'
    result = network_retry(lambda: download(target, files, snapshot_download, repo=REPO, revision=REVISION))
    print(result.resolve())


if __name__ == '__main__':
    main()
