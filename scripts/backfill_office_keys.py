"""One-time backfill: compute office_key for existing buyer_offices rows and
merge duplicates (references repoint to the surviving lowest-id row).

Usage: python -m scripts.backfill_office_keys
"""
from src import db
from src.intel.offices import office_key


def run():
    conn = db.get_conn()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute("""select id, department_name, subtier_name, office_name,
                              organization_code, full_parent_path_code
                       from buyer_offices order by id""")
        seen: dict[str, int] = {}
        merged = updated = 0
        for row in cur.fetchall():
            identity = dict(zip(("id", "department_name", "subtier_name", "office_name",
                                 "organization_code", "full_parent_path_code"),
                                row, strict=True))
            key, _, method = office_key(identity)
            if key == "unknown":
                continue
            if key in seen:                       # duplicate: repoint + delete
                survivor = seen[key]
                cur.execute("update opportunity_dossiers set buyer_office_id=%s "
                            "where buyer_office_id=%s", (survivor, identity["id"]))
                cur.execute("update office_market_stats set buyer_office_id=%s "
                            "where buyer_office_id=%s", (survivor, identity["id"]))
                cur.execute("delete from buyer_offices where id=%s", (identity["id"],))
                merged += 1
            else:
                cur.execute("update buyer_offices set office_key=%s, office_key_method=%s "
                            "where id=%s", (key, method, identity["id"]))
                seen[key] = identity["id"]
                updated += 1
        conn.commit()
        print(f"backfilled {updated} office keys; merged {merged} duplicates")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
