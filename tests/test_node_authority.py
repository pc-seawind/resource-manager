"""Real PostgreSQL ownership tests; never launch a model or another unit."""
from datetime import datetime, timedelta, timezone
import json
import socket
import uuid

import psycopg
import pytest
from psycopg import sql

from owned_compute.database import Store
from owned_compute import manager, node

DSN = 'dbname=visual_memory_v2 user=emox host=/var/run/postgresql'
T = datetime.now(timezone.utc)


@pytest.fixture
def store():
    value = Store(DSN, 'resource_test_' + uuid.uuid4().hex)
    value.install()
    yield value
    with psycopg.connect(DSN) as db:
        db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(value.schema)))


def option(host='gpu-host', placement='local', gpu=0):
    return dict(candidate_id='gpu', binding=dict(host=host, placement=placement,
        gpu=gpu, leases=['/lease/' + str(gpu)], minimum_free_mib=1))


def enqueue(store, task, candidate=None):
    candidate = candidate or option()
    with store.db() as db:
        return manager.enqueue(db, 'example', task, 'token', [candidate], priority='batch',
            is_retry=False, deadline=T+timedelta(hours=1), stall_seconds=120, spec={}, now=T)


def allocate(store, key, candidate=None):
    candidate = candidate or option()
    with store.db() as db:
        return manager.allocate(db, key, 'token', [dict(candidate, free_mib=32000)], now=T)


def test_pending_node_cannot_grant_and_active_node_shares_cross_project_ledger(store):
    result = node.install(store, 'single5090', 'gpu-host', 'single5090')
    assert result['node']['phase'] == 'pending'
    key = enqueue(store, 'one')
    with pytest.raises(psycopg.errors.RaiseException, match='not active'):
        allocate(store, key)
    node.activate(store, 'single5090', 'a'*32)
    assert allocate(store, key)['host'] == 'gpu-host'
    other = enqueue(store, 'two')
    assert allocate(store, other) is None
    with store.db() as db:
        manager.release(db, key, 'token', dict(exited=True), now=T, result={'success': True})
    assert allocate(store, other)


@pytest.mark.parametrize('candidate', [option('foreign'), option(placement='single5090')])
def test_node_database_rejects_remote_candidates_before_allocation(store, candidate):
    node.install(store, 'single5090', 'gpu-host', 'single5090')
    with pytest.raises(psycopg.errors.RaiseException, match='local physical'):
        enqueue(store, 'foreign', candidate)


def test_fence_rejects_old_allocator_new_grants_but_not_other_devices(store):
    own = enqueue(store, 'old-client')
    proof = node.fence_host(store, 'gpu-host', 'single5090')
    assert node.fence_host(store, 'gpu-host', 'single5090')['fence_id'] == proof['fence_id']
    # manager.allocate itself is unchanged, as are previously pinned allocators.
    with pytest.raises(psycopg.errors.RaiseException, match='authority moved'):
        allocate(store, own)
    other = option('other-host')
    key = enqueue(store, 'other-device', other)
    assert allocate(store, key, other)['host'] == 'other-host'
    with store.db() as db:
        manager.ready(db, key, 'token', {'unit': 'old-owner'}, now=T)
        manager.release(db, key, 'token', dict(exited=True), now=T)


def test_source_fence_never_steals_active_or_unknown_owner(store):
    key = enqueue(store, 'live')
    allocate(store, key)
    with pytest.raises(ValueError, match='original physical owners'):
        node.fence_host(store, 'gpu-host', 'single5090')
    with store.db() as db:
        row = db.execute('SELECT * FROM compute_requests WHERE id=%s', (key,)).fetchone()
        assert row['state'] == 'reserved' and row['token'] == 'token'


def test_node_identity_and_activation_receipt_cannot_be_rewritten(store):
    node.install(store, 'single5090', 'gpu-host', 'single5090')
    with pytest.raises(ValueError, match='another node'):
        node.install(store, 'dual5090', 'other-host', 'dual5090')
    node.activate(store, 'single5090', 'a'*32)
    assert node.activate(store, 'single5090', 'a'*32)['node']['phase'] == 'active'
    with pytest.raises(ValueError, match='another handoff'):
        node.activate(store, 'single5090', 'b'*32)


def test_fence_cannot_be_reassigned_to_another_node(store):
    node.fence_host(store, 'gpu-host', 'single5090')
    with pytest.raises(ValueError, match='another node'):
        node.fence_host(store, 'gpu-host', 'different-node')


def test_node_config_requires_local_database_and_actual_host(tmp_path):
    path = tmp_path/'node.json'
    value = dict(node_id='single5090', host=socket.gethostname(), device='single5090',
        dsn='dbname=resource_manager host=/a/local/socket', schema='resource_manager')
    path.write_text(json.dumps(value))
    assert node.load_config(path)['device'] == 'single5090'
    value['dsn'] = 'dbname=resource_manager host=remote-host'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='local Unix socket'):
        node.load_config(path)
