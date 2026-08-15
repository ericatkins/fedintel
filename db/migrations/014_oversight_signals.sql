-- Oversight demand signals: GAO recommendations / high-risk areas and agency
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
