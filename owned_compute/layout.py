"""Owner-specified device roots; no mixed code/model/data execution root."""
from pathlib import Path
import re


DEVICES = {
    'local': ('work/projects', 'work/models', 'work/data'),
    'office': ('work/projects', 'work/models', 'work/data'),
    'wsl': ('work/projects', 'work/models', 'work/data'),
    'single5090': ('sry/projects', 'models', 'sry/data'),
    'dual5090': ('sry/projects', 'models', 'sry/data'),
}


def slug(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}', value):
        raise ValueError('invalid compute namespace')
    return value


def roots(device, home=None):
    home = Path.home() if home is None else Path(home)
    return dict(zip(('workspace', 'models', 'data'), (home / p for p in DEVICES[device]), strict=True))


def code(project, revision, home=None, *, device='local'):
    return roots(device, home)['workspace'] / slug(project) / '.releases' / slug(revision)


def work(project, task, home=None, *, device='local'):
    return roots(device, home)['data'] / slug(project) / 'work' / slug(task)


def receipts(device, home=None):
    return roots(device, home)['data'] / 'resource-manager/state/receipts.sqlite3'


def environment(project, task, home=None, *, device='local'):
    paths = roots(device, home)
    scratch = work(project, task, home, device=device)
    return dict(OWNED_COMPUTE_PROJECT=slug(project), OWNED_COMPUTE_TASK=slug(task),
                OWNED_COMPUTE_DEVICE=device, HF_HOME=str(paths['models'] / 'huggingface'),
                TORCH_HOME=str(paths['models'] / 'torch'),
                XDG_CACHE_HOME=str(scratch / 'cache'), TMPDIR=str(scratch / 'tmp'),
                PYTHONPYCACHEPREFIX=str(scratch / 'cache/python'), PYTHONNOUSERSITE='1')
