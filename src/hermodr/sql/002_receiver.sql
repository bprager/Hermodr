ALTER TABLE devices ADD COLUMN source_tid TEXT;
CREATE INDEX devices_source_tid ON devices(source_tid) WHERE source_tid IS NOT NULL;
CREATE UNIQUE INDEX credentials_key_id_unique ON credentials(key_id);
ALTER TABLE raw_events ADD COLUMN request_id TEXT;
ALTER TABLE raw_events ADD COLUMN key_id TEXT;
ALTER TABLE raw_events ADD COLUMN content_type TEXT;
ALTER TABLE raw_events ADD COLUMN content_length INTEGER CHECK (content_length >= 0);
ALTER TABLE raw_events ADD COLUMN user_agent_family TEXT;
ALTER TABLE raw_events ADD COLUMN receiver_build TEXT;
CREATE UNIQUE INDEX processing_jobs_ingest_unique
    ON processing_jobs(subject_id, ingest_id) WHERE ingest_id IS NOT NULL;
