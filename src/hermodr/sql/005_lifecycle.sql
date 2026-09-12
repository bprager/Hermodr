ALTER TABLE raw_events ADD COLUMN payload_expired_at_ms INTEGER;

CREATE INDEX raw_events_retention ON raw_events(subject_id, captured_at_ms, payload_expired_at_ms);
CREATE INDEX observations_retention ON observations(subject_id, captured_at_ms);
CREATE INDEX outbox_consumer_lag ON outbox_consumers(last_sequence);
