-- Migration 005: public-beta readiness — org-scoped feedback, per-org matching,
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
