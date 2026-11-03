"""Cross-project queue and physical ownership, using a caller's existing PG transaction.

No Visual Memory task FK or model assumptions. Drivers provide already-admitted
candidate bindings and physical probes; the same allocator arbitrates them all.
"""
import hashlib
import json
from psycopg.types.json import Jsonb

PRIORITIES={'realtime':0,'seconds':1,'batch':2,'background':3}


class Busy(RuntimeError):pass


def identifier(project,task):
    return hashlib.sha256(json.dumps([project,task],separators=(',',':')).encode()).hexdigest()


def conflicts(a,b):
    if a['host']!=b['host']:return False
    return ((a.get('gpu') is not None and a['gpu']==b.get('gpu'))
        or bool(set(a.get('leases',[]))&set(b.get('leases',[]))))


def enqueue(db,project,task,token,candidates,*,priority,is_retry,deadline,stall_seconds,spec,now):
    from .layout import slug
    slug(project)
    if not candidates or deadline<=now or deadline.tzinfo is None:raise ValueError('ready candidates and a future absolute deadline required')
    key=identifier(project,task)
    row=db.execute('SELECT * FROM compute_requests WHERE id=%s FOR UPDATE',(key,)).fetchone()
    if row:
        if row['candidates']!=candidates or row['deadline']!=deadline or row['spec']!=spec:raise ValueError('frozen resource request changed')
        if row['state'] in ('reserved','running'):raise Busy('original project resource owner unresolved')
        if row['state']=='expired':raise Busy('original resource request expired')
        if row['state']=='released' and row['result'] is not None:raise Busy('terminal resource result must be reused')
        # A released pre-model refusal can resubmit its same immutable request.
        # Polling is not progress: it cannot renew either wait bound.
        db.execute("UPDATE compute_requests SET state='queued',token=%s,updated_at=%s,proof=NULL,binding=NULL,receipt=NULL,ready_at=NULL,ended_at=NULL WHERE id=%s",
                   (token,row['updated_at'] if row['state']=='queued' else now,key))
    else:
        db.execute('''INSERT INTO compute_requests(id,project,task_key,token,priority,is_retry,state,deadline,stall_seconds,candidates,spec,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s)''',
            (key,project,task,token,PRIORITIES[priority],is_retry,deadline,stall_seconds,Jsonb(candidates),Jsonb(spec),now,now))
    return key


def allocate(db,key,token,available,*,now,external=()):
    schema=db.execute('SELECT current_schema() schema').fetchone()['schema']
    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(schema+':owned-compute-allocation',))
    # Only never-started queued requests may expire without physical exit proof.
    db.execute("UPDATE compute_requests SET state='expired',ended_at=%s WHERE state='queued' AND (deadline<=%s OR updated_at+stall_seconds*interval '1 second'<=%s)",(now,now,now))
    own=db.execute("SELECT * FROM compute_requests WHERE id=%s AND token=%s AND state='queued' FOR UPDATE",(key,token)).fetchone()
    if own is None:return None
    active=[r['binding'] for r in db.execute("SELECT binding FROM compute_requests WHERE state IN ('reserved','running')")]
    active.extend(external)
    earlier=db.execute('''SELECT * FROM compute_requests WHERE state='queued' AND id!=%s
        AND (priority,is_retry,deadline,created_at,id)<(%s,%s,%s,%s,%s)
        ORDER BY priority,is_retry,deadline,created_at,id''',
        (key,own['priority'],own['is_retry'],own['deadline'],own['created_at'],key)).fetchall()
    # Measurements are optional, never zero-filled. With no calibrated cost,
    # prefer best-fit memory rather than consuming the largest card by default.
    def rank(option):
        estimate=option.get('estimated_seconds')
        return (estimate is None,estimate if estimate is not None else 0,
            option['free_mib']-option['binding'].get('minimum_free_mib',0),option['candidate_id'])
    ordered=sorted(available,key=rank)
    planned=[]
    # A higher-priority flexible request needs ONE device, not every device in
    # its candidate pool. Plan its first eligible slot without changing owners;
    # another request can use the remaining compatible slots immediately.
    for predecessor in earlier:
        for option in ordered:
            b=option['binding']
            if any(conflicts(b,x) for x in [*active,*planned]):continue
            if any(conflicts(b,c['binding']) and c['binding'].get('minimum_free_mib',0)<=option['free_mib']
                   for c in predecessor['candidates']):
                planned.append(b);break
    for option in ordered:
        binding=option['binding']
        if any(conflicts(binding,other) for other in [*active,*planned]):continue
        db.execute("UPDATE compute_requests SET state='reserved',binding=%s,updated_at=%s WHERE id=%s AND token=%s",
                   (Jsonb(binding),now,key,token))
        return binding
    return None


def ready(db,key,token,receipt,*,now):
    row=db.execute("UPDATE compute_requests SET state='running',ready_at=%s,receipt=%s,updated_at=%s WHERE id=%s AND token=%s AND state='reserved' RETURNING id",
                   (now,Jsonb(receipt),now,key,token)).fetchone()
    if row is None:raise ValueError('no matching reserved resource owner')


def release(db,key,token,proof,*,now,result=None):
    if not proof['exited']:raise ValueError('physical exit proof required')
    db.execute("UPDATE compute_requests SET state='released',ended_at=%s,updated_at=%s,proof=%s,result=%s WHERE id=%s AND token=%s AND state IN ('reserved','running')",
               (now,now,Jsonb(proof),Jsonb(result) if result is not None else None,key,token))
