import os

# Required env vars before src.config imports (tests never touch real services)
os.environ.setdefault("SAM_API_KEY", "test-key-not-real")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("TIMEZONE", "America/Chicago")

import pytest


@pytest.fixture
def sam_record():
    """Representative SAM.gov v2 record."""
    return {
        "noticeId": "abc123",
        "solicitationNumber": "W58RGZ-26-R-0042",
        "title": "Enterprise Inventory Management System Modernization",
        "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY.AMC",
        "type": "Sources Sought",
        "naicsCode": "541512",
        "typeOfSetAside": "Total Small Business Set-Aside",
        "postedDate": "2026-07-07",
        "responseDeadLine": "2026-07-29T17:00:00-05:00",
        "placeOfPerformance": {"city": {"name": "Huntsville"}, "state": {"code": "AL"}},
        "description": (
            "The Army seeks to modernize a legacy inventory management system with a "
            "web-based application including dashboards, workflow automation, API "
            "integration and data migration."
        ),
        "uiLink": "https://sam.gov/opp/abc123/view",
    }


@pytest.fixture
def profile():
    return {
        "name": "Test Firm",
        "industries": ["defense software"],
        "capabilities": ["legacy system modernization", "dashboards", "data migration"],
        "technologies": ["python", "postgres"],
        "naics_codes": ["541512"],
        "agencies_of_interest": ["army"],
        "locations": ["huntsville", "redstone"],
        "set_aside_eligibility": ["small business"],
        "excluded_categories": ["Enterprise IT"],
        "keywords_boost": ["inventory management"],
        "keywords_suppress": ["help desk"],
    }


def make_award(**kw):
    """Fixture factory: representative normalized contract award."""
    base = {
        "source": "usaspending",
        "source_award_id": "AW-1",
        "piid": "W58RGZ21C0001",
        "solicitation_number": "W58RGZ-21-R-0042",
        "award_title": "Inventory Management System Support",
        "award_description": "web-based inventory management application, dashboards, data migration",
        "recipient_name": "ABC Systems, Inc.",
        "recipient_uei": "UEI111111111",
        "recipient_cage": None,
        "awarding_department": "DEPT OF DEFENSE",
        "awarding_subtier": "DEPT OF THE ARMY",
        "awarding_office": "AMC",
        "awarding_office_code": None,
        "funding_department": "DEPT OF DEFENSE",
        "funding_subtier": "DEPT OF THE ARMY",
        "naics": "541512",
        "psc": "DA01",
        "award_type": "Definitive Contract",
        "contract_vehicle": None,
        "extent_competed": "Full and open competition",
        "set_aside": "Total Small Business Set-Aside",
        "award_date": "2023-06-15",
        "period_start": "2023-06-15",
        "period_end": "2026-06-14",
        "obligated_amount": 4_200_000.0,
        "place_of_performance_json": {"city": "Huntsville", "state": "AL"},
    }
    base.update(kw)
    return base


@pytest.fixture
def opp_norm(sam_record):
    from src.normalize import normalize_sam
    return normalize_sam(sam_record)


@pytest.fixture
def opp_identity(opp_norm):
    from src.intel.offices import office_identity_from_opportunity
    return office_identity_from_opportunity(opp_norm)
