"""Company profile: who we are, so scoring can be about fit, not just keywords."""
import json
import os

from .log import log

DEFAULT_PROFILE = {
    "name": "",
    "industries": [],
    "capabilities": [],
    "technologies": [],
    "naics_codes": [],
    "agencies_of_interest": [],
    "locations": [],
    "set_aside_eligibility": [],
    "excluded_categories": [],
    "keywords_boost": [],
    "keywords_suppress": [],
}


def load_profile(path: str | None = None) -> dict:
    """Load the company profile JSON; return default (neutral) profile if absent."""
    path = path or os.getenv("COMPANY_PROFILE_PATH", "company_profile.json")
    if not os.path.exists(path):
        log("profile_missing", path=path, note="running with neutral profile")
        return dict(DEFAULT_PROFILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log("profile_load_error", error=str(exc))
        return dict(DEFAULT_PROFILE)
    profile = dict(DEFAULT_PROFILE)
    for key in profile:
        if key in data:
            profile[key] = data[key]
    return profile
