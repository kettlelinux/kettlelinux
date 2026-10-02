-- Kettle game database: npx wrangler d1 execute kettle-games --remote --file schema.sql
CREATE TABLE IF NOT EXISTS profiles (
  id          TEXT PRIMARY KEY,           -- 12 base32 characters
  app_id      INTEGER NOT NULL,
  game        TEXT NOT NULL,
  device      TEXT NOT NULL,              -- device model (/proc/device-tree/model)
  variant     TEXT NOT NULL,              -- Kettle image variant (device/<name>): odin2portal, thor, rp5
  build       TEXT NOT NULL,              -- Kettle build id it was shared from
  hash        TEXT NOT NULL,              -- the settings, canonical: one entry per game, device, settings
  compat_tool TEXT,                       -- Steam compatibility tool name; NULL: Steam's choice
  settings    TEXT NOT NULL,              -- JSON {option id: value} (shared/game-options.json)
  env         TEXT NOT NULL,              -- JSON [[name, value]]
  dlls        TEXT NOT NULL,              -- JSON [[dll, mode]]
  rating      TEXT NOT NULL,              -- great | playable
  notes       TEXT NOT NULL DEFAULT '',   -- shown once approved
  status      TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
  submitter   TEXT NOT NULL,              -- SHA-256 of the device's random install id
  created     INTEGER NOT NULL,           -- unix seconds
  reviewed    INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS profiles_unique ON profiles (app_id, variant, hash);
CREATE INDEX IF NOT EXISTS profiles_status ON profiles (status, created);

-- whether a profile worked for another device (one row per device and profile)
CREATE TABLE IF NOT EXISTS votes (
  profile_id  TEXT NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
  voter       TEXT NOT NULL,              -- SHA-256 of the install id
  works       INTEGER NOT NULL,
  device      TEXT NOT NULL,
  variant     TEXT NOT NULL,
  build       TEXT NOT NULL,
  created     INTEGER NOT NULL,
  PRIMARY KEY (profile_id, voter)
);

-- devices whose entries and votes are refused (SHA-256 of the install id), set from the admin page
CREATE TABLE IF NOT EXISTS banned (
  submitter   TEXT PRIMARY KEY,
  reason      TEXT NOT NULL DEFAULT '',
  created     INTEGER NOT NULL
);
