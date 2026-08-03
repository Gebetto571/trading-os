ALTER TABLE download_manifest
    RENAME COLUMN attempt_count TO invocation_count;

ALTER TABLE download_manifest
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN fallback_parent_url TEXT REFERENCES download_manifest(source_url),
    ADD COLUMN coverage_start TIMESTAMPTZ,
    ADD COLUMN coverage_end TIMESTAMPTZ,
    ADD COLUMN coverage_row_count BIGINT;

ALTER TABLE download_manifest
    DROP CONSTRAINT download_manifest_status_check;

ALTER TABLE download_manifest
    ADD CONSTRAINT download_manifest_status_check CHECK (status IN (
        'planned',
        'downloading',
        'downloaded',
        'checksum_verified',
        'imported',
        'validated',
        'fallback_pending',
        'fallback_complete',
        'failed'
    )),
    ADD CONSTRAINT download_manifest_invocation_count_check
        CHECK (invocation_count >= 0),
    ADD CONSTRAINT download_manifest_attempt_count_check
        CHECK (attempt_count >= 0),
    ADD CONSTRAINT download_manifest_coverage_check CHECK (
        (coverage_start IS NULL AND coverage_end IS NULL AND coverage_row_count IS NULL)
        OR (
            coverage_start IS NOT NULL
            AND coverage_end IS NOT NULL
            AND coverage_start < coverage_end
            AND coverage_row_count IS NOT NULL
            AND coverage_row_count >= 0
        )
    );

CREATE INDEX download_manifest_fallback_parent_url
    ON download_manifest(fallback_parent_url)
    WHERE fallback_parent_url IS NOT NULL;

UPDATE download_manifest
SET status = 'fallback_pending',
    completed_at = NULL,
    coverage_start = NULL,
    coverage_end = NULL,
    coverage_row_count = NULL,
    updated_at = now()
WHERE status = 'fallback_complete';

UPDATE download_manifest AS child
SET fallback_parent_url = parent.source_url,
    updated_at = now()
FROM download_manifest AS parent
WHERE parent.source_type = 'monthly'
  AND parent.status = 'fallback_pending'
  AND child.source_type = 'daily'
  AND child.period LIKE parent.period || '-%'
  AND child.file_name = replace(
      parent.file_name,
      parent.period || '.zip',
      child.period || '.zip'
  );

ALTER TABLE download_manifest
    ADD CONSTRAINT download_manifest_fallback_coverage_check CHECK (
        status <> 'fallback_complete'
        OR (
            coverage_start IS NOT NULL
            AND coverage_end IS NOT NULL
            AND coverage_row_count IS NOT NULL
        )
    );
