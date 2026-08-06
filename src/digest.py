"""Morning intelligence briefing email.

Security: rendered through a Jinja Environment with HTML autoescaping ON.
Every dynamic field is escaped; URLs pass through safety.safe_sam_url().
All SAM.gov data is treated as hostile input. Do not reuse Template(...)
without autoescape anywhere else (including the future dashboard).

Sections: Act Today · High-Match New · Amendments to Tracked ·
Early-Stage Market Research · Closing Soon · Market Signals.
"""
from collections import Counter
from datetime import datetime, timezone

from jinja2 import Environment, select_autoescape

from . import actions
from .safety import safe_sam_url

_env = Environment(autoescape=select_autoescape(default_for_string=True, default=True))

TEMPLATE = _env.from_string("""\
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f3f5f9;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f9;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

  <tr><td style="background:#0b1220;border-radius:12px 12px 0 0;padding:24px 28px;">
    <div style="color:#ffffff;font-size:20px;font-weight:700;">Fed<span style="color:#4f8ff7;">intel</span></div>
    <div style="color:#8b97ad;font-size:12px;margin-top:2px;">Daily Intelligence Briefing &middot; {{ date_str }}</div>
    <table role="presentation" width="100%" style="margin-top:18px;"><tr>
      <td style="color:#ffffff;font-size:20px;font-weight:700;">{{ stats.total }}<div style="color:#8b97ad;font-size:11px;font-weight:400;">New matches</div></td>
      <td style="color:#ffffff;font-size:20px;font-weight:700;">{{ stats.high }}<div style="color:#8b97ad;font-size:11px;font-weight:400;">High match (80+)</div></td>
      <td style="color:#ffffff;font-size:20px;font-weight:700;">{{ stats.act }}<div style="color:#8b97ad;font-size:11px;font-weight:400;">Act today</div></td>
      <td style="color:#ffffff;font-size:20px;font-weight:700;">{{ stats.tracked }}<div style="color:#8b97ad;font-size:11px;font-weight:400;">Tracked changed</div></td>
    </tr></table>
  </td></tr>

  {% for section in sections if section.rows %}
  <tr><td style="background:#ffffff;padding:22px 28px 4px;{% if loop.first %}border-top:1px solid #eef1f6;{% endif %}">
    <div style="font-size:15px;font-weight:700;color:#0b1220;">{{ section.title }}</div>
    <div style="font-size:12px;color:#8b97ad;margin-top:2px;">{{ section.subtitle }}</div>
  </td></tr>
  {% for o in section.rows %}
  <tr><td style="background:#ffffff;padding:8px 28px;">
    <table role="presentation" width="100%" style="border:1px solid #e5eaf2;border-radius:10px;">
    <tr>
      <td width="64" align="center" valign="top" style="padding:14px 0 14px 12px;">
        <div style="background:{{ '#e8f5ee' if o.score >= 80 else '#eef2f9' }};color:{{ '#177a4c' if o.score >= 80 else '#3b5bdb' }};border-radius:8px;font-size:16px;font-weight:800;padding:10px 0;width:52px;">{{ o.score }}<div style="font-size:9px;font-weight:600;letter-spacing:.5px;">MATCH</div></div>
      </td>
      <td style="padding:14px 14px;">
        {% if o.safe_url %}<a href="{{ o.safe_url }}" style="color:#0b1220;font-size:14px;font-weight:700;text-decoration:none;">{{ o.title }}</a>
        {% else %}<span style="color:#0b1220;font-size:14px;font-weight:700;">{{ o.title }}</span>{% endif %}
        <div style="color:#5b6879;font-size:12px;margin-top:3px;">{{ o.agency or 'Federal' }} &middot; {{ o.notice_type or '—' }}{% if o.set_aside %} &middot; {{ o.set_aside }}{% endif %}</div>
        <div style="color:#8b97ad;font-size:12px;margin-top:3px;">{{ o.category }}{% if o.naics %} &middot; NAICS {{ o.naics }}{% endif %}{% if o.place_of_performance %} &middot; {{ o.place_of_performance }}{% endif %}</div>
        {% if o.response_deadline %}<div style="color:{{ '#b91c1c' if o.days_left is not none and o.days_left <= 3 else '#c2410c' }};font-size:12px;font-weight:600;margin-top:4px;">Due {{ o.deadline_str }}{% if o.days_left is not none %} &middot; {{ o.days_left }} day{{ '' if o.days_left == 1 else 's' }} left{% endif %}</div>{% endif %}
        {% if o.changes_text %}<div style="color:#7c3aed;font-size:12px;font-weight:600;margin-top:4px;">Changed: {{ o.changes_text }}</div>{% endif %}
        {% if o.why %}<div style="color:#475569;font-size:12px;margin-top:6px;"><span style="font-weight:600;">Why it matched:</span> {{ o.why }}</div>{% endif %}
        {% if o.recommended_action %}<div style="color:#0b1220;font-size:12px;margin-top:4px;"><span style="font-weight:600;">Next action:</span> {{ o.recommended_action }}</div>{% endif %}
        {% if o.intel_line %}<div style="color:#1e40af;font-size:12px;margin-top:4px;background:#eef2f9;border-radius:6px;padding:6px 8px;">{{ o.intel_line }}</div>{% endif %}
        {% if o.top_risk %}<div style="color:#9a3412;font-size:12px;margin-top:4px;"><span style="font-weight:600;">Top risk:</span> {{ o.top_risk }}</div>{% endif %}
        <div style="margin-top:10px;">
          {% if o.safe_url %}<a href="{{ o.safe_url }}" style="display:inline-block;background:#0b1220;color:#ffffff;font-size:12px;font-weight:600;text-decoration:none;padding:6px 12px;border-radius:6px;margin-right:6px;">View</a>{% endif %}
          {% for a in o.action_links %}<a href="{{ a.href }}" style="display:inline-block;background:#eef2f9;color:#3b5bdb;font-size:12px;font-weight:600;text-decoration:none;padding:6px 12px;border-radius:6px;margin-right:6px;">{{ a.label }}</a>{% endfor %}
        </div>
      </td>
    </tr>
    </table>
  </td></tr>
  {% endfor %}
  {% endfor %}

  {% if signals %}
  <tr><td style="background:#ffffff;padding:22px 28px 4px;">
    <div style="font-size:15px;font-weight:700;color:#0b1220;">Market Signals</div>
    <div style="font-size:12px;color:#8b97ad;margin-top:2px;">Today's ingest at a glance</div>
  </td></tr>
  <tr><td style="background:#ffffff;padding:8px 28px 16px;">
    <table role="presentation" width="100%" style="border:1px solid #e5eaf2;border-radius:10px;">
      {% for s in signals %}
      <tr><td style="padding:8px 14px;color:#5b6879;font-size:12px;border-bottom:{{ '0' if loop.last else '1px solid #eef1f6' }};">
        <span style="font-weight:700;color:#0b1220;">{{ s.label }}:</span> {{ s.value }}
      </td></tr>
      {% endfor %}
    </table>
  </td></tr>
  {% endif %}

  {% if empty %}
  <tr><td style="background:#ffffff;padding:20px 28px 24px;color:#5b6879;font-size:13px;">
    No opportunities cleared your score threshold today. Everything was still ingested and stored; thresholds can be tuned in .env.
  </td></tr>
  {% endif %}

  <tr><td style="background:#ffffff;border-radius:0 0 12px 12px;padding:18px 28px 26px;border-top:1px solid #eef1f6;">
    <div style="color:#8b97ad;font-size:11px;">Fedintel watches SAM.gov so you can build. Raw data is stored for reclassification as scoring improves.</div>
  </td></tr>

</table>
</td></tr>
</table>
{% if links %}
<div style="color:#8b97ad;font-size:11px;margin:18px 24px;border-top:1px solid #26334d;padding-top:10px;">
  You receive this brief because your organization subscribed to Fedintel's daily digest.
  {% if links.manage_url %}<a href="{{ links.manage_url }}" style="color:#4F8FF7;">Manage preferences</a>{% endif %}
  {% if links.unsubscribe_url %} &middot; <a href="{{ links.unsubscribe_url }}" style="color:#4F8FF7;">Unsubscribe</a>{% endif %}
</div>
{% endif %}
</body>
</html>
""")


