"""Document intelligence: SSRF-guarded fetch, bounded extraction, deterministic
requirement mining with evidence, qualification tiers, UI safety and gating."""
import pytest
from fastapi.testclient import TestClient

from src.documents.extract import extract_text
from src.documents.fetch import filename_from, resource_links, safe_document_url
from src.documents.qualification import apply_to_score, assess
from src.documents.requirements import classify_document, extract_requirements
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"
PAYLOAD = "<script>alert(1)</script>"

SOLICITATION = """
The contractor shall hold an active CIO-SP4 contract. Personnel require a
TS/SCI clearance. This is a Total Small Business Set-Aside. CMMC Level 2
certification is required. The proposal shall not exceed 30 pages.
Davis-Bacon wage rates apply. A performance bond is required.
"""


def test_safe_document_url_blocks_ssrf():
    assert safe_document_url("https://sam.gov/api/file/1") == "https://sam.gov/api/file/1"
    for bad in ("http://sam.gov/f",                 # not https
                "https://evil.example/f",           # not SAM
                "https://user:pw@sam.gov/f",        # credentials
                "//sam.gov/f", "javascript:alert(1)", "file:///etc/passwd",
                "https://sam.gov.evil.example/f",   # suffix trick
                "", None):
        assert safe_document_url(bad) is None, bad


def test_filename_is_sanitized():
    assert filename_from({"content-disposition": 'attachment; filename="PWS v2.pdf"'},
                         "https://sam.gov/x") == "PWS_v2.pdf"
    # path traversal and exotic characters are stripped to underscores
    evil = filename_from({"content-disposition": 'filename="../../etc/passwd"'},
                         "https://sam.gov/x")
    assert "/" not in evil and evil == ".._.._etc_passwd"
    assert filename_from({}, "https://sam.gov/files/sow.pdf") == "sow.pdf"


def test_resource_links_filters_to_allowlist():
    raw = {"resourceLinks": ["https://sam.gov/a.pdf", "https://evil.example/b.pdf",
                             None, 42]}
    assert resource_links(raw) == ["https://sam.gov/a.pdf"]
    assert resource_links({}) == []


def test_extract_text_handles_text_and_garbage():
    out = extract_text(b"hello world", "notes.txt")
    assert out["status"] == "extracted" and "hello" in out["text"]
    bad = extract_text(b"%PDF-1.4 not really a pdf", "broken.pdf")
    assert bad["status"] in ("failed", "unsupported") and bad["text"] == ""
    assert extract_text(b"", "x.pdf")["status"] == "failed"


def test_requirements_extracted_with_evidence():
    rows = extract_requirements([(3, SOLICITATION)])
    found = {r["value"]: r for r in rows}
    assert "TS/SCI" in found and "CIO-SP4" in found
    assert "Total Small Business" in found and "CMMC Level 2" in found
    assert "30-page limit" in found and "Davis-Bacon" in found
    ts = found["TS/SCI"]
    assert ts["page"] == 3 and ts["method"] == "tssci" and ts["confidence"] >= 90
    assert "TS/SCI" in ts["evidence_quote"]          # evidence is real text
    assert "\n" not in ts["evidence_quote"]          # single-line excerpt


def test_requirement_tiers_never_blurred():
    rows = extract_requirements([(1, "Secret clearance needed. Some roles need TS/SCI.")])
    values = {r["value"] for r in rows}
    assert "TS/SCI" in values and "Secret" not in values
    rows = extract_requirements([(1, "CMMC applies. CMMC Level 3 is required.")])
    values = {r["value"] for r in rows}
    assert "CMMC Level 3" in values and "CMMC (level unstated)" not in values


def test_no_requirements_from_empty_or_silent_text():
    assert extract_requirements([]) == []
    assert extract_requirements([(1, "This notice describes landscaping services.")]) == []


def test_document_kind_classification():
    assert classify_document("Draft_PWS.pdf", "") == "pws"
    assert classify_document("attachment3.pdf", "STATEMENT OF WORK") == "sow"
    assert classify_document("random.pdf", "hello") == "other"


