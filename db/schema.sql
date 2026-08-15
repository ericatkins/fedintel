-- Fedintel schema — FRESH INSTALL (baseline + migration 002 merged).
-- Existing databases: run db/migrations/002_hardening_and_saas.sql instead.

create table if not exists opportunities (
  id bigserial primary key,
  source text not null default 'sam.gov',          -- 'sam.gov' | 'bonfire' | 'bidnet' | 'city:...'
  source_notice_id text not null,                  -- SAM noticeId or platform-native id
  solicitation_number text,
  title text not null,
  agency text,
  office text,
  jurisdiction text not null default 'federal',    -- 'federal' | 'state:TX' | 'city:huntsville-al'
  notice_type text,                                -- Sources Sought | RFI | Solicitation | Award | ...
  naics text,
  set_aside text,
  posted_date date,
  response_deadline timestamptz,
  place_of_performance text,
  description_text text,
  url text,
  raw_json jsonb not null,                         -- store forever; enables reclassification
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_notice_id)
);

create index if not exists idx_opp_posted on opportunities (posted_date desc);
create index if not exists idx_opp_solnum on opportunities (solicitation_number);
create index if not exists idx_opp_hash on opportunities (content_hash);

-- Lineage: links notices in the same pursuit (Sources Sought -> RFI -> RFP -> Amendment -> Award)
create table if not exists opportunity_lineage (
  id bigserial primary key,
  solicitation_number text not null,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  stage text not null,
  linked_at timestamptz not null default now()
);
create index if not exists idx_lineage_solnum on opportunity_lineage (solicitation_number);

create table if not exists classifications (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  category text not null,
  score int not null,
  confidence text not null,                        -- 'rules' | 'ai'
  reasons jsonb not null default '[]'::jsonb,
  keywords_matched jsonb not null default '[]'::jsonb,
  ai_summary text,
  classified_at timestamptz not null default now(),
  unique (opportunity_id)
);
create index if not exists idx_class_score on classifications (score desc);

create table if not exists email_digests (
  id bigserial primary key,
  digest_date date not null unique,
  sent_at timestamptz,
  opportunity_count int not null default 0,
  top_score int,
  html_body text
);

-- Change events power future instant alerts ("your 92-score Sources Sought is now an RFP")
create table if not exists change_events (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  event_type text not null,                        -- 'new' | 'amended' | 'stage_change' | 'deadline_change'
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  notified boolean not null default false
);

-- Post-MVP: per-user alert rules (schema ready now so the rules engine bolts on cleanly)
create table if not exists alert_rules (
  id bigserial primary key,
  user_email text not null,
  notice_types text[] default '{}',
  min_score int default 70,
  jurisdictions text[] default '{federal}',
  keywords text[] default '{}',
  channel text not null default 'email',
  immediacy text not null default 'digest',        -- 'digest' | 'instant'
  created_at timestamptz not null default now()
);

-- ==== migration 002 content ====

-- Digest send-state: sent_at now means "provider confirmed", nothing less.
alter table email_digests
  add column if not exists generated_at timestamptz,
  add column if not exists send_attempted_at timestamptz,
  add column if not exists send_status text not null default 'pending',  -- pending|sent|failed
  add column if not exists send_error text,
  add column if not exists provider_message_id text;

alter table classifications
  add column if not exists components jsonb not null default '{}'::jsonb,
  add column if not exists recommended_action text;

create table if not exists digest_delivery_events (
  id bigserial primary key,
  digest_id bigint not null references email_digests(id) on delete cascade,
  status text not null,                              -- sent | failed
  provider_message_id text,
  error text,
  created_at timestamptz not null default now()
);

-- ---- SaaS tenancy (single-user MVP still works: these can sit empty) ----

