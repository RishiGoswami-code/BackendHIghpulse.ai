-- HighPulse.ai Supabase PostgreSQL Schema Setup
-- Paste these statements directly into the SQL Editor of your Supabase Dashboard to instantiate the cloud tables.

-- 1. Create the Users Table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT, -- Will be NULL for OAuth/Google users
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create the Analyses Table for Scrape Audits
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email TEXT NOT NULL,
    query TEXT NOT NULL,
    platform_status JSONB NOT NULL,
    analysis JSONB NOT NULL,
    google_trends JSONB, -- Can be NULL if trends crawl is throttled or empty
    source_count INTEGER DEFAULT 0,
    scraped_sources JSONB DEFAULT '[]'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Setup Indexes for Lightning-Fast Search Queries
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_analyses_user_email ON analyses(user_email);
CREATE INDEX IF NOT EXISTS idx_analyses_query ON analyses(query);

-- Enable Row Level Security (RLS) or public policies as desired.
-- By default, this enables global backend CRUD sync operations.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anonymous read" ON users FOR SELECT USING (true);
CREATE POLICY "Allow anonymous insert" ON users FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow anonymous update" ON users FOR UPDATE USING (true);

CREATE POLICY "Allow anonymous read analyses" ON analyses FOR SELECT USING (true);
CREATE POLICY "Allow anonymous insert analyses" ON analyses FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow anonymous delete analyses" ON analyses FOR DELETE USING (true);
