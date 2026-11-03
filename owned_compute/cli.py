"""项目无关的已拥有设备资源入口；应用通过stdin提交冻结请求。"""
import argparse
from datetime import datetime
import json
import subprocess
import sys

from .layout import DEVICES, roots
from .transport import argv


def probe(binding):
    if binding.get('gpu') is not None:
        raise ValueError('GPU jobs require their admitted model driver')
    code = "import json,os,socket,pathlib;m={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines()};print(json.dumps(dict(host=socket.gethostname(),cpu=os.cpu_count(),free_mib=m['MemAvailable']//1024)))"
    result = subprocess.run(argv(binding['placement'], ['python3', '-c', code]),
                            capture_output=True, text=True, check=True, timeout=20)
    observed = json.loads(result.stdout)
    if observed['host'] != binding['host']:
        raise ValueError('CPU resource host differs')
    return dict(available=observed['free_mib'] >= binding['memory_mib'] and observed['cpu'] >= binding['cpu_cores'],
                free_mib=observed['free_mib'])


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--dsn', default='dbname=visual_memory_v2 user=emox host=/var/run/postgresql')
    p.add_argument('--schema', default='visual_memory_v2')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('version')
    paths = commands.add_parser('paths'); paths.add_argument('--device', choices=DEVICES, required=True)
    commands.add_parser('install-db')
    commands.add_parser('worker')
    commands.add_parser('run')
    reconcile = commands.add_parser('reconcile'); reconcile.add_argument('request_id')
    cleanup = commands.add_parser('retire-work')
    for key in ('project', 'task', 'unit'):
        cleanup.add_argument('--' + key, required=True)
    cleanup.add_argument('--device', choices=DEVICES, required=True)
    args = p.parse_args()
    if args.command == 'version':
        from ._build import REVISION, PYTHON_TAG
        value = dict(source_commit=REVISION, python_tag=PYTHON_TAG)
    elif args.command == 'paths':
        value = {k: str(v) for k, v in roots(args.device).items()}
    elif args.command == 'worker':
        from .worker import main as worker
        sys.exit(worker())
    elif args.command == 'retire-work':
        from .cleanup import retire
        value = retire(args.project, args.task, args.device, args.unit)
    else:
        from .database import Store
        store = Store(args.dsn, args.schema)
        if args.command == 'install-db':
            store.install()
            value = dict(installed=True, schema=store.schema)
        elif args.command == 'run':
            from .execution import run
            request = json.load(sys.stdin)
            request['deadline'] = datetime.fromisoformat(request['deadline'])
            value = run(store, argv, request, probe)
        else:
            from .execution import reconcile
            value = reconcile(store, argv, args.request_id)
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)