create table if not exists organizations (
  id bigserial primary key,
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists users (
  id bigserial primary key,
  email text not null unique,
  auth_provider_id text,                             -- Supabase auth uid when dashboard lands
  created_at timestamptz not null default now()
);

create table if not exists organization_members (
  organization_id bigint not null references organizations(id) on delete cascade,
  user_id bigint not null references users(id) on delete cascade,
  role text not null default 'member',               -- owner | admin | member
  primary key (organization_id, user_id)
);

create table if not exists company_profiles (
  id bigserial primary key,
  organization_id bigint references organizations(id) on delete cascade,
  profile jsonb not null,                            -- same shape as company_profile.example.json
  updated_at timestamptz not null default now()
);

create table if not exists saved_searches (
  id bigserial primary key,
  organization_id bigint references organizations(id) on delete cascade,
  user_id bigint references users(id) on delete set null,
  name text not null,
  criteria jsonb not null,                           -- keywords, naics, notice_types, min_score, ...
  created_at timestamptz not null default now()
);

create table if not exists tracked_opportunities (
  id bigserial primary key,
  organization_id bigint references organizations(id) on delete cascade,
  user_id bigint references users(id) on delete set null,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  status text not null default 'tracking',           -- tracking | pursuing | ignored
  created_at timestamptz not null default now(),
  unique (organization_id, opportunity_id)
);
create index if not exists idx_tracked_opp on tracked_opportunities (opportunity_id);

create table if not exists digest_subscriptions (
  id bigserial primary key,
  organization_id bigint references organizations(id) on delete cascade,
  user_id bigint references users(id) on delete cascade,
  email text not null,
  timezone text not null default 'America/Chicago',
  min_score int not null default 40,
  sections jsonb not null default '["act_today","high_match","tracked","early_stage","closing_soon","signals"]'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists opportunity_feedback (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  user_email text,
  user_id bigint references users(id) on delete set null,
  action text not null,                              -- good_match | bad_match | hide_similar | track | pursuing | ignore
  created_at timestamptz not null default now()
);
create index if not exists idx_feedback_opp on opportunity_feedback (opportunity_id);

-- Tenant isolation note: the browser must NEVER hold broad DB credentials.
-- When the dashboard ships, either (a) serve everything through a backend API
-- that scopes queries by organization_id, or (b) enable Supabase RLS with
-- policies keyed on auth.uid() -> users.auth_provider_id -> organization_members.
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
-- tracked statuses, action-token support.

alter table users
  add column if not exists password_hash text,
  add column if not exists is_admin boolean not null default false;

create table if not exists user_sessions (
  id bigserial primary key,
  user_id bigint not null references users(id) on delete cascade,
  token_hash text not null unique,          -- sha256 of the cookie token; raw token never stored
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz
);
create index if not exists idx_sessions_user on user_sessions (user_id);

-- Office identity fix: `office` becomes the BUYING OFFICE name (from the
-- hierarchy path); the mailing city moves to office_location.
alter table opportunities
  add column if not exists office_location text;

-- Tracked statuses now cover the capture pipeline:
-- watching | researching | pursuing | submitted | won | lost | ignored
alter table tracked_opportunities
  alter column status set default 'watching';

-- Stage transitions (Sources Sought -> RFP etc.) land in change_events with
-- event_type 'stage_transition'; no schema change needed, documented here.
-- office identity keys, lineage hardening, stat dedup, auth/security tables,
-- multi-user digest delivery, observability, entitlements, check constraints.

-- 1) Org-scoped feedback -----------------------------------------------------
alter table opportunity_feedback
  add column if not exists organization_id bigint references organizations(id) on delete cascade,
  add column if not exists notes text;
create index if not exists idx_feedback_org_opp on opportunity_feedback (organization_id, opportunity_id);
create index if not exists idx_feedback_org_action on opportunity_feedback (organization_id, action);
create index if not exists idx_feedback_user_time on opportunity_feedback (user_id, created_at desc);

-- 2) Per-organization opportunity matching -----------------------------------
create table if not exists profile_opportunity_matches (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  company_profile_id bigint references company_profiles(id) on delete set null,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  base_classification_score int,
  profile_match_score int,
  final_match_score int not null default 0,
  confidence int,
  category text,
  recommendation text,
  match_reasons_json jsonb not null default '[]'::jsonb,
  score_components_json jsonb not null default '{}'::jsonb,
  status text not null default 'new',
  hidden boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, opportunity_id)
);
create index if not exists idx_pom_org_score on profile_opportunity_matches (organization_id, final_match_score desc);
create index if not exists idx_pom_opp on profile_opportunity_matches (opportunity_id);

