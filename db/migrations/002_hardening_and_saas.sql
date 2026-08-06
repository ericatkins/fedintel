-- Migration 002: digest send-state, delivery events, SaaS tenancy, feedback.
-- Safe to run on an existing 001-era database. Fresh installs: run db/schema.sql instead.

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
