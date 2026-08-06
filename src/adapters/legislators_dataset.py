"""Adapter: unitedstates/congress-legislators (public domain).

Pulls the generated JSON from the project's gh-pages branch — current members,
their terms/contacts/FEC candidate IDs, plus committee rosters. This is the
same dataset behind theunitedstates.io and is maintained by a long-running
open-government project; refresh weekly.
"""
import json

import requests

from ..log import log

BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/"
TIMEOUT = 60


def _get_json(name: str):
    resp = requests.get(BASE + name, timeout=TIMEOUT)
    resp.raise_for_status()
    return json.loads(resp.content)


def fetch_current_legislators() -> list[dict]:
    """Normalized current members with their committee assignments attached."""
    members = _get_json("legislators-current.json")
    committees = _get_json("committees-current.json")
    membership = _get_json("committee-membership-current.json")
    names = {c["thomas_id"]: c["name"] for c in committees}
    by_bioguide: dict[str, list[dict]] = {}
    for code, roster in membership.items():
        if code not in names:            # subcommittee codes: attach to parent
            parent = code[:4]
            if parent not in names:
                continue
            label = f"{names[parent]} (subcommittee {code[4:]})"
        else:
            label = names[code]
        for m in roster:
            by_bioguide.setdefault(m["bioguide"], []).append(
                {"code": code, "name": label, "title": m.get("title"),
                 "rank": m.get("rank")})
    out = []
    for m in members:
        term = m["terms"][-1]
        bioguide = m["id"]["bioguide"]
        out.append({
            "bioguide_id": bioguide,
            "full_name": m["name"].get("official_full")
                         or f"{m['name'].get('first', '')} {m['name'].get('last', '')}".strip(),
            "chamber": term["type"],                      # 'sen' | 'rep'
            "state": term["state"],
            "district": term.get("district"),
            "party": term.get("party"),
            "phone": term.get("phone"),
            "office": term.get("office") or term.get("address"),
            "website": term.get("url"),
            "contact_form": term.get("contact_form"),
            "state_rank": term.get("state_rank"),
            "fec_candidate_ids": m["id"].get("fec") or [],
            "committees": sorted(by_bioguide.get(bioguide, []),
                                 key=lambda c: c["code"]),
            "term_end": term.get("end"),
        })
    log("legislators_fetched", count=len(out))
    return out