-- 3) Buyer office identity key (dedup) ----------------------------------------
alter table buyer_offices
  add column if not exists office_key text,
  add column if not exists office_key_method text;
create unique index if not exists uq_office_key on buyer_offices (office_key)
  where office_key is not null;
-- Backfill: run `python -m scripts.backfill_office_keys` (key derives from
-- Python office_key(); duplicates merge into the lowest id).

-- 4) Lineage hardening ---------------------------------------------------------
alter table opportunity_lineage
  add column if not exists stage_rank int not null default 0,
  add column if not exists first_seen_stage_at timestamptz not null default now(),
  add column if not exists last_seen_stage_at timestamptz not null default now();
create unique index if not exists uq_lineage_sol_opp_stage
  on opportunity_lineage (solicitation_number, opportunity_id, stage);

-- 5) Office market stats: null-safe identity ----------------------------------
alter table office_market_stats
  add column if not exists naics_key text generated always as (coalesce(naics, '')) stored,
  add column if not exists psc_key text generated always as (coalesce(psc, '')) stored;
alter table office_market_stats drop constraint if exists office_market_stats_buyer_office_id_fiscal_year_naics_psc_key;
create unique index if not exists uq_office_stats_identity
  on office_market_stats (buyer_office_id, fiscal_year, naics_key, psc_key);

-- 6) Multi-user digest delivery -------------------------------------------------
alter table digest_subscriptions
  add column if not exists categories jsonb not null default '[]'::jsonb,
  add column if not exists agencies jsonb not null default '[]'::jsonb,
  add column if not exists notice_types jsonb not null default '[]'::jsonb,
  add column if not exists instant_alerts boolean not null default false,
  add column if not exists daily_digest boolean not null default true;

create table if not exists digest_deliveries (
  id bigserial primary key,
  subscription_id bigint not null references digest_subscriptions(id) on delete cascade,
  organization_id bigint not null references organizations(id) on delete cascade,
  user_id bigint references users(id) on delete set null,
  digest_date date not null,
  generated_at timestamptz not null default now(),
  send_attempted_at timestamptz,
  sent_at timestamptz,
  send_status text not null default 'generated',
  send_error text,
  provider_message_id text,
  opportunity_count int not null default 0,
  html_body text,
  unique (subscription_id, digest_date)
);
create index if not exists idx_deliveries_org on digest_deliveries (organization_id, digest_date desc);

-- 7) Account security ------------------------------------------------------------
alter table users
  add column if not exists email_verified_at timestamptz;

create table if not exists login_attempts (
  id bigserial primary key,
  rate_key text not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_login_attempts on login_attempts (rate_key, created_at desc);

create table if not exists audit_log (
  id bigserial primary key,
  organization_id bigint,
  user_id bigint,
  event text not null,
  detail jsonb not null default '{}'::jsonb,
  ip text,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_org on audit_log (organization_id, created_at desc);

-- 8) Observability -----------------------------------------------------------------
create table if not exists job_runs (
  id bigserial primary key,
  job_name text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',   -- running|ok|failed
  records_fetched int not null default 0,
  records_inserted int not null default 0,
  records_amended int not null default 0,
  records_failed int not null default 0,
  api_calls int not null default 0,
  error_summary text
);
create index if not exists idx_job_runs on job_runs (job_name, started_at desc);

-- 9) Entitlements -----------------------------------------------------------------
alter table organizations
  add column if not exists plan text not null default 'early_access';

