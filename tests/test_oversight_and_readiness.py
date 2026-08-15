"""Oversight demand signals and grant applicant-type eligibility."""
import pytest

from src.db_oversight import OversightImportError, parse_oversight_csv
from src.intel.grant_readiness import assess_grant_eligibility
from src.intel.oversight_link import link_findings, score_oversight_link

OPP = {"title": "Enterprise inventory management system modernization",
       "agency": "DEPT OF THE ARMY",
       "description_text": "modernize legacy inventory application, "
                           "dashboards, data migration"}


def _finding(**kw):
    f = {"id": 1, "finding_type": "recommendation",
         "agency": "DEPT OF THE ARMY",
         "title": "Army should modernize legacy inventory management systems",
         "detail": "legacy inventory applications limit asset visibility; "
                   "recommends modernization with data migration",
         "report_number": "GAO-25-106230", "status": "open",
         "source_url": "https://www.gao.gov/products/gao-25-106230"}
    f.update(kw)
    return f


def test_inferred_link_needs_agency_and_subject_overlap():
    ln = score_oversight_link(OPP, _finding())
    assert ln and ln["link_kind"] == "inferred"
    assert ln["confidence"] <= 75          # inferred links never look certain
    joined = " ".join(ln["evidence"])
    assert "same agency" in joined and "similarity" in joined
    assert "still open" in joined


def test_notice_citation_upgrades_to_cited():
    opp = dict(OPP, description_text="In response to GAO-25-106230, the Army "
                                     "requires modernization services.")
    ln = score_oversight_link(opp, _finding())
    assert ln["link_kind"] == "cited"
    assert "cites GAO-25-106230" in ln["evidence"][0]


def test_unrelated_finding_is_not_linked():
    unrelated = _finding(agency="EPA", title="EPA should improve water "
                         "quality monitoring", detail="water quality sensors",
                         report_number="GAO-25-000001")
    assert score_oversight_link(OPP, unrelated) is None
    assert link_findings(OPP, [unrelated]) == []


def test_cited_links_sort_before_inferred():
    opp = dict(OPP, description_text=OPP["description_text"] +
               " per GAO-25-999999")
    cited = _finding(id=2, report_number="GAO-25-999999",
                     title="Unrelated title", detail="unrelated", agency="EPA")
    links = link_findings(opp, [_finding(), cited])
    assert links[0]["link_kind"] == "cited"


def test_oversight_csv_provenance_rule(tmp_path):
    path = tmp_path / "o.csv"
    path.write_text("source_record_id,finding_type,title,source_url\n"
                    "R1,recommendation,Fix the thing,\n")
    with pytest.raises(OversightImportError, match="provenance"):
        list(parse_oversight_csv(str(path)))
    path.write_text("source_record_id,finding_type,title,source_url\n"
                    "R1,opinion,Fix the thing,https://gao.gov/x\n")
    with pytest.raises(OversightImportError, match="finding_type"):
        list(parse_oversight_csv(str(path)))
    path.write_text("source_record_id,finding_type,title,source_url,status\n"
                    "R1,recommendation,Fix the thing,https://gao.gov/x,open\n")
    rows = list(parse_oversight_csv(str(path)))
    assert rows[0]["status"] == "open" and rows[0]["source"] == "csv_import"


# ---- grant readiness ----

GRANT = {"eligible_applicants": ["Public and State controlled institutions "
                                 "of higher education", "Nonprofits"],
         "cost_sharing": True}


def test_matching_applicant_type_is_likely_eligible_with_cost_share_note():
    r = assess_grant_eligibility(GRANT, "nonprofit")
    assert r["verdict"] == "likely_eligible"
    assert "nonprofit" in r["why"]
    assert "Cost sharing is required" in r["cost_share_note"]


def test_non_matching_type_is_not_listed_never_certain():
    r = assess_grant_eligibility(GRANT, "small business")
    assert r["verdict"] == "not_listed"
    assert "does not appear" in r["why"]
    assert any("read the notice" in c for c in r["caveats"])


def test_missing_inputs_are_unknown_not_negative():
    assert assess_grant_eligibility(GRANT, None)["verdict"] == "unknown"
    assert assess_grant_eligibility({"eligible_applicants": []},
                                    "nonprofit")["verdict"] == "unknown"


def test_unrestricted_eligibility():
    r = assess_grant_eligibility({"eligible_applicants":
                                  ["Unrestricted (see NOFO)"]}, "tribal")
    assert r["verdict"] == "likely_eligible"


def test_agency_path_matches_subtier_level_findings():
    """A department-labeled notice (DEPT OF DEFENSE) must still match a
    subtier-level finding (DEPT OF THE ARMY) via the hierarchy path."""
    opp = dict(OPP, agency="DEPT OF DEFENSE",
               agency_path="DEPT OF DEFENSE.DEPT OF THE ARMY.ACC")
    ln = score_oversight_link(opp, _finding())
    assert ln and "same agency" in " ".join(ln["evidence"])


def test_forecast_link_also_uses_agency_path():
    from src.intel.forecast_link import score_forecast_link
    opp = {"title": "Inventory management modernization",
           "description_text": "dashboards, data migration",
           "agency": "DEPT OF DEFENSE",
           "agency_path": "DEPT OF DEFENSE.DEPT OF THE ARMY.ACC",
           "naics": "541512", "posted_date": "2026-08-01"}
    fc = {"id": 1, "agency": "DEPT OF THE ARMY", "office": None,
          "title": "Inventory management system recompete",
          "description": "dashboards, data migration", "naics": "541512",
          "anticipated_solicitation": "2026-06-15"}
    ln = score_forecast_link(opp, fc)
    assert ln and "same agency" in ln["evidence"]
