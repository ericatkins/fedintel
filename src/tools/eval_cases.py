"""Golden evaluation cases: diverse opportunity scenarios with expected
intelligence conclusions.

Each case is a full offline scenario (opportunity + award history + documents
+ profile inputs) with the conclusions a careful human analyst would accept.
The runner (src/tools/run_eval.py) rebuilds every dossier and decision stack
from scratch and fails the release when any expectation breaks — the
regression gate for the intelligence pipeline itself, not just its parts.

Extend with live-record cases (real SAM.gov notices with hand-verified
expectations) once network access and a SAM_API_KEY are available; the case
shape is designed so live captures drop in unchanged.
"""
from datetime import date

TODAY = date(2026, 8, 15)


def _award(i, vendor, *, sol=None, piid=None, title="IT support services",
           naics="541512", award_date="2023-06-15", period_end="2026-06-14",
           obligated=3_000_000, potential=None, office="ACC",
           set_aside=None, extent="Full and open competition"):
    return {"source": "usaspending", "source_award_id": f"EV-{i}",
            "piid": piid or f"EV{i:04d}", "parent_award_id": None,
            "solicitation_number": sol, "award_title": title,
            "award_description": title, "recipient_name": vendor,
            "recipient_name_normalized": vendor.upper(),
            "recipient_uei": None, "recipient_cage": None,
            "awarding_department": "DEPT OF DEFENSE",
            "awarding_subtier": "DEPT OF THE ARMY",
            "awarding_office": office, "awarding_office_code": None,
            "funding_department": "DEPT OF DEFENSE",
            "funding_subtier": "DEPT OF THE ARMY", "funding_office": None,
            "naics": naics, "psc": "DA01", "award_type": "Definitive Contract",
            "contract_type": None, "contract_vehicle": None,
            "extent_competed": extent, "set_aside": set_aside,
            "award_date": award_date, "period_start": award_date,
            "period_end": period_end, "obligated_amount": float(obligated),
            "total_obligated_amount": float(obligated),
            "potential_total_value": float(potential) if potential else None,
            "place_of_performance_json": None}


def _opp(**kw):
    base = {"title": "Enterprise IT support services",
            "agency": "DEPT OF THE ARMY", "office": "ACC",
            "notice_type": "Solicitation", "naics": "541512",
            "set_aside": None, "solicitation_number": "W900-26-R-0001",
            "description_text": "information technology support services",
            "posted_date": "2026-08-01", "response_deadline": None,
            # real SAM notices carry the hierarchy path; office identity
            # resolution depends on it, so golden cases mirror that shape
            "raw_json": {"fullParentPathName":
                         "DEPT OF DEFENSE.DEPT OF THE ARMY.ACC"}}
    base.update(kw)
    return base