-- 10) Check constraints (belt and suspenders beyond app code) ----------------------
alter table profile_opportunity_matches
  add constraint ck_pom_score check (final_match_score between 0 and 100),
  add constraint ck_pom_status check (status in
    ('new','saved','watching','researching','pursuing','submitted','won','lost','ignored'));
alter table tracked_opportunities
  add constraint ck_tracked_status check (status in
    ('watching','researching','pursuing','submitted','won','lost','ignored'));
alter table opportunity_feedback
  add constraint ck_feedback_action check (action in
    ('track','save','ignore','pursuing','good_match','bad_match','hide_similar',
     'watching','researching','submitted','won','lost'));
alter table opportunities
  add constraint ck_enrichment_status check (enrichment_status in
    ('pending','running','done','failed','skipped'));
alter table digest_deliveries
  add constraint ck_delivery_status check (send_status in
    ('generated','sending','sent','failed','skipped'));
alter table organizations
  add constraint ck_org_plan check (plan in ('early_access','scout','pro','team'));
-- delivery), account deletion path, saved-view uniqueness.

-- Instant alerts: one delivery per (subscription, change event), ever.
create table if not exists instant_alert_deliveries (
  id bigserial primary key,
  subscription_id bigint not null references digest_subscriptions(id) on delete cascade,
  organization_id bigint not null references organizations(id) on delete cascade,
  change_event_id bigint not null references change_events(id) on delete cascade,
  sent_at timestamptz,
  send_status text not null default 'generated',
  send_error text,
  created_at timestamptz not null default now(),
  unique (subscription_id, change_event_id)
);
create index if not exists idx_instant_alerts_org on instant_alert_deliveries (organization_id, created_at desc);
alter table instant_alert_deliveries
  add constraint ck_instant_alert_status check (send_status in
    ('generated','sending','sent','failed','skipped'));

-- Account deletion: soft delete; login and sessions blocked immediately.
alter table users
  add column if not exists deleted_at timestamptz;

-- Saved views: one name per organization.
create unique index if not exists uq_saved_search_org_name
  on saved_searches (organization_id, name);
-- deterministic feedback learning, migration tracking.

-- Digests deliver at the subscriber's local time via an hourly worker.
alter table digest_subscriptions
  add column if not exists delivery_hour_local int not null default 6,
  add column if not exists delivery_minute_local int not null default 30;
alter table digest_subscriptions
  add constraint ck_delivery_hour check (delivery_hour_local between 0 and 23),
  add constraint ck_delivery_minute check (delivery_minute_local between 0 and 59);

-- Deterministic, bounded, explainable feedback learning.
create table if not exists org_preference_weights (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  feature text not null,               -- e.g. 'naics:541512', 'agency:DEPT OF THE ARMY'
  weight int not null default 0,
  updated_at timestamptz not null default now(),
  unique (organization_id, feature)
);
alter table org_preference_weights
  add constraint ck_pref_weight check (weight between -10 and 10);

-- Migration runner bookkeeping.
create table if not exists schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);
-- All data is public-record: unitedstates/congress-legislators (public domain),
-- FEC itemized-receipt aggregates, and operator-imported staff rosters.

create table if not exists legislators (
  id bigserial primary key,
  bioguide_id text not null unique,
  full_name text not null,
  chamber text not null,                -- 'sen' | 'rep'
  state text not null,                  -- USPS code
  district int,                         -- null for senators; 0 = at-large
  party text,
  phone text,
  office text,
  website text,
  contact_form text,
  state_rank text,                      -- senators: senior/junior
  fec_candidate_ids jsonb not null default '[]'::jsonb,
  committees jsonb not null default '[]'::jsonb,   -- [{code,name,title,rank}]
  term_end date,
  source text not null default 'unitedstates/congress-legislators',
  updated_at timestamptz not null default now()
);
create index if not exists idx_legislators_state on legislators (state, chamber, district);
alter table legislators
  add constraint ck_legislator_chamber check (chamber in ('sen', 'rep'));

