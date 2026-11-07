"""Node-local resource authority and an explicit, fail-closed central handoff.

Each device has one cross-project ledger.  A database trigger also protects
against old, already-installed allocators: copying a Python library is not a
transfer of the right to grant a physical device.
"""
import json
from pathlib import Path
import socket
import uuid

from psycopg import sql

from .layout import DEVICES, slug


def load_config(path):
    value = json.loads(Path(path).read_text())
    if set(value) != {'node_id', 'host', 'device', 'dsn', 'schema'}:
        raise ValueError('explicit node identity, device and local database required')
    slug(value['node_id'])
    if value['device'] not in DEVICES or value['device'] == 'local':
        raise ValueError('physical device class required, not the local transport alias')
    if value['host'] != socket.gethostname():
        raise ValueError('node configuration belongs to another physical host')
    # The database belongs to this device, never a remote central server.
    from psycopg.conninfo import conninfo_to_dict
    dsn = conninfo_to_dict(value['dsn'])
    if (not dsn.get('host', '').startswith('/') or ',' in dsn['host']
            or 'hostaddr' in dsn):
        raise ValueError('node resource ledger requires a local Unix socket')
    return value


def _lock(store, db):
    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
               (store.schema + ':owned-compute-allocation',))


def _qualified(store, name):
    return sql.Identifier(store.schema, name)


def install(store, node_id, host, device):
    """Create an inert node ledger.  Activation follows the central fence."""
    slug(node_id)
    if device not in DEVICES or device == 'local':
        raise ValueError('physical device class required')
    store.install()
    with store.db() as db:
        _lock(store, db)
        db.execute('''CREATE TABLE IF NOT EXISTS compute_node_identity (
            singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK(singleton),
            node_id TEXT NOT NULL, host TEXT NOT NULL, device TEXT NOT NULL,
            phase TEXT NOT NULL CHECK(phase IN ('pending','active')),
            fence_id TEXT, activated_at TIMESTAMPTZ)''')
        old = db.execute('SELECT * FROM compute_node_identity').fetchone()
        if old and any(old[k] != v for k, v in [('node_id', node_id), ('host', host), ('device', device)]):
            raise ValueError('resource ledger already belongs to another node')
        active = db.execute("SELECT id FROM compute_requests WHERE state IN ('reserved','running')").fetchall()
        if not old and active:
            raise ValueError('cannot convert a ledger with existing physical owners')
        if not old:
            db.execute("INSERT INTO compute_node_identity(node_id,host,device,phase) VALUES(%s,%s,%s,'pending')",
                       (node_id, host, device))
        identity = _qualified(store, 'compute_node_identity')
        function = _qualified(store, 'compute_require_local_authority')
        db.execute(sql.SQL('''CREATE OR REPLACE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE n RECORD;
            BEGIN
                SELECT * INTO STRICT n FROM {};
                IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.candidates) c
                          WHERE c->'binding'->>'host' IS DISTINCT FROM n.host
                             OR c->'binding'->>'placement' IS DISTINCT FROM 'local') THEN
                    RAISE EXCEPTION 'node ledger only accepts its local physical resources';
                END IF;
                IF NEW.state IN ('reserved','running') AND
                   (n.phase <> 'active' OR NEW.binding->>'host' IS DISTINCT FROM n.host
                    OR NEW.binding->>'placement' IS DISTINCT FROM 'local') THEN
                    RAISE EXCEPTION 'local resource authority is not active for this binding';
                END IF;
                RETURN NEW;
            END $$''').format(function, identity))
        db.execute('DROP TRIGGER IF EXISTS compute_local_authority ON compute_requests')
        db.execute(sql.SQL('''CREATE TRIGGER compute_local_authority BEFORE INSERT OR UPDATE
            ON compute_requests FOR EACH ROW EXECUTE FUNCTION {}()''').format(function))
    return status(store)


def fence_host(store, host, node_id):
    """Stop new central grants atomically; never release an old live owner."""
    slug(node_id)
    with store.db() as db:
        _lock(store, db)
        db.execute('''CREATE TABLE IF NOT EXISTS compute_host_authorities (
            host TEXT PRIMARY KEY, node_id TEXT NOT NULL, fence_id TEXT NOT NULL UNIQUE,
            fenced_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        prior = db.execute('SELECT * FROM compute_host_authorities WHERE host=%s', (host,)).fetchone()
        if prior:
            if prior['node_id'] != node_id:
                raise ValueError('physical host already handed to another node')
            return dict(prior)
        owners = db.execute("SELECT id,state FROM compute_requests WHERE state IN ('reserved','running') AND binding->>'host'=%s", (host,)).fetchall()
        if owners:
            raise ValueError('original physical owners must finish or be reconciled before handoff')
        function = _qualified(store, 'compute_require_central_authority')
        authorities = _qualified(store, 'compute_host_authorities')
        db.execute(sql.SQL('''CREATE OR REPLACE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.state NOT IN ('reserved','running') THEN RETURN NEW; END IF;
                IF TG_OP = 'UPDATE' AND OLD.state IN ('reserved','running')
                   AND NEW.binding IS NOT DISTINCT FROM OLD.binding THEN RETURN NEW; END IF;
                IF EXISTS(SELECT 1 FROM {} WHERE host=NEW.binding->>'host') THEN
                    RAISE EXCEPTION 'resource authority moved to target node; submit to its local manager';
                END IF;
                RETURN NEW;
            END $$''').format(function, authorities))
        db.execute('DROP TRIGGER IF EXISTS compute_central_authority ON compute_requests')
        db.execute(sql.SQL('''CREATE TRIGGER compute_central_authority BEFORE INSERT OR UPDATE
            ON compute_requests FOR EACH ROW EXECUTE FUNCTION {}()''').format(function))
        result = db.execute('''INSERT INTO compute_host_authorities(host,node_id,fence_id)
            VALUES(%s,%s,%s) RETURNING *''', (host, node_id, uuid.uuid4().hex)).fetchone()
        return dict(result)


def activate(store, node_id, fence_id):
    """Apply the deployment handoff receipt; no automatic takeover on timeout."""
    if not isinstance(fence_id, str) or len(fence_id) != 32 or any(c not in '0123456789abcdef' for c in fence_id):
        raise ValueError('explicit central handoff receipt required')
    with store.db() as db:
        _lock(store, db)
        row = db.execute('SELECT * FROM compute_node_identity FOR UPDATE').fetchone()
        if not row or row['node_id'] != node_id:
            raise ValueError('node identity differs from handoff')
        if row['phase'] == 'active' and row['fence_id'] != fence_id:
            raise ValueError('node is already active under another handoff')
        db.execute("UPDATE compute_node_identity SET phase='active',fence_id=%s,activated_at=COALESCE(activated_at,now())", (fence_id,))
    return status(store)


def status(store):
    with store.db() as db:
        row = db.execute('SELECT * FROM compute_node_identity').fetchone()
        counts = db.execute('SELECT state,count(*) count FROM compute_requests GROUP BY state ORDER BY state').fetchall()
        return dict(node=dict(row), requests=[dict(r) for r in counts])
