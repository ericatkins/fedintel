"""Structured logging. One JSON object per line; never logs secrets.

Rules enforced here:
- Event names + counts + sanitized messages only.
- sanitize() strips query strings (API keys ride in query params on SAM.gov)
  and known secret values from any message before it is emitted.
"""
import json
import os
import re
import sys
import time

_SECRET_ENV_KEYS = ("SAM_API_KEY", "RESEND_API_KEY", "DATABASE_URL")


# Below this length a "secret" is a placeholder, not a credential; redacting it
# would mangle unrelated text without protecting anything real.
MIN_REDACTABLE_SECRET_LEN = 8


def sanitize(message: str) -> str:
    msg = str(message)
    # Strip query strings from any URL (api_key=... lives there)
    msg = re.sub(r"(https?://[^\s?'\"]+)\?[^\s'\"]*", r"\1?[params-redacted]", msg)
    # Strip literal secret values if they leak into exception text.
    # Only redact values long enough to be real credentials: a short or
    # placeholder value (e.g. SAM_API_KEY="x" in a dev shell) would otherwise
    # blind-replace substrings of ordinary words and corrupt the logs.
    for key in _SECRET_ENV_KEYS:
        val = os.getenv(key)
        if val and len(val) >= MIN_REDACTABLE_SECRET_LEN and val in msg:
            msg = msg.replace(val, f"[{key}-redacted]")
    return msg


def log(event: str, **fields):
    record = {"ts": round(time.time(), 3), "event": event}
    for k, v in fields.items():
        record[k] = sanitize(v) if isinstance(v, str) else v
    print(json.dumps(record, default=str), file=sys.stdout, flush=True)
