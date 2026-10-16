-- 0002: at most one ACTIVE DEMO batch (business rule enforced by the database, not only by code).
-- MANUAL_IMPORT batches stay independent: several may be ACTIVE; the active dataset is chosen in settings.
CREATE UNIQUE INDEX ux_import_batches_one_active_demo ON import_batches(data_source)
    WHERE data_source = 'DEMO' AND status = 'ACTIVE';
