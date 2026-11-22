-- Database schema for Task 1, 2, and 3

CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL UNIQUE,
    video_url TEXT NOT NULL,
    file_path TEXT NOT NULL,
    processed_video_url TEXT,
    sidecar_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_video_url TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS sidecar_path TEXT;

CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL UNIQUE,
    language TEXT,
    country TEXT,
    postcode TEXT,
    city TEXT,
    street TEXT,
    house_no TEXT,
    web TEXT,
    status INTEGER,
    impressum_url TEXT,
    legal_name TEXT,
    postal_address TEXT,
    handelsregister TEXT,
    vat_number TEXT,
    phone TEXT,
    email TEXT,
    responsible_person TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);
