import pytest

from src.normalize import InvalidRecord, content_hash, normalize_sam, parse_dt


def test_normalize_happy_path(sam_record):
    opp = normalize_sam(sam_record)
    assert opp["source_notice_id"] == "abc123"
    assert opp["agency"] == "DEPT OF DEFENSE"
    assert opp["place_of_performance"] == "Huntsville, AL"
    assert opp["naics"] == "541512"
    assert opp["response_deadline"].year == 2026
    assert opp["content_hash"]


def test_missing_notice_id_rejected(sam_record):
    sam_record.pop("noticeId")
    with pytest.raises(InvalidRecord):
        normalize_sam(sam_record)


def test_missing_title_rejected(sam_record):
    sam_record["title"] = "   "
    with pytest.raises(InvalidRecord):
        normalize_sam(sam_record)


def test_office_identity_vs_location(sam_record):
    sam_record["officeAddress"] = {"city": "Fort Belvoir", "state": "VA"}
    opp = normalize_sam(sam_record)
    assert opp["office"] == "AMC"                       # buying office from hierarchy path
    assert opp["office_location"] == "Fort Belvoir, VA" # mailing address is location only


def test_malformed_nested_fields_survive(sam_record):
    sam_record["placeOfPerformance"] = "not a dict"
    sam_record["officeAddress"] = 42
    sam_record["naicsCode"] = {"weird": True}
    sam_record["description"] = None
    sam_record.pop("fullParentPathName")
    opp = normalize_sam(sam_record)
    assert opp["place_of_performance"] is None
    assert opp["office"] is None
    assert opp["office_location"] is None
    assert opp["naics"] is None
    assert opp["description_text"] == ""


def test_non_dict_record_rejected():
    with pytest.raises(InvalidRecord):
        normalize_sam(["not", "a", "dict"])


def test_overlong_title_truncated(sam_record):
    sam_record["title"] = "x" * 5000
    opp = normalize_sam(sam_record)
    assert len(opp["title"]) == 1000


@pytest.mark.parametrize("val,ok", [
    ("2026-07-29T17:00:00-05:00", True),
    ("2026-07-07", True),
    ("07/07/2026", True),
    ("not a date", False),
    ("", False),
    (None, False),
    (12345, False),
])
def test_parse_dt(val, ok):
    assert (parse_dt(val) is not None) == ok


def test_content_hash_stable_and_sensitive(sam_record):
    h1 = content_hash(sam_record)
    assert h1 == content_hash(dict(sam_record))
    changed = dict(sam_record, responseDeadLine="2026-08-15T17:00:00-05:00")
    assert content_hash(changed) != h1
