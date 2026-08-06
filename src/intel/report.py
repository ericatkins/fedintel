"""Opportunity Intelligence Report — printable HTML (web view first, PDF later).

Same security posture as the digest: autoescaped Environment, safe URLs only,
all award/vendor/budget text treated as hostile.
"""
from jinja2 import Environment, select_autoescape

from ..safety import safe_sam_url

_env = Environment(autoescape=select_autoescape(default_for_string=True, default=True))

_TEMPLATE = _env.from_string("""\
<!doctype html><html><head><meta charset="utf-8">
<title>Opportunity Intelligence Report</title>
{% if inline_css %}<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0b1220;
      max-width:860px;margin:32px auto;padding:0 20px;}
 h1{font-size:22px;} h2{font-size:16px;margin-top:28px;border-bottom:1px solid #e5eaf2;padding-bottom:4px;}
 .badge{display:inline-block;background:#eef2f9;color:#3b5bdb;border-radius:6px;padding:2px 10px;
        font-weight:700;font-size:13px;}
 .conf{color:#5b6879;font-size:12px;}
 table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px;}
 th,td{border:1px solid #e5eaf2;padding:6px 8px;text-align:left;vertical-align:top;}
 th{background:#f3f5f9;}
 .caveat{color:#8a5a00;background:#fff8e8;border:1px solid #f2e2ae;border-radius:6px;
         padding:8px 12px;font-size:12px;margin:6px 0;}
 .quality{color:#5b6879;font-size:12px;}
 @media print {.noprint{display:none}}
</style>{% else %}<link rel="stylesheet" href="/static/report.css">{% endif %}</head><body>
<h1>Fedintel — Opportunity Intelligence Report</h1>

<h2>1. Executive Summary</h2>
<p>{{ d.snapshot.what_this_is }}</p>
<p><span class="badge">{{ d.pursuit_recommendation.recommendation }}</span>
 <span class="conf">confidence {{ d.pursuit_recommendation.confidence }}/100
 ({{ d.pursuit_recommendation.confidence_band }})</span></p>
<ul>{% for r in d.pursuit_recommendation.top_reasons %}<li>{{ r }}</li>{% endfor %}</ul>

<h2>2. Opportunity Details</h2>
<table>
<tr><th>Title</th><td>{% if url %}<a href="{{ url }}">{{ d.snapshot.title }}</a>{% else %}{{ d.snapshot.title }}{% endif %}</td></tr>
<tr><th>Agency / Office</th><td>{{ d.snapshot.agency }} — {{ d.snapshot.office or '—' }}</td></tr>
<tr><th>Notice type</th><td>{{ d.snapshot.notice_type }}</td></tr>
<tr><th>NAICS / PSC</th><td>{{ d.snapshot.naics or '—' }} / {{ d.snapshot.psc or '—' }}</td></tr>
<tr><th>Set-aside</th><td>{{ d.snapshot.set_aside or '—' }}</td></tr>
<tr><th>Place of performance</th><td>{{ d.snapshot.place_of_performance or '—' }}</td></tr>
<tr><th>Response deadline</th><td>{{ d.snapshot.response_deadline or '—' }}</td></tr>
<tr><th>Match score</th><td>{{ d.snapshot.match_score }}</td></tr>
</table>

<h2>3. Buyer Office Profile</h2>
<p class="conf">{{ d.buyer_profile.resolution.claim }} —
 {{ d.buyer_profile.resolution.confidence }}/100</p>
<p>Labels: {{ d.buyer_profile.labels | join(', ') if d.buyer_profile.labels else '—' }}</p>
{% if d.buyer_profile.windows %}
<table><tr><th>Window</th><th>Awards</th><th>Obligations</th><th>Median</th><th>Largest</th></tr>
{% for w, v in d.buyer_profile.windows.items() %}
<tr><td>{{ w }}</td><td>{{ v.award_count }}</td><td>{{ v.total_obligations }}</td>
<td>{{ v.median_award_value or '—' }}</td><td>{{ v.largest_award or '—' }}</td></tr>
{% endfor %}</table>{% endif %}

<h2>4. Last 10 Relevant Awards</h2>
{% if d.last_10_relevant_awards %}
<table><tr><th>Date</th><th>Vendor</th><th>Title</th><th>Obligated</th><th>Similarity</th><th>Why matched</th></tr>
{% for a in d.last_10_relevant_awards %}
<tr><td>{{ a.award_date }}</td><td>{{ a.vendor }}</td><td>{{ a.title }}</td>
<td>{{ a.obligated_amount or '—' }}</td><td>{{ a.similarity_score }}</td>
<td>{{ a.reason_matched | join('; ') }}</td></tr>
{% endfor %}</table>
{% else %}<p>No relevant prior awards found in loaded data.</p>{% endif %}

<h2>5. Incumbent Analysis</h2>
<p><strong>{{ d.incumbent_analysis.incumbent_status | replace('_',' ') }}</strong>
{% if d.incumbent_analysis.likely_incumbent_name %} — {{ d.incumbent_analysis.likely_incumbent_name }}{% endif %}
 <span class="conf">{{ d.incumbent_analysis.incumbent_confidence }}/100
 ({{ d.incumbent_analysis.confidence_band }})</span></p>
<ul>{% for e in d.incumbent_analysis.supporting_evidence %}<li>{{ e }}</li>{% endfor %}</ul>
{% for c in d.incumbent_analysis.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}

<h2>6. Work Origin</h2>
<p><strong>{{ d.work_origin_assessment.work_origin_assessment | replace('_',' ') }}</strong>
 <span class="conf">{{ d.work_origin_assessment.confidence }}/100</span></p>

<h2>7. Funding Context</h2>
<p><strong>{{ d.funding_context.label }}</strong>
 <span class="conf">{{ d.funding_context.confidence }}/100 ({{ d.funding_context.confidence_band }})</span></p>
{% for c in d.funding_context.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}

<h2>8. Market &amp; Competition</h2>
<p>Trend: <strong>{{ d.market_size.trend }}</strong>
{% if d.market_size.yoy_change_pct is not none %} ({{ d.market_size.yoy_change_pct }}% YoY){% endif %}
 — Competition: <strong>{{ d.competition_landscape.label }}</strong></p>
{% if d.competition_landscape.vendors %}
<table><tr><th>Vendor</th><th>Obligations</th><th>Awards</th><th>Last award</th></tr>
{% for v in d.competition_landscape.vendors[:5] %}
<tr><td>{{ v.vendor_name }}</td><td>{{ v.obligations }}</td><td>{{ v.award_count }}</td>
<td>{{ v.last_award_date or '—' }}</td></tr>
{% endfor %}</table>{% endif %}

<h2>9. Pursuit Recommendation</h2>
<p><span class="badge">{{ d.pursuit_recommendation.recommendation }}</span></p>
<p>Risks:</p><ul>{% for r in d.pursuit_recommendation.top_risks %}<li>{{ r }}</li>{% endfor %}</ul>
<p>Next actions:</p><ul>{% for a in d.pursuit_recommendation.next_actions %}<li>{{ a }}</li>{% endfor %}</ul>

{% if delegation %}
<h2>10. Congressional Delegation (place of performance)</h2>
<table>
  <tr><th>Member</th><th>Match</th><th>Committee relevance to this buyer</th></tr>
  {% for m in delegation %}
  <tr>
    <td>{{ m.full_name }} ({{ m.party or '—' }}–{{ m.state }}{% if m.chamber == 'rep' %}-{{ m.district or 'AL' }}{% endif %})</td>
    <td>{{ 'state (certain)' if m.match_method == 'state' else m.match_method ~ ' — ' ~ m.match_confidence ~ '/100' }}</td>
    <td>{% for c in m.committee_relevance %}{{ c.name }}{% if c.why %} — {{ c.why }}{% endif %}{% if not loop.last %}; {% endif %}{% else %}no committee of jurisdiction{% endfor %}</td>
  </tr>
  {% endfor %}
</table>
<p class="caveat">{{ delegation_note }}</p>
{% endif %}
{% if requirements %}
<h2>{{ '11' if delegation else '10' }}. Solicitation Requirements (extracted)</h2>
<table>
  <tr><th>Type</th><th>Requirement</th><th>Source</th><th>Confidence</th></tr>
  {% for r in requirements %}
  <tr><td>{{ r.requirement_type }}</td><td>{{ r.value }}</td>
      <td>{{ r.filename or 'document' }}{% if r.page %} p.{{ r.page }}{% endif %}</td>
      <td>{{ r.confidence }}/100</td></tr>
  {% endfor %}
</table>
<p class="caveat">Extracted by deterministic rules from solicitation attachments.
Absence of a row means no rule matched — not that the requirement is absent.
Always read the solicitation.</p>
{% endif %}
<h2>{{ (12 if delegation else 11) if requirements else (11 if delegation else 10) }}. Caveats and Data Sources</h2>

{% for q in d.data_quality %}<p class="quality">• {{ q }}</p>{% endfor %}
<p class="quality">Sources: SAM.gov opportunity data, SAM.gov award notices,
USAspending award and budget data. All assertions carry confidence bands;
inference is labeled as inference.</p>
</body></html>
""")


def render_report(dossier: dict, opp_url: str | None = None,
                  notice_id: str | None = None, inline_css: bool = True,
                  delegation: list | None = None,
                  requirements: list | None = None) -> str:
    """inline_css=True for standalone/export HTML; False for the web route,
    which links /static/report.css so the strict CSP (style-src 'self')
    applies without 'unsafe-inline'."""
    from .delegation import COMPLIANCE_NOTE
    return _TEMPLATE.render(d=dossier, url=safe_sam_url(opp_url, notice_id),
                            inline_css=inline_css, delegation=delegation or [],
                            delegation_note=COMPLIANCE_NOTE,
                            requirements=requirements or [])
