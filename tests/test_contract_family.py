"""Contract family, recompete clock, and vulnerability signals."""
from datetime import date

from src.intel.buyer_dna import build_buyer_dna
from src.intel.contract_family import build_contract_family

TODAY = date(2026, 8, 6)
OPP = {"title": "IT support services recompete", "description_text": "",
       "set_aside": None}


def _award(**kw):
    a = {"source_award_id": kw.get("source_award_id", "A1"), "piid": "W9124-20-C-0001",
         "parent_award_id": None, "recipient_name": "ACME CORP",
         "award_title": "IT support", "award_date": "2020-09-15",
         "period_start": "2020-10-01", "period_end": "2025-09-30",
         "obligated_amount": 5_000_000, "total_obligated_amount": 5_000_000,
         "potential_total_value": 10_000_000, "award_type": "C",
         "contract_vehicle": None}
    a.update(kw)
    return a


def _link(award, link_type="same_solicitation", sim=90,
          evidence=("shares the solicitation number",)):
    return {"award": award, "link_type": link_type, "similarity_score": sim,
            "evidence": list(evidence)}


def test_confirmed_predecessor_and_recompete_clock():
    fam = build_contract_family(OPP, [_link(_award())], today=TODAY)
    assert fam["member_count"] == 1
    m = fam["members"][0]
    assert m["role"] == "predecessor" and m["confirmed"]
    rc = fam["recompete"]
    assert rc["estimated_expiration"] == "2025-09-30"
    assert rc["assumptions"]
    # period already passed → caveat present and confidence reduced
    assert any("already passed" in c for c in rc["caveats"])


def test_inferred_member_marked_and_low_similarity_excluded():
    links = [_link(_award(source_award_id="B1"), "same_office_same_naics", 60,
                   ("same buying office", "NAICS matches")),
             _link(_award(source_award_id="B2"), "similar_scope", 41,
                   ("scope keywords",))]
    fam = build_contract_family(OPP, links, today=TODAY)
    assert fam["member_count"] == 1          # 41-sim link excluded
    assert not fam["members"][0]["confirmed"]
    assert fam["members"][0]["role"] == "predecessor"  # best inferred promoted
    assert fam["confirmed_count"] == 0


def test_bridge_detection_and_vulnerability_signal():
    base = _award()
    bridge = _award(source_award_id="A2", piid="W9124-25-P-0009",
                    award_date="2025-10-01", period_start="2025-10-05",
                    period_end="2026-03-31", obligated_amount=400_000,
                    total_obligated_amount=400_000, potential_total_value=400_000)
    links = [_link(base), _link(bridge, "same_office_same_naics", 70,
                                ("same buying office", "NAICS matches"))]
    fam = build_contract_family(OPP, links, today=TODAY)
    roles = {m["source_award_id"]: m["role"] for m in fam["members"]}
    assert roles["A2"] == "bridge"
    vul = fam["vulnerability"]
    assert any(s["signal"] == "bridge extension" for s in vul["signals"])


def test_vulnerability_no_members_is_no_defensible_assessment():
    fam = build_contract_family(OPP, [], today=TODAY)
    assert fam["vulnerability"]["assessment"] == "no defensible assessment"
    assert fam["recompete"]["estimated_expiration"] is None


def test_vulnerability_never_claims_cpars():
    fam = build_contract_family(OPP, [_link(_award())], today=TODAY)
    assert any("CPARS" in c for c in fam["vulnerability"]["caveats"])


def test_set_aside_change_signal():
    opp = dict(OPP, set_aside="Total Small Business")
    fam = build_contract_family(opp, [_link(_award())], today=TODAY)
    assert any(s["signal"] == "set-aside on the new notice"
               for s in fam["vulnerability"]["signals"])


def test_timeline_merges_lineage_and_awards_with_confirmed_flags():
    lineage = [{"stage": "Sources Sought", "opportunity_id": 5,
                "posted_date": "2026-01-10"}]
    fam = build_contract_family(OPP, [_link(_award())], lineage_rows=lineage,
                                today=TODAY)
    kinds = [t["kind"] for t in fam["timeline"]]
    assert "notice" in kinds and "award" in kinds and "recompete_estimate" in kinds
    dates = [t["date"] for t in fam["timeline"]]
    assert dates == sorted(dates)
    est = next(t for t in fam["timeline"] if t["kind"] == "recompete_estimate")
    assert est["confirmed"] is False


# ---- Buyer DNA ----

def _pool(n, office="OFF-A", code="C1", vendor="V", competed="FULL AND OPEN COMPETITION",
          set_aside=None, month="03"):
    return [{"awarding_office": office, "awarding_office_code": code,
             "recipient_name": f"{vendor}{i % 3}", "recipient_name_normalized": f"{vendor}{i % 3}",
             "obligated_amount": 1_000_000, "extent_competed": competed,
             "set_aside": set_aside, "award_date": f"202{i % 4}-{month}-01",
             "contract_vehicle": None} for i in range(n)]


def test_buyer_dna_insufficient_data_gets_no_labels():
    dna = build_buyer_dna(_pool(3), _pool(3, office="OFF-B", code="C2"))
    assert dna["status"] == "insufficient_data"
    assert dna["labels"] == []


def test_buyer_dna_material_delta_produces_label_with_baseline():
    office = _pool(10, month="08")                      # all Q4 awards
    peers = _pool(20, office="OFF-B", code="C2", month="02")  # none in Q4
    dna = build_buyer_dna(office, peers)
    assert dna["status"] == "ok"
    q4 = next(c for c in dna["comparisons"] if c["key"] == "q4_share_pct")
    assert q4["material"] and q4["office_value_pct"] == 100
    label = next(lb for lb in dna["labels"] if lb["label"] == "Q4-driven")
    assert "peer baseline" in label["evidence"]
    assert label["implication"]


def test_buyer_dna_excludes_own_office_from_peers():
    office = _pool(10)
    subtier = office + _pool(12, office="OFF-B", code="C2")
    dna = build_buyer_dna(office, subtier)
    assert dna["basis"]["peer_awards"] == 12


def test_buyer_dna_similar_metrics_get_no_label():
    office = _pool(12)
    peers = _pool(12, office="OFF-B", code="C2")
    dna = build_buyer_dna(office, peers)
    assert all(not c["material"] for c in dna["comparisons"])
    assert dna["labels"] == []