-- Staff rosters are NOT in any free machine-readable source; rows arrive via
-- operator import (LegiStorm export, House Statement of Disbursements, or
-- manual research) and always carry source + as-of date.
create table if not exists legislator_staff (
  id bigserial primary key,
  legislator_id bigint not null references legislators(id) on delete cascade,
  name text not null,
  title text,
  role_tag text,            -- e.g. military_la, approps, district_director, grants
  email text,
  source text not null,
  source_date date,
  created_at timestamptz not null default now(),
  unique (legislator_id, name, title)
);

-- FEC aggregates. kind='employer_aggregate' = individual contributions summed
-- by reported employer (corporations CANNOT give to candidates); kind='pac' =
-- committee/PAC receipts. Labels in the UI must preserve this distinction.
create table if not exists legislator_funding (
  id bigserial primary key,
  legislator_id bigint not null references legislators(id) on delete cascade,
  cycle int not null,
  kind text not null,
  contributor_name text not null,
  total numeric not null,
  contribution_count int,
  source text not null default 'FEC schedule A aggregates',
  fetched_at timestamptz not null default now(),
  unique (legislator_id, cycle, kind, contributor_name)
);
alter table legislator_funding
  add constraint ck_funding_kind check (kind in ('employer_aggregate', 'pac'));

-- Cached place → district lookups (Census geocoder), keyed on normalized place.
create table if not exists district_lookups (
  id bigserial primary key,
  place_key text not null unique,       -- normalized "city|st|zip"
  state text,
  congressional_district int,
  method text not null,                 -- address_geocode|city_geocode|state_only
  confidence int not null,
  raw_json jsonb,
  resolved_at timestamptz not null default now()
);
alter table district_lookups
  add constraint ck_lookup_confidence check (confidence between 0 and 100);

-- Per-opportunity delegation cache (global, not org-scoped: representation is
-- a fact about the place, not about the viewer).
create table if not exists opportunity_delegations (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  legislator_id bigint not null references legislators(id) on delete cascade,
  match_method text not null,
  match_confidence int not null,
  committee_relevance jsonb not null default '[]'::jsonb,  -- [{code,name,why}]
  resolved_at timestamptz not null default now(),
  unique (opportunity_id, legislator_id)
);
alter table opportunity_delegations
  add constraint ck_delegation_confidence check (match_confidence between 0 and 100);
-- district (USAspending place-of-performance aggregates), election results for
-- computed partisan lean, and the data behind an explainable seat outlook.
-- ATTRIBUTION RULE (enforced in copy everywhere): district inflows are facts
-- about the PLACE; only congressionally-directed spending (CPF/earmarks) is
-- attributable to a member. We never say a member "brought in" general awards.

create table if not exists district_spending (
  id bigserial primary key,
  state text not null,                  -- USPS
  district int not null,                -- 0 = at-large
  fiscal_year int not null,
  agency text not null,                 -- toptier name; '' = all agencies
  obligations numeric not null default 0,
  award_count int,
  source text not null default 'USAspending spending_by_geography (place of performance)',
  fetched_at timestamptz not null default now(),
  unique (state, district, fiscal_year, agency)
);
create index if not exists idx_district_spending_rank
  on district_spending (fiscal_year, agency, obligations desc);

-- Election results: imported (MIT Election Lab / state SoS / operator CSV),
-- every row sourced. stage 'general' | 'primary'. district_key normalizes null
-- (statewide) to -1 so uniqueness works. Powers computed partisan lean, margin
-- trend, and primary-history questions.
create table if not exists election_results (
  id bigserial primary key,
  state text not null,
  district int,                         -- null for statewide (Senate)
  district_key int generated always as (coalesce(district, -1)) stored,
  office text not null,                 -- 'house' | 'senate' | 'president'
  cycle int not null,
  stage text not null default 'general',
  candidate_name text not null,
  party text,
  votes int,
  vote_share numeric,                   -- 0-100
  won boolean,
  incumbent boolean,
  source text not null,
  imported_at timestamptz not null default now(),
  unique (state, district_key, office, cycle, stage, candidate_name)
);
create index if not exists idx_election_results_seat
  on election_results (state, district_key, office, cycle desc);
