-- Protest history: GAO bid-protest docket records, imported with provenance
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
