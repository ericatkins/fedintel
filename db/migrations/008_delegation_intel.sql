-- Migration 008: congressional delegation intelligence.
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
