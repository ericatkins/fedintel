"""Office resolution, vendor normalization, similarity primitives."""
from src.intel.offices import office_identity_from_opportunity, office_key
from src.intel.similarity import cosine, solnum_family
from src.intel.vendors import build_vendor_profile, normalize_vendor_name, same_vendor
from tests.conftest import make_award


def test_office_resolution_priority():
    assert office_key({"organization_code": "100511234"})[1:] == (90, "organization_code")
    assert office_key({"full_parent_path_code": "057.5700.X"})[1:] == (85, "full_parent_path_code")
    assert office_key({"office_name": "AMC", "subtier_name": "Army"})[1] == 70
    assert office_key({"subtier_name": "Army"})[1] == 40
    assert office_key({"department_name": "DoD"})[1] == 25
    assert office_key({}) == ("unknown", 0, "unresolved")


def test_office_key_normalizes_variants():
    a = office_key({"office_name": " Army  Contracting  Command ", "subtier_name": "dept of the army"})
    b = office_key({"office_name": "ARMY CONTRACTING COMMAND", "subtier_name": "Dept of the Army"})
    assert a[0] == b[0]


def test_office_identity_from_opportunity(opp_norm):
    ident = office_identity_from_opportunity(opp_norm)
    assert ident["department_name"] == "DEPT OF DEFENSE"
    assert ident["subtier_name"] == "DEPT OF THE ARMY"
    assert ident["office_name"] == "AMC"


def test_vendor_normalization():
    assert normalize_vendor_name("ABC Systems, Inc.") == "ABC SYSTEMS"
    assert normalize_vendor_name("Acme Corp.") == "ACME"
    assert normalize_vendor_name("Widget Co, LLC") == "WIDGET"
    assert normalize_vendor_name("Data & Things Limited") == "DATA THINGS"
    assert normalize_vendor_name(None) == ""


def test_same_vendor_prefers_identifiers_over_names():
    a = {"recipient_name": "Totally Different Name", "recipient_uei": "UEI1"}
    b = {"recipient_name": "Other Name", "recipient_uei": "UEI1"}
    assert same_vendor(a, b)
    c = {"recipient_name": "ABC Systems Inc"}
    d = {"recipient_name": "ABC Systems, LLC"}
    assert same_vendor(c, d)  # same normalized name
    e = {"recipient_name": "ABC Sytems Inc"}  # typo — fuzzy: must NOT merge
    assert not same_vendor(c, e)


def test_vendor_profile_aggregation():
    awards = [make_award(obligated_amount=1e6, award_date="2021-01-01"),
              make_award(source_award_id="AW-2", obligated_amount=2e6, award_date="2024-05-01")]
    p = build_vendor_profile(awards)
    assert p["award_count"] == 2
    assert p["total_obligations"] == 3e6
    assert p["first_award_date"] == "2021-01-01"
    assert p["last_award_date"] == "2024-05-01"


def test_title_similarity_and_solnum_family():
    assert cosine("Inventory Management System Modernization",
                  "Inventory Management System Support") > 0.5
    assert cosine("Inventory Management", "Janitorial Services") < 0.2
    assert solnum_family("W58RGZ-26-R-0042", "W58RGZ26R0042")
    assert solnum_family("W58RGZ-26-R-0042-0001", "W58RGZ-26-R-0042")
    assert not solnum_family("W58RGZ-26-R-0042", "FA8750-26-R-0001")
    assert not solnum_family(None, "X")
