"""项目无关的已拥有设备资源入口；应用通过stdin提交冻结请求。"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
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
    p.add_argument('--dsn')
    p.add_argument('--schema')
    p.add_argument('--node-config', type=Path)
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('version')
    paths = commands.add_parser('paths'); paths.add_argument('--device', choices=DEVICES, required=True)
    commands.add_parser('install-db')
    node_install = commands.add_parser('node-install')
    node_install.add_argument('--node-id', required=True)
    node_install.add_argument('--host', default=socket.gethostname())
    node_install.add_argument('--device', choices=tuple(k for k in DEVICES if k != 'local'), required=True)
    commands.add_parser('node-status')
    activate = commands.add_parser('node-activate')
    activate.add_argument('--node-id', required=True)
    activate.add_argument('--fence-id', required=True)
    fence = commands.add_parser('fence-host')
    fence.add_argument('--host', required=True)
    fence.add_argument('--node-id', required=True)
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
        device = args.device
        config_path = args.node_config or Path.home()/'.config/resource-manager/node.json'
        if device == 'local' and config_path.exists():
            from .node import load_config
            device = load_config(config_path)['device']
        value = {k: str(v) for k, v in roots(device).items()}
    elif args.command == 'worker':
        from .worker import main as worker
        sys.exit(worker())
    elif args.command == 'retire-work':
        from .cleanup import retire
        value = retire(args.project, args.task, args.device, args.unit)
    else:
        from .database import Store
        from . import node
        config_path = args.node_config or Path.home()/'.config/resource-manager/node.json'
        config = node.load_config(config_path) if args.node_config or config_path.exists() else None
        dsn = args.dsn or (config['dsn'] if config else 'dbname=visual_memory_v2 user=emox host=/var/run/postgresql')
        schema = args.schema or (config['schema'] if config else 'visual_memory_v2')
        store = Store(dsn, schema)
        if args.command == 'install-db':
            store.install()
            value = dict(installed=True, schema=store.schema)
        elif args.command == 'node-install':
            if args.host != socket.gethostname():
                raise ValueError('install node authority on its physical host')
            value = node.install(store, args.node_id, args.host, args.device)
        elif args.command == 'node-status':
            value = node.status(store)
        elif args.command == 'node-activate':
            value = node.activate(store, args.node_id, args.fence_id)
        elif args.command == 'fence-host':
            value = node.fence_host(store, args.host, args.node_id)
        elif args.command == 'run':
            from .execution import run
            request = json.load(sys.stdin)
            if config:
                for candidate in request['candidates']:
                    binding = candidate['binding']
                    if binding['host'] != config['host'] or binding['placement'] != 'local':
                        raise ValueError('submit foreign work to the receiving node manager')
                    binding['device'] = config['device']
            request['deadline'] = datetime.fromisoformat(request['deadline'])
            value = run(store, argv, request, probe)
        else:
            from .execution import reconcile
            value = reconcile(store, argv, args.request_id)
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)
