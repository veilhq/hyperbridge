-- Each set may name the entry (by uid) whose image is its cover; '' falls back to the newest placed image.
ALTER TABLE sets ADD COLUMN cover_uid TEXT NOT NULL DEFAULT '';
