"""Persistence for the intelligence layer: awards, offices, dossiers, links."""
import datetime as _dt
import decimal
import json


def _json_default(o):
    """Dossiers are built from DB rows: Decimals and dates must serialize."""
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(value) -> str:
    return json.dumps(value, default=_json_default)

_AWARD_COLS = (
    "source", "source_award_id", "piid", "parent_award_id", "solicitation_number",
    "award_title", "award_description", "recipient_name", "recipient_name_normalized",
    "recipient_uei", "recipient_cage", "awarding_department", "awarding_subtier",
    "awarding_office", "awarding_office_code", "funding_department", "funding_subtier",
    "funding_office", "naics", "psc", "award_type", "contract_type", "contract_vehicle",
    "extent_competed", "set_aside", "award_date", "period_start", "period_end",
    "obligated_amount", "total_obligated_amount", "potential_total_value",
)

_UPSERT_AWARD_SQL = """
    insert into contract_awards
      (source, source_award_id, piid, parent_award_id, solicitation_number,
       award_title, award_description, recipient_name, recipient_name_normalized,
       recipient_uei, recipient_cage, awarding_department, awarding_subtier,
       awarding_office, awarding_office_code, funding_department, funding_subtier,
       funding_office, naics, psc, award_type, contract_type, contract_vehicle,
       extent_competed, set_aside, award_date, period_start, period_end,
       obligated_amount, total_obligated_amount, potential_total_value,
       place_of_performance_json, raw_json, content_hash)
    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s)
    on conflict (source, source_award_id) do update
      set obligated_amount=excluded.obligated_amount,
          total_obligated_amount=excluded.total_obligated_amount,
          period_end=excluded.period_end,
          raw_json=excluded.raw_json, content_hash=excluded.content_hash,
          updated_at=now()
    returning id"""


def upsert_award(cur, a: dict) -> int:
    cur.execute(_UPSERT_AWARD_SQL,
                tuple(a.get(c) for c in _AWARD_COLS)
                + (dumps(a.get("place_of_performance_json") or {}),
                   dumps(a.get("raw_json") or {}), a["content_hash"]))
    return cur.fetchone()[0]


def upsert_buyer_office(cur, identity: dict, confidence: int) -> int | None:
    """Upsert by deterministic office_key (see intel.offices.office_key) so
    repeated enrichment can never duplicate an office."""
    from .intel.offices import office_key as _office_key
    key, key_conf, method = _office_key(identity)
    if key == "unknown":
        return None
    cur.execute(
        """insert into buyer_offices
             (department_name, subtier_name, office_name, organization_code,
              full_parent_path_name, full_parent_path_code, source_confidence,
              office_key, office_key_method)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (office_key) where office_key is not null do update set
             department_name=coalesce(buyer_offices.department_name, excluded.department_name),
             subtier_name=coalesce(buyer_offices.subtier_name, excluded.subtier_name),
             office_name=coalesce(buyer_offices.office_name, excluded.office_name),
             source_confidence=greatest(buyer_offices.source_confidence,
                                        excluded.source_confidence),
             last_seen_at=now(), updated_at=now()
           returning id""",
        (identity.get("department_name"), identity.get("subtier_name"),
         identity.get("office_name"), identity.get("organization_code"),
         identity.get("full_parent_path_name"), identity.get("full_parent_path_code"),
         max(confidence, key_conf), key, method))
    row = cur.fetchone()
    return row[0] if row else None


_AWARD_SELECT = """
    select source, source_award_id, piid, parent_award_id, solicitation_number,
           award_title, award_description, recipient_name, recipient_name_normalized,
           recipient_uei, recipient_cage, awarding_department, awarding_subtier,
           awarding_office, awarding_office_code, funding_department, funding_subtier,
           funding_office, naics, psc, award_type, contract_type, contract_vehicle,
           extent_competed, set_aside, award_date, period_start, period_end,
           obligated_amount, total_obligated_amount, potential_total_value,
           place_of_performance_json
    from contract_awards"""
_AWARD_ORDER = " order by award_date desc nulls last limit %s"
# Static query variants — no query text is ever assembled from variables.
_Q_BY_OFFICE_CODE = _AWARD_SELECT + " where awarding_office_code=%s" + _AWARD_ORDER
_Q_BY_OFFICE_NAME = _AWARD_SELECT + " where upper(awarding_office)=upper(%s)" + _AWARD_ORDER
_Q_BY_SUBTIER_NAICS = (_AWARD_SELECT
                       + " where upper(awarding_subtier)=upper(%s) and naics=%s" + _AWARD_ORDER)
_Q_BY_SUBTIER = _AWARD_SELECT + " where upper(awarding_subtier)=upper(%s)" + _AWARD_ORDER

for _f in _AWARD_COLS:
    if _f not in _AWARD_SELECT:
        raise RuntimeError(f"_AWARD_COLS out of sync with _AWARD_SELECT: {_f}")


