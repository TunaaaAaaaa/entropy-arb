CREATE TABLE research.record_events (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 record_id TEXT NOT NULL REFERENCES research.records(id),
 version_id BIGINT NOT NULL REFERENCES research.record_versions(id),
 previous_status TEXT, status TEXT NOT NULL, at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE research.experiment_links (
 record_version_id BIGINT NOT NULL REFERENCES research.record_versions(id),
 experiment_id TEXT NOT NULL REFERENCES research.experiment_runs(id),
 PRIMARY KEY(record_version_id,experiment_id)
);
CREATE TRIGGER immutable_record_event BEFORE UPDATE OR DELETE ON research.record_events
 FOR EACH ROW EXECUTE FUNCTION evidence.prevent_mutation();
