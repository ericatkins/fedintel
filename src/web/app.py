"""Fedintel web app — authenticated backend-for-frontend (Option A).

Security model:
- Browser talks ONLY to this FastAPI app; it never holds DB credentials.
- org_id comes exclusively from the authenticated session (store layer);
  it is never read from the request.
- All HTML renders through a Jinja Environment with autoescape ON.
- Strict security headers incl. CSP: scripts/styles only from /static.
- Action links verified with expiring HMAC tokens (src/actions.py).

Run: uvicorn src.web.app:app  (see docs/DEPLOYMENT.md)
"""
import csv
import io
import os
from datetime import datetime, timezone

from fastapi import Cookie, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import actions
from ..safety import safe_sam_url
from .auth import hash_password, new_session_token, password_policy_error, verify_password
from .store import TRACK_STATUSES, PgStore

app = FastAPI(title="Fedintel", docs_url=None, redoc_url=None)
app.state.store = None  # created lazily; tests inject MemoryStore

_TEMPLATES = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
    autoescape=select_autoescape(default=True, default_for_string=True),
)
_TEMPLATES.globals["safe_sam_url"] = safe_sam_url

SESSION_COOKIE = "fedintel_session"
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_TYPES = {".css": "text/css", ".js": "application/javascript"}


def store():
    if app.state.store is None:
        app.state.store = PgStore()
    return app.state.store


def render(name: str, **ctx) -> HTMLResponse:
    html = _TEMPLATES.get_template(name).render(**ctx)
    return HTMLResponse(html)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if os.getenv("COOKIE_SECURE", "1") != "0":
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


def current_user(session: str | None):
    if not session:
        return None
    return store().user_org_for_session(session)


def require_user(session: str | None):
    user = current_user(session)
    if not user:
        raise HTTPException(status_code=303, detail="login required",
                            headers={"Location": "/login"})
    return user


def csrf_for(session: str) -> str:
    """CSRF token derived from the session cookie: an attacker who can't read
    the cookie can't forge the token. Verified on every authenticated POST."""
    import hashlib
    return hashlib.sha256(f"csrf:{session}".encode()).hexdigest()[:32]


def require_csrf(session: str | None, csrf_token: str):
    import hmac as _hmac
    if not session or not _hmac.compare_digest(csrf_for(session), csrf_token or ""):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def rate_limit(request: Request, key: str, limit: int, window_seconds: int = 900):
    """DB/memory-backed limiter per (route-class, identifier, client IP)."""
    ip = request.client.host if request.client else "unknown"
    for rate_key in (f"{key}:{ip}", key):
        if not store().rate_limit_allow(rate_key, limit, window_seconds):
            raise HTTPException(status_code=429,
                                detail="Too many attempts. Try again later.")


def audit(request: Request, event: str, user=None, **detail):
    ip = request.client.host if request.client else None
    store().audit(event, org_id=(user or {}).get("org_id"),
                  user_id=(user or {}).get("user_id"), ip=ip, detail=detail)


@app.get("/static/{name}")
def static_file(name: str):
    # allowlist: flat directory, known extensions, no separators
    ext = os.path.splitext(name)[1]
    if "/" in name or "\\" in name or ".." in name or ext not in _STATIC_TYPES:
        raise HTTPException(status_code=404)
    path = os.path.join(_STATIC_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404)
    with open(path, encoding="utf-8") as f:
        return Response(f.read(), media_type=_STATIC_TYPES[ext],
                        headers={"Cache-Control": "public, max-age=3600"})


# ---------- public pages ----------

@app.get("/", response_class=HTMLResponse)
def landing(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    if current_user(session):
        return RedirectResponse("/app", status_code=303)
    return render("landing.html")


def require_entitlement(user: dict, flag: str):
    """Server-side plan gate. Hiding a nav link is not access control."""
    from .entitlements import allows
    if not allows(store().org_plan(user["org_id"]), flag):
        raise HTTPException(status_code=403,
                            detail=f"Your plan does not include {flag.replace('_', ' ')}.")


def _early_access_required() -> bool:
    return bool(os.getenv("EARLY_ACCESS_CODE"))


@app.get("/signup", response_class=HTMLResponse)
def signup_page():
    return render("signup.html", error=None, gated=_early_access_required())


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...),
           org_name: str = Form(...), access_code: str = Form("")):
    rate_limit(request, "signup", limit=10)
    email = email.strip().lower()
    err = password_policy_error(password)
    if not email or "@" not in email:
        err = err or "A valid email is required."
    if not org_name.strip():
        err = err or "Organization name is required."
    if _early_access_required():
        import hmac as _hmac
        if not _hmac.compare_digest(access_code.strip(), os.environ["EARLY_ACCESS_CODE"]):
            err = err or "Fedintel is in early access — a valid invite code is required."
    if not err and store().get_user_by_email(email):
        err = "An account with that email already exists."
    if err:
        return render("signup.html", error=err, gated=_early_access_required())
    user_id, _org_id = store().create_user_with_org(email, hash_password(password),
                                                    org_name.strip())
    _send_verification_email(user_id, email)
    return _login_response(user_id, "/onboarding")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return render("login.html", error=None)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    rate_limit(request, f"login:{email}", limit=8)
    user = store().get_user_by_email(email)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        audit(request, "login_failed", detail_email=email)
        return render("login.html", error="Invalid email or password.")
    if (os.getenv("REQUIRE_EMAIL_VERIFICATION", "1") != "0"
            and not user.get("email_verified_at")):
        audit(request, "login_blocked_unverified",
              user={"user_id": user["id"], "org_id": None})
        return render("verify_needed.html", email=user["email"])
    audit(request, "login", user={"user_id": user["id"], "org_id": None})
    return _login_response(user["id"], "/app")


