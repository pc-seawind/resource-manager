"""Existing shared PostgreSQL; no application framework or per-project database."""
from contextlib import contextmanager
from importlib.resources import files
import re

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class Store:
    def __init__(self, dsn, schema='visual_memory_v2'):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', schema):
            raise ValueError('invalid database schema')
        self.dsn, self.schema = dsn, schema

    @contextmanager
    def db(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as db:
            db.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(self.schema)))
            db.execute("SET LOCAL statement_timeout TO '15s'")
            yield db

    def install(self):
        with self.db() as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (self.schema + ':owned-compute-schema',))
            db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(self.schema)))
            db.execute(files('owned_compute').joinpath('schema.sql').read_text().replace('visual_memory_v2.', self.schema + '.'))
