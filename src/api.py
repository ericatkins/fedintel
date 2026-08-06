"""Intelligence API (FastAPI, optional — pip install -r requirements-api.txt).

Serves stored dossiers only; it never triggers live external API calls in the
request path. Missing dossier -> basic details + 'intelligence generation
pending' + queued enrichment (performance rule from the spec).

Security: read-only endpoints return sanitized stored JSON, never raw_json.
Admin regenerate requires the ADMIN_TOKEN env var via X-Admin-Token header.
Single-user MVP; when SaaS auth lands, org scoping slots in here (SECURITY.md).
"""
import hmac
import os

from fastapi import FastAPI, Header, HTTPException

from . import db, db_intel

# ADMIN/OPS ONLY. This service is DISABLED unless INTEL_API_ENABLED=1, and every
# endpoint requires X-Admin-Token. User-facing intelligence lives in the
# authenticated web app (src/web/app.py). Do not deploy this publicly.
if os.getenv("INTEL_API_ENABLED", "") != "1":
    raise RuntimeError(
        "The intelligence API is admin-only and disabled by default. "
        "Set INTEL_API_ENABLED=1 and ADMIN_TOKEN to run it privately; "
        "user-facing routes are in src.web.app.")

app = FastAPI(title="Fedintel Intelligence API (admin)", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _require_admin_everywhere(request, call_next):
    from fastapi.responses import JSONResponse
    expected = os.getenv("ADMIN_TOKEN", "")
    supplied = request.headers.get("x-admin-token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return JSONResponse({"detail": "admin token required"}, status_code=403)
    return await call_next(request)


def _cursor():
    conn = db.get_conn()
    conn.autocommit = True
    return conn


def _require_admin(token: str | None):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="admin token required")


@app.get("/api/opportunities/{opp_id}/dossier")
def get_dossier(opp_id: int):
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            d = db_intel.fetch_dossier(cur, opp_id)
            if d:
                return d
            cur.execute("select title, agency, notice_type, enrichment_status "
                        "from opportunities where id=%s", (opp_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="opportunity not found")
            if row[3] in ("done", "running"):
                status = row[3]
            else:
                db_intel.mark_enrichment(cur, opp_id, "pending")
                status = "pending"
            return {"opportunity": {"title": row[0], "agency": row[1], "notice_type": row[2]},
                    "intelligence": "generation pending", "enrichment_status": status}
    finally:
        conn.close()


@app.post("/api/opportunities/{opp_id}/dossier/regenerate")
def regenerate(opp_id: int, x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            db_intel.mark_enrichment(cur, opp_id, "pending")
        return {"status": "queued", "opportunity_id": opp_id}
    finally:
        conn.close()


def _section(opp_id: int, key: str):
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            d = db_intel.fetch_dossier(cur, opp_id)
        if not d:
            raise HTTPException(status_code=404, detail="dossier not generated yet")
        return d[key]
    finally:
        conn.close()


@app.get("/api/opportunities/{opp_id}/similar-awards")
def similar_awards(opp_id: int):
    return _section(opp_id, "similar_work")


@app.get("/api/opportunities/{opp_id}/incumbent-analysis")
def incumbent(opp_id: int):
    return _section(opp_id, "incumbent_analysis")


@app.get("/api/opportunities/{opp_id}/funding-context")
def funding(opp_id: int):
    return _section(opp_id, "funding_context")


@app.get("/api/opportunities/{opp_id}/market-stats")
def market(opp_id: int):
    return _section(opp_id, "market_size")


@app.get("/api/opportunities/{opp_id}/report")
def report(opp_id: int):
    from fastapi.responses import HTMLResponse

    from .intel.report import render_report
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            d = db_intel.fetch_dossier(cur, opp_id)
            if not d:
                raise HTTPException(status_code=404, detail="dossier not generated yet")
            cur.execute("select url, source_notice_id from opportunities where id=%s", (opp_id,))
            row = cur.fetchone() or (None, None)
        return HTMLResponse(render_report(d, row[0], row[1]))
    finally:
        conn.close()


@app.get("/api/offices/{office_id}/profile")
def office_profile(office_id: int):
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """select department_name, subtier_name, office_name, organization_code,
                          full_parent_path_name, location_json, source_confidence
                   from buyer_offices where id=%s""", (office_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="office not found")
        keys = ("department_name", "subtier_name", "office_name", "organization_code",
                "full_parent_path_name", "location", "source_confidence")
        return dict(zip(keys, row, strict=True))
    finally:
        conn.close()


@app.get("/api/offices/{office_id}/awards")
def office_awards(office_id: int, limit: int = 25):
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """select a.award_date, a.recipient_name, a.award_title, a.obligated_amount,
                          a.piid, a.naics, a.psc, a.award_type
                   from contract_awards a
                   join buyer_offices o on o.id=%s
                   where (o.organization_code is not null and a.awarding_office_code=o.organization_code)
                      or (o.office_name is not null and upper(a.awarding_office)=upper(o.office_name))
                   order by a.award_date desc nulls last limit %s""",
                (office_id, min(limit, 100)))
            keys = ("award_date", "vendor", "title", "obligated_amount", "piid",
                    "naics", "psc", "award_type")
            return [dict(zip(keys, r, strict=True)) for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/vendors/{vendor_id}/profile")
def vendor_profile(vendor_id: int):
    conn = _cursor()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """select recipient_name, recipient_uei, total_obligations, award_count,
                          first_award_date, last_award_date, top_agencies_json,
                          top_naics_json, top_offices_json
                   from vendor_profiles where id=%s""", (vendor_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="vendor not found")
        keys = ("recipient_name", "recipient_uei", "total_obligations", "award_count",
                "first_award_date", "last_award_date", "top_agencies", "top_naics", "top_offices")
        return dict(zip(keys, row, strict=True))
    finally:
        conn.close()
