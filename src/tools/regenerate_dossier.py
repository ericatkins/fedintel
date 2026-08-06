"""Admin tool: regenerate a dossier and inspect its evidence.

Usage:
  python -m src.tools.regenerate_dossier <opportunity_id>
  python -m src.tools.regenerate_dossier <opportunity_id> --show
"""
import json
import sys

from .. import db, db_intel
from ..enrich import enrich_one
from ..profile import load_profile


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print(__doc__)
        raise SystemExit(2)
    opp_id = int(sys.argv[1])
    conn = db.get_conn()
    conn.autocommit = False
    try:
        ok = enrich_one(conn, opp_id, load_profile())
        print(f"regenerated dossier for opportunity {opp_id}: {'ok' if ok else 'FAILED'}")
        if "--show" in sys.argv:
            with conn.cursor() as cur:
                d = db_intel.fetch_dossier(cur, opp_id)
            print(json.dumps(d, indent=2, default=str) if d else "no dossier stored")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
