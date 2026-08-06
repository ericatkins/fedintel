from src.classify import classify
from src.normalize import normalize_sam


def test_high_score_for_ideal_fit(sam_record, profile):
    res = classify(normalize_sam(sam_record), profile)
    assert res["score"] >= 80
    assert res["category"] == "Inventory / Asset / Logistics Tools"
    assert res["components"]["keyword"] > 0
    assert res["components"]["naics"] == 20
    assert res["components"]["profile_match"] > 0
    assert res["reasons"]
    assert "Respond" in res["recommended_action"]


def test_components_sum_to_score_when_in_range(sam_record, profile):
    res = classify(normalize_sam(sam_record), profile)
    raw = sum(res["components"].values())
    assert res["score"] == max(0, min(100, raw))


def test_negative_scoring_staffing_and_award(sam_record):
    sam_record["title"] = "Award Notice: Staff Augmentation Personnel Services"
    sam_record["description"] = "Staff augmentation body shop. Award notice."
    res = classify(normalize_sam(sam_record))
    assert res["components"]["negative"] <= -40
    assert res["score"] < 40


def test_profile_suppress_and_exclusion(sam_record, profile):
    sam_record["title"] = "Enterprise IT Help Desk Support Services"
    sam_record["description"] = "help desk ticket answering, system administration"
    res = classify(normalize_sam(sam_record), profile)
    assert res["category"] == "Enterprise IT"
    assert res["components"]["profile_match"] < 0  # suppress + excluded category


def test_neutral_profile_still_scores(sam_record):
    res = classify(normalize_sam(sam_record), None)
    assert res["score"] > 50


def test_semantic_component_reflects_capability_overlap(sam_record, profile):
    res = classify(normalize_sam(sam_record), profile)
    assert res["components"]["semantic"] >= 1
