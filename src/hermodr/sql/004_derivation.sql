ALTER TABLE places ADD COLUMN label TEXT;
ALTER TABLE places ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE places ADD COLUMN source_digest TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';
ALTER TABLE places ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'place-registry-v1';
ALTER TABLE places ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

ALTER TABLE transitions ADD COLUMN place_id TEXT;
ALTER TABLE transitions ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transitions ADD COLUMN source_digest TEXT NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';
ALTER TABLE transitions ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'event-time-deriver-v1';
ALTER TABLE transitions ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

ALTER TABLE visits ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE visits ADD COLUMN source_digests_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_digests_json));
ALTER TABLE visits ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'event-time-deriver-v1';
ALTER TABLE visits ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

ALTER TABLE trips ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE trips ADD COLUMN source_digests_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_digests_json));
ALTER TABLE trips ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'event-time-deriver-v1';
ALTER TABLE trips ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

ALTER TABLE coverage_gaps ADD COLUMN processed_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE coverage_gaps ADD COLUMN source_digests_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(source_digests_json));
ALTER TABLE coverage_gaps ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'event-time-deriver-v1';
ALTER TABLE coverage_gaps ADD COLUMN algorithm_config_version TEXT NOT NULL DEFAULT '0000000000000000';

ALTER TABLE recompute_windows ADD COLUMN created_at_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recompute_windows ADD COLUMN updated_at_ms INTEGER NOT NULL DEFAULT 0;
CREATE INDEX recompute_windows_state_time ON recompute_windows(state, subject_id, start_ms);