def test_qualification_tiers_and_score_caps():
    reqs = extract_requirements([(1, SOLICITATION)])
    # profile that cannot prime an 8(a)-style set-aside but is a small business
    sb = assess(reqs, {"set_aside_eligibility": "small business",
                       "clearances": ["Secret"], "contract_vehicles": ["GSA MAS"]})
    assert sb["verdict"] == "blocked unless teaming"     # SB met; vehicle/clearance gate
    capped, notes = apply_to_score(90, sb)
    assert capped == 55 and notes and "blocked unless teaming" in notes[0]
    # fully qualified
    ready = assess(reqs, {"set_aside_eligibility": "small business",
                          "clearances": ["TS/SCI"],
                          "contract_vehicles": ["CIO-SP4"],
                          "certifications": ["CMMC Level 2"]})
    assert ready["verdict"] in ("qualified", "qualified with gaps")
    assert apply_to_score(90, ready)[0] == 90
    # ineligible set-aside is the hardest tier
    ineligible = assess([{"requirement_type": "set_aside", "value": "8(a)",
                          "confidence": 90, "method": "eight_a", "page": 1,
                          "evidence_quote": "q"}],
                        {"set_aside_eligibility": "small business"})
    assert ineligible["verdict"] == "not eligible to prime"
    assert apply_to_score(95, ineligible)[0] == 15


def test_empty_profile_yields_unknown_never_disqualified():
    reqs = extract_requirements([(1, SOLICITATION)])
    result = assess(reqs, {})
    assert result["verdict"] == "qualified — profile incomplete"
    assert not result["disqualifying"] and not result["blocking"]
    assert apply_to_score(88, result)[0] == 88       # never punished for silence


@pytest.fixture
def env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com", hash_password(PASSWORD), "org")
    token, th, exp = new_session_token()
    store.create_session(uid, th, exp)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_compliance_matrix_renders_and_escapes(env):
    client, store, ctx = env
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army", "score": 90,
                              "source_notice_id": "x"}
    store.profiles[ctx["org_id"]] = {"set_aside_eligibility": ["small business"],
                                     "clearances": ["Secret"]}
    store.requirements[1] = [
        {"requirement_type": "clearance", "value": "TS/SCI", "page": 4,
         "method": "tssci", "confidence": 95,
         "evidence_quote": f"Personnel require TS/SCI {PAYLOAD}",
         "filename": f"PWS{PAYLOAD}.pdf", "doc_kind": "pws"},
        {"requirement_type": "set_aside", "value": "8(a)", "page": 1,
         "method": "eight_a", "confidence": 90, "evidence_quote": "8(a) set-aside",
         "filename": "RFP.pdf", "doc_kind": "rfp"},
    ]
    store.documents[1] = [{"id": 1, "filename": f"PWS{PAYLOAD}.pdf", "doc_kind": "pws",
                           "page_count": 40, "byte_size": 1000,
                           "fetch_status": "extracted", "fetch_error": None,
                           "source_url": "https://sam.gov/a.pdf",
                           "extracted_at": None}]
    html = client.get("/app/opportunities/1").text
    assert "Compliance matrix" in html
    assert "TS/SCI" in html and "rule: tssci" in html      # evidence + method shown
    assert "Bid qualification" in html and "not eligible to prime" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_document_intel_gated_by_plan(env):
    client, store, ctx = env
    store.plans[ctx["org_id"]] = "scout"
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army", "score": 90,
                              "source_notice_id": "x"}
    store.requirements[1] = [{"requirement_type": "clearance", "value": "TS/SCI",
                              "page": 1, "method": "tssci", "confidence": 95,
                              "evidence_quote": "q", "filename": "f", "doc_kind": "pws"}]
    html = client.get("/app/opportunities/1").text
    assert "Compliance matrix" not in html and "Bid qualification" not in html


def test_profile_accepts_qualification_fields(env):
    client, store, ctx = env
    from src.web.app import csrf_for
    r = client.post("/app/profile", data={
        "csrf_token": csrf_for(ctx["token"]), "name": "Acme",
        "capabilities": "software", "industries": "", "naics_codes": "541512",
        "agencies_of_interest": "", "locations": "", "set_aside_eligibility": "8(a)",
        "keywords_boost": "", "keywords_suppress": "", "excluded_categories": "",
        "contract_vehicles": "CIO-SP4, GSA MAS", "clearances": "TS/SCI",
        "certifications": "CMMC Level 2"})
    assert r.status_code == 200
    saved = store.profiles[ctx["org_id"]]
    assert saved["contract_vehicles"] == ["CIO-SP4", "GSA MAS"]
    assert saved["clearances"] == ["TS/SCI"] and saved["certifications"] == ["CMMC Level 2"]
