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

DEMO_AWARDS = [
    {"source": "usaspending", "source_award_id": f"DEMO-AW-{i}",
     "piid": f"W58RGZ2{i}C000{i}", "solicitation_number": "W58RGZ-21-R-0042",
     "award_title": "Inventory Management System Support",
     "award_description": "web-based inventory application support, dashboards, data migration",
     "recipient_name": name, "recipient_name_normalized": name.upper().replace(", INC.", ""),
     "recipient_uei": f"UEIDEMO{i}", "recipient_cage": None,
     "awarding_department": "DEPT OF DEFENSE", "awarding_subtier": "DEPT OF THE ARMY",
     "awarding_office": "ARMY CONTRACTING COMMAND", "awarding_office_code": None,
     "funding_department": "DEPT OF DEFENSE", "funding_subtier": "DEPT OF THE ARMY",
     "funding_office": None, "naics": "541512", "psc": "DA01",
     "award_type": "Definitive Contract", "contract_type": None, "contract_vehicle": None,
     "extent_competed": "Full and open competition",
     "set_aside": "Total Small Business Set-Aside",
     "award_date": f"202{i}-06-15", "period_start": f"202{i}-06-15",
     "period_end": "2026-09-30" if i == 3 else f"202{i + 2}-06-14",
     "obligated_amount": float(2_000_000 + i * 1_750_000),
     "total_obligated_amount": None, "potential_total_value": None,
     "place_of_performance_json": {"city": "Huntsville", "state": "AL"},
     "raw_json": {"demo": True}, "content_hash": f"demohash{i}"}
    for i, name in ((1, "ABC Systems, Inc."), (2, "ABC Systems, Inc."),
                    (3, "ABC Systems, Inc."), (4, "Northstar Data LLC"))
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
