-- Migration 003: Market Intelligence & Historical Intelligence Dossiers.
-- Awards, buyer offices, vendors, funding context, market stats, dossiers.

create table if not exists buyer_offices (
  id bigserial primary key,
  department_name text,
  department_code text,
  subtier_name text,
  subtier_code text,
  office_name text,
  office_code text,
  organization_code text,
  full_parent_path_name text,
  full_parent_path_code text,
  location_json jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  source_confidence int not null default 50,        -- 0-100, see src/intel/confidence.py bands
  raw_hierarchy_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_office_org on buyer_offices (organization_code);
create index if not exists idx_office_path on buyer_offices (full_parent_path_code);
create index if not exists idx_office_names on buyer_offices (department_name, subtier_name, office_name);

create table if not exists contract_awards (
  id bigserial primary key,
  source text not null,                              -- 'usaspending' | 'sam.gov'
  source_award_id text not null,
  piid text,
  parent_award_id text,
  solicitation_number text,
  award_title text,
  award_description text,
  recipient_name text,
  recipient_name_normalized text,
  recipient_uei text,
  recipient_cage text,
  awarding_department text,
  awarding_subtier text,
  awarding_office text,
  awarding_office_code text,
  funding_department text,
  funding_subtier text,
  funding_office text,
  naics text,
  psc text,
  award_type text,
  contract_type text,
  contract_vehicle text,
  extent_competed text,
  set_aside text,
  award_date date,
  period_start date,
  period_end date,
  obligated_amount numeric,
  total_obligated_amount numeric,
  potential_total_value numeric,
  place_of_performance_json jsonb,
  raw_json jsonb not null,
  content_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source, source_award_id)
);
create index if not exists idx_awards_office on contract_awards (awarding_office_code, naics);
create index if not exists idx_awards_subtier on contract_awards (awarding_subtier, naics);
create index if not exists idx_awards_solnum on contract_awards (solicitation_number);
create index if not exists idx_awards_recipient on contract_awards (recipient_name_normalized);
create index if not exists idx_awards_date on contract_awards (award_date desc);

create table if not exists opportunity_award_links (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  contract_award_id bigint not null references contract_awards(id) on delete cascade,
  link_type text not null,       -- same_solicitation | same_contract | same_office_same_naics |
                                 -- same_office_same_psc | similar_scope | possible_recompete |
                                 -- possible_incumbent | same_vehicle
  similarity_score int not null, -- 0-100
  confidence int not null,       -- 0-100
  evidence_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (opportunity_id, contract_award_id, link_type)
);
create index if not exists idx_links_opp on opportunity_award_links (opportunity_id, similarity_score desc);

create table if not exists opportunity_dossiers (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  buyer_office_id bigint references buyer_offices(id),
  generated_at timestamptz not null default now(),
  dossier_version int not null default 1,
  snapshot_json jsonb not null default '{}'::jsonb,
  buyer_profile_json jsonb not null default '{}'::jsonb,
  similar_work_json jsonb not null default '[]'::jsonb,
  last_10_relevant_awards_json jsonb not null default '[]'::jsonb,
  incumbent_analysis_json jsonb not null default '{}'::jsonb,
  work_origin_assessment_json jsonb not null default '{}'::jsonb,
  funding_context_json jsonb not null default '{}'::jsonb,
  market_size_json jsonb not null default '{}'::jsonb,
  competition_landscape_json jsonb not null default '{}'::jsonb,
  acquisition_pattern_json jsonb not null default '{}'::jsonb,
  pursuit_recommendation_json jsonb not null default '{}'::jsonb,
  data_quality_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (opportunity_id)
);

create table if not exists vendor_profiles (
  id bigserial primary key,
  recipient_name text not null,
  normalized_recipient_name text not null,
  recipient_uei text,
  recipient_cage text,
  total_obligations numeric not null default 0,
  award_count int not null default 0,
  first_award_date date,
  last_award_date date,
  top_agencies_json jsonb not null default '[]'::jsonb,
  top_naics_json jsonb not null default '[]'::jsonb,
  top_psc_json jsonb not null default '[]'::jsonb,
  top_offices_json jsonb not null default '[]'::jsonb,
  source_confidence int not null default 50,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (normalized_recipient_name, recipient_uei)
);
create index if not exists idx_vendor_norm on vendor_profiles (normalized_recipient_name);

create table if not exists funding_accounts (
  id bigserial primary key,
  agency_code text,
  agency_name text,
  bureau_code text,
  bureau_name text,
  federal_account_code text,
  federal_account_name text,
  treasury_account_symbol text,
  budget_function text,
  budget_subfunction text,
  fiscal_year int,
  budgetary_resources numeric,
  obligations numeric,
  outlays numeric,
  president_budget_amount numeric,
  source text not null,                              -- 'usaspending' | 'omb_budget' | 'omb_apportionment'
  raw_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source, federal_account_code, fiscal_year)
);

create table if not exists office_market_stats (
  id bigserial primary key,
  buyer_office_id bigint references buyer_offices(id) on delete cascade,
  fiscal_year int not null,
  naics text,
  psc text,
  fedintel_category text,
  award_count int not null default 0,
  total_obligations numeric not null default 0,
  median_award_value numeric,
  average_award_value numeric,
  largest_award_value numeric,
  unique_vendor_count int,
  top_vendor_share numeric,
  small_business_share numeric,
  set_aside_share numeric,
  competed_share numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (buyer_office_id, fiscal_year, naics, psc)
);

-- Enrichment queue state on opportunities (async: ingest never blocks on intel)
alter table opportunities
  add column if not exists enrichment_status text not null default 'pending',  -- pending|running|done|failed|skipped
  add column if not exists enriched_at timestamptz;
create index if not exists idx_opp_enrich on opportunities (enrichment_status);