alter table election_results
  add constraint ck_election_stage check (stage in ('general', 'primary', 'runoff')),
  add constraint ck_election_office check (office in ('house', 'senate', 'president')),
  add constraint ck_vote_share check (vote_share is null or vote_share between 0 and 100);

-- Congressionally-directed spending (CPF/earmarks): the ONE attributable
-- category. Rows imported from appropriations committee disclosures.
create table if not exists directed_spending (
  id bigserial primary key,
  fiscal_year int not null,
  member_bioguide_id text,
  member_name text not null,
  state text not null,
  district int,
  agency text,
  account text,
  project text not null,
  amount numeric not null,
  source text not null,
  imported_at timestamptz not null default now(),
  unique (fiscal_year, member_name, project, amount)
);
create index if not exists idx_directed_member
  on directed_spending (member_bioguide_id, fiscal_year desc);

-- FEC candidate-committee financial snapshots for outlook context.
create table if not exists candidate_finance (
  id bigserial primary key,
  legislator_id bigint references legislators(id) on delete cascade,
  state text not null,
  district int,
  office text not null,                 -- 'house' | 'senate'
  cycle int not null,
  candidate_name text not null,
  candidate_id text,
  is_incumbent boolean not null default false,
  receipts numeric,
  disbursements numeric,
  cash_on_hand numeric,
  fetched_at timestamptz not null default now(),
  unique (cycle, candidate_id)
);
create index if not exists idx_candidate_finance_seat
  on candidate_finance (state, district, office, cycle desc);
-- are fetched, text-extracted, and mined DETERMINISTICALLY for requirements.
-- Every extracted requirement keeps its evidence (quote + page + method) so the
-- UI can answer "why do you say that?" for each row. Documents are global facts
-- about the notice; qualification/gap analysis is org-scoped at read time.

create table if not exists opportunity_documents (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  source_url text not null,
  filename text,
  content_type text,
  byte_size int,
  sha256 text,
  page_count int,
  text_chars int,
  doc_kind text,                        -- pws|sow|rfp|amendment|qa|pricing|other
  fetch_status text not null default 'pending',
  fetch_error text,
  extracted_text text,
  fetched_at timestamptz,
  extracted_at timestamptz,
  created_at timestamptz not null default now(),
  unique (opportunity_id, source_url)
);
create index if not exists idx_docs_opp on opportunity_documents (opportunity_id);
alter table opportunity_documents
  add constraint ck_doc_fetch_status check (fetch_status in
    ('pending','fetched','extracted','failed','skipped','too_large','unsupported'));

create table if not exists document_requirements (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  document_id bigint references opportunity_documents(id) on delete cascade,
  requirement_type text not null,       -- clearance|vehicle|set_aside|certification|...
  value text not null,                  -- normalized token, e.g. 'TS/SCI', 'CMMC L2'
  evidence_quote text,                  -- short excerpt from the document
  page int,
  method text not null,                 -- extractor rule name (explainability)
  confidence int not null default 70,
  doc_key bigint generated always as (coalesce(document_id, 0)) stored,
  created_at timestamptz not null default now(),
  unique (opportunity_id, requirement_type, value, doc_key)
);
create index if not exists idx_reqs_opp on document_requirements (opportunity_id, requirement_type);
alter table document_requirements
  add constraint ck_req_confidence check (confidence between 0 and 100);
-- Capture intelligence: company evidence graph, capture tasks, and the
-- contract-family / Buyer DNA / evidence-ledger dossier sections (011).