def fetch_candidate_awards(cur, identity: dict, naics: str | None, limit: int = 400):
    """Two pools: office-attributed awards, and subtier/category fallback."""
    cols = _AWARD_COLS + ("place_of_performance_json",)

    def q(sql, params):
        cur.execute(sql, params + (limit,))
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    office, subtier = [], []
    if identity.get("organization_code"):
        office = q(_Q_BY_OFFICE_CODE, (identity["organization_code"],))
    if not office and identity.get("office_name"):
        office = q(_Q_BY_OFFICE_NAME, (identity["office_name"],))
    if identity.get("subtier_name"):
        if naics:
            subtier = q(_Q_BY_SUBTIER_NAICS, (identity["subtier_name"], naics))
        if not subtier:
            subtier = q(_Q_BY_SUBTIER, (identity["subtier_name"],))
    return office, subtier


def save_links(cur, opportunity_id: int, links: list[dict], award_ids: dict):
    for ln in links:
        aid = award_ids.get(ln["award"].get("source_award_id"))
        if not aid:
            continue
        cur.execute(
            """insert into opportunity_award_links
                 (opportunity_id, contract_award_id, link_type, similarity_score,
                  confidence, evidence_json)
               values (%s,%s,%s,%s,%s,%s)
               on conflict (opportunity_id, contract_award_id, link_type) do update
                 set similarity_score=excluded.similarity_score,
                     evidence_json=excluded.evidence_json""",
            (opportunity_id, aid, ln["link_type"], ln["similarity_score"],
             ln["similarity_score"], dumps(ln["evidence"])))


def save_dossier(cur, opportunity_id: int, buyer_office_id: int | None, dossier: dict):
    cur.execute(
        """insert into opportunity_dossiers
             (opportunity_id, buyer_office_id, dossier_version, snapshot_json,
              buyer_profile_json, similar_work_json, last_10_relevant_awards_json,
              incumbent_analysis_json, work_origin_assessment_json, funding_context_json,
              market_size_json, competition_landscape_json, acquisition_pattern_json,
              pursuit_recommendation_json, data_quality_json,
              contract_family_json, buyer_dna_json, generated_at, updated_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())
           on conflict (opportunity_id) do update set
             buyer_office_id=excluded.buyer_office_id,
             dossier_version=excluded.dossier_version,
             snapshot_json=excluded.snapshot_json,
             buyer_profile_json=excluded.buyer_profile_json,
             similar_work_json=excluded.similar_work_json,
             last_10_relevant_awards_json=excluded.last_10_relevant_awards_json,
             incumbent_analysis_json=excluded.incumbent_analysis_json,
             work_origin_assessment_json=excluded.work_origin_assessment_json,
             funding_context_json=excluded.funding_context_json,
             market_size_json=excluded.market_size_json,
             competition_landscape_json=excluded.competition_landscape_json,
             acquisition_pattern_json=excluded.acquisition_pattern_json,
             pursuit_recommendation_json=excluded.pursuit_recommendation_json,
             data_quality_json=excluded.data_quality_json,
             contract_family_json=excluded.contract_family_json,
             buyer_dna_json=excluded.buyer_dna_json,
             generated_at=now(), updated_at=now()""",
        (opportunity_id, buyer_office_id, dossier["dossier_version"],
         dumps(dossier["snapshot"]), dumps(dossier["buyer_profile"]),
         dumps(dossier["similar_work"]), dumps(dossier["last_10_relevant_awards"]),
         dumps(dossier["incumbent_analysis"]), dumps(dossier["work_origin_assessment"]),
         dumps(dossier["funding_context"]), dumps(dossier["market_size"]),
         dumps(dossier["competition_landscape"]), dumps(dossier["acquisition_pattern"]),
         dumps(dossier["pursuit_recommendation"]), dumps(dossier["data_quality"]),
         dumps(dossier.get("contract_family") or {}),
         dumps(dossier.get("buyer_dna") or {})))


