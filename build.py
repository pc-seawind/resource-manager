#!/usr/bin/env python3
"""构建独立Python 3.12字节码runtime，并把构建产物链接到用户bin。"""
import argparse
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent


def build(install=False):
    if sys.version_info[:2] != (3, 12):
        raise ValueError('runtime contract requires Python 3.12')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('commit source before building an immutable runtime')
    dest = ROOT / 'dist' / revision / 'resource-manager.pyz'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with tempfile.TemporaryDirectory(prefix='build-', dir=ROOT / 'dist') as scratch:
            scratch = Path(scratch)
            sources = {str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / 'owned_compute').glob('*.py'))}
            sources['owned_compute/_build.py'] = f'REVISION={revision!r}\nPYTHON_TAG={sys.implementation.cache_tag!r}\n'
            sources['__main__.py'] = 'from owned_compute.cli import main\nmain()\n'
            target = scratch / 'resource-manager.pyz'
            # This interpreter is independently installed in this repository, never
            # an application's venv. Remote worker and client use the same runtime.
            target.write_bytes(('#!' + str(Path(sys.executable).absolute()) + '\n').encode())
            with zipfile.ZipFile(target, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, text in sources.items():
                    source = scratch / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text(text)
                    compiled = source.with_suffix('.pyc')
                    py_compile.compile(str(source), cfile=str(compiled), dfile='resource-manager/' + name, doraise=True)
                    archive.write(compiled, name[:-3] + '.pyc')
                archive.write(ROOT / 'owned_compute/schema.sql', 'owned_compute/schema.sql')
            target.chmod(0o755)
            target.replace(dest)
    if install:
        link = Path.home() / '.local/bin/resource-manager'
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() and not link.is_symlink():
            raise ValueError('refuse to overwrite an unrelated existing executable')
        temporary = link.with_name('.resource-manager.installing')
        temporary.symlink_to(dest)
        temporary.replace(link)
    return dest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--install', action='store_true')
    print(build(parser.parse_args().install))
