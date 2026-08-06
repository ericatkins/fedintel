"""Buyer DNA: peer-normalized behavioral profile of the buying office.

The useful claim is not "this office retained incumbents 68% of the time" but
"materially higher than peer offices buying the same category". Peers are
other offices in the same subtier purchasing the same NAICS — the broadest
pool the dossier already loads, with this office's own awards excluded.

Every label carries its numbers, its baseline, and an implication for this
pursuit. Comparisons are only made when both pools are big enough; thin data
says "insufficient peer data", never a confident label.
"""
MIN_POOL = 8            # awards needed on each side before comparing
MATERIAL_PP = 15        # percentage-point delta that counts as material


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _is_competed(extent) -> bool | None:
    if not extent:
        return None
    e = str(extent).lower()
    if e.startswith("not") or "not competed" in e or "only one" in e:
        return False
    return "compet" in e


def _metrics(pool: list[dict]) -> dict:
    n = len(pool)
    if not n:
        return {"award_count": 0}
    amounts = sorted(float(a.get("obligated_amount") or 0) for a in pool
                     if a.get("obligated_amount"))
    total = sum(amounts)
    competed_flags = [_is_competed(a.get("extent_competed")) for a in pool]
    competed_known = [f for f in competed_flags if f is not None]
    set_aside_n = sum(1 for a in pool
                      if (a.get("set_aside") or "").strip()
                      and "none" not in str(a.get("set_aside")).lower())
    q4_n = sum(1 for a in pool
               if a.get("award_date") and str(a["award_date"])[5:7] in
               ("07", "08", "09"))
    dated_n = sum(1 for a in pool if a.get("award_date"))
    by_vendor: dict[str, dict] = {}
    for a in pool:
        v = a.get("recipient_name_normalized") or a.get("recipient_name")
        if not v:
            continue
        row = by_vendor.setdefault(v, {"count": 0, "obligations": 0.0})
        row["count"] += 1
        row["obligations"] += float(a.get("obligated_amount") or 0)
    repeat_awards = sum(r["count"] for r in by_vendor.values() if r["count"] > 1)
    named_awards = sum(r["count"] for r in by_vendor.values())
    top_vendor_obl = max((r["obligations"] for r in by_vendor.values()),
                         default=0.0)
    vehicles: dict[str, int] = {}
    for a in pool:
        v = (a.get("contract_vehicle") or "").strip()
        if v:
            vehicles[v] = vehicles.get(v, 0) + 1
    return {
        "award_count": n,
        "total_obligations": total,
        "median_award": amounts[len(amounts) // 2] if amounts else None,
        "competed_share_pct": _pct(sum(competed_known), len(competed_known)),
        "set_aside_share_pct": _pct(set_aside_n, n),
        "q4_share_pct": _pct(q4_n, dated_n),
        "repeat_vendor_share_pct": _pct(repeat_awards, named_awards),
        "top_vendor_share_pct": _pct(top_vendor_obl, total) if total else None,
        "unique_vendors": len(by_vendor),
        "top_vehicles": sorted(vehicles.items(), key=lambda kv: -kv[1])[:3],
    }


_COMPARE_FIELDS = (
    ("repeat_vendor_share_pct", "incumbent retention (repeat-vendor share)"),
    ("competed_share_pct", "competition rate"),
    ("set_aside_share_pct", "set-aside share"),
    ("q4_share_pct", "Q4 award concentration"),
    ("top_vendor_share_pct", "top-vendor concentration"),
)


def _compare(office_m, peer_m):
    comps = []
    for key, name in _COMPARE_FIELDS:
        ov, pv = office_m.get(key), peer_m.get(key)
        if ov is None or pv is None:
            continue
        delta = ov - pv
        if abs(delta) >= MATERIAL_PP:
            direction = "materially higher" if delta > 0 else "materially lower"
            material = True
        else:
            direction = "similar"
            material = False
        comps.append({
            "metric": name, "key": key, "office_value_pct": ov,
            "peer_value_pct": pv, "delta_pp": delta,
            "direction": direction, "material": material,
            "evidence": f"office {ov}% vs peer baseline {pv}% "
                        f"({'+' if delta >= 0 else ''}{delta}pp)",
        })
    return comps


_LABEL_RULES = (
    ("repeat_vendor_share_pct", 1, "incumbent-favoring",
     "This office re-awards to the same vendors materially more than peers — "
     "expect a strong incumbent advantage; plan discriminators or a teaming "
     "path."),
    ("competed_share_pct", -1, "competition-limited",
     "This office competes work materially less than peers — early customer "
     "engagement and requirement shaping matter more here than proposal "
     "volume."),
    ("set_aside_share_pct", 1, "small-business accessible",
     "This office sets aside materially more than peers — a strong signal for "
     "eligible small businesses."),
    ("q4_share_pct", 1, "Q4-driven",
     "Awards cluster in Q4 (Jul–Sep) materially more than peers — expect "
     "use-it-or-lose-it timing; have your response machinery ready before "
     "summer."),
    ("top_vendor_share_pct", 1, "vendor-concentrated",
     "Obligations concentrate in one vendor materially more than peers — the "
     "market has a gatekeeper; evaluate subcontracting to them."),
)


def build_buyer_dna(awards_office: list[dict], awards_subtier: list[dict],
                    opp: dict | None = None) -> dict:
    """Peer-normalized office behavior. Returns honest 'insufficient data'
    shapes when either pool is too thin to compare."""
    office_codes = {a.get("awarding_office_code") for a in awards_office
                    if a.get("awarding_office_code")}
    office_names = {a.get("awarding_office") for a in awards_office
                    if a.get("awarding_office")}
    peers = [a for a in awards_subtier
             if a.get("awarding_office_code") not in office_codes
             and a.get("awarding_office") not in office_names]
    office_m = _metrics(awards_office)
    peer_m = _metrics(peers)
    caveats = ["Peer baseline: other offices in the same subtier purchasing "
               "this NAICS (public award records). Peer pools differ in "
               "mission and scale; treat deltas as behavioral signals, not "
               "verdicts."]

    if office_m["award_count"] < MIN_POOL or peer_m["award_count"] < MIN_POOL:
        return {
            "status": "insufficient_data",
            "office_metrics": office_m,
            "peer_metrics": peer_m,
            "comparisons": [],
            "labels": [],
            "basis": {"office_awards": office_m["award_count"],
                      "peer_awards": peer_m["award_count"],
                      "min_required": MIN_POOL},
            "caveats": caveats + [
                f"Comparison requires ≥{MIN_POOL} awards on each side "
                f"(office has {office_m['award_count']}, peers have "
                f"{peer_m['award_count']})."],
        }

    comparisons = _compare(office_m, peer_m)
    by_key = {c["key"]: c for c in comparisons}
    labels = []
    for key, sign, label, implication in _LABEL_RULES:
        c = by_key.get(key)
        if c and c["material"] and (c["delta_pp"] * sign) > 0:
            labels.append({"label": label, "evidence": c["evidence"],
                           "implication": implication})
    return {
        "status": "ok",
        "office_metrics": office_m,
        "peer_metrics": peer_m,
        "comparisons": comparisons,
        "labels": labels,
        "basis": {"office_awards": office_m["award_count"],
                  "peer_awards": peer_m["award_count"],
                  "min_required": MIN_POOL},
        "caveats": caveats,
    }
