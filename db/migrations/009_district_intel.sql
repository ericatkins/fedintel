-- Migration 009: district intelligence — federal money into each congressional
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
