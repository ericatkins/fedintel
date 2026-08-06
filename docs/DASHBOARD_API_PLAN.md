# Dashboard API Plan (build after backend hardening — do not start UI first)

Backend-for-frontend on Railway (FastAPI) or Supabase RLS. Browsers never get
broad DB credentials (see SECURITY.md rule 6). Every endpoint is scoped by
organization_id derived from the authenticated user, never from the request.

## Screens -> endpoints (all data already exists in the schema)

| Screen | Endpoint | Backing data |
|---|---|---|
| Home dashboard | GET /api/dashboard | today's counts, top matches (classifications), deadlines, change_events |
| Opportunities table | GET /api/opportunities?filters | opportunities + classifications (score, category, components) |
| Opportunity detail | GET /api/opportunities/{id} | + change_events (change history), opportunity_lineage (stage history), similar via keywords_matched overlap |
| Agency intelligence | GET /api/agencies/{name} | aggregates over opportunities by agency |
| Saved searches | CRUD /api/saved-searches | saved_searches |
| Tracked opportunities | CRUD /api/tracked | tracked_opportunities |
| Reports | GET /api/reports/{kind} | aggregates; email_digests archive |
| Company profile | CRUD /api/profile | company_profiles |
| Alert preferences | CRUD /api/subscriptions | digest_subscriptions, alert_rules |
| Feedback actions | POST /a/{opp_id}/{action}?t= | verified by actions.verify(); writes opportunity_feedback |

## Opportunity detail payload
summary, why-matched (classifications.reasons + components), requirements
(description_text), key dates, place of performance, NAICS, set-aside,
documents/links (safe_sam_url), change history, similar opportunities,
recommended capture actions (classifications.recommended_action).
