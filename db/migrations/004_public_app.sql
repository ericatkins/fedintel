-- Migration 004: public web app — auth sessions, office identity fix,
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
