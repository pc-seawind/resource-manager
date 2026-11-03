"""One bounded cross-project command execution, coordinated through shared PG."""
from datetime import datetime,timezone
import json
import selectors
import re
import subprocess
import uuid
from psycopg.types.json import Jsonb

from . import manager
from .layout import slug


def now():return datetime.now(timezone.utc)


def inspect_unit(route,placement,unit,*,stop=False):
    if not re.fullmatch(r'oc-[a-f0-9]{24}\.service',unit):raise ValueError('not an owned compute unit')
    p=subprocess.run(route(placement,['systemctl','--user','show',unit,'-p','ActiveState','-p','MainPID','-p','InvocationID']),
                     check=True,capture_output=True,text=True,timeout=15)
    state=dict(line.split('=',1) for line in p.stdout.splitlines())
    live=state['ActiveState'] in ('active','activating','deactivating','reloading')
    if stop and live:
        subprocess.run(route(placement,['systemctl','--user','stop',unit]),capture_output=True,check=True,timeout=20)
        return inspect_unit(route,placement,unit)
    return dict(exited=not live and state['MainPID']=='0',unit=unit,placement=placement,state=state)


def run(rt,route,request,probe,*,clock=now):
    """`route` is the infrastructure transport; application launch occurs only here."""
    project=slug(request['project']);task=slug(request['task']);key=manager.identifier(project,task)
    with rt.db() as db:
        old=db.execute('SELECT * FROM compute_requests WHERE id=%s',(key,)).fetchone()
    if old and (old['spec']!={k:request[k] for k in ('script','args','asset_paths')} or old['deadline']!=request['deadline'] or old['candidates']!=sorted(request['candidates'],key=lambda c:c['candidate_id'])):
        raise ValueError('immutable application request changed')
    if old and old['state']=='released' and old['result'] is not None:
        result=_cleanup(rt,route,old) if old['result'].get('cleanup_pending') else old['result']
        return dict(reused=True,request_id=key,result=result)
    if old and old['state'] in ('reserved','running'):raise manager.Busy('reconcile original execution; no duplicate launch')
    token=uuid.uuid4().hex
    choices=sorted(request['candidates'],key=lambda c:c['candidate_id'])
    with rt.db() as db:
        manager.enqueue(db,project,task,token,choices,priority=request['priority'],is_retry=False,
            deadline=request['deadline'],stall_seconds=120,spec={k:request[k] for k in ('script','args','asset_paths')},now=clock())
    available=[]
    for candidate in choices:
        state=probe(candidate['binding'])
        if state['available']:available.append(dict(candidate,free_mib=state['free_mib']))
    with rt.db() as db:
        selected=manager.allocate(db,key,token,available,now=clock())
    if selected is None:return dict(request_id=key,state='resource_wait',deadline=request['deadline'].isoformat())
    seconds=int((request['deadline']-clock()).total_seconds())
    if seconds<=0:raise ValueError('physical execution cannot start after deadline')
    unit='oc-'+key[:24]+'.service'
    header=dict(project=project,task=task,host=selected['host'],unit=unit,device=selected['placement'],python=selected['python'],
        script=selected['code']+'/'+request['script'],args=request['args'],asset_paths=request['asset_paths'],remaining_seconds=seconds)
    # Persist the deterministic physical intention before a lost SSH response.
    with rt.db() as db:
        db.execute('UPDATE compute_requests SET receipt=%s WHERE id=%s AND token=%s',
                   (Jsonb(dict(unit=unit,placement=selected['placement'],phase='launch_intent')),key,token))
    command=['systemd-run','--user','--quiet','--collect','--pipe','--wait','--unit='+unit,
        '--property=RuntimeMaxSec='+str(seconds),'--property=TimeoutStopSec=10','--property=KillMode=control-group',
        '--property=MemoryMax='+selected['memory_max'],'--property=CPUQuota='+selected['cpu_quota'],
        selected['resource_runtime'],'worker']
    proc=subprocess.Popen(route(selected['placement'],command),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None)
    proc.stdin.write((json.dumps(header)+'\n').encode());proc.stdin.flush()
    buffer=bytearray();physical=None
    while b'\n' not in buffer:
        remaining=(request['deadline']-clock()).total_seconds()
        if remaining<=0:raise TimeoutError('resource owner unknown at consumer cutoff')
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ)
            if not selector.select(min(remaining,10)):continue
        chunk=proc.stdout.read1(8192)
        if not chunk:raise RuntimeError('resource launch ended without owner acknowledgement')
        buffer.extend(chunk)
        if len(buffer)>65536:raise ValueError('unexpected resource protocol size')
    first,_,rest=buffer.partition(b'\n');physical=json.loads(first)
    if physical['op']!='ready' or physical['host']!=selected['host']:raise ValueError('physical resource owner differs')
    with rt.db() as db:manager.ready(db,key,token,physical,now=clock())
    proc.stdin.close();proc.stdin=None
    output,_=proc.communicate(timeout=max(1,(request['deadline']-clock()).total_seconds()+15))
    finished=json.loads(bytes(rest)+output)
    if finished['op']!='finished' or finished['returncode']!=proc.returncode:raise ValueError('application outcome differs from physical unit')
    proof=inspect_unit(route,selected['placement'],unit)
    if not proof['exited']:raise RuntimeError('physical resource owner still active')
    result=dict(returncode=proc.returncode,host=physical['host'],unit=unit,project=project,
        cwd=physical['cwd'],roots=physical['roots'],cleanup_pending=True)
    with rt.db() as db:manager.release(db,key,token,proof,now=clock(),result=result)
    with rt.db() as db:row=db.execute('SELECT * FROM compute_requests WHERE id=%s',(key,)).fetchone()
    result=_cleanup(rt,route,row)
    return dict(request_id=key,state='complete' if proc.returncode==0 else 'failed',result=result)


def reconcile(rt,route,key,*,clock=now):
    with rt.db() as db:
        row=db.execute('SELECT * FROM compute_requests WHERE id=%s',(key,)).fetchone()
    if row is None:raise KeyError(key)
    if row['state']=='released' and row['result'] and row['result'].get('cleanup_pending'):
        return dict(state='released',result=_cleanup(rt,route,row))
    if row['state'] not in ('reserved','running'):return dict(state=row['state'])
    proof=inspect_unit(route,row['binding']['placement'],'oc-'+key[:24]+'.service',stop=clock()>=row['deadline'])
    if proof['exited']:
        with rt.db() as db:manager.release(db,key,row['token'],proof,now=clock(),result=dict(state='execution_ended_outcome_unreceived',not_success=True))
    return proof


def _cleanup(rt,route,row):
    b=row['binding'];value=dict(row['result'])
    p=subprocess.run(route(b['placement'],[b['resource_runtime'],'retire-work','--project',row['project'],
        '--task',row['task_key'],'--device',b['placement'],'--unit','oc-'+row['id'][:24]+'.service']),
        capture_output=True,text=True,check=True,timeout=20)
    receipt=json.loads(p.stdout)
    if receipt['retired'] is not True or receipt['path']!=value['cwd']:raise ValueError('workspace retirement differs from physical ACK')
    value.update(cleanup_pending=False,cleanup=receipt)
    with rt.db() as db:db.execute('UPDATE compute_requests SET result=%s WHERE id=%s AND state=\'released\'',(Jsonb(value),row['id']))
    return value
