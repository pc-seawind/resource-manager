from datetime import datetime, timedelta, timezone
import uuid

import psycopg
from psycopg import sql
import pytest

from owned_compute.database import Store
from owned_compute import manager, migration

DSN='dbname=visual_memory_v2 user=emox host=/var/run/postgresql'
T=datetime(2026,11,3,tzinfo=timezone.utc)


@pytest.fixture
def store():
    store=Store(DSN,'resource_test_'+uuid.uuid4().hex)
    store.install()
    yield store
    with psycopg.connect(DSN) as db:
        db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(store.schema)))


def candidate(gpu):
    return dict(candidate_id=str(gpu),binding=dict(host='owned',gpu=gpu,leases=['/lease/'+str(gpu)],minimum_free_mib=8000))


def enqueue(db,project,task,priority='batch',options=None):
    return manager.enqueue(db,project,task,'token',options or [candidate(0)],priority=priority,
                           is_retry=False,deadline=T+timedelta(hours=1),stall_seconds=120,spec={'command':'fixed'},now=T)


def available(gpu):return dict(candidate(gpu),free_mib=24000)


def test_different_projects_share_one_owner(store):
    with store.db() as db:
        a=enqueue(db,'project-a','a')
        assert manager.allocate(db,a,'token',[available(0)],now=T)
        b=enqueue(db,'project-b','b')
        assert manager.allocate(db,b,'token',[available(0)],now=T) is None


def test_realtime_priority_and_flexible_candidate_do_not_reserve_all_devices(store):
    with store.db() as db:
        high=enqueue(db,'realtime-project','high','realtime',[candidate(0),candidate(1)])
        low=enqueue(db,'batch-project','low',options=[candidate(0),candidate(1)])
        a=manager.allocate(db,low,'token',[available(0),available(1)],now=T)
        b=manager.allocate(db,high,'token',[available(0),available(1)],now=T)
        assert a and b and a['gpu']!=b['gpu']


def test_unknown_owner_not_expired_or_released_without_exit(store):
    with store.db() as db:
        key=enqueue(db,'project','one')
        assert manager.allocate(db,key,'token',[available(0)],now=T)
        with pytest.raises(ValueError,match='exit'):
            manager.release(db,key,'token',dict(exited=False),now=T)
        other=enqueue(db,'other','waiting')
        assert manager.allocate(db,other,'token',[available(0)],now=T+timedelta(hours=2)) is None
        assert db.execute('SELECT state FROM compute_requests WHERE id=%s',(key,)).fetchone()['state']=='reserved'


def test_successful_result_cannot_be_resubmitted(store):
    with store.db() as db:
        key=enqueue(db,'project','one');manager.allocate(db,key,'token',[available(0)],now=T)
        manager.release(db,key,'token',dict(exited=True),now=T,result={'returncode':0})
        with pytest.raises(manager.Busy,match='reused'):enqueue(db,'project','one')


def test_path_policy_correction_preserves_owner_and_does_not_claim_movement(store):
    with store.db() as db:
        owner={'pid':123,'state':'unknown'}
        migration.register(db,'single5090','/old','/wrong','project','code',owner,now=T)
        migration.retarget(db,'single5090','/old','/home/aaa/sry/projects/project','owner-specified device roots',now=T)
        row=db.execute('SELECT * FROM compute_path_migrations').fetchone()
        assert row['state']=='waiting_owner' and row['owner']==owner
        assert row['proof']['previous_target']=='/wrong' and row['proof']['physical_files_moved'] is False
        db.execute("UPDATE compute_path_migrations SET state='staged'")
        with pytest.raises(ValueError,match='staged'):
            migration.retarget(db,'single5090','/old','/other','must not move an in-flight migration',now=T)
