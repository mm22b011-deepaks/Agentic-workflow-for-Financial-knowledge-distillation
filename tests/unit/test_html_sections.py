"""Unit tests for HTML conversion and section splitting."""

from __future__ import annotations

from nowcast.parsing.html import html_to_text, text_stats
from nowcast.parsing.sections import Section, pick_sections, split_sections


def test_html_strips_scripts() -> None:
    """Script and style content never reaches the text."""
    html = (
        '<html><head><style>.x{color:red}</style><script>alert(1)</script></head>'
        '<body><p>Revenue was $1.20 billion.</p><table><tr><td>EPS</td><td>0.55</td></tr></table></body>'
    )
    text = html_to_text(html)
    assert 'Revenue was $1.20 billion.' in text
    assert 'alert' not in text
    assert 'color:red' not in text
    assert 'EPS 0.55' in text or ('EPS' in text and '0.55' in text)


def test_html_keeps_paragraph_breaks() -> None:
    """Separate paragraphs occupy separate lines."""
    text = html_to_text('<p>First para.</p><p>Second para.</p>')
    assert text.splitlines() == ['First para.', 'Second para.']


def test_html_empty_input() -> None:
    """An empty document yields empty text and zero stats."""
    assert html_to_text('') == ''
    assert text_stats('') == {'characters': 0, 'words': 0, 'lines': 0}


def test_sections_offsets_roundtrip() -> None:
    """Each section slice begins with its header text."""
    text = 'HEADER\nDiscussion and Analysis here.\nFinancial Statements start here.\n'
    patterns = {
        'discussion': r'Discussion and Analysis',
        'financials': r'Financial Statements',
    }
    sections = split_sections(text, patterns)
    assert [section.name for section in sections] == ['discussion', 'financials']
    assert text[sections[0].start :].startswith('Discussion and Analysis')
    assert text[sections[1].start :].startswith('Financial Statements')
    assert sections[0].end == sections[1].start


def test_sections_empty_patterns_returns_full() -> None:
    """With no patterns the whole document is one section."""
    sections = split_sections('anything', {})
    assert sections == [Section(name='full', start=0, end=len('anything'))]


def test_sections_unmatched_patterns_returns_full() -> None:
    """Patterns that never match fall back to the full document."""
    sections = split_sections('nothing here', {'x': r'absent'})
    assert sections[0].name == 'full'


def test_pick_sections_joins_named_spans() -> None:
    """Selecting by name returns only the requested spans."""
    text = 'AAA intro\nBBB body\nCCC tail\n'
    patterns = {'intro': r'AAA', 'body': r'BBB', 'tail': r'CCC'}
    picked = pick_sections(text, patterns, ['body'])
    assert picked.startswith('BBB')
    assert 'AAA' not in picked


def test_sgml_strip_only_when_wrapped_at_start() -> None:
    """Inline SVG <text> in an ordinary page is not mistaken for an SGML envelope."""
    from nowcast.parsing.html import strip_sgml_wrapper

    page = (
        '<html><body><p>Results.</p><svg><text>Revenue 1.2bn</text></svg><p>Tail.</p></body></html>'
    )
    assert strip_sgml_wrapper(page) == page


def test_sgml_strip_keeps_everything_up_to_the_final_text_close() -> None:
    """A nested </TEXT> inside the body must not truncate the document."""
    from nowcast.parsing.html import strip_sgml_wrapper

    raw = (
        '<DOCUMENT><TYPE>EX-99.1<SEQUENCE>1<TEXT>'
        '<html><body><p>Revenue was $5 million.</p>'
        '<p>Inline </TEXT> marker inside the body.</p>'
        '<p>Guidance unchanged.</p></body></html>'
        '</TEXT></DOCUMENT>'
    )
    payload = strip_sgml_wrapper(raw)
    assert 'Revenue was $5 million.' in payload
    assert 'Guidance unchanged.' in payload
    assert 'EX-99.1' not in payload
