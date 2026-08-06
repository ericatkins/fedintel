-- Migration 001: original MVP baseline (opportunities, lineage, classifications,
-- email_digests, change_events, alert_rules). Fresh installs use db/schema.sql.

create table if not exists opportunities (
  id bigserial primary key,
  source text not null default 'sam.gov',
  source_notice_id text not null,
  solicitation_number text,
  title text not null,
  agency text,
  office text,
  jurisdiction text not null default 'federal',
  notice_type text,
  naics text,
  set_aside text,
  posted_date date,
  response_deadline timestamptz,
  place_of_performance text,
  description_text text,
  url text,
  raw_json jsonb not null,
  content_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (source, source_notice_id)
);
create index if not exists idx_opp_posted on opportunities (posted_date desc);
create index if not exists idx_opp_solnum on opportunities (solicitation_number);
create index if not exists idx_opp_hash on opportunities (content_hash);

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
  confidence text not null,
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

create table if not exists change_events (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  event_type text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  notified boolean not null default false
);

create table if not exists alert_rules (
  id bigserial primary key,
  user_email text not null,
  notice_types text[] default '{}',
  min_score int default 70,
  jurisdictions text[] default '{federal}',
  keywords text[] default '{}',
  channel text not null default 'email',
  immediacy text not null default 'digest',
  created_at timestamptz not null default now()
);
