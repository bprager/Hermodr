ALTER TABLE recompute_windows RENAME TO recompute_windows_v1;

CREATE TABLE recompute_windows (
    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
    window_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    cause TEXT NOT NULL CHECK (cause IN ('new_data', 'late_data', 'operator', 'algorithm_change')),
    algorithm_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'processing', 'processed', 'failed')),
    coalescing_key TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (subject_id, window_id),
    UNIQUE (subject_id, coalescing_key),
    CHECK (end_ms >= start_ms)
) STRICT;

INSERT INTO recompute_windows SELECT * FROM recompute_windows_v1;
DROP TABLE recompute_windows_v1;
CREATE INDEX recompute_windows_state_time ON recompute_windows(state, subject_id, start_ms);
