-- Migration 010: document intelligence. Solicitation attachments (PWS/SOW/RFP)
-- are fetched, text-extracted, and mined DETERMINISTICALLY for requirements.
-- Every extracted requirement keeps its evidence (quote + page + method) so the
-- UI can answer "why do you say that?" for each row. Documents are global facts
-- about the notice; qualification/gap analysis is org-scoped at read time.

create table if not exists opportunity_documents (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  source_url text not null,
  filename text,
  content_type text,
  byte_size int,
  sha256 text,
  page_count int,
  text_chars int,
  doc_kind text,                        -- pws|sow|rfp|amendment|qa|pricing|other
  fetch_status text not null default 'pending',
  fetch_error text,
  extracted_text text,
  fetched_at timestamptz,
  extracted_at timestamptz,
  created_at timestamptz not null default now(),
  unique (opportunity_id, source_url)
);
create index if not exists idx_docs_opp on opportunity_documents (opportunity_id);
alter table opportunity_documents
  add constraint ck_doc_fetch_status check (fetch_status in
    ('pending','fetched','extracted','failed','skipped','too_large','unsupported'));

create table if not exists document_requirements (
  id bigserial primary key,
  opportunity_id bigint not null references opportunities(id) on delete cascade,
  document_id bigint references opportunity_documents(id) on delete cascade,
  requirement_type text not null,       -- clearance|vehicle|set_aside|certification|...
  value text not null,                  -- normalized token, e.g. 'TS/SCI', 'CMMC L2'
  evidence_quote text,                  -- short excerpt from the document
  page int,
  method text not null,                 -- extractor rule name (explainability)
  confidence int not null default 70,
  doc_key bigint generated always as (coalesce(document_id, 0)) stored,
  created_at timestamptz not null default now(),
  unique (opportunity_id, requirement_type, value, doc_key)
);
create index if not exists idx_reqs_opp on document_requirements (opportunity_id, requirement_type);
alter table document_requirements
  add constraint ck_req_confidence check (confidence between 0 and 100);
