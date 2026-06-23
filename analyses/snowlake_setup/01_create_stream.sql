-- Run once manually in Snowflake to set up CDC stream on raw_events
-- Append-only: GH Archive events are immutable (never updated/deleted)

CREATE OR REPLACE STREAM GH_ARCHIVE.RAW.raw_events_stream
ON TABLE GH_ARCHIVE.RAW.raw_events
APPEND_ONLY = TRUE;