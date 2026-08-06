"""Persistence for delegation intelligence (global public-record data)."""
import json

from .intel.delegation import (
    committee_relevance,
    parse_place,
    resolve_confidence,
)
from .log import log


def upsert_legislator(cur, member: dict) -> int:
    cur.execute(
        """insert into legislators
             (bioguide_id, full_name, chamber, state, district, party, phone,
              office, website, contact_form, state_rank, fec_candidate_ids,
              committees, term_end, updated_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           on conflict (bioguide_id) do update set
             full_name=excluded.full_name, chamber=excluded.chamber,
             state=excluded.state, district=excluded.district,
             party=excluded.party, phone=excluded.phone, office=excluded.office,
             website=excluded.website, contact_form=excluded.contact_form,
             state_rank=excluded.state_rank,
             fec_candidate_ids=excluded.fec_candidate_ids,
             committees=excluded.committees, term_end=excluded.term_end,
             updated_at=now()
           returning id""",
        (member["bioguide_id"], member["full_name"], member["chamber"],
         member["state"], member.get("district"), member.get("party"),
         member.get("phone"), member.get("office"), member.get("website"),
         member.get("contact_form"), member.get("state_rank"),
         json.dumps(member.get("fec_candidate_ids") or []),
         json.dumps(member.get("committees") or []), member.get("term_end")))
    return cur.fetchone()[0]


def refresh_legislators(conn) -> int:
    from .adapters.legislators_dataset import fetch_current_legislators
    members = fetch_current_legislators()
    with conn.cursor() as cur:
        for m in members:
            upsert_legislator(cur, m)
    conn.commit()
    log("legislators_refreshed", count=len(members))
    return len(members)


def upsert_funding(cur, legislator_id: int, cycle: int, rows: list[dict]):
    for r in rows:
        cur.execute(
            """insert into legislator_funding
                 (legislator_id, cycle, kind, contributor_name, total,
                  contribution_count, fetched_at)
               values (%s,%s,%s,%s,%s,%s,now())
               on conflict (legislator_id, cycle, kind, contributor_name)
               do update set total=excluded.total,
                 contribution_count=excluded.contribution_count,
                 fetched_at=now()""",
            (legislator_id, cycle, r["kind"], r["contributor_name"][:200],
             r["total"], r.get("contribution_count")))


def refresh_legislator_funding(conn, cycle: int, limit_members: int = 600) -> int:
    """Top employer-aggregates + PAC receipts per member's principal committee."""
    from .adapters import fec
    updated = 0
    with conn.cursor() as cur:
        cur.execute("select id, bioguide_id, fec_candidate_ids from legislators "
                    "order by state, chamber limit %s", (limit_members,))
        members = cur.fetchall()
    for leg_id, _bioguide, fec_ids in members:
        candidate_ids = fec_ids if isinstance(fec_ids, list) else []
        if not candidate_ids:
            continue
        committee_id = fec.principal_committee_id(candidate_ids[-1])
        if not committee_id:
            continue
        rows = fec.top_employers(committee_id, cycle) + fec.top_pacs(committee_id, cycle)
        if not rows:
            continue
        with conn.cursor() as cur:
            upsert_funding(cur, leg_id, cycle, rows)
        conn.commit()
        updated += 1
    log("legislator_funding_refreshed", members=updated, cycle=cycle)
    return updated


def import_staff_csv(conn, path: str) -> int:
    """Operator import: name,title,bioguide_id,role_tag,email,source,source_date.
    Staff data has no free machine-readable source; every row keeps provenance."""
    import csv
    inserted = 0
    with open(path, newline="", encoding="utf-8") as f, conn.cursor() as cur:
        for row in csv.DictReader(f):
            cur.execute("select id from legislators where bioguide_id=%s",
                        (row["bioguide_id"].strip(),))
            found = cur.fetchone()
            if not found:
                continue
            cur.execute(
                """insert into legislator_staff
                     (legislator_id, name, title, role_tag, email, source, source_date)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (legislator_id, name, title) do update set
                     role_tag=excluded.role_tag, email=excluded.email,
                     source=excluded.source, source_date=excluded.source_date""",
                (found[0], row["name"].strip(), (row.get("title") or "").strip(),
                 (row.get("role_tag") or "").strip() or None,
                 (row.get("email") or "").strip() or None,
                 (row.get("source") or "operator import").strip(),
                 (row.get("source_date") or None)))
            inserted += 1
    conn.commit()
    log("staff_imported", rows=inserted)
    return inserted


