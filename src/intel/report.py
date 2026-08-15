"""Opportunity Intelligence Report — printable HTML (web view first, PDF later).

Same security posture as the digest: autoescaped Environment, safe URLs only,
all award/vendor/budget text treated as hostile. Sections are auto-numbered so
optional panels (delegation, forecasts, family) never break the numbering.
The print export preserves the research hierarchy AND the citations: the
evidence ledger and per-section caveats always print.
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
{% set ns = namespace(n=0) %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Executive Intelligence Brief</h2>
{% if brief %}
{% for p in brief %}<p>{{ p.text }}
 {% if p.refs %}<span class="conf">[{{ p.refs | join(' · ') }}]</span>{% endif %}</p>
{% endfor %}
{% else %}<p>{{ d.snapshot.what_this_is }}</p>{% endif %}
{% if decision %}
<p><span class="badge">{{ decision.summary.recommendation }}</span>
 <span class="conf">confidence {{ decision.summary.confidence }}/100
 ({{ decision.summary.confidence_band }}) · dossier completeness
 {{ decision.completeness_pct }}%{% if days_left is not none %} ·
 {{ days_left }} day(s) to respond{% endif %}</span></p>
<ul>{% for r in decision.summary.rationale %}<li>{{ r }}</li>{% endfor %}</ul>
{% if decision.top_risks %}<p>Top risks:</p>
<ul>{% for r in decision.top_risks %}<li>{{ r }}</li>{% endfor %}</ul>{% endif %}
{% else %}
<p><span class="badge">{{ d.pursuit_recommendation.recommendation }}</span>
 <span class="conf">confidence {{ d.pursuit_recommendation.confidence }}/100</span></p>
<ul>{% for r in d.pursuit_recommendation.top_reasons %}<li>{{ r }}</li>{% endfor %}</ul>
{% endif %}
{% if value_est %}
<p>Comparable-award estimate: <strong>${{ '{:,.0f}'.format(value_est.low) }}–${{ '{:,.0f}'.format(value_est.high) }}</strong>
 <span class="conf">median ${{ '{:,.0f}'.format(value_est.median) }} ·
 {{ value_est.basis }} comparable award(s)</span></p>
{% endif %}

{% if decision %}
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Capture Decision Stack</h2>
<table><tr><th>Dimension</th><th>Rating</th><th>Evidence</th><th>Mitigation</th></tr>
{% for dim in decision.dimensions %}
<tr><td>{{ dim.name }} <span class="conf">({{ dim.materiality }})</span></td>
<td>{{ dim.rating }} <span class="conf">{{ dim.confidence }}/100</span></td>
<td>{{ dim.evidence | join('; ') }}{% if dim.unknowns %}
  <div class="conf">Unknown: {{ dim.unknowns | join('; ') }}</div>{% endif %}</td>
<td class="conf">{{ dim.mitigation or '' }}</td></tr>
{% endfor %}</table>
<p class="quality">"Unknown" means the data to judge is missing — never a
negative finding. The verdict comes from ordered rules over these ratings.</p>
{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Opportunity Details</h2>
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

{% if forecasts %}
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Forecast Lineage</h2>
{% for f in forecasts %}
<p><strong>{{ f.title }}</strong> <span class="conf">match {{ f.similarity_score }}/100</span><br>
<span class="conf">{{ f.subtier or f.agency }}{% if f.anticipated_solicitation %} ·
anticipated solicitation {{ f.anticipated_solicitation }}{% endif %}{% if f.action_type %} ·
{{ f.action_type | replace('_', ' ') }}{% endif %}{% if f.incumbent_name %} ·
stated incumbent: {{ f.incumbent_name }}{% endif %}</span><br>
<span class="conf">Why linked: {{ f.evidence | join('; ') }}</span></p>
{% endfor %}
<div class="caveat">Forecasts are agency planning statements, not commitments;
links are inferred by agency, NAICS, scope, and timing.</div>
{% endif %}

{% set fam = d.contract_family or {} %}
{% if fam.members %}
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Contract Family &amp; Recompete Clock</h2>
<table><tr><th>Role</th><th>Vendor</th><th>PIID</th><th>Awarded</th><th>Period</th><th>Obligated</th><th>Link</th></tr>
{% for m in fam.members %}
<tr><td>{{ m.role }}</td><td>{{ m.vendor or '—' }}</td><td>{{ m.piid or m.source_award_id or '—' }}</td>
<td>{{ m.award_date or '—' }}</td><td>{{ m.period_start or '?' }} → {{ m.period_end or '?' }}</td>
<td>{{ '${:,.0f}'.format(m.obligated_amount) if m.obligated_amount else '—' }}</td>
<td>{{ 'confirmed' if m.confirmed else 'inferred' }} — {{ m.evidence | join('; ') }}</td></tr>
{% endfor %}</table>
{% set rc = fam.recompete or {} %}
{% if rc.estimated_expiration %}
<p>Estimated predecessor expiration: <strong>{{ rc.estimated_expiration }}</strong>
 <span class="conf">{{ rc.confidence }}/100</span></p>
{% for a in rc.assumptions %}<div class="caveat">{{ a }}</div>{% endfor %}
{% endif %}
{% set vul = fam.vulnerability or {} %}
<p>Incumbent vulnerability (public signals only): <strong>{{ vul.assessment }}</strong></p>
{% for s in vul.signals %}<p class="quality">• {{ s.signal }} — {{ s.evidence }}</p>{% endfor %}
{% for c in vul.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}
{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Incumbent Analysis</h2>
<p><strong>{{ d.incumbent_analysis.incumbent_status | replace('_',' ') }}</strong>
{% if d.incumbent_analysis.likely_incumbent_name %} — {{ d.incumbent_analysis.likely_incumbent_name }}{% endif %}
 <span class="conf">{{ d.incumbent_analysis.incumbent_confidence }}/100
 ({{ d.incumbent_analysis.confidence_band }})</span></p>
<ul>{% for e in d.incumbent_analysis.supporting_evidence %}<li>{{ e }}</li>{% endfor %}</ul>
{% for c in d.incumbent_analysis.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Buyer Office Profile</h2>
<p class="conf">{{ d.buyer_profile.resolution.claim }} —
 {{ d.buyer_profile.resolution.confidence }}/100</p>
<p>Labels: {{ d.buyer_profile.labels | join(', ') if d.buyer_profile.labels else '—' }}</p>
{% if d.buyer_profile.windows %}
<table><tr><th>Window</th><th>Awards</th><th>Obligations</th><th>Median</th><th>Largest</th></tr>
{% for w, v in d.buyer_profile.windows.items() %}
<tr><td>{{ w }}</td><td>{{ v.award_count }}</td><td>{{ v.total_obligations }}</td>
<td>{{ v.median_award_value or '—' }}</td><td>{{ v.largest_award or '—' }}</td></tr>
{% endfor %}</table>{% endif %}
{% set dna = d.buyer_dna or {} %}
{% if dna.status == 'ok' %}
<p><strong>Buyer DNA</strong> <span class="conf">vs peer offices buying the
same category ({{ dna.basis.office_awards }} office / {{ dna.basis.peer_awards }} peer awards)</span></p>
<table><tr><th>Behavior</th><th>This office</th><th>Peer baseline</th><th>Read</th></tr>
{% for c in dna.comparisons %}
<tr><td>{{ c.metric }}</td><td>{{ c.office_value_pct }}%</td>
<td>{{ c.peer_value_pct }}%</td><td>{{ c.direction }}</td></tr>
{% endfor %}</table>
{% for lb in dna.labels %}<p class="quality">• <strong>{{ lb.label }}</strong>
 ({{ lb.evidence }}) — {{ lb.implication }}</p>{% endfor %}
{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Last 10 Relevant Awards</h2>
{% if d.last_10_relevant_awards %}
<table><tr><th>Date</th><th>Vendor</th><th>Title</th><th>Obligated</th><th>Similarity</th><th>Why matched</th></tr>
{% for a in d.last_10_relevant_awards %}
<tr><td>{{ a.award_date }}</td><td>{{ a.vendor }}</td><td>{{ a.title }}</td>
<td>{{ a.obligated_amount or '—' }}</td><td>{{ a.similarity_score }}</td>
<td>{{ a.reason_matched | join('; ') }}</td></tr>
{% endfor %}</table>
{% else %}<p>No relevant prior awards found in loaded data.</p>{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Market, Competition &amp; Teaming</h2>
<p>Trend: <strong>{{ d.market_size.trend }}</strong>
{% if d.market_size.yoy_change_pct is not none %} ({{ d.market_size.yoy_change_pct }}% YoY){% endif %}
 — Competition: <strong>{{ d.competition_landscape.label }}</strong></p>
{% set ct = d.competitive_teaming or {} %}
{% if ct.status == 'ok' %}
<table><tr><th>Vendor</th><th>Strength</th><th>Read</th><th>Evidence</th></tr>
{% for c in ct.competitors %}
<tr><td>{{ c.vendor }}{% if c.is_incumbent %} (incumbent){% endif %}</td>
<td>{{ c.strength }}/100</td><td>{{ c.read }}</td>
<td class="conf">{{ c.evidence | join('; ') }}</td></tr>
{% endfor %}</table>
{% for p in ct.teaming_candidates %}
<p class="quality">• Teaming candidate <strong>{{ p.vendor }}</strong> —
fills: {{ p.gap_filled }}. {{ p.evidence | join('; ') }}</p>
{% endfor %}
{% for c in ct.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}
{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Funding Context</h2>
<p><strong>{{ d.funding_context.label }}</strong>
 <span class="conf">{{ d.funding_context.confidence }}/100 ({{ d.funding_context.confidence_band }})</span></p>
{% set ladder = d.funding_context.ladder %}
{% if ladder %}
<table><tr><th>FY</th><th>Requested</th><th>Available</th><th>Obligated</th><th>Rate</th></tr>
{% for r in ladder.rows %}
<tr><td>FY{{ r.fiscal_year }}</td>
<td>{{ '${:,.0f}'.format(r.requested) if r.requested else '—' }}</td>
<td>{{ '${:,.0f}'.format(r.available) if r.available else '—' }}</td>
<td>{{ '${:,.0f}'.format(r.obligated) if r.obligated else '—' }}</td>
<td>{{ (r.obligation_rate_pct ~ '%') if r.obligation_rate_pct is not none else '—' }}</td></tr>
{% endfor %}</table>
{% for n in ladder.notes %}<p class="quality">• {{ n }}</p>{% endfor %}
{% for c in ladder.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}
{% endif %}
{% for c in d.funding_context.caveats %}<div class="caveat">{{ c }}</div>{% endfor %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Work Origin</h2>
<p><strong>{{ d.work_origin_assessment.work_origin_assessment | replace('_',' ') }}</strong>
 <span class="conf">{{ d.work_origin_assessment.confidence }}/100</span></p>

{% if delegation %}
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Congressional Delegation (place of performance)</h2>
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
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Solicitation Requirements (extracted)</h2>
<table>
  <tr><th>Type</th><th>Requirement</th><th>Your evidence</th><th>Source</th><th>Confidence</th></tr>
  {% for r in requirements %}
  <tr><td>{{ r.requirement_type }}</td><td>{{ r.value }}</td>
      <td class="conf">{% if r.proof_status == 'profile' %}from profile fields
        {%- elif r.proof_status %}{{ r.proof_status }}{% if r.proof_project %} — {{ r.proof_project }}{% endif %}
        {%- else %}—{% endif %}</td>
      <td>{{ r.filename or 'document' }}{% if r.page %} p.{{ r.page }}{% endif %}</td>
      <td>{{ r.confidence }}/100</td></tr>
  {% endfor %}
</table>
<p class="caveat">Extracted by deterministic rules from solicitation attachments.
Absence of a row means no rule matched — not that the requirement is absent.
Always read the solicitation.</p>
{% endif %}

{% if ledger %}
{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Evidence &amp; Source Ledger</h2>
<table><tr><th>Source</th><th>Identifier</th><th>Retrieved</th><th>Used by</th><th>Limitations</th></tr>
{% for s in ledger %}
<tr><td>{{ s.source_title }} <span class="conf">{{ s.organization }}</span></td>
<td>{{ s.identifier or '—' }}</td><td class="conf">{{ s.retrieved or '—' }}</td>
<td class="conf">{{ s.used_by | join('; ') }}</td>
<td class="conf">{{ s.limitations or '' }}</td></tr>
{% endfor %}</table>
{% endif %}

{% set ns.n = ns.n + 1 %}<h2>{{ ns.n }}. Caveats and Data Sources</h2>
{% for q in d.data_quality %}<p class="quality">• {{ q }}</p>{% endfor %}
<p class="quality">Sources: SAM.gov opportunity data, SAM.gov award notices,
USAspending award and budget data, agency procurement forecasts where linked.
All assertions carry confidence bands; inference is labeled as inference.</p>
</body></html>
""")


def render_report(dossier: dict, opp_url: str | None = None,
                  notice_id: str | None = None, inline_css: bool = True,
                  delegation: list | None = None,
                  requirements: list | None = None,
                  decision: dict | None = None, value_est: dict | None = None,
                  days_left: int | None = None,
                  forecasts: list | None = None,
                  ledger: list | None = None,
                  brief: list | None = None) -> str:
    """inline_css=True for standalone/export HTML; False for the web route,
    which links /static/report.css so the strict CSP (style-src 'self')
    applies without 'unsafe-inline'."""
    from .delegation import COMPLIANCE_NOTE
    return _TEMPLATE.render(d=dossier, url=safe_sam_url(opp_url, notice_id),
                            inline_css=inline_css, delegation=delegation or [],
                            delegation_note=COMPLIANCE_NOTE,
                            requirements=requirements or [],
                            decision=decision, value_est=value_est,
                            days_left=days_left, forecasts=forecasts or [],
                            ledger=ledger or [], brief=brief or [])