GOLDEN_CASES = [
    {
        "name": "confirmed_recompete",
        "description": "Identifier-matched predecessor: confirmed incumbent, "
                       "recompete origin, conditional pursuit.",
        "opp": _opp(title="IT support services recompete",
                    description_text="recompete of existing IT support"),
        "score": 82, "days_left": 30,
        "awards_office": [_award(1, "ACME CORP", sol="W900-26-R-0001")],
        "expected": {
            "incumbent_status": "confirmed_incumbent",
            "incumbent_name": "ACME CORP",
            "work_origin": "recompete",
            "family_confirmed_count": 1,
            "decision_key": "conditional",
        },
    },
    {
        "name": "likely_incumbent_downgrades_to_track",
        "description": "Inferred incumbent (office+NAICS+scope) must yield "
                       "track-and-verify, never pursue-as-prime.",
        "opp": _opp(title="Enterprise IT support services",
                    solicitation_number="W900-26-R-0002",
                    description_text="enterprise network administration, "
                                     "help desk operations, and application "
                                     "sustainment for Army installations"),
        "score": 85, "days_left": 30,
        "awards_office": [{
            **_award(2, "NORTHSTAR LLC",
                     title="Enterprise IT support services"),
            "award_description": "enterprise network administration, help "
                                 "desk operations, and application "
                                 "sustainment for Army installations",
        }],
        "expected": {
            "incumbent_status": "likely_incumbent",
            "incumbent_name": "NORTHSTAR LLC",
            "decision_key": "track",
        },
    },
    {
        "name": "sources_sought_new_start",
        "description": "Early-stage market research with new-start language "
                       "and no history: shape the requirement.",
        "opp": _opp(notice_type="Sources Sought",
                    title="New data platform — market research",
                    description_text="market research for a new requirement; "
                                     "sources sought to gauge industry "
                                     "capability",
                    solicitation_number="W900-26-S-0003"),
        "score": 80, "days_left": 40,
        "awards_office": [],
        "expected": {
            "incumbent_status": "insufficient_data",
            "work_origin": "new_start",
            "decision_key": "shape",
        },
    },
    {
        "name": "set_aside_bar_routes_to_subcontract",
        "description": "Documents show a set-aside the org doesn't hold: "
                       "prime barred, subcontract recommended, score capped "
                       "logic honored in eligibility.",
        "opp": _opp(solicitation_number="W900-26-R-0004"),
        "score": 78, "days_left": 25,
        "awards_office": [_award(4, "ACME CORP")],
        "requirements": [{"requirement_type": "set_aside", "value": "8(a)",
                          "evidence_quote": "8(a) set-aside", "method": "rule",
                          "confidence": 90, "page": 2}],
        "profile": {"set_aside_eligibility": ["small business"]},
        "expected": {"decision_key": "pursue_subcontract",
                     "eligibility_rating": "blocked"},
    },
    {
        "name": "vehicle_gate_prime_with_partner",
        "description": "A vehicle requirement the org lacks gates the bid "
                       "but teaming clears it.",
        "opp": _opp(solicitation_number="W900-26-R-0005"),
        "score": 80, "days_left": 25,
        "awards_office": [],
        "requirements": [{"requirement_type": "vehicle", "value": "GSA MAS",
                          "evidence_quote": "orders via GSA MAS",
                          "method": "rule", "confidence": 85, "page": 3}],
        "profile": {"contract_vehicles": ["SEWP V"],
                    "set_aside_eligibility": ["small business"]},
        "expected": {"decision_key": "pursue_prime_with_partner",
                     "eligibility_rating": "weak"},
    },
    {
        "name": "sparse_data_is_insufficient_evidence",
        "description": "No profile match, no history, no documents: the only "
                       "honest verdict is insufficient evidence — never "
                       "no-bid.",
        "opp": _opp(solicitation_number=None, naics=None, agency="HUD",
                    office=None,
                    title="Program support", description_text=""),
        "score": None, "days_left": None,
        "awards_office": [],
        "expected": {
            "incumbent_status": "insufficient_data",
            "funding_label_key": "none",
            "decision_key": "insufficient_evidence",
        },
    },
    {
        "name": "bridge_plus_protest_is_displacement_opportunity",
        "description": "Bridge award + family protest + set-aside change: "
                       "multiple public signals → credible displacement.",
        "opp": _opp(set_aside="Total Small Business Set-Aside",
                    solicitation_number="W900-26-R-0007"),
        "score": 75, "days_left": 30,
        "awards_office": [
            _award(7, "ACME CORP", sol="W900-26-R-0007",
                   award_date="2021-06-15", period_end="2025-06-14",
                   obligated=8_000_000, potential=20_000_000),
            _award(8, "ACME CORP", title="IT support bridge",
                   award_date="2025-06-20", period_end="2025-12-19",
                   obligated=600_000, potential=600_000),
        ],
        "protests": [{"source_record_id": "B-419999", "protester": "Rival",
                      "agency": "DEPT OF THE ARMY",
                      "solicitation_number": "W900-26-R-0007",
                      "filed_date": "2025-05-01", "decided_date": None,
                      "outcome": "pending",
                      "source_url": "https://gao.gov/b-419999"}],
        "expected": {
            "incumbent_status": "confirmed_incumbent",
            "vulnerability": "credible displacement opportunity",
        },
    },
    {
        "name": "conflicting_incumbent_evidence_is_surfaced",
        "description": "Award history says one vendor, the agency forecast "
                       "names another: the conflict must be shown, not "
                       "silently resolved.",
        "opp": _opp(solicitation_number="W900-26-R-0008"),
        "score": 80, "days_left": 30,
        "awards_office": [_award(9, "ACME CORP",
                                 title="Enterprise IT support services")],
        "forecasts": [{"incumbent_name": "OTHERCO INC"}],
        "expected": {
            "incumbent_evidence_contains": "CONFLICTS",
        },
    },
    {
        "name": "expired_deadline_is_no_bid",
        "description": "A passed response deadline blocks execution "
                       "readiness regardless of fit.",
        "opp": _opp(solicitation_number="W900-26-R-0009"),
        "score": 90, "days_left": -3,
        "awards_office": [],
        "expected": {"decision_key": "no_bid",
                     "execution_rating": "blocked"},
    },
]

GRANT_CASES = [
    {
        "name": "grant_eligible_nonprofit",
        "grant": {"eligible_applicants": ["Nonprofits", "State governments"],
                  "cost_sharing": True},
        "applicant_type": "nonprofit",
        "expected_verdict": "likely_eligible",
    },
    {
        "name": "grant_not_listed_is_caution",
        "grant": {"eligible_applicants": ["State governments"],
                  "cost_sharing": False},
        "applicant_type": "small business",
        "expected_verdict": "not_listed",
    },
    {
        "name": "grant_unknown_without_profile_type",
        "grant": {"eligible_applicants": ["Nonprofits"]},
        "applicant_type": None,
        "expected_verdict": "unknown",
    },
]
