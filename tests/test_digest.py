from datetime import datetime, timedelta, timezone

from src.digest import build_sections, render

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
DATE = NOW.date()


def row(**kw):
    base = {
        "id": 1, "title": "Inventory System Modernization", "agency": "Army",
        "notice_type": "Solicitation", "naics": "541512", "set_aside": "Small Business",
        "response_deadline": NOW + timedelta(days=10),
        "url": "https://sam.gov/opp/abc/view", "source_notice_id": "abc",
        "place_of_performance": "Huntsville, AL",
        "category": "Inventory / Asset / Logistics Tools", "score": 85,
        "reasons": ["software keywords in title", "software NAICS 541512"],
        "components": {}, "recommended_action": "Begin bid/no-bid review.",
        "first_seen_at": NOW,
    }
    base.update(kw)
    return base


XSS_PAYLOADS = [
    "<img src=x onerror=alert(1)>",
    "<script>alert(1)</script>",
    "<b onmouseover=alert(1)>bold</b",   # malformed HTML
    '"><style>*{display:none}</style>',
]


def test_malicious_fields_are_escaped_everywhere():
    for payload in XSS_PAYLOADS:
        html = render(
            [row(id=1, title=payload, agency=payload, set_aside=payload,
                 category=payload, reasons=[payload], recommended_action=payload)],
            DATE, now=NOW,
        )
        # No unescaped tag may survive; escaped text (&lt;img ... &gt;) is inert.
        for tag in ("<img", "<script", "<style", "<b onmouseover"):
            assert tag not in html
        assert "&lt;" in html  # payload present, but escaped
        # onerror= must never appear inside a real attribute context
        assert 'src=x onerror="' not in html and "'onerror'=" not in html


def test_unsafe_url_never_reaches_href():
    html = render([row(url="javascript:alert(1)", source_notice_id="abc123")], DATE, now=NOW)
    assert "javascript:" not in html
    assert 'href="https://sam.gov/opp/abc123/view"' in html


def test_no_link_when_nothing_safe():
    html = render([row(url="javascript:alert(1)", source_notice_id="../evil")], DATE, now=NOW)
    assert "javascript:" not in html
    assert "Inventory System Modernization" in html  # title still rendered, linkless


def test_sections_route_correctly():
    rows = [
        row(id=1, score=90, response_deadline=NOW + timedelta(days=1)),        # act today
        row(id=2, score=88, response_deadline=NOW + timedelta(days=30)),       # high match
        row(id=3, score=55, notice_type="Sources Sought",
            response_deadline=NOW + timedelta(days=30)),                        # early stage
        row(id=4, score=50, response_deadline=NOW + timedelta(days=5)),        # closing soon
    ]
    tracked = [dict(row(id=9, score=70), changes=[{"event_type": "deadline_changed", "detail": {}}])]
    sections, stats = build_sections(rows, tracked, now=NOW)
    by_title = {s["title"]: [o["id"] for o in s["rows"]] for s in sections}
    assert by_title["Act Today"] == [1]
    assert by_title["High-Match New Opportunities"] == [2]
    assert by_title["Amendments to Tracked Opportunities"] == [9]
    assert by_title["Early-Stage Market Research"] == [3]
    assert by_title["Closing Soon"] == [4]
    assert stats == {"total": 4, "high": 2, "act": 1, "tracked": 1}


def test_render_contains_why_action_countdown_and_signals():
    html = render([row()], DATE, now=NOW)
    assert "Why it matched:" in html
    assert "Next action:" in html
    assert "10 days left" in html
    assert "Market Signals" in html


def test_tracked_change_summary_rendered():
    tracked = [dict(row(id=9), changes=[{"event_type": "deadline_changed", "detail": {}},
                                        {"event_type": "stage_changed", "detail": {}}])]
    html = render([], DATE, tracked_amendments=tracked, now=NOW)
    assert "Changed:" in html and "deadline" in html and "notice stage" in html


def test_empty_digest_renders_gracefully():
    html = render([], DATE, now=NOW)
    assert "No opportunities cleared" in html
