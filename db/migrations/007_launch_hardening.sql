-- Migration 007: launch hardening — timezone-honest digest delivery,
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
