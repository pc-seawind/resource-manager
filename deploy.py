#!/usr/bin/env python3
"""部署独立仓库、构建runtime、安装bin并将真实读回保存到现有PG。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

from psycopg.types.json import Jsonb
from owned_compute.database import Store
from owned_compute.transport import argv

ROOT = Path(__file__).resolve().parent
DSN = 'dbname=visual_memory_v2 user=emox host=/var/run/postgresql'
INSTALL = r'''
import json,pathlib,subprocess,sys,socket
device,revision=sys.argv[1:]
workspace='sry/projects' if device in ('single5090','dual5090') else 'work/projects'
root=pathlib.Path.home()/workspace/'resource-manager'
root.mkdir(parents=True,exist_ok=True)
def run(args,**kw):return subprocess.run(args,cwd=root,check=True,capture_output=True,text=True,timeout=120,**kw).stdout
if not (root/'.git').exists():run(['git','init','-b','main'])
if run(['git','status','--porcelain']).strip():raise ValueError('existing remote working tree is not clean')
bundle=root/'.git/deploy.bundle';bundle.write_bytes(sys.stdin.buffer.read())
try:run(['git','fetch',str(bundle),'main'])
finally:bundle.unlink()
head=subprocess.run(['git','rev-parse','--verify','HEAD'],cwd=root,capture_output=True,text=True,timeout=10)
if head.returncode==0:
 old=head.stdout.strip()
 if subprocess.run(['git','merge-base','--is-ancestor',old,revision],cwd=root,timeout=10).returncode:raise ValueError('refuse downgrade or unrelated deployment')
run(['git','checkout','--detach',revision])
if not (root/'.venv/bin/python').exists():run(['/usr/bin/python3.12','-m','venv',str(root/'.venv')])
python=str(root/'.venv/bin/python')
run([python,'-m','pip','install','--no-cache-dir','-r','requirements.txt'])
artifact=run([python,'build.py','--install']).strip()
link=pathlib.Path.home()/'.local/bin/resource-manager'
version=json.loads(run([str(link),'version']))
if version['source_commit']!=revision or str(link.resolve())!=artifact:raise ValueError('installed bin/runtime differs from source commit')
paths=json.loads(run([str(link),'paths','--device',device]))
print(json.dumps(dict(physical_host=socket.gethostname(),source_path=str(root),source_commit=revision,
 runtime_path=artifact,bin_path=str(link),roots=paths,version=version,source_git_managed=True)))
'''


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--host',action='append',choices=('office','single5090','dual5090'),required=True)
    args=parser.parse_args()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise ValueError('commit source before deployment')
    store=Store(DSN);store.install()
    def deploy(host,payload):
        p=subprocess.run(argv(host,['/usr/bin/python3.12','-c',INSTALL,host,revision]),input=payload,
                         capture_output=True,check=True,timeout=300)
        value=json.loads(p.stdout)
        if value['source_commit']!=revision:raise ValueError('deployment returned another source commit')
        with store.db() as db:
            db.execute('''INSERT INTO compute_runtime_installations
                (host,physical_host,source_path,source_commit,runtime_path,bin_path,proof)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(host) DO UPDATE SET
                physical_host=excluded.physical_host,source_path=excluded.source_path,source_commit=excluded.source_commit,
                runtime_path=excluded.runtime_path,bin_path=excluded.bin_path,proof=excluded.proof,installed_at=now()''',
                (host,value['physical_host'],value['source_path'],revision,value['runtime_path'],value['bin_path'],Jsonb(value)))
        print(json.dumps(dict(host=host,**value)),flush=True)
    with tempfile.TemporaryDirectory(prefix='deploy-',dir=ROOT/'dist') as folder:
        bundle=Path(folder)/'source.bundle'
        subprocess.run(['git','bundle','create',str(bundle),'main'],cwd=ROOT,check=True,timeout=30)
        payload=bundle.read_bytes()
        with ThreadPoolExecutor(max_workers=len(args.host)) as pool:
            for result in pool.map(lambda host:deploy(host,payload),args.host):pass


if __name__=='__main__':main()
