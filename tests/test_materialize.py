"""Materialization jobs: vendor grouping, office market stats, fiscal years."""
from src.intel.materialize import _fiscal_year, group_awards_by_vendor, office_market_stats, vendor_profiles
from tests.conftest import make_award


def test_fiscal_year_boundary():
    assert _fiscal_year("2025-09-30") == 2025
    assert _fiscal_year("2025-10-01") == 2026   # federal FY starts Oct 1
    assert _fiscal_year(None) is None
    assert _fiscal_year("garbage") is None


def test_vendor_grouping_by_identifier_not_fuzzy_name():
    a = make_award(recipient_name="ABC Systems, Inc.", recipient_uei="UEI1")
    b = make_award(source_award_id="AW-2", recipient_name="ABC SYSTEMS LLC",
                   recipient_uei="UEI1")                      # same UEI -> same vendor
    c = make_award(source_award_id="AW-3", recipient_name="ABC Sytems Inc",  # typo
                   recipient_uei="UEI9")                      # different UEI -> separate
    groups = group_awards_by_vendor([a, b, c])
    sizes = sorted(len(g) for g in groups.values())
    assert sizes == [1, 2]


def test_vendor_profiles_materialize():
    awards = [make_award(obligated_amount=1e6),
              make_award(source_award_id="AW-2", obligated_amount=3e6,
                         award_date="2025-01-01")]
    (p,) = vendor_profiles(awards)
    assert p["award_count"] == 2 and p["total_obligations"] == 4e6


def test_office_market_stats_grouping_and_shares():
    awards = [
        make_award(source_award_id=f"A{i}", awarding_office_code="ORG1",
                   award_date="2025-06-01", obligated_amount=1e6,
                   recipient_name="Vendor One Inc", recipient_uei="U1")
        for i in range(3)
    ] + [
        make_award(source_award_id="B1", awarding_office_code="ORG1",
                   award_date="2025-06-01", obligated_amount=7e6,
                   recipient_name="Vendor Two LLC", recipient_uei="U2",
                   set_aside=None, extent_competed="Not competed")
    ]
    (row,) = office_market_stats(awards)
    assert row["fiscal_year"] == 2025
    assert row["award_count"] == 4
    assert row["total_obligations"] == 10e6
    assert row["unique_vendor_count"] == 2
    assert row["top_vendor_share"] == 70.0
    assert row["set_aside_share"] == 75.0
    assert row["competed_share"] == 75.0


def test_office_market_stats_skips_unresolvable_offices():
    a = make_award(awarding_office_code=None, awarding_office=None,
                   awarding_subtier=None, awarding_department=None)
    assert office_market_stats([a]) == []
