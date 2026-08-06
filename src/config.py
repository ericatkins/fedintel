"""Central configuration. Everything comes from environment variables."""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Ingest/pipeline settings are validated at USE time via require(), not at
# import time — the web app must boot without SAM/Resend credentials.
SAM_API_KEY = os.getenv("SAM_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


def require(name: str) -> str:
    """Fetch a setting that is mandatory for the current entrypoint."""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is required for this command but is not set")
    return value
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
DIGEST_FROM = os.getenv("DIGEST_FROM", "Fedintel <digest@fedintel.local>")
DIGEST_TO = [e.strip() for e in os.getenv("DIGEST_TO", "").split(",") if e.strip()]
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "2"))
MIN_DIGEST_SCORE = int(os.getenv("MIN_DIGEST_SCORE", "40"))
TIMEZONE = os.getenv("TIMEZONE", "America/Chicago")
TZ = ZoneInfo(TIMEZONE)
INGEST_BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "50"))

# Optional: base URL + secret for signed action links (Track / Good match / ...).
# If unset, the digest renders View-only links and the pipeline still works.
ACTION_BASE_URL = os.getenv("ACTION_BASE_URL", "")
ACTION_SECRET = os.getenv("ACTION_SECRET", "")

# Company profile for personalized scoring (JSON file; see company_profile.example.json)
COMPANY_PROFILE_PATH = os.getenv("COMPANY_PROFILE_PATH", "company_profile.json")

# Software-relevant NAICS codes (filter at query time to cut noise, but keywords also
# catch misclassified software work under other NAICS)
NAICS_TARGETS = ["541511", "541512", "541513", "541519", "541330", "541715", "518210", "541690"]
