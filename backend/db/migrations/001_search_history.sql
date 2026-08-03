-- Run in the Supabase SQL editor (or psql) before deploying search history.
CREATE TABLE IF NOT EXISTS search_history (
  id SERIAL PRIMARY KEY,
  player_name TEXT NOT NULL,
  position TEXT,
  team TEXT,
  confidence FLOAT,
  response_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_history_created_at
  ON search_history (created_at DESC);
