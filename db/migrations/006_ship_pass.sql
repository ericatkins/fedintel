-- Migration 006: ship pass — instant stage-transition alerts (idempotent
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
