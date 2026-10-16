"""A fake BigQuery client used when no real credentials/dataset exist. It records every query."""
from __future__ import annotations

import re
from types import SimpleNamespace


class FakeJob:
    def __init__(self, rows, bytes_, schema=None, statement_type="SELECT", referenced_tables=None):
        self._rows = rows
        self.total_bytes_processed = bytes_
        self.schema = [SimpleNamespace(name=n, field_type=t) for n, t in (schema or [])]
        self.statement_type = statement_type
        self.referenced_tables = referenced_tables or []

    def result(self, timeout=None):
        return list(self._rows)


class FakeBQ:
    def __init__(self, location="asia-southeast1", schema=None, responses=None, bytes_=1000, errors=None):
        self.location = location
        self.schema = schema or [("order_id", "STRING"), ("created_at", "TIMESTAMP"), ("sku", "STRING"),
                                 ("warehouse", "STRING"), ("qty", "INT64"), ("price", "FLOAT64"),
                                 ("updated_at", "TIMESTAMP"), ("dt", "DATE")]
        self.responses = responses or {}
        self.bytes = bytes_
        self.errors = errors or {}
        self.queries: list[tuple[str, dict]] = []
        self.dry_schema = list(self.schema)      # output schema returned by a dry run of a user SQL
        self.statement_type = "SELECT"
        self.referenced_tables = []

    def __call__(self, settings):
        if "auth" in self.errors:
            raise self.errors["auth"]
        return self

    def get_dataset(self, name):
        if "dataset" in self.errors:
            raise self.errors["dataset"]
        return SimpleNamespace(location=self.location)

    def get_table(self, name):
        if "table" in self.errors:
            raise self.errors["table"]
        return SimpleNamespace(schema=[SimpleNamespace(name=n, field_type=t, mode="NULLABLE") for n, t in self.schema],
                               num_rows=12345, time_partitioning="DAY(dt)")

    def query(self, sql, job_config=None):
        kind = re.match(r"-- df:(\w+)", sql).group(1)
        self.queries.append((sql, job_config))
        if kind in self.errors:
            raise self.errors[kind]
        if job_config and job_config.get("dry_run"):
            if kind == "sql_dry_run":     # dry run of a user SQL text: output schema + statement type
                return FakeJob([], self.bytes, schema=self.dry_schema, statement_type=self.statement_type,
                               referenced_tables=self.referenced_tables)
            return FakeJob([], self.bytes)
        r = self.responses.get(kind, [])
        return FakeJob(r(job_config) if callable(r) else r, self.bytes)


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass
