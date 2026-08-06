-- Capture intelligence release: company evidence graph, capture tasks,
-- contract-family / Buyer DNA / evidence-ledger dossier sections.

-- 1) Company evidence graph -------------------------------------------------
-- Per-organization past-project records. PRIVATE tenant data: never global,
-- never fed to another org's results. Powers past-performance and
-- buyer-position dimensions plus requirement-to-proof mapping.
create table if not exists company_projects (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  title text not null,
  customer_agency text,
  customer_office text,
  contract_identifier text,
  role text,                         -- prime | sub
  naics text,
  psc text,
  period_start date,
  period_end date,
  value_total numeric,
  scope text,
  technologies text,                 -- comma-separated capability tokens
  outcomes text,
  partners text,
  source_note text,                  -- provenance: where this evidence comes from
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_projects_org on company_projects (organization_id);
alter table company_projects
  add constraint ck_project_role check (role is null or role in ('prime', 'sub'));

-- 2) Capture tasks ------------------------------------------------------------
-- Turns dossier recommendations into owned, dated work items. Per-org.
create table if not exists capture_tasks (
  id bigserial primary key,
  organization_id bigint not null references organizations(id) on delete cascade,
  opportunity_id bigint references opportunities(id) on delete cascade,
  user_id bigint references users(id) on delete set null,
  title text not null,
  detail text,
  owner text,
  due_date date,
  status text not null default 'open',
  source text not null default 'manual',   -- manual | generated
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_capture_tasks_org
  on capture_tasks (organization_id, status, due_date);
create index if not exists idx_capture_tasks_opp on capture_tasks (opportunity_id);
alter table capture_tasks
  add constraint ck_capture_status check (status in ('open', 'done', 'dropped')),
  add constraint ck_capture_source check (source in ('manual', 'generated'));

-- 3) New dossier sections -------------------------------------------------------
alter table opportunity_dossiers
  add column if not exists contract_family_json jsonb not null default '{}'::jsonb,
  add column if not exists buyer_dna_json jsonb not null default '{}'::jsonb,
  add column if not exists evidence_ledger_json jsonb not null default '[]'::jsonb;