def fetch_dossier(cur, opportunity_id: int) -> dict | None:
    cur.execute(
        """select snapshot_json, buyer_profile_json, similar_work_json,
                  last_10_relevant_awards_json, incumbent_analysis_json,
                  work_origin_assessment_json, funding_context_json, market_size_json,
                  competition_landscape_json, acquisition_pattern_json,
                  pursuit_recommendation_json, data_quality_json,
                  contract_family_json, buyer_dna_json, generated_at
           from opportunity_dossiers where opportunity_id=%s""", (opportunity_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("snapshot", "buyer_profile", "similar_work", "last_10_relevant_awards",
            "incumbent_analysis", "work_origin_assessment", "funding_context",
            "market_size", "competition_landscape", "acquisition_pattern",
            "pursuit_recommendation", "data_quality", "contract_family",
            "buyer_dna")
    d = dict(zip(keys, row[:-1], strict=True))
    d["generated_at"] = str(row[-1])
    return d


def pending_enrichment(cur, limit: int = 50):
    cur.execute(
        """select o.id from opportunities o
           join classifications c on c.opportunity_id=o.id
           where o.enrichment_status in ('pending','failed') and c.score >= 40
           order by c.score desc limit %s""", (limit,))
    return [r[0] for r in cur.fetchall()]


def mark_enrichment(cur, opportunity_id: int, status: str):
    cur.execute(
        "update opportunities set enrichment_status=%s, enriched_at=now() where id=%s",
        (status, opportunity_id))


def fetch_all_awards(cur, limit: int = 20000) -> list[dict]:
    cols = _AWARD_COLS + ("place_of_performance_json",)
    cur.execute(_AWARD_SELECT + _AWARD_ORDER, (limit,))
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def upsert_vendor_profile(cur, p: dict):
    cur.execute(
        """insert into vendor_profiles
             (recipient_name, normalized_recipient_name, recipient_uei, recipient_cage,
              total_obligations, award_count, first_award_date, last_award_date,
              top_agencies_json, top_naics_json, top_psc_json, top_offices_json,
              source_confidence, updated_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           on conflict (normalized_recipient_name, recipient_uei) do update set
             total_obligations=excluded.total_obligations,
             award_count=excluded.award_count,
             first_award_date=excluded.first_award_date,
             last_award_date=excluded.last_award_date,
             top_agencies_json=excluded.top_agencies_json,
             top_naics_json=excluded.top_naics_json,
             top_psc_json=excluded.top_psc_json,
             top_offices_json=excluded.top_offices_json,
             updated_at=now()""",
        (p.get("recipient_name"), p.get("normalized_recipient_name"),
         p.get("recipient_uei") or "", p.get("recipient_cage"),
         p.get("total_obligations", 0), p.get("award_count", 0),
         p.get("first_award_date"), p.get("last_award_date"),
         dumps(p.get("top_agencies", [])), dumps(p.get("top_naics", [])),
         dumps(p.get("top_psc", [])), dumps(p.get("top_offices", [])),
         p.get("source_confidence", 60)))


def upsert_office_market_stat(cur, buyer_office_id: int, row: dict):
    cur.execute(
        """insert into office_market_stats
             (buyer_office_id, fiscal_year, naics, psc, fedintel_category,
              award_count, total_obligations,
              median_award_value, average_award_value, largest_award_value,
              unique_vendor_count, top_vendor_share, small_business_share,
              set_aside_share, competed_share, updated_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           on conflict (buyer_office_id, fiscal_year, naics_key, psc_key) do update set
             award_count=excluded.award_count,
             total_obligations=excluded.total_obligations,
             median_award_value=excluded.median_award_value,
             average_award_value=excluded.average_award_value,
             largest_award_value=excluded.largest_award_value,
             unique_vendor_count=excluded.unique_vendor_count,
             top_vendor_share=excluded.top_vendor_share,
             small_business_share=excluded.small_business_share,
             set_aside_share=excluded.set_aside_share,
             competed_share=excluded.competed_share,
             fedintel_category=excluded.fedintel_category,
             updated_at=now()""",
        (buyer_office_id, row["fiscal_year"], row.get("naics"), row.get("psc"),
         row.get("fedintel_category"), row["award_count"],
         row["total_obligations"], row.get("median_award_value"),
         row.get("average_award_value"), row.get("largest_award_value"),
         row.get("unique_vendor_count"), row.get("top_vendor_share"),
         row.get("small_business_share"), row.get("set_aside_share"),
         row.get("competed_share")))


def update_office_from_hierarchy(cur, office_id: int, h: dict):
    cur.execute(
        """update buyer_offices set
             department_name=coalesce(%s, department_name),
             department_code=coalesce(%s, department_code),
             subtier_name=coalesce(%s, subtier_name),
             subtier_code=coalesce(%s, subtier_code),
             office_code=coalesce(%s, office_code),
             location_json=coalesce(%s, location_json),
             source_confidence=greatest(source_confidence, %s),
             raw_hierarchy_json=%s, updated_at=now()
           where id=%s""",
        (h.get("department_name"), h.get("department_code"), h.get("subtier_name"),
         h.get("subtier_code"), h.get("office_code"),
         dumps(h.get("location_json") or {}), h.get("source_confidence", 85),
         dumps(h.get("raw_hierarchy_json") or {}), office_id))


def opportunities_for_solnums(cur, solnums: list[str]) -> list[int]:
    if not solnums:
        return []
    cur.execute("select id from opportunities where solicitation_number = any(%s)", (solnums,))
    return [r[0] for r in cur.fetchall()]


def requeue_enrichment(cur, opportunity_ids: list[int]):
    if opportunity_ids:
        cur.execute(
            "update opportunities set enrichment_status='pending' where id = any(%s)",
            (opportunity_ids,))