def _district_for_place(cur, parsed: dict, geocode=None) -> dict:
    """Cached place → district resolution with confidence tiers."""
    if not parsed["place_key"]:
        return {"state": None, "congressional_district": None,
                "method": "state_only", "confidence": 0}
    cur.execute("select state, congressional_district, method, confidence "
                "from district_lookups where place_key=%s", (parsed["place_key"],))
    row = cur.fetchone()
    if row:
        return dict(zip(("state", "congressional_district", "method", "confidence"),
                        row, strict=True))
    method, district = "state_only", None
    if parsed["city"] and geocode is not None:
        query = ", ".join(p for p in (parsed["city"], parsed["state"],
                                      parsed["zip"]) if p)
        result = geocode(query)
        if result and result.get("state") == parsed["state"]:
            district = result["congressional_district"]
            method = "address_geocode" if parsed["zip"] else "city_geocode"
    confidence = resolve_confidence(method)
    cur.execute(
        """insert into district_lookups
             (place_key, state, congressional_district, method, confidence)
           values (%s,%s,%s,%s,%s)
           on conflict (place_key) do nothing""",
        (parsed["place_key"], parsed["state"], district, method, confidence))
    return {"state": parsed["state"], "congressional_district": district,
            "method": method, "confidence": confidence}


_LEG_COLS = ("id", "bioguide_id", "full_name", "chamber", "state", "district",
             "party", "phone", "office", "website", "contact_form", "state_rank",
             "committees")
_LEG_SELECT = """select id, bioguide_id, full_name, chamber, state, district,
                        party, phone, office, website, contact_form, state_rank,
                        committees from legislators"""


def resolve_delegation(conn, opportunity_id: int, geocode=None) -> list[dict]:
    """Resolve + cache the delegation for one opportunity. Senators match on
    state (confidence 95); the House member needs a district (tiered)."""
    with conn.cursor() as cur:
        cur.execute("select agency, place_of_performance from opportunities "
                    "where id=%s", (opportunity_id,))
        row = cur.fetchone()
        if not row:
            return []
        agency, place = row
        parsed = parse_place(place)
        if not parsed["state"]:
            return []
        lookup = _district_for_place(cur, parsed, geocode=geocode)
        cur.execute(_LEG_SELECT + " where state=%s and chamber='sen'",
                    (parsed["state"],))
        members = [dict(zip(_LEG_COLS, r, strict=True)) for r in cur.fetchall()]
        for m in members:
            m["match_method"], m["match_confidence"] = "state", 95
        if lookup["congressional_district"] is not None:
            cur.execute(_LEG_SELECT + " where state=%s and chamber='rep' "
                        "and coalesce(district, 0)=%s",
                        (parsed["state"], lookup["congressional_district"]))
            for r in cur.fetchall():
                m = dict(zip(_LEG_COLS, r, strict=True))
                m["match_method"] = lookup["method"]
                m["match_confidence"] = lookup["confidence"]
                members.append(m)
        for m in members:
            relevance = committee_relevance(agency, m.get("committees") or [])
            m["committee_relevance"] = relevance
            cur.execute(
                """insert into opportunity_delegations
                     (opportunity_id, legislator_id, match_method,
                      match_confidence, committee_relevance, resolved_at)
                   values (%s,%s,%s,%s,%s,now())
                   on conflict (opportunity_id, legislator_id) do update set
                     match_method=excluded.match_method,
                     match_confidence=excluded.match_confidence,
                     committee_relevance=excluded.committee_relevance,
                     resolved_at=now()""",
                (opportunity_id, m["id"], m["match_method"],
                 m["match_confidence"], json.dumps(relevance)))
    conn.commit()
    return members


# ---------------- district intelligence persistence ----------------

DISTRICT_AGENCIES = [
    "Department of Defense", "National Aeronautics and Space Administration",
    "Department of Justice", "Department of Homeland Security",
    "Department of Health and Human Services", "Department of Veterans Affairs",
    "Department of Energy", "General Services Administration",
    "Department of Transportation", "Department of Commerce",
    "Department of Agriculture", "Department of the Interior",
]


def refresh_district_spending(conn, fiscal_years: list[int],
                              agencies: list[str] | None = None) -> int:
    """FY × agency place-of-performance obligations per district. '' agency row
    is the all-agencies total. (FBI-level detail: FBI is a DOJ subtier; the
    toptier DOJ row covers it, subtier splits are a roadmap item.)"""
    from .adapters.usaspending_geo import district_obligations
    agencies = [""] + (agencies if agencies is not None else DISTRICT_AGENCIES)
    written = 0
    for fy in fiscal_years:
        for agency in agencies:
            rows = district_obligations(fy, agency or None)
            if not rows:
                continue
            with conn.cursor() as cur:
                for r in rows:
                    cur.execute(
                        """insert into district_spending
                             (state, district, fiscal_year, agency, obligations,
                              fetched_at)
                           values (%s,%s,%s,%s,%s,now())
                           on conflict (state, district, fiscal_year, agency)
                           do update set obligations=excluded.obligations,
                                         fetched_at=now()""",
                        (r["state"], r["district"], fy, agency, r["obligations"]))
                    written += 1
            conn.commit()
    log("district_spending_refreshed", rows=written, years=fiscal_years)
    return written


