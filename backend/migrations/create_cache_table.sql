CREATE TABLE IF NOT EXISTS report_cache (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  player_key TEXT UNIQUE NOT NULL,
  report JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  hit_count INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_report_cache_player_key
ON report_cache(player_key);
