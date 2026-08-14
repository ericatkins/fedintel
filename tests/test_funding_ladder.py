"""Funding ladder: disciplined money-stage rows over cached account data."""
from src.intel.funding import build_funding_context, build_funding_ladder


def _row(fy, available, obligated, requested=0):
    return {"fiscal_year": fy, "budgetary_resources": available,
            "obligations": obligated, "president_budget_amount": requested,
            "source": "usaspending"}


def test_ladder_aggregates_by_fy_with_rates_and_yoy():
    ladder = build_funding_ladder([
        _row(2024, 10_000_000, 9_000_000),
        _row(2025, 8_000_000, 2_000_000),
        _row(2025, 4_000_000, 1_000_000),      # second account, same FY
    ])
    assert [r["fiscal_year"] for r in ladder["rows"]] == [2024, 2025]
    fy25 = ladder["rows"][1]
    assert fy25["available"] == 12_000_000
    assert fy25["obligated"] == 3_000_000
    assert fy25["obligation_rate_pct"] == 25
    assert fy25["yoy_available_pct"] == 20


def test_ladder_notes_material_increase_and_low_obligation():
    ladder = build_funding_ladder([_row(2024, 10_000_000, 9_000_000),
                                   _row(2025, 12_000_000, 3_000_000)])
    joined = " ".join(ladder["notes"])
    assert "increased 20%" in joined
    assert "only 25%" in joined


def test_requested_note_only_with_presidents_budget_data():
    no_pb = build_funding_ladder([_row(2025, 5_000_000, 1_000_000)])
    assert not any("President" in n for n in no_pb["notes"])
    with_pb = build_funding_ladder([_row(2026, 5_000_000, 0,
                                         requested=6_000_000)])
    assert any("request is not an appropriation" in n for n in with_pb["notes"])


def test_ladder_none_without_usable_rows():
    assert build_funding_ladder([]) is None
    assert build_funding_ladder([{"budgetary_resources": 1}]) is None


def test_ladder_never_claims_the_opportunity_is_funded():
    ladder = build_funding_ladder([_row(2025, 5_000_000, 4_000_000)])
    assert any("never proves" in c for c in ladder["caveats"])


def test_funding_context_carries_the_ladder():
    ctx = build_funding_context({"agency": "X"}, [], [],
                                [_row(2025, 5_000_000, 4_000_000)])
    assert ctx["label_key"] == "agency"
    assert ctx["ladder"]["rows"][0]["obligation_rate_pct"] == 80