def _prep_row(o: dict, now) -> dict:
    row = dict(o)
    row["safe_url"] = safe_sam_url(o.get("url"), o.get("source_notice_id"))
    d = o.get("response_deadline")
    row["days_left"] = None
    row["deadline_str"] = ""
    if d:
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        row["days_left"] = max(0, (d - now).days)
        row["deadline_str"] = d.strftime("%b %d, %Y")
    reasons = o.get("reasons") or []
    row["why"] = "; ".join(reasons[:4]) if isinstance(reasons, list) else ""
    changes = o.get("changes") or []
    labels = {
        "deadline_changed": "deadline", "stage_changed": "notice stage",
        "title_changed": "title", "url_changed": "link", "amended": "details",
        "tracked_opportunity_changed": "tracked item",
        "stage_transition": "stage transition",
    }
    row["changes_text"] = ", ".join(sorted({labels.get(c.get("event_type"), "details")
                                            for c in changes if isinstance(c, dict)})) if changes else ""
    if o.get("action_links"):          # subscription-bound links from the engine
        row["action_links"] = o["action_links"]
    else:                              # dogfood/global digest: unbound links
        links = []
        for action, label in (("track", "Track"), ("ignore", "Ignore"),
                              ("good_match", "Good match"), ("bad_match", "Bad match")):
            href = actions.url(o.get("id"), action)
            if href:
                links.append({"href": href, "label": label})
        row["action_links"] = links
    row["intel_line"] = o.get("intel_line") or ""
    row["top_risk"] = o.get("top_risk") or ""
    return row


