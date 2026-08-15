"""Protest ingestion and the protest/oversight vulnerability signals."""
from datetime import date

import pytest

from src.db_protests import ProtestImportError, parse_protest_csv
from src.intel.contract_family import build_contract_family

TODAY = date(2026, 8, 15)
OPP = {"title": "IT support recompete", "description_text": "", "set_aside": None}


def _link():
    award = {"source_award_id": "A1", "piid": "W9124-20-C-0001",
             "parent_award_id": None, "recipient_name": "ACME CORP",
             "award_title": "IT support", "award_date": "2022-09-15",
             "period_start": "2022-10-01", "period_end": "2027-09-30",
             "obligated_amount": 5e6, "total_obligated_amount": 5e6,
             "potential_total_value": 6e6, "award_type": "C",
             "contract_vehicle": None}
    return {"award": award, "link_type": "same_solicitation",
            "similarity_score": 90,
            "evidence": ["shares the solicitation number"]}


def _protest(**kw):
    p = {"source_record_id": "B-421111", "protester": "Rival LLC",
         "agency": "DEPT OF THE ARMY", "solicitation_number": "W9124-20-R-0001",
         "filed_date": "2025-01-15", "decided_date": "2025-04-20",
         "outcome": "denied", "source_url": "https://gao.gov/b-421111"}
    p.update(kw)
    return p


def test_protest_becomes_vulnerability_signal_and_timeline_entry():
    fam = build_contract_family(OPP, [_link()], today=TODAY,
                                protests=[_protest()])
    sig = next(s for s in fam["vulnerability"]["signals"]
               if s["signal"] == "bid protest in this solicitation family")
    assert "B-421111" in sig["evidence"]
    assert "unsuccessful protests" in sig["evidence"]
    assert any(t["kind"] == "protest" for t in fam["timeline"])
    assert fam["protests"][0]["b_number"] == "B-421111"


def test_sustained_protest_reads_stronger():
    fam = build_contract_family(
        OPP, [_link()], today=TODAY,
        protests=[_protest(outcome="corrective_action")])
    sig = next(s for s in fam["vulnerability"]["signals"]
               if "protest" in s["signal"])
    assert "revisit the award" in sig["evidence"]


def test_open_oversight_finding_is_inferred_signal():
    finding = {"report_number": "GAO-25-000042", "status": "open",
               "title": "Army should modernize inventory systems",
               "link_kind": "inferred"}
    fam = build_contract_family(OPP, [_link()], today=TODAY,
                                oversight=[finding])
    sig = next(s for s in fam["vulnerability"]["signals"]
               if s["signal"] == "open oversight finding")
    assert "GAO-25-000042" in sig["evidence"]
    assert "inferred context" in sig["evidence"]


def test_closed_findings_do_not_signal():
    finding = {"report_number": "GAO-20-1", "status": "closed",
               "title": "Old finding", "link_kind": "inferred"}
    fam = build_contract_family(OPP, [_link()], today=TODAY,
                                oversight=[finding])
    assert not any(s["signal"] == "open oversight finding"
                   for s in fam["vulnerability"]["signals"])


def test_signals_never_apply_without_an_incumbent():
    fam = build_contract_family(OPP, [], today=TODAY,
                                protests=[_protest()],
                                oversight=[{"status": "open"}])
    assert fam["vulnerability"]["assessment"] == "no defensible assessment"
    assert fam["vulnerability"]["signals"] == []


def test_protest_csv_provenance_and_outcome_vocabulary(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("source_record_id,agency,source_url\nB-1,Army,\n")
    with pytest.raises(ProtestImportError, match="provenance"):
        list(parse_protest_csv(str(path)))
    path.write_text("source_record_id,agency,source_url,outcome\n"
                    "B-1,Army,https://gao.gov/b-1,granted\n")
    with pytest.raises(ProtestImportError, match="outcome"):
        list(parse_protest_csv(str(path)))
    path.write_text("source_record_id,agency,source_url,outcome,filed_date\n"
                    "B-1,Army,https://gao.gov/b-1,sustained,2025-01-02\n")
    rows = list(parse_protest_csv(str(path)))
    assert rows[0]["outcome"] == "sustained"
    assert rows[0]["filed_date"] == "2025-01-02"
