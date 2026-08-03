-- Earlier importer versions validated every archive before inserting it but left the
-- manifest at `imported`. Preserve that evidence while aligning existing rows with
-- the explicit state machine.
UPDATE download_manifest
SET status = 'validated',
    completed_at = COALESCE(completed_at, updated_at),
    error_message = NULL,
    updated_at = now()
WHERE status = 'imported';
