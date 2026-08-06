"""Buyer office identity resolution and buyer profiles.

Resolution priority: organization code > full parent path code > office name
> subtier name > department name > normalized text fallback. Public federal
hierarchy data may be incomplete at office level, so opportunity and award
records are also identity sources — confidence reflects which key matched.
"""
import re
from collections import Counter
from statistics import median

from .confidence import claim


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().upper())


def office_key(rec: dict) -> tuple[str, int, str]:
    """Return (key, confidence, method) identifying the buying office."""
    if rec.get("organization_code"):
        return f"org:{_norm(rec['organization_code'])}", 90, "organization_code"
    if rec.get("full_parent_path_code"):
        return f"path:{_norm(rec['full_parent_path_code'])}", 85, "full_parent_path_code"
    if rec.get("office_name") and rec.get("subtier_name"):
        return f"name:{_norm(rec['subtier_name'])}/{_norm(rec['office_name'])}", 70, "office+subtier name"
    if rec.get("office_name"):
        return f"office:{_norm(rec['office_name'])}", 55, "office name only"
    if rec.get("subtier_name"):
        return f"subtier:{_norm(rec['subtier_name'])}", 40, "subtier name only"
    if rec.get("department_name"):
        return f"dept:{_norm(rec['department_name'])}", 25, "department name only"
    return "unknown", 0, "unresolved"


def office_identity_from_opportunity(opp: dict) -> dict:
    """Extract office identity fields from a normalized opportunity."""
    raw = opp.get("raw_json") or {}
    return {
        "department_name": opp.get("agency"),
        "subtier_name": (raw.get("fullParentPathName", "").split(".")[1]
                         if isinstance(raw.get("fullParentPathName"), str)
                         and raw.get("fullParentPathName", "").count(".") >= 1 else None),
        "office_name": (raw.get("fullParentPathName", "").split(".")[-1]
                        if isinstance(raw.get("fullParentPathName"), str) else opp.get("office")),
        "organization_code": (raw.get("organizationCode")
                              if isinstance(raw.get("organizationCode"), str) else None),
        "full_parent_path_name": raw.get("fullParentPathName"),
        "full_parent_path_code": raw.get("fullParentPathCode"),
    }


BEHAVIOR_THRESHOLDS = {"frequent": 12, "occasional": 3}  # awards/year


def buyer_profile(identity: dict, awards: list[dict], years: int = 10) -> dict:
    """Compute the Buyer/Office Profile from that office's award history."""
    key, conf, method = office_key(identity)
    profile = {
        "identity": identity,
        "office_key": key,
        "resolution": claim(f"Office resolved via {method}", conf, method),
        "windows": {},
        "labels": [],
    }
    if not awards:
        profile["labels"] = ["insufficient data"]
        profile["note"] = "No award history found for this office in loaded data."
        return profile

    def window(yrs: int) -> dict:
        cut = _max_year(awards) - yrs
        sub = [a for a in awards if _year(a) and _year(a) > cut]
        vals = [float(a.get("obligated_amount") or 0) for a in sub]
        return {
            "award_count": len(sub),
            "total_obligations": round(sum(vals), 2),
            "median_award_value": round(median(vals), 2) if vals else None,
            "average_award_value": round(sum(vals) / len(vals), 2) if vals else None,
            "largest_award": round(max(vals), 2) if vals else None,
        }

    for yrs in (1, 3, 5, 10):
        profile["windows"][f"{yrs}y"] = window(yrs)

    top = lambda key_, n=5: [v for v, _ in Counter(  # noqa: E731
        a.get(key_) for a in awards if a.get(key_)).most_common(n)]
    profile["most_common_naics"] = top("naics")
    profile["most_common_psc"] = top("psc")
    profile["most_common_vendors"] = top("recipient_name")
    profile["most_common_vehicles"] = top("contract_vehicle")
    profile["most_common_set_asides"] = top("set_aside")
    profile["labels"] = behavior_labels(awards)
    return profile


def behavior_labels(awards: list[dict]) -> list[str]:
    labels = []
    yrs = max(1, _max_year(awards) - _min_year(awards) + 1) if awards else 1
    per_year = len(awards) / yrs
    if per_year >= BEHAVIOR_THRESHOLDS["frequent"]:
        labels.append("Frequent buyer")
    elif per_year >= BEHAVIOR_THRESHOLDS["occasional"]:
        labels.append("Occasional buyer")
    else:
        labels.append("Rare buyer")

    software = sum(1 for a in awards if (a.get("naics") or "").startswith("5415")
                   or (a.get("psc") or "").upper().startswith(("D", "70", "7A")))
    if awards and software / len(awards) >= 0.5:
        labels.append("Heavy software buyer")
    elif awards and software / len(awards) >= 0.2:
        labels.append("Heavy services buyer")

    task_orders = sum(1 for a in awards if "task" in (a.get("award_type") or "").lower()
                      or "delivery order" in (a.get("award_type") or "").lower())
    if awards and task_orders / len(awards) >= 0.5:
        labels.append("Mostly task orders")

    competed = [a for a in awards if a.get("extent_competed")]
    if competed:
        full = sum(1 for a in competed if "full" in a["extent_competed"].lower()
                   or "competed" == a["extent_competed"].lower())
        sole = sum(1 for a in competed if "not competed" in a["extent_competed"].lower()
                   or "sole" in a["extent_competed"].lower()
                   or "only one source" in a["extent_competed"].lower())
        if full / len(competed) >= 0.6:
            labels.append("Mostly competitive awards")
        if sole / len(competed) >= 0.4:
            labels.append("Mostly sole-source / limited competition")

    set_asides = sum(1 for a in awards if a.get("set_aside")
                     and "none" not in a["set_aside"].lower() and "no set" not in a["set_aside"].lower())
    if awards and set_asides / len(awards) >= 0.4:
        labels.append("Set-aside friendly")
        labels.append("Small-business friendly")
    elif awards and set_asides / len(awards) <= 0.1:
        labels.append("Large-business dominated")
    return labels


def _year(a: dict):
    d = a.get("award_date")
    if not d:
        return None
    return int(str(d)[:4])


def _max_year(awards):
    ys = [y for y in (_year(a) for a in awards) if y]
    return max(ys) if ys else 0


def _min_year(awards):
    ys = [y for y in (_year(a) for a in awards) if y]
    return min(ys) if ys else 0
