-- Demand radar release: procurement forecasts, forecast-to-opportunity links,
-- and the competitive/teaming dossier section.

-- 1) Procurement forecasts ----------------------------------------------------
-- Canonical forecast records from agency forecast systems (DHS APFS API) and
-- operator CSV imports (most agencies publish XLSX/CSV, not APIs). Raw JSON
-- retained; content hash detects revisions. GLOBAL public facts.
create table if not exists procurement_forecasts (
  id bigserial primary key,
  source text not null,                    -- 'dhs_apfs' | 'csv_import'
  source_record_id text not null,
  agency text,
  subtier text,
  office text,
  title text not null,
  description text,
  naics text,
  psc text,
  estimated_value_low numeric,
  estimated_value_high numeric,
  action_type text,                        -- new_requirement | recompete | option | unknown
  incumbent_name text,                     -- ONLY when the source states it
  contract_vehicle text,
  set_aside text,
  anticipated_solicitation date,
  anticipated_award date,
  fiscal_year int,
  place_of_performance text,
  point_of_contact text,
  status text not null default 'active',   -- active | archived
  source_url text,
  raw_json jsonb not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_record_id)
);
create index if not exists idx_forecast_naics on procurement_forecasts (naics);
create index if not exists idx_forecast_agency on procurement_forecasts (agency, subtier);
create index if not exists idx_forecast_when
  on procurement_forecasts (anticipated_solicitation);
alter table procurement_forecasts
  add constraint ck_forecast_action check (action_type is null or action_type in
    ('new_requirement', 'recompete', 'option', 'unknown')),
  add constraint ck_forecast_status check (status in ('active', 'archived'));

-- 2) Forecast-to-opportunity links ---------------------------------------------
-- "Opportunity follows forecast": deterministic match with stored evidence.
create table if not exists opportunity_forecast_links (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  forecast_id bigint not null references procurement_forecasts(id) on delete cascade,
  similarity_score int not null,
  confidence int not null,
  evidence_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (opportunity_id, forecast_id)
);
create index if not exists idx_forecast_links_opp
  on opportunity_forecast_links (opportunity_id, similarity_score desc);
create index if not exists idx_forecast_links_fc
  on opportunity_forecast_links (forecast_id);

-- 3) Competitive / teaming dossier section --------------------------------------
alter table opportunity_dossiers
  add column if not exists competitive_teaming_json jsonb not null default '{}'::jsonb;