def _login_response(user_id: int, dest: str):
    token, token_hash, expires = new_session_token()
    store().create_session(user_id, token_hash, expires)
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                    secure=os.getenv("COOKIE_SECURE", "1") != "0",
                    max_age=14 * 24 * 3600, path="/")
    return resp


@app.get("/logout")
def logout(request: Request,
           session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    if session:
        user = current_user(session)
        store().revoke_session(session)
        if user:
            audit(request, "logout", user=user)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.post("/app/logout-all")
def logout_all(request: Request, csrf_token: str = Form(""),
               session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    store().revoke_all_sessions(user["user_id"])
    audit(request, "logout_all_sessions", user=user)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ---------- email verification & password reset (signed, expiring tokens) ------

def _send_verification_email(user_id: int, email: str):
    from .. import tokens
    if not tokens.enabled():
        return
    token, exp = tokens.sign("verify_email", a=user_id)
    link = f"{os.getenv('ACTION_BASE_URL', '').rstrip('/')}/verify?u={user_id}&e={exp}&t={token}"
    _deliver_email(email, "Verify your Fedintel email",
                   f"Confirm your email address by opening: {link}")


def _deliver_email(to_email: str, subject: str, body: str):
    """Send via Resend when configured; otherwise log the link so a beta
    operator can relay it manually. Never blocks the request path."""
    try:
        from ..send_email import send_plain
        send_plain(to_email, subject, body)
    except Exception as exc:  # noqa: BLE001 — account emails are best-effort in beta
        from ..log import log
        log("account_email_not_sent", to=to_email, subject=subject,
            reason=type(exc).__name__)


@app.post("/verify/resend")
def resend_verification(request: Request, email: str = Form(...)):
    rate_limit(request, f"verify:{email.strip().lower()}", limit=5)
    user = store().get_user_by_email(email.strip().lower())
    if user and not user.get("email_verified_at"):
        _send_verification_email(user["id"], user["email"])
    return render("verify_needed.html", email=email.strip().lower(), resent=True)


@app.get("/verify", response_class=HTMLResponse)
def verify_email(u: int = Query(default=0), e: int = Query(default=0),
                 t: str = Query(default="")):
    from .. import tokens
    if not tokens.verify("verify_email", t, a=u, exp=e):
        return render("action_result.html", ok=False,
                      message="This verification link is invalid or has expired.")
    store().mark_email_verified(u)
    return render("action_result.html", ok=True, message="Email verified — thank you.")


@app.get("/forgot", response_class=HTMLResponse)
def forgot_page():
    return render("forgot.html", sent=False)


@app.post("/forgot")
def forgot(request: Request, email: str = Form(...)):
    rate_limit(request, f"forgot:{email.strip().lower()}", limit=5)
    from .. import tokens
    user = store().get_user_by_email(email.strip().lower())
    if user and tokens.enabled():
        token, exp = tokens.sign("reset_password", a=user["id"])
        link = (f"{os.getenv('ACTION_BASE_URL', '').rstrip('/')}"
                f"/reset?u={user['id']}&e={exp}&t={token}")
        _deliver_email(user["email"], "Reset your Fedintel password",
                       f"Reset your password by opening: {link} (valid 2 hours)")
        audit(request, "password_reset_requested",
              user={"user_id": user["id"], "org_id": None})
    # Same response whether or not the account exists (no user enumeration).
    return render("forgot.html", sent=True)


@app.get("/reset", response_class=HTMLResponse)
def reset_page(u: int = Query(default=0), e: int = Query(default=0),
               t: str = Query(default="")):
    from .. import tokens
    if not tokens.verify("reset_password", t, a=u, exp=e):
        return render("action_result.html", ok=False,
                      message="This reset link is invalid or has expired.")
    return render("reset.html", u=u, e=e, t=t, error=None)


@app.post("/reset")
def reset(request: Request, u: int = Form(...), e: int = Form(...), t: str = Form(...),
          password: str = Form(...)):
    from .. import tokens
    if not tokens.verify("reset_password", t, a=int(u), exp=int(e)):
        return render("action_result.html", ok=False,
                      message="This reset link is invalid or has expired.")
    err = password_policy_error(password)
    if err:
        return render("reset.html", u=u, e=e, t=t, error=err)
    store().set_password(int(u), hash_password(password))
    store().revoke_all_sessions(int(u))   # every existing session dies
    audit(request, "password_reset_completed", user={"user_id": int(u), "org_id": None})
    return render("action_result.html", ok=True,
                  message="Password updated. Log in with your new password.")


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(s: int = Query(default=0), e: int = Query(default=0),
                t: str = Query(default="")):
    from .. import tokens
    if not tokens.verify("unsub", t, a=s, exp=e):
        return render("action_result.html", ok=False,
                      message="This unsubscribe link is invalid or has expired.")
    store().deactivate_subscription(int(s))
    return render("action_result.html", ok=True,
                  message="You are unsubscribed from the daily digest. "
                          "Re-enable it anytime under Alerts.")


# ---------- authenticated app ----------

@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    profile = store().get_profile(user["org_id"]) or {}
    return render("profile.html", user=user, profile=profile, saved=False,
                  csrf=csrf_for(session), title="Set up your company profile")


@app.get("/app/profile", response_class=HTMLResponse)
def profile_page(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    profile = store().get_profile(user["org_id"]) or {}
    return render("profile.html", user=user, profile=profile, saved=False,
                  csrf=csrf_for(session), title="Company profile",
                  learned=store().preference_weights(user["org_id"]),
                  projects=store().list_projects(user["org_id"]))


PROFILE_LIST_FIELDS = ("capabilities", "industries", "naics_codes", "agencies_of_interest",
                       "locations", "set_aside_eligibility", "keywords_boost",
                       "keywords_suppress", "excluded_categories",
                       # qualification fields — drive document-based disqualifiers
                       "contract_vehicles", "clearances", "certifications")


@app.post("/app/profile")
def save_profile(request: Request,
                 session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                 csrf_token: str = Form(""),
                 name: str = Form(""), capabilities: str = Form(""), industries: str = Form(""),
                 naics_codes: str = Form(""), agencies_of_interest: str = Form(""),
                 locations: str = Form(""), set_aside_eligibility: str = Form(""),
                 keywords_boost: str = Form(""), keywords_suppress: str = Form(""),
                 excluded_categories: str = Form(""), contract_vehicles: str = Form(""),
                 clearances: str = Form(""), certifications: str = Form("")):
    user = require_user(session)
    require_csrf(session, csrf_token)
    values = {"name": name.strip(), "capabilities": capabilities, "industries": industries,
              "naics_codes": naics_codes, "agencies_of_interest": agencies_of_interest,
              "locations": locations, "set_aside_eligibility": set_aside_eligibility,
              "keywords_boost": keywords_boost, "keywords_suppress": keywords_suppress,
              "excluded_categories": excluded_categories,
              "contract_vehicles": contract_vehicles, "clearances": clearances,
              "certifications": certifications}
    profile = {"name": values["name"]}
    for field in PROFILE_LIST_FIELDS:
        profile[field] = [x.strip() for x in values[field].split(",") if x.strip()][:50]
    store().upsert_profile(user["org_id"], profile)
    store().request_match_refresh(user["org_id"])
    audit(request, "profile_update", user=user)
    return render("profile.html", user=user, profile=profile, saved=True,
                  csrf=csrf_for(session), title="Company profile",
                  learned=store().preference_weights(user["org_id"]),
                  projects=store().list_projects(user["org_id"]))


def _clean_date(value: str):
    from datetime import date as _date
    try:
        return _date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _clean_number(value: str):
    try:
        return float(value.replace(",", "").replace("$", "").strip()) \
            if value.strip() else None
    except ValueError:
        return None


@app.post("/app/profile/projects")
def add_project(request: Request,
                session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                csrf_token: str = Form(""), title: str = Form(""),
                customer_agency: str = Form(""), customer_office: str = Form(""),
                contract_identifier: str = Form(""), role: str = Form(""),
                naics: str = Form(""), psc: str = Form(""),
                period_start: str = Form(""), period_end: str = Form(""),
                value_total: str = Form(""), scope: str = Form(""),
                technologies: str = Form(""), outcomes: str = Form(""),
                partners: str = Form(""), source_note: str = Form("")):
    user = require_user(session)
    require_csrf(session, csrf_token)
    if not title.strip():
        return RedirectResponse("/app/profile", status_code=303)
    store().add_project(user["org_id"], {
        "title": title.strip()[:300],
        "customer_agency": customer_agency.strip()[:200],
        "customer_office": customer_office.strip()[:200],
        "contract_identifier": contract_identifier.strip()[:100],
        "role": role if role in ("prime", "sub") else None,
        "naics": naics.strip()[:10], "psc": psc.strip()[:10],
        "period_start": _clean_date(period_start),
        "period_end": _clean_date(period_end),
        "value_total": _clean_number(value_total),
        "scope": scope.strip()[:4000], "technologies": technologies.strip()[:1000],
        "outcomes": outcomes.strip()[:2000], "partners": partners.strip()[:500],
        "source_note": source_note.strip()[:500]})
    store().request_match_refresh(user["org_id"])
    audit(request, "project_added", user=user)
    return RedirectResponse("/app/profile#projects", status_code=303)


@app.post("/app/profile/projects/{project_id}/delete")
def delete_project(request: Request, project_id: int, csrf_token: str = Form(""),
                   session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    store().delete_project(user["org_id"], project_id)
    audit(request, "project_deleted", user=user, project_id=project_id)
    return RedirectResponse("/app/profile#projects", status_code=303)


@app.post("/app/opportunities/{opp_id}/tasks")
def add_capture_task(request: Request, opp_id: int, csrf_token: str = Form(""),
                     title: str = Form(""), detail: str = Form(""),
                     owner: str = Form(""), due_date: str = Form(""),
                     source: str = Form("manual"),
                     session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    if not store().get_opportunity(user["org_id"], opp_id):
        raise HTTPException(status_code=404, detail="opportunity not found")
    if title.strip():
        store().add_capture_task(
            user["org_id"], title.strip()[:300], detail=detail.strip()[:1000],
            opportunity_id=opp_id, user_id=user["user_id"],
            owner=owner.strip()[:100], due_date=_clean_date(due_date),
            source="generated" if source == "generated" else "manual")
        audit(request, "capture_task_added", user=user, opportunity_id=opp_id)
    return RedirectResponse(f"/app/opportunities/{opp_id}#capture",
                            status_code=303)


@app.post("/app/tasks/{task_id}/status")
def set_task_status(request: Request, task_id: int, status: str = Form(...),
                    csrf_token: str = Form(""),
                    session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    if status not in ("open", "done", "dropped"):
        raise HTTPException(status_code=400, detail="invalid status")
    store().set_capture_task_status(user["org_id"], task_id, status)
    audit(request, "capture_task_status", user=user, task_id=task_id,
          status=status)
    dest = request.headers.get("referer") or "/app/watchlist"
    from urllib.parse import urlparse
    parsed = urlparse(dest)
    safe_dest = parsed.path if parsed.path.startswith("/app") else "/app/watchlist"
    return RedirectResponse(safe_dest, status_code=303)


@app.get("/app", response_class=HTMLResponse)
def dashboard(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    st = store()
    counts = st.dashboard_counts(user["org_id"], os.getenv("TIMEZONE", "America/Chicago"))
    return render("dashboard.html", user=user, counts=counts,
                  top=st.list_opportunities(user["org_id"], min_score=70, limit=8),
                  events=st.recent_events(limit=10),
                  closing=st.closing_soon(user["org_id"]),
                  transitions=st.stage_transitions_for_org(user["org_id"]),
                  pipeline=st.pipeline_report(user["org_id"]),
                  delivery=st.latest_delivery(user["org_id"]))


@app.get("/app/opportunities", response_class=HTMLResponse)
def opportunities(session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                  q: str = Query(default=""), min_score: int = Query(default=40),
                  notice_type: str = Query(default=""), view: int = Query(default=0)):
    user = require_user(session)
    if view:
        saved = store().get_view(user["org_id"], view)   # org-scoped lookup
        if saved:
            criteria = saved["criteria"] or {}
            q = criteria.get("q", q)
            min_score = int(criteria.get("min_score", min_score))
            notice_type = criteria.get("notice_type", notice_type)
    rows = store().list_opportunities(user["org_id"], q=q.strip() or None,
                                      min_score=max(0, min(100, min_score)),
                                      notice_type=notice_type.strip() or None, limit=200)
    return render("opportunities.html", user=user, rows=rows, q=q,
                  min_score=min_score, notice_type=notice_type,
                  views=store().list_views(user["org_id"]),
                  csrf=csrf_for(session))


@app.get("/app/opportunities/{opp_id}", response_class=HTMLResponse)
def opportunity_detail(opp_id: int,
                       session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    opp = store().get_opportunity(user["org_id"], opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="opportunity not found")
    dossier = store().get_dossier(opp_id)
    if not dossier:
        store().mark_enrichment_pending(opp_id)
    lineage = store().get_lineage(opp.get("solicitation_number")) \
        if opp.get("solicitation_number") else []
    value_est = None
    if dossier:
        from ..intel.value_estimate import estimate
        value_est = estimate(dossier.get("last_10_relevant_awards") or [])
    from .entitlements import allows
    plan = store().org_plan(user["org_id"])
    delegation = (store().delegation_for_opportunity(opp_id)
                  if allows(plan, "delegation_intel") else None)
    projects = store().list_projects(user["org_id"])
    documents = requirements = qualification = proof = None
    if allows(plan, "document_intel"):
        documents = store().documents_for_opportunity(opp_id)
        requirements = store().requirements_for_opportunity(opp_id)
        if requirements:
            from ..documents.qualification import assess
            from ..intel.proof import map_requirements_to_proof
            qualification = assess(requirements,
                                   store().get_profile(user["org_id"]) or {})
            proof = map_requirements_to_proof(qualification["rows"], projects,
                                              opp)
    from datetime import date
    from datetime import timezone as _tz

    from ..intel.decision import build_decision_stack
    days_left = None
    if opp.get("response_deadline"):
        rd = opp["response_deadline"]
        rd = rd if getattr(rd, "tzinfo", None) else rd.replace(tzinfo=_tz.utc)
        days_left = (rd.date() - date.today()).days
    opp_forecasts = (store().forecasts_for_opportunity(opp_id)
                     if allows(plan, "demand_radar") else None)
    decision = build_decision_stack(
        opp=opp,
        match={"score": opp.get("score"), "reasons": opp.get("reasons") or []},
        dossier=dossier, qualification=qualification, value_est=value_est,
        documents=documents, days_left=days_left,
        projects=projects,
        weights=store().preference_weights(user["org_id"]),
        forecasts=opp_forecasts)
    req_delta = None
    if requirements and lineage:
        from ..intel.requirement_delta import lineage_requirement_delta
        reqs_by_opp = {opp_id: requirements}
        for step in lineage:
            sid = step.get("opportunity_id")
            if sid and sid != opp_id and sid not in reqs_by_opp:
                reqs_by_opp[sid] = store().requirements_for_opportunity(sid)
        req_delta = lineage_requirement_delta(opp_id, lineage, reqs_by_opp)
    tasks = store().list_capture_tasks(user["org_id"], opportunity_id=opp_id)
    from ..intel.ledger import build_evidence_ledger
    ledger = build_evidence_ledger(opp, dossier, documents, delegation,
                                   forecasts=opp_forecasts)
    history = store().change_history_for_opportunity(opp_id)
    return render("opportunity_detail.html", user=user, o=opp, d=dossier,
                  lineage=lineage, statuses=TRACK_STATUSES, csrf=csrf_for(session),
                  value_est=value_est, delegation=delegation, documents=documents,
                  requirements=requirements, qualification=qualification,
                  proof=proof, decision=decision, days_left=days_left,
                  tasks=tasks, ledger=ledger, history=history,
                  opp_forecasts=opp_forecasts, req_delta=req_delta)


@app.post("/app/opportunities/{opp_id}/status")
def set_status(request: Request, opp_id: int, status: str = Form(...),
               csrf_token: str = Form(""),
               session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    if status not in TRACK_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    if not store().get_opportunity(user["org_id"], opp_id):
        raise HTTPException(status_code=404, detail="opportunity not found")
    store().set_tracked(user["org_id"], opp_id, status, user_id=user["user_id"])
    store().set_match_status(user["org_id"], opp_id, status)
    store().record_feedback(user["org_id"], opp_id, status, user_id=user["user_id"])
    audit(request, "status_update", user=user, opportunity_id=opp_id, status=status)
    return RedirectResponse(f"/app/opportunities/{opp_id}", status_code=303)


@app.get("/app/watchlist", response_class=HTMLResponse)
def watchlist(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    rows = store().list_tracked(user["org_id"])
    tasks = store().list_capture_tasks(user["org_id"])
    return render("watchlist.html", user=user, rows=rows,
                  statuses=TRACK_STATUSES, tasks=tasks,
                  csrf=csrf_for(session))


@app.get("/app/alerts", response_class=HTMLResponse)
def alerts(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    sub = store().get_subscription(user["org_id"]) or {}
    return render("alerts.html", user=user, sub=sub, saved=False,
                  csrf=csrf_for(session))


@app.post("/app/alerts")
def save_alerts(request: Request, email: str = Form(...),
                timezone_name: str = Form("America/Chicago"),
                min_score: int = Form(40), active: str = Form("on"),
                delivery_hour: int = Form(6), delivery_minute: int = Form(30),
                instant_alerts: str = Form(""),
                csrf_token: str = Form(""),
                session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    audit(request, "alert_preferences_update", user=user)
    store().upsert_subscription(user["org_id"], user["user_id"], email.strip(),
                                timezone_name.strip() or "America/Chicago",
                                max(0, min(100, int(min_score))), active == "on",
                                delivery_hour=delivery_hour,
                                delivery_minute=delivery_minute,
                                instant_alerts=instant_alerts == "on")
    return render("alerts.html", user=user,
                  sub=store().get_subscription(user["org_id"]) or {}, saved=True,
                  csrf=csrf_for(session))


@app.get("/app/report/{opp_id}", response_class=HTMLResponse)
def report_view(opp_id: int, session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    opp = store().get_opportunity(user["org_id"], opp_id)
    dossier = store().get_dossier(opp_id)
    if not opp or not dossier:
        raise HTTPException(status_code=404, detail="dossier not generated yet")
    from ..intel.report import render_report
    from .entitlements import allows
    delegation = (store().delegation_for_opportunity(opp_id)
                  if allows(store().org_plan(user["org_id"]), "delegation_intel")
                  else [])
    requirements = (store().requirements_for_opportunity(opp_id)
                    if allows(store().org_plan(user["org_id"]), "document_intel")
                    else [])
    return HTMLResponse(render_report(dossier, opp.get("url"),
                                      opp.get("source_notice_id"), inline_css=False,
                                      delegation=delegation,
                                      requirements=requirements))


@app.get("/app/opportunities.csv")
def opportunities_csv(session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                      q: str = Query(default=""), min_score: int = Query(default=40),
                      notice_type: str = Query(default="")):
    """CSV export of the current opportunity view. Cells that could be
    interpreted as spreadsheet formulas are prefixed to stay inert."""
    user = require_user(session)
    require_entitlement(user, "csv_export")
    rows = store().list_opportunities(user["org_id"], q=q.strip() or None,
                                      min_score=max(0, min(100, min_score)),
                                      notice_type=notice_type.strip() or None, limit=500)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["score", "title", "agency", "office", "notice_type", "set_aside",
                     "naics", "response_deadline", "recommendation", "user_status"])
    for o in rows:
        rec = (o.get("recommendation") or {}).get("recommendation") \
            if isinstance(o.get("recommendation"), dict) else None
        writer.writerow([_csv_safe(v) for v in (
            o.get("score"), o.get("title"), o.get("agency"), o.get("office"),
            o.get("notice_type"), o.get("set_aside"), o.get("naics"),
            o.get("response_deadline"), rec, o.get("user_status"))])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=opportunities.csv"})


def _csv_safe(value):
    """Neutralize CSV/spreadsheet formula injection from untrusted text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t"):
        return "'" + value
    return value


@app.get("/app/radar", response_class=HTMLResponse)
def demand_radar(q: str = Query(default=""),
                 session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "demand_radar")
    forecasts = store().list_forecasts(q=q.strip() or None)
    profile = store().get_profile(user["org_id"]) or {}
    from ..classify import classify
    scored = []
    for fc in forecasts:
        pseudo = {"title": fc.get("title"), "description_text": fc.get("description"),
                  "naics": fc.get("naics"), "agency": fc.get("agency"),
                  "office": fc.get("office"), "set_aside": fc.get("set_aside"),
                  "notice_type": "Special Notice", "response_deadline": None}
        result = classify(pseudo, profile)
        scored.append({**fc, "match_score": result.get("score", 0),
                       "match_reasons": (result.get("reasons") or [])[:3]})
    scored.sort(key=lambda f: (-f["match_score"],
                               str(f.get("anticipated_solicitation") or "9999")))
    return render("radar.html", user=user, forecasts=scored, q=q)


@app.get("/app/agencies", response_class=HTMLResponse)
def agencies(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "agency_intel")
    return render("agencies.html", user=user, rows=store().list_agencies(limit=100))


@app.get("/app/agencies/{office_id}", response_class=HTMLResponse)
def agency_detail(office_id: int,
                  session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "agency_intel")
    office = store().get_agency(office_id)
    if not office:
        raise HTTPException(status_code=404, detail="office not found")
    return render("agency_detail.html", user=user, a=office)


@app.get("/app/vendors", response_class=HTMLResponse)
def vendors(session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
            q: str = Query(default="")):
    user = require_user(session)
    require_entitlement(user, "vendor_intel")
    return render("vendors.html", user=user, q=q,
                  rows=store().list_vendors(q=q.strip() or None, limit=100))


@app.get("/app/vendors/{vendor_id}", response_class=HTMLResponse)
def vendor_detail(vendor_id: int,
                  session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "vendor_intel")
    vendor = store().get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="vendor not found")
    return render("vendor_detail.html", user=user, v=vendor)


@app.get("/app/legislators/{bioguide_id}", response_class=HTMLResponse)
def legislator_page(bioguide_id: str,
                    session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "delegation_intel")
    member = store().get_legislator(bioguide_id)
    if not member:
        raise HTTPException(status_code=404, detail="legislator not found")
    from ..intel.delegation import (
        COMPLIANCE_NOTE,
        STAFF_ROLE_PLAYBOOK,
        engagement_windows,
        format_funding_label,
    )
    return render("legislator.html", user=user, m=member,
                  playbook=STAFF_ROLE_PLAYBOOK, compliance=COMPLIANCE_NOTE,
                  windows=engagement_windows(),
                  funding_label=format_funding_label)


@app.get("/app/districts", response_class=HTMLResponse)
def districts(session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
              fy: int = Query(default=0), agency: str = Query(default="")):
    user = require_user(session)
    require_entitlement(user, "delegation_intel")
    years, agencies = store().district_agency_years()
    fy = fy or (years[0] if years else 0)
    from ..intel.district import ATTRIBUTION_NOTE, rank_note
    rows = store().district_rankings(fy, agency) if fy else []
    return render("districts.html", user=user, rows=rows, fy=fy, years=years,
                  agency=agency, agencies=agencies,
                  note=rank_note(agency or None), attribution=ATTRIBUTION_NOTE)


@app.get("/app/districts/{state}/{district}", response_class=HTMLResponse)
def district_detail(state: str, district: int,
                    session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_entitlement(user, "delegation_intel")
    state = state.upper()[:2]
    profile = store().district_profile(state, district)
    from ..intel.district import (
        ATTRIBUTION_NOTE,
        SENTIMENT_NOTE,
        partisan_lean,
        primary_history,
        seat_outlook,
    )
    results = profile["election_results"]
    lean = partisan_lean(results)
    rep_name = (profile["rep"] or {}).get("full_name") or ""
    primaries = primary_history(results, rep_name)
    last_margin = lean["per_cycle"][0]["margin"] if lean else None
    finance = profile["finance"]
    latest_cycle = max((f["cycle"] for f in finance), default=None)
    incumbent_cash = challenger_best = incumbent_running = None
    if latest_cycle:
        current = [f for f in finance if f["cycle"] == latest_cycle]
        incumbents = [f for f in current if f["is_incumbent"]]
        challengers = [f for f in current if not f["is_incumbent"]]
        incumbent_running = bool(incumbents)
        if incumbents:
            incumbent_cash = float(incumbents[0].get("cash_on_hand") or 0)
        if challengers:
            challenger_best = max(float(f.get("receipts") or 0) for f in challengers)
    outlook = seat_outlook(lean, last_margin, incumbent_running,
                           incumbent_cash, challenger_best)
    # money rollups for the page
    by_fy: dict[int, float] = {}
    by_agency: dict[str, float] = {}
    for r in profile["spending"]:
        if r["agency"] == "":
            by_fy[r["fiscal_year"]] = float(r["obligations"])
        else:
            by_agency[r["agency"]] = by_agency.get(r["agency"], 0) + float(r["obligations"])
    top_agencies = sorted(by_agency.items(), key=lambda kv: -kv[1])[:10]
    return render("district_detail.html", user=user, p=profile,
                  by_fy=sorted(by_fy.items(), reverse=True),
                  top_agencies=top_agencies, lean=lean, primaries=primaries,
                  outlook=outlook, latest_cycle=latest_cycle,
                  attribution=ATTRIBUTION_NOTE, sentiment_note=SENTIMENT_NOTE)


@app.get("/app/reports", response_class=HTMLResponse)
def reports(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    """Reports hub — everything renders from stored data, never live APIs."""
    user = require_user(session)
    require_entitlement(user, "reports")
    pipeline = store().pipeline_report(user["org_id"])
    top = store().list_opportunities(user["org_id"], min_score=70, limit=15)
    return render("reports.html", user=user, pipeline=pipeline, top=top,
                  today=datetime.now(timezone.utc).date())


MARKET_CATEGORIES = {
    "Software": ["541511", "541512", "541519"],
    "Cloud/Data": ["518210"],
    "IT Services": ["541513"],
    "Cyber": ["541512", "541690"],
    "Engineering": ["541330"],
    "R&D": ["541715"],
}


@app.get("/app/market", response_class=HTMLResponse)
def market_intel(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    return render("market.html", user=user,
                  rows=store().market_intel(MARKET_CATEGORIES))


@app.get("/app/admin", response_class=HTMLResponse)
def admin(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
    return render("admin.html", user=user, ops=store().admin_ops())


# ---------- digest action links (signed, expiring; no login required) ----------

@app.post("/app/views")
def save_view(request: Request, name: str = Form(...), q: str = Form(""),
              min_score: int = Form(40), notice_type: str = Form(""),
              csrf_token: str = Form(""),
              session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    from .entitlements import limit as plan_limit
    plan = store().org_plan(user["org_id"])
    if len(store().list_views(user["org_id"])) >= plan_limit(plan, "saved_views"):
        raise HTTPException(status_code=403,
                            detail="Saved-view limit reached for your plan.")
    name = name.strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="view name required")
    store().save_view(user["org_id"], user["user_id"], name,
                      {"q": q.strip(), "min_score": max(0, min(100, min_score)),
                       "notice_type": notice_type.strip()})
    audit(request, "saved_view_created", user=user, name=name)
    return RedirectResponse("/app/opportunities", status_code=303)


@app.post("/app/views/{view_id}/delete")
def delete_view(request: Request, view_id: int, csrf_token: str = Form(""),
                session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    store().delete_view(user["org_id"], view_id)   # org-scoped delete
    return RedirectResponse("/app/opportunities", status_code=303)


@app.post("/app/profile/reset-preferences")
def reset_preferences(request: Request, csrf_token: str = Form(""),
                      session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    store().reset_preferences(user["org_id"])
    store().request_match_refresh(user["org_id"])
    audit(request, "preferences_reset", user=user)
    return RedirectResponse("/app/profile", status_code=303)


@app.get("/app/account", response_class=HTMLResponse)
def account(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    return render("account.html", user=user, csrf=csrf_for(session),
                  plan=store().org_plan(user["org_id"]), error=None)


@app.post("/app/account/delete")
def delete_account(request: Request, confirm: str = Form(""),
                   csrf_token: str = Form(""),
                   session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    user = require_user(session)
    require_csrf(session, csrf_token)
    if confirm.strip().lower() != "delete my account":
        return render("account.html", user=user, csrf=csrf_for(session),
                      plan=store().org_plan(user["org_id"]),
                      error='Type "delete my account" exactly to confirm.')
    store().delete_account(user["user_id"])
    audit(request, "account_deleted", user=user)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


ACTION_LABELS = {
    "track": "add this opportunity to your watchlist",
    "save": "save this opportunity",
    "ignore": "ignore this opportunity (similar matches will rank lower)",
    "pursuing": "mark this opportunity as pursuing",
    "good_match": "record this as a good match",
    "bad_match": "record this as a bad match",
    "hide_similar": "suppress similar opportunities",
}
ACTION_DONE = {
    "track": "Opportunity added to your watchlist.",
    "save": "Opportunity saved.",
    "ignore": "Opportunity ignored — similar matches will rank lower.",
    "pursuing": "Marked as pursuing.",
    "good_match": "Thanks — this improves your future matches.",
    "bad_match": "Thanks — this improves your future matches.",
    "hide_similar": "We'll suppress similar opportunities.",
}


@app.get("/a/{opp_id}/{action}", response_class=HTMLResponse)
def action_confirm(opp_id: int, action: str, t: str = Query(default=""),
                   e: int = Query(default=0), s: int = Query(default=0),
                   o: int = Query(default=0)):
    """GET verifies the token and shows a confirmation page — it NEVER changes
    state, so email security scanners that prefetch links are harmless."""
    if not actions.verify(opp_id, action, t, sub=s, org=o, exp=e):
        return render("action_result.html", ok=False,
                      message="This link is invalid or has expired.")
    return render("action_confirm.html", opp_id=opp_id, action=action,
                  label=ACTION_LABELS.get(action, action), t=t, e=e, s=s, o=o)


@app.post("/a/{opp_id}/{action}", response_class=HTMLResponse)
def action_commit(request: Request, opp_id: int, action: str,
                  t: str = Form(""), e: int = Form(0), s: int = Form(0),
                  o: int = Form(0),
                  session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    """POST commits the action. Org comes from the signed token (digest links
    work logged-out); a live session may refine it but never widen it."""
    if not actions.verify(opp_id, action, t, sub=int(s), org=int(o), exp=int(e)):
        return render("action_result.html", ok=False,
                      message="This link is invalid or has expired.")
    user = current_user(session)
    org_id = int(o) or (user["org_id"] if user else None)
    user_id = user["user_id"] if user else None
    if org_id is None:
        return render("action_result.html", ok=False,
                      message="This link isn't tied to an organization. "
                              "Log in and use the app instead.")
    st = store()
    try:
        st.record_feedback(org_id, opp_id, action, user_id=user_id)
        status_map = {"track": "watching", "save": "watching", "ignore": "ignored",
                      "pursuing": "pursuing"}
        if action in status_map:
            st.set_tracked(org_id, opp_id, status_map[action], user_id=user_id)
            st.set_match_status(org_id, opp_id, status_map[action])
        if action == "hide_similar":
            st.hide_match(org_id, opp_id)
    except Exception:  # noqa: BLE001 — e.g. org/opportunity since deleted
        from ..log import log
        log("digest_action_failed", opportunity_id=opp_id, action=action, org_id=org_id)
        return render("action_result.html", ok=False,
                      message="This link refers to data that no longer exists.")
    audit(request, "digest_action", user={"org_id": org_id, "user_id": user_id},
          action=action, opportunity_id=opp_id)
    return render("action_result.html", ok=True,
                  message=ACTION_DONE.get(action, "Recorded."))


@app.get("/healthz")
def healthz():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}
