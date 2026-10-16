"""data-check is read-only and reports (never repairs) broken data invariants."""
import hashlib
import json

from app import cli, data_checks, db, paths

from test_import import _import, _rows, _xlsx   # tests/ is on sys.path (pytest rootdir-less "prepend" import mode)


def _status(res):
    return {x["check"]: x["status"] for x in res["checks"]}


def test_clean_database_passes_and_file_is_not_modified(client, small_demo):
    _import(client, _xlsx(_rows(10, qty=3)))
    before = hashlib.sha256(paths.db_path().read_bytes()).hexdigest()
    res = data_checks.run(paths.db_path(), paths.models_dir())
    assert res["status"] == "OK", [x for x in res["checks"] if x["status"] != "OK"]
    assert res["row_counts"]["order_lines"] > 0
    assert hashlib.sha256(paths.db_path().read_bytes()).hexdigest() == before


def test_reports_lines_left_in_a_closed_batch_and_demand_drift(client):
    a, _ = _import(client, _xlsx(_rows(10, qty=3)))
    b, _ = _import(client, _xlsx(_rows(10, qty=7)))
    with db.tx() as c:   # simulate corruption the code must never produce
        c.execute("UPDATE import_batches SET status='REPLACED' WHERE id=?", (a["id"],))
        c.execute("UPDATE demand_daily SET qty = qty + 1 WHERE scope_key=? AND order_date="
                  "(SELECT MIN(order_date) FROM demand_daily WHERE scope_key=?)", (b["id"], b["id"]))
    res = data_checks.run(paths.db_path())
    st = _status(res)
    assert res["status"] == "FAIL"
    assert st["closed_batches_hold_no_rows"] == "FAIL" and st["demand_matches_order_lines"] == "FAIL"
    bad = next(x for x in res["checks"] if x["check"] == "demand_matches_order_lines")
    assert bad["examples"][0][0] == b["id"]
    assert st["accepted_model_files"] == "OK"   # skipped without a models folder, never a false alarm


def test_active_dataset_pointing_to_a_closed_batch_and_missing_model(client, small_demo, fast_model):
    a, _ = _import(client, _xlsx(_rows(10, qty=3)))
    with db.tx() as c:
        c.execute("UPDATE app_settings SET value_json=? WHERE section='general'",
                  (json.dumps({"active_source": "MANUAL_IMPORT", "active_import_batch_id": "IMP-NOPE"}),))
        c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at, model_path, "
                  "model_sha256) VALUES ('TRN-X', 'MV-X', ?, 'DEMO', 'ACCEPTED', '2026-01-01T00:00:00+00:00', "
                  "'MV-X.txt', 'abc')", (small_demo["batch_id"],))
    st = _status(data_checks.run(paths.db_path(), paths.models_dir()))
    assert st["active_dataset_setting"] == "FAIL" and st["accepted_model_files"] == "FAIL"


def test_cli_exit_codes(client, capsys):
    _import(client, _xlsx(_rows(5)))
    assert cli.main(["data-check"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] in ("OK", "WARN")
    with db.tx() as c:
        c.execute("INSERT INTO import_batches(id, data_source, status, created_at) "
                  "VALUES ('DEMO-2', 'DEMO', 'REPLACED', '2026-01-01T00:00:00+00:00')")
        c.execute("INSERT INTO order_lines(batch_id, order_date, sku_id, fc_id, order_qty) "
                  "VALUES ('DEMO-2', '2026-01-01', 'S', 'F', 1)")
    assert cli.main(["data-check", "--db", str(paths.db_path())]) == 1
