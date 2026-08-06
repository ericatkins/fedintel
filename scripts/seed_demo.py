"""Seed demo data so the web app shows Bloomberg-style workflows immediately.

Creates: demo user/org, a company profile, three scored opportunities with
change events (including a Sources Sought -> Solicitation stage transition),
award history, and a full dossier for the flagship opportunity.

Usage:  python -m scripts.seed_demo
Login:  demo@fedintel.local / fedintel-demo-password
"""
import json
from datetime import datetime, timedelta, timezone

from src import db, db_intel
from src.classify import classify
from src.db import save_classification, upsert_opportunity
from src.intel.dossier import build_dossier
from src.intel.offices import office_identity_from_opportunity, office_key
from src.normalize import normalize_sam
from src.web.auth import hash_password

NOW = datetime.now(timezone.utc)

DEMO_OPPS = [
    {"noticeId": "demo-inv-001", "solicitationNumber": "W58RGZ-26-R-0042",
     "title": "Enterprise Inventory Management System Modernization",
     "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY.ARMY CONTRACTING COMMAND",
     "type": "Solicitation", "naicsCode": "541512",
     "typeOfSetAside": "Total Small Business Set-Aside",
     "postedDate": NOW.strftime("%Y-%m-%d"),
     "responseDeadLine": (NOW + timedelta(days=18)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
     "placeOfPerformance": {"city": {"name": "Huntsville"}, "state": {"code": "AL"}},
     "officeAddress": {"city": "Redstone Arsenal", "state": "AL"},
     "description": ("Modernize a legacy inventory management application into a web-based "
                     "system with dashboards, workflow automation, API integration, and data "
                     "migration from the existing system."),
     "uiLink": "https://sam.gov/opp/demo-inv-001/view"},
    {"noticeId": "demo-cyber-002", "solicitationNumber": "FA8750-26-R-0100",
     "title": "Zero Trust Security Automation Toolkit",
     "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE.AFRL",
     "type": "Sources Sought", "naicsCode": "541512", "typeOfSetAside": None,
     "postedDate": NOW.strftime("%Y-%m-%d"),
     "responseDeadLine": (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
     "placeOfPerformance": {"city": {"name": "Rome"}, "state": {"code": "NY"}},
     "description": "Market research for cybersecurity software, security automation and "
                    "vulnerability management tooling.",
     "uiLink": "https://sam.gov/opp/demo-cyber-002/view"},
]

# Same solicitation posted earlier as Sources Sought -> creates a stage transition
DEMO_EARLIER_STAGE = {**DEMO_OPPS[0], "noticeId": "demo-inv-000", "type": "Sources Sought",
                      "title": "Inventory Management Modernization — Market Research"}

def _award(i, name, *, office="ARMY CONTRACTING COMMAND", title=None,
           description=None, award_date=None, period_start=None,
           period_end=None, obligated=None, potential=None, competed=None,
           set_aside="Total Small Business Set-Aside", piid=None,
           solicitation="W58RGZ-21-R-0042"):
    return {
        "source": "usaspending", "source_award_id": f"DEMO-AW-{i}",
        "piid": piid or f"W58RGZ2{i % 10}C{i:04d}",
        "solicitation_number": solicitation,
        "award_title": title or "Inventory Management System Support",
        "award_description": description or ("web-based inventory application "
                                             "support, dashboards, data migration"),
        "recipient_name": name,
        "recipient_name_normalized": name.upper().replace(", INC.", ""),
        "recipient_uei": f"UEIDEMO{i}", "recipient_cage": None,
        "awarding_department": "DEPT OF DEFENSE",
        "awarding_subtier": "DEPT OF THE ARMY",
        "awarding_office": office, "awarding_office_code": None,
        "funding_department": "DEPT OF DEFENSE",
        "funding_subtier": "DEPT OF THE ARMY", "funding_office": None,
        "naics": "541512", "psc": "DA01", "award_type": "Definitive Contract",
        "contract_type": None, "contract_vehicle": None,
        "extent_competed": competed or "Full and open competition",
        "set_aside": set_aside,
        "award_date": award_date or f"202{i % 5}-06-15",
        "period_start": period_start or award_date or f"202{i % 5}-06-15",
        "period_end": period_end or "2026-06-14",
        "obligated_amount": float(obligated or 2_000_000 + (i % 5) * 1_750_000),
        "total_obligated_amount": float(obligated) if obligated else None,
        "potential_total_value": float(potential) if potential else None,
        "place_of_performance_json": {"city": "Huntsville", "state": "AL"},
        "raw_json": {"demo": True}, "content_hash": f"demohash{i}",
    }


DEMO_AWARDS = [
    # The contract family behind the flagship recompete: ABC held it for
    # years, Northstar took it over, and a short bridge follows Northstar's
    # period end — classic contested-recompete signals.
    _award(1, "ABC Systems, Inc.", award_date="2021-06-15",
           period_end="2023-06-14"),
    _award(2, "ABC Systems, Inc.", award_date="2022-06-15",
           period_end="2024-06-14"),
    _award(3, "ABC Systems, Inc.", award_date="2023-06-15",
           period_end="2025-06-14"),
    _award(4, "Northstar Data LLC", award_date="2024-06-15",
           period_end="2026-06-14", obligated=9_000_000, potential=22_000_000),
    _award(5, "Northstar Data LLC", title="Inventory System Bridge Support",
           award_date="2026-06-20", period_start="2026-06-20",
           period_end="2026-12-19", obligated=800_000, potential=800_000,
           competed="Not competed", piid="W58RGZ26P0099",
           solicitation=None),
    # Additional office history so Buyer DNA has a real office pool: awards
    # cluster in Q4 and repeat the same vendors.
    *[_award(10 + j, ("ABC Systems, Inc.", "Northstar Data LLC",
                      "Redstone Apps LLC")[j % 3],
             title="Logistics software task", award_date=f"202{2 + j % 4}-08-2{j % 9}",
             period_end=f"202{4 + j % 3}-08-01", obligated=1_200_000 + j * 90_000)
      for j in range(8)],
    # Peer-office awards (same subtier, same NAICS, different office): spread
    # across the year, diverse vendors, so the office's Q4/incumbent behavior
    # is materially different from its peers.
    *[_award(30 + j, f"Peer Vendor {j:02d} LLC", office="PEO ENTERPRISE SERVICES",
             title="Enterprise software services", award_date=f"202{2 + j % 4}-0{2 + j % 4}-11",
             period_end=f"202{4 + j % 3}-03-01", obligated=1_500_000 + j * 120_000,
             set_aside=None, solicitation=None)
      for j in range(12)],
]

DEMO_PROJECTS = [
    {"title": "Army Logistics Cloud Migration",
     "customer_agency": "Dept of the Army",
     "customer_office": "Army Contracting Command",
     "contract_identifier": "W58RGZ-23-C-0107", "role": "prime",
     "naics": "541512", "period_start": "2023-01-15", "period_end": "2025-06-30",
     "value_total": 3_200_000,
     "scope": "Migrated a legacy inventory application to a cloud web system "
              "with dashboards, workflow automation, and data migration",
     "technologies": "Python, Postgres, AWS, API integration",
     "outcomes": "Cut inventory reconciliation time 60%",
     "partners": "", "source_note": "contract file + final CPARS copy"},
    {"title": "State Health Data Warehouse",
     "customer_agency": "State of Alabama", "customer_office": "",
     "contract_identifier": "AL-DPH-2016-44", "role": "sub",
     "naics": "541511", "period_start": "2016-02-01", "period_end": "2018-09-30",
     "value_total": 900_000,
     "scope": "Data warehouse and reporting dashboards for public health data",
     "technologies": "SQL Server, ETL", "outcomes": "",
     "partners": "BigPrime Corp", "source_note": "subcontract agreement"},
]

DEMO_REQUIREMENTS = [
    ("set_aside", "Total Small Business",
     "This procurement is a Total Small Business Set-Aside under FAR 19.5.", 2),
    ("clearance", "Secret",
     "Key personnel shall possess an active SECRET clearance at award.", 14),
    ("certification", "CMMC Level 2",
     "The contractor shall achieve CMMC Level 2 certification prior to award.", 15),
    ("personnel", "cloud migration engineers",
     "The contractor shall provide experienced cloud migration engineers.", 9),
    ("submission", "20-page technical volume limit",
     "The technical volume shall not exceed 20 pages.", 31),
    ("deliverable", "monthly status reports",
     "The contractor shall deliver monthly status reports to the COR.", 12),
]


def run():
    conn = db.get_conn()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        # demo account
        cur.execute("select id from users where email=%s", ("demo@fedintel.local",))
        if not cur.fetchone():
            cur.execute("insert into users (email, password_hash, is_admin, "
                        "email_verified_at) values (%s,%s,true,now()) returning id",
                        ("demo@fedintel.local", hash_password("fedintel-demo-password")))
            uid = cur.fetchone()[0]
            cur.execute("insert into organizations (name) values ('Demo Softworks') returning id")
            oid = cur.fetchone()[0]
            cur.execute("insert into organization_members (organization_id, user_id, role) "
                        "values (%s,%s,'owner')", (oid, uid))
            with open("company_profile.example.json", encoding="utf-8") as f:
                cur.execute("insert into company_profiles (organization_id, profile) "
                            "values (%s,%s)", (oid, f.read()))
        # awards first so the dossier has history
        for a in DEMO_AWARDS:
            db_intel.upsert_award(cur, a)
        # earlier stage, then current stage (records the stage transition)
        for raw in (DEMO_EARLIER_STAGE, *DEMO_OPPS):
            opp = normalize_sam(raw)
            opp_id, _, _ = upsert_opportunity(cur, opp)
            result = classify(opp, json.load(open("company_profile.example.json",
                                                  encoding="utf-8")))
            save_classification(cur, opp_id, result)
            if raw["noticeId"] == "demo-inv-001":
                identity = office_identity_from_opportunity(opp)
                _, conf, _ = office_key(identity)
                office_id = db_intel.upsert_buyer_office(cur, identity, conf)
                awards_office, awards_subtier = db_intel.fetch_candidate_awards(
                    cur, identity, opp.get("naics"))
                dossier = build_dossier(opp, result, awards_office, awards_subtier, [], [])
                db_intel.save_dossier(cur, opp_id, office_id, dossier)
                db_intel.mark_enrichment(cur, opp_id, "done")
        # subscription + per-org matches: the full multi-user workflow is visible
        cur.execute("select u.id, m.organization_id from users u "
                    "join organization_members m on m.user_id=u.id "
                    "where u.email='demo@fedintel.local' limit 1")
        demo_uid, demo_oid = cur.fetchone()

        # amendment: the flagship deadline moves, recording a field-level diff
        amended = dict(DEMO_OPPS[0])
        amended["responseDeadLine"] = (NOW + timedelta(days=25)).strftime(
            "%Y-%m-%dT%H:%M:%S+0000")
        upsert_opportunity(cur, normalize_sam(amended))

        # solicitation document + extracted requirements → compliance matrix,
        # qualification verdict, and requirement-to-proof all light up
        cur.execute("select id from opportunities where source_notice_id=%s",
                    ("demo-inv-001",))
        flagship_id = cur.fetchone()[0]
        cur.execute(
            """insert into opportunity_documents (opportunity_id, source_url,
                 filename, content_type, byte_size, sha256, page_count,
                 text_chars, doc_kind, fetch_status, fetched_at, extracted_at)
               values (%s,%s,%s,'application/pdf',482133,%s,42,88000,'pws',
                       'extracted',now(),now())
               on conflict (opportunity_id, source_url) do nothing""",
            (flagship_id,
             "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/demo-pws/download",
             "PWS_Inventory_Modernization.pdf", "d" * 64))
        cur.execute("select id from opportunity_documents where opportunity_id=%s "
                    "limit 1", (flagship_id,))
        doc_id = cur.fetchone()[0]
        for rtype, value, quote, page in DEMO_REQUIREMENTS:
            cur.execute(
                """insert into document_requirements (opportunity_id, document_id,
                     requirement_type, value, evidence_quote, page, method,
                     confidence)
                   values (%s,%s,%s,%s,%s,%s,'seed_demo_rule',85)
                   on conflict do nothing""",
                (flagship_id, doc_id, rtype, value, quote, page))

        # past-performance evidence library
        cur.execute("select count(*) from company_projects where organization_id=%s",
                    (demo_oid,))
        if cur.fetchone()[0] == 0:
            for p in DEMO_PROJECTS:
                cur.execute(
                    """insert into company_projects (organization_id, title,
                         customer_agency, customer_office, contract_identifier,
                         role, naics, psc, period_start, period_end, value_total,
                         scope, technologies, outcomes, partners, source_note)
                       values (%s,%s,%s,%s,%s,%s,%s,null,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (demo_oid, p["title"], p["customer_agency"],
                     p["customer_office"], p["contract_identifier"], p["role"],
                     p["naics"], p["period_start"], p["period_end"],
                     p["value_total"], p["scope"], p["technologies"],
                     p["outcomes"], p["partners"], p["source_note"]))

        # one open capture task so the watchlist tasks table is populated
        cur.execute("select count(*) from capture_tasks where organization_id=%s",
                    (demo_oid,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                """insert into capture_tasks (organization_id, opportunity_id,
                     user_id, title, detail, owner, due_date, source)
                   values (%s,%s,%s,%s,%s,'demo user',
                           (now() + interval '10 days')::date, 'generated')""",
                (demo_oid, flagship_id,
                 demo_uid, "Verify Northstar bridge award and recompete timing",
                 "Bridge W58RGZ26P0099 suggests a delayed recompete — confirm "
                 "with the contracting office before the response deadline."))
        cur.execute(
            """insert into digest_subscriptions (organization_id, user_id, email,
                 timezone, min_score) values (%s,%s,%s,'America/Chicago',40)
               on conflict do nothing""",
            (demo_oid, demo_uid, "demo@fedintel.local"))
        from src.matching import refresh_profile_matches_for_org
        conn.commit()
        refresh_profile_matches_for_org(conn, demo_oid)
        print("Demo data seeded. Login: demo@fedintel.local / fedintel-demo-password")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
