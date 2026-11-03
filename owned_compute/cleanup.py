"""Remove only the exact supervised task scratch, after physical exit and ACK."""
from pathlib import Path
import re
import shutil
import subprocess

from .layout import work


def retire(project, task, device, unit):
    if not re.fullmatch(r'oc-[a-f0-9]{24}\.service', unit):
        raise ValueError('not an owned compute unit')
    result = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID'],
                            capture_output=True, text=True, check=True, timeout=10)
    state = dict(line.split('=', 1) for line in result.stdout.splitlines())
    if state['ActiveState'] in ('active', 'activating', 'deactivating', 'reloading') or state['MainPID'] != '0':
        raise ValueError('physical owner has not exited')
    path = work(project, task, device=device)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('task workspace is a symlink')
    if path.exists():
        shutil.rmtree(path)
    return dict(retired=True, path=str(path), unit=unit)