def build_sections(rows: list[dict], tracked_amendments: list[dict], now=None) -> tuple[list[dict], dict]:
    """Sort today's rows into briefing sections. Returns (sections, stats)."""
    now = now or datetime.now(timezone.utc)
    prepped = [_prep_row(o, now) for o in rows]
    tracked = [_prep_row(o, now) for o in tracked_amendments]
    tracked_ids = {t["id"] for t in tracked}

    def fresh(pool):  # avoid repeating tracked items in other sections
        return [o for o in pool if o["id"] not in tracked_ids]

    act = [o for o in fresh(prepped) if o["days_left"] is not None and o["days_left"] <= 3 and o["score"] >= 60]
    used = {o["id"] for o in act}
    high = [o for o in fresh(prepped) if o["score"] >= 80 and o["id"] not in used][:8]
    used |= {o["id"] for o in high}
    early = [o for o in fresh(prepped)
             if any(t in (o.get("notice_type") or "").lower()
                    for t in ("sources sought", "presolicitation", "special notice"))
             and o["id"] not in used][:6]
    used |= {o["id"] for o in early}
    closing = [o for o in fresh(prepped)
               if o["days_left"] is not None and o["days_left"] <= 14 and o["id"] not in used][:6]

    sections = [
        {"title": "Act Today", "subtitle": "High-fit opportunities with imminent deadlines", "rows": act},
        {"title": "High-Match New Opportunities", "subtitle": "Strongest fits from the last 24 hours", "rows": high},
        {"title": "Amendments to Tracked Opportunities", "subtitle": "Pursuits you're watching that changed", "rows": tracked},
        {"title": "Early-Stage Market Research", "subtitle": "Sources Sought and RFIs — shape the requirement", "rows": early},
        {"title": "Closing Soon", "subtitle": "Deadlines within 14 days", "rows": closing},
    ]
    stats = {
        "total": len(prepped),
        "high": sum(1 for o in prepped if o["score"] >= 80),
        "act": len(act),
        "tracked": len(tracked),
    }
    return sections, stats


def build_signals(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    cats = Counter(o.get("category") or "Uncategorized" for o in rows)
    agencies = Counter(o.get("agency") or "Unknown" for o in rows)
    stages = Counter(o.get("notice_type") or "Unknown" for o in rows)
    fmt = lambda c: ", ".join(f"{k} ({v})" for k, v in c.most_common(4))  # noqa: E731
    return [
        {"label": "Top categories", "value": fmt(cats)},
        {"label": "Most active agencies", "value": fmt(agencies)},
        {"label": "Notice stages", "value": fmt(stages)},
    ]


def footer_links(subscription_id: int | None) -> dict:
    """Signed unsubscribe + manage-preferences links for one subscription.
    Every public digest must carry these (and the why-receiving text below)."""
    from . import tokens
    from .config import ACTION_BASE_URL
    if not subscription_id or not ACTION_BASE_URL or not tokens.enabled():
        return {}
    token, exp = tokens.sign("unsub", a=subscription_id)
    base = ACTION_BASE_URL.rstrip("/")
    return {
        "unsubscribe_url": f"{base}/unsubscribe?s={subscription_id}&e={exp}&t={token}",
        "manage_url": f"{base}/app/alerts",
    }


def render(rows: list[dict], digest_date, tracked_amendments: list[dict] | None = None,
           now=None, links: dict | None = None) -> str:
    sections, stats = build_sections(rows, tracked_amendments or [], now=now)
    return TEMPLATE.render(
        sections=sections,
        stats=stats,
        signals=build_signals(rows),
        empty=not any(s["rows"] for s in sections),
        date_str=digest_date.strftime("%B %d, %Y"),
        links=links or {},
    )