create table if not exists company_projects (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  title text not null,
  customer_agency text,
  customer_office text,
  contract_identifier text,
  role text,                         -- prime | sub
  naics text,
  psc text,
  period_start date,
  period_end date,
  value_total numeric,
  scope text,
  technologies text,
  outcomes text,
  partners text,
  source_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_projects_org on company_projects (organization_id);
alter table company_projects
  add constraint ck_project_role check (role is null or role in ('prime', 'sub'));

create table if not exists capture_tasks (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  opportunity_id bigint references opportunities(id) on delete cascade,
  user_id bigint references users(id) on delete set null,
  title text not null,
  detail text,
  owner text,
  due_date date,
  status text not null default 'open',
  source text not null default 'manual',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_capture_tasks_org
  on capture_tasks (organization_id, status, due_date);
create index if not exists idx_capture_tasks_opp on capture_tasks (opportunity_id);
alter table capture_tasks
  add constraint ck_capture_status check (status in ('open', 'done', 'dropped')),
  add constraint ck_capture_source check (source in ('manual', 'generated'));

alter table opportunity_dossiers
  add column if not exists contract_family_json jsonb not null default '{}'::jsonb,
  add column if not exists buyer_dna_json jsonb not null default '{}'::jsonb,
  add column if not exists evidence_ledger_json jsonb not null default '[]'::jsonb;
-- Demand radar (012): procurement forecasts, links, competitive/teaming section.

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
-- IG findings, linked to opportunities as INFERRED demand context ("why this
-- requirement exists"). Rows arrive via provenance-enforced operator import
-- (GAO publishes CSV downloads; no row without a source URL).

create table if not exists oversight_findings (
  id bigserial primary key,
  source text not null,                    -- 'gao' | 'ig' | 'csv_import'
  source_record_id text not null,
  finding_type text not null,              -- recommendation | high_risk | ig_finding
  agency text,
  subtier text,
  title text not null,
  detail text,
  report_number text,
  published_date date,
  status text,                             -- open | closed | addressed | unknown
  source_url text not null,
  raw_json jsonb not null default '{}'::jsonb,
  imported_at timestamptz not null default now(),
  unique (source, source_record_id)
);
create index if not exists idx_oversight_agency on oversight_findings (agency);
alter table oversight_findings
  add constraint ck_oversight_type check (finding_type in
    ('recommendation', 'high_risk', 'ig_finding')),
  add constraint ck_oversight_status check (status is null or status in
    ('open', 'closed', 'addressed', 'unknown'));

create table if not exists opportunity_oversight_links (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  finding_id bigint not null references oversight_findings(id) on delete cascade,
  link_kind text not null default 'inferred',  -- cited | inferred
  similarity_score int not null,
  confidence int not null,
  evidence_json jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (opportunity_id, finding_id)
);
create index if not exists idx_oversight_links_opp
  on opportunity_oversight_links (opportunity_id, similarity_score desc);
alter table opportunity_oversight_links
  add constraint ck_oversight_link_kind check (link_kind in ('cited', 'inferred'));
-- (GAO publishes decisions searchable by agency and solicitation; docket
-- exports arrive as operator CSV). Protests power incumbent-vulnerability
-- signals and office protest-history context.

create table if not exists protest_records (
  id bigserial primary key,
  source text not null default 'gao_docket',   -- 'gao_docket' | 'csv_import'
  source_record_id text not null,              -- GAO B-number
  protester text,
  agency text,
  solicitation_number text,
  filed_date date,
  decided_date date,
  outcome text,                                -- sustained | denied | dismissed | withdrawn | corrective_action | pending
  summary text,
  source_url text not null,
  raw_json jsonb not null default '{}'::jsonb,
  imported_at timestamptz not null default now(),
  unique (source, source_record_id)
);
create index if not exists idx_protests_solnum on protest_records (solicitation_number);
create index if not exists idx_protests_agency on protest_records (agency);
alter table protest_records
  add constraint ck_protest_outcome check (outcome is null or outcome in
    ('sustained', 'denied', 'dismissed', 'withdrawn', 'corrective_action',
     'pending'));
