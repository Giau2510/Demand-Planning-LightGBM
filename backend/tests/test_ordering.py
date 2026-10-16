"""'Newest first' must be deterministic: timestamps have one-second resolution, so rows written in the same second
are ordered by insertion (rowid) instead of arbitrarily."""
from app import db


def _job(c, jid, created):
    c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) "
              "VALUES (?, 'D0_SYNC', ?, 'MANUAL', 'SUCCEEDED', ?)", (jid, f"k-{jid}", created))


def test_jobs_written_in_the_same_second_list_newest_insert_first(client):
    same = "2099-01-01T00:00:00+00:00"   # newer than anything the fixtures create
    with db.tx() as c:
        for jid in ("JOB-A", "JOB-B", "JOB-C"):
            _job(c, jid, same)
    # unfiltered list: no index covers created_at, so SQLite sorts and keeps ties in insertion order
    ids = [j["id"] for j in client.get("/api/jobs").json()]
    assert ids[:3] == ["JOB-C", "JOB-B", "JOB-A"]
    assert client.get("/api/jobs", params={"limit": 1}).json()[0]["id"] == "JOB-C"
