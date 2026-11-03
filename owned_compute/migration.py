"""Persistent exact-path migration ledger; registration never moves a live owner."""
from pathlib import PurePosixPath
from psycopg.types.json import Jsonb


def register(db,host,old,new,project,kind,owners,*,now):
    old=str(PurePosixPath(old));new=str(PurePosixPath(new))
    if old==new:raise ValueError('migration source equals destination')
    row=db.execute('SELECT * FROM compute_path_migrations WHERE host=%s AND old_path=%s FOR UPDATE',(host,old)).fetchone()
    if row:
        if row['new_path']!=new or row['kind']!=kind:raise ValueError('registered path migration changed')
        return row['state']
    db.execute('''INSERT INTO compute_path_migrations(host,old_path,new_path,project,kind,state,owner,updated_at)
        VALUES(%s,%s,%s,%s,%s,'waiting_owner',%s,%s)''',
        (host,old,new,project,kind,Jsonb(owners),now))
    return 'waiting_owner'


def retarget(db,host,old,new,reason,*,now):
    """The owner's corrected path policy changes a target, never physical state."""
    row=db.execute('SELECT * FROM compute_path_migrations WHERE host=%s AND old_path=%s FOR UPDATE',(host,old)).fetchone()
    if row is None:raise KeyError((host,old))
    if row['new_path']==new:return row['state']
    if row['state'] not in ('registered','waiting_owner'):raise ValueError('cannot retarget a staged or migrated owner')
    if not reason:raise ValueError('explicit path-policy correction required')
    proof=dict(previous_target=row['new_path'],reason=reason,physical_files_moved=False)
    db.execute('UPDATE compute_path_migrations SET new_path=%s,proof=%s,updated_at=%s WHERE host=%s AND old_path=%s',
               (str(PurePosixPath(new)),Jsonb(proof),now,host,old))
    return row['state']
