"""One supervised command; output goes to journal, result ACK belongs to PG."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from .layout import roots, work, environment


def main():
    raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not raw or len(raw) > 1024 * 1024:
        raise ValueError('bounded one-line command header required')
    request = json.loads(raw)
    if not os.environ.get('INVOCATION_ID'):
        raise ValueError('supervised compute unit required')
    if socket.gethostname() != request['host']:
        raise ValueError('unexpected execution host')
    project, task, device = request['project'], request['task'], request['device']
    paths = roots(device)
    cwd = work(project, task, device=device)
    cwd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **environment(project, task, device=device))
    Path(env['TMPDIR']).mkdir(exist_ok=True)
    script = Path(request['script']).resolve()
    if not script.is_relative_to(paths['workspace'] / project):
        raise ValueError('application code outside its project workspace')
    for value in request['asset_paths']:
        asset = Path(value).resolve()
        if not any(asset.is_relative_to(root) for root in paths.values()):
            raise ValueError('asset outside declared workspace/model/data roots')
    print(json.dumps(dict(op='ready', host=socket.gethostname(), pid=os.getpid(),
                          unit=request['unit'], invocation=os.environ['INVOCATION_ID'],
                          cwd=str(cwd), roots={k: str(v) for k, v in paths.items()})), flush=True)
    outcome = subprocess.run([request['python'], str(script), *request['args']],
                             cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=sys.stderr, stderr=sys.stderr, timeout=request['remaining_seconds'])
    print(json.dumps(dict(op='finished', returncode=outcome.returncode)), flush=True)
    return outcome.returncode
