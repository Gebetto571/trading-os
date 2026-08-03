ALTER TABLE download_manifest
    DROP CONSTRAINT IF EXISTS download_manifest_status_check;

ALTER TABLE download_manifest
    ADD CONSTRAINT download_manifest_status_check CHECK (status IN (
        'planned',
        'downloading',
        'downloaded',
        'checksum_verified',
        'imported',
        'validated',
        'fallback_complete',
        'failed'
    ));

ALTER TABLE download_manifest
    ADD COLUMN IF NOT EXISTS fallback_source_count INTEGER;

ALTER TABLE download_manifest
    ADD CONSTRAINT download_manifest_fallback_source_count_check
    CHECK (fallback_source_count IS NULL OR fallback_source_count >= 0);