def import_election_results_csv(conn, path: str) -> int:
    """CSV: state,district,office,cycle,stage,candidate_name,party,votes,
    vote_share,won,incumbent,source  (MIT Election Lab exports map onto this).
    district blank for statewide; every row must carry a source."""
    import csv
    inserted = 0
    with open(path, newline="", encoding="utf-8") as f, conn.cursor() as cur:
        for row in csv.DictReader(f):
            if not (row.get("source") or "").strip():
                continue                      # provenance is mandatory
            district = row.get("district", "").strip()
            cur.execute(
                """insert into election_results
                     (state, district, office, cycle, stage, candidate_name,
                      party, votes, vote_share, won, incumbent, source)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (state, district_key, office, cycle, stage,
                                candidate_name)
                   do update set votes=excluded.votes,
                     vote_share=excluded.vote_share, won=excluded.won,
                     incumbent=excluded.incumbent, source=excluded.source""",
                (row["state"].strip().upper(),
                 int(district) if district else None,
                 row["office"].strip().lower(),
                 int(row["cycle"]), (row.get("stage") or "general").strip().lower(),
                 row["candidate_name"].strip(), (row.get("party") or "").strip() or None,
                 int(row["votes"]) if (row.get("votes") or "").strip() else None,
                 float(row["vote_share"]) if (row.get("vote_share") or "").strip() else None,
                 (row.get("won") or "").strip().lower() in ("1", "true", "yes"),
                 (row.get("incumbent") or "").strip().lower() in ("1", "true", "yes"),
                 row["source"].strip()))
            inserted += 1
    conn.commit()
    log("election_results_imported", rows=inserted)
    return inserted


def import_directed_spending_csv(conn, path: str) -> int:
    """CSV: fiscal_year,member_bioguide_id,member_name,state,district,agency,
    account,project,amount,source — from appropriations committee CPF tables.
    The ONE member-attributable funding category."""
    import csv
    inserted = 0
    with open(path, newline="", encoding="utf-8") as f, conn.cursor() as cur:
        for row in csv.DictReader(f):
            if not (row.get("source") or "").strip():
                continue
            district = (row.get("district") or "").strip()
            cur.execute(
                """insert into directed_spending
                     (fiscal_year, member_bioguide_id, member_name, state,
                      district, agency, account, project, amount, source)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (fiscal_year, member_name, project, amount)
                   do nothing""",
                (int(row["fiscal_year"]),
                 (row.get("member_bioguide_id") or "").strip() or None,
                 row["member_name"].strip(), row["state"].strip().upper(),
                 int(district) if district else None,
                 (row.get("agency") or "").strip() or None,
                 (row.get("account") or "").strip() or None,
                 row["project"].strip(), float(row["amount"]),
                 row["source"].strip()))
            inserted += 1
    conn.commit()
    log("directed_spending_imported", rows=inserted)
    return inserted


def refresh_candidate_finance(conn, cycle: int) -> int:
    """Incumbent cash-on-hand + challenger filings per House seat (FEC)."""
    from .adapters import fec
    updated = 0
    with conn.cursor() as cur:
        cur.execute("select id, full_name, state, district, chamber, "
                    "fec_candidate_ids from legislators")
        members = cur.fetchall()
    for leg_id, _name, state, district, chamber, fec_ids in members:
        office = "S" if chamber == "sen" else "H"
        candidates = fec.district_candidates(state, district, cycle, office=office)
        for c in candidates:
            committee_id = c.get("principal_committee_id")
            totals = (fec.committee_totals(committee_id, cycle)
                      if committee_id else None) or {}
            is_incumbent = (c.get("incumbent_challenge") == "I"
                            or (c.get("candidate_id") or "") in (fec_ids or []))
            with conn.cursor() as cur:
                cur.execute(
                    """insert into candidate_finance
                         (legislator_id, state, district, office, cycle,
                          candidate_name, candidate_id, is_incumbent, receipts,
                          disbursements, cash_on_hand, fetched_at)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                       on conflict (cycle, candidate_id) do update set
                         receipts=excluded.receipts,
                         disbursements=excluded.disbursements,
                         cash_on_hand=excluded.cash_on_hand,
                         is_incumbent=excluded.is_incumbent, fetched_at=now()""",
                    (leg_id if is_incumbent else None, state, district,
                     "senate" if office == "S" else "house", cycle,
                     c.get("candidate_name") or "UNKNOWN", c.get("candidate_id"),
                     is_incumbent, totals.get("receipts"),
                     totals.get("disbursements"), totals.get("cash_on_hand")))
            updated += 1
        conn.commit()
    log("candidate_finance_refreshed", rows=updated, cycle=cycle)
    return updated
