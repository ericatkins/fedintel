-- OCR support metadata and the grants vertical foundation.

-- 1) Extraction method on documents ------------------------------------------
-- 'pypdf' (embedded text), 'ocr' (rasterized + tesseract, reduced confidence),
-- null for unprocessed/unsupported. OCR page coverage recorded so the UI can
-- say "OCR of 20 of 63 pages" instead of implying full coverage.
alter table opportunity_documents
  add column if not exists extraction_method text,
  add column if not exists ocr_pages int;
alter table opportunity_documents
  add constraint ck_doc_extraction_method check (extraction_method is null or
    extraction_method in ('pypdf', 'ocr', 'text'));

-- 2) Grant opportunities --------------------------------------------------------
-- A SEPARATE vertical: grants share agencies/programs with contracts but have
-- different decision logic. Contract scoring is never applied to these rows.
create table if not exists grant_opportunities (
  id bigserial primary key,
  source text not null,                    -- 'grants_gov' | 'csv_import'
  source_grant_id text not null,           -- Grants.gov opportunity number/id
  opportunity_number text,
  title text not null,
  agency_code text,
  agency_name text,
  assistance_listings jsonb not null default '[]'::jsonb,  -- CFDA numbers
  opportunity_status text,                 -- forecasted | posted | closed | archived
  posted_date date,
  close_date date,
  award_floor numeric,
  award_ceiling numeric,
  expected_awards int,
  total_funding numeric,
  funding_instrument text,                 -- grant | cooperative_agreement | other
  category text,
  eligible_applicants jsonb not null default '[]'::jsonb,
  cost_sharing boolean,
  description_text text,
  source_url text,
  raw_json jsonb not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_grant_id)
);
create index if not exists idx_grants_close on grant_opportunities (close_date);
create index if not exists idx_grants_agency on grant_opportunities (agency_code);
create index if not exists idx_grants_status on grant_opportunities (opportunity_status);
