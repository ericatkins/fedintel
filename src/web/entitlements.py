"""Plan entitlement flags. Pricing lives in Stripe/admin tooling — NEVER here.
organizations.plan holds one of the keys below; flags gate features."""

PLAN_FLAGS = {
    "early_access": {"daily_digest": True, "instant_alerts": True, "csv_export": True,
                     "saved_views": 10, "profiles": 1, "vendor_intel": True,
                     "agency_intel": True, "reports": True, "api_access": False,
                     "delegation_intel": True, "document_intel": True},
    "scout":        {"daily_digest": True, "instant_alerts": False, "csv_export": True,
                     "saved_views": 3, "profiles": 1, "vendor_intel": False,
                     "agency_intel": True, "reports": True, "api_access": False,
                     "delegation_intel": False, "document_intel": False},
    "pro":          {"daily_digest": True, "instant_alerts": True, "csv_export": True,
                     "saved_views": 25, "profiles": 3, "vendor_intel": True,
                     "agency_intel": True, "reports": True, "api_access": False,
                     "delegation_intel": True, "document_intel": True},
    "team":         {"daily_digest": True, "instant_alerts": True, "csv_export": True,
                     "saved_views": 100, "profiles": 10, "vendor_intel": True,
                     "agency_intel": True, "reports": True, "api_access": True,
                     "delegation_intel": True, "document_intel": True},
}


def allows(plan: str, flag: str):
    """Truthy flag value for a plan; unknown plans get early_access defaults."""
    return PLAN_FLAGS.get(plan, PLAN_FLAGS["early_access"]).get(flag, False)


def limit(plan: str, flag: str) -> int:
    value = allows(plan, flag)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
