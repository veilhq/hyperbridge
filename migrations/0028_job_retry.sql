-- The earliest time a queued job may run, so a capture that hit a passing network error waits before its next try.
ALTER TABLE jobs ADD COLUMN run_after TEXT NOT NULL DEFAULT '';
