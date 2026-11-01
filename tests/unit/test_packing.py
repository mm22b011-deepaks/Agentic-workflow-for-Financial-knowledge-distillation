"""Step 5: the interim packer keeps the passages that carry the facts."""

from __future__ import annotations

from nowcast.parsing.packing import OMISSION, pack

HEAD = 'ACME Q3 RESULTS. ' + 'x' * 900
GUIDANCE = 'Outlook: we expect revenue growth of 6% in the next quarter. '
MIDDLE = 'y' * 5000
REVENUE = 'Third quarter revenue was $1.20 billion. '
TAIL = 'z' * 3000
TEXT = HEAD + MIDDLE + GUIDANCE + MIDDLE + REVENUE + TAIL


def test_packer_keeps_guidance_window_past_the_cut() -> None:
    """Guidance text that sits past a plain cut is kept by the windows."""
    limit = 4000
    assert TEXT.index('Outlook') > limit, 'fixture must put guidance past the cut'
    packed = pack(TEXT, limit, ('guidance', 'revenue'))
    assert len(packed.text) <= limit
    assert 'Outlook' in packed.text
    assert '$1.20 billion' in packed.text
    # A plain cut would have dropped both.
    assert 'Outlook' not in TEXT[:limit]


def test_packer_output_in_document_order() -> None:
    """Regions are joined in the order they appear, never rearranged."""
    packed = pack(TEXT, 4000, ('revenue', 'outlook'))
    assert 0 <= packed.text.index('ACME') < packed.text.index('Outlook')
    assert packed.text.index('Outlook') < packed.text.index('$1.20 billion')


def test_packer_marks_omissions() -> None:
    """A gap between kept regions is marked, so nobody reads the text as continuous."""
    packed = pack(TEXT, 4000, ('outlook', 'revenue'))
    assert OMISSION.strip() in packed.text
    assert packed.windows_used >= 1
    assert packed.truncated


def test_short_text_is_untouched() -> None:
    """A document inside the limit is passed through unchanged."""
    packed = pack('short release', 4000, ('guidance',))
    assert packed.text == 'short release'
    assert not packed.truncated


def test_no_phrases_means_a_plain_head_cut() -> None:
    """With no configured phrases the packer is a cut, as before."""
    packed = pack('a' * 100, 10, ())
    assert packed.text == 'a' * 10
    assert packed.truncated


def test_tail_guidance_kept_when_revenue_is_frequent() -> None:
    """When 'revenue' appears everywhere, guidance at the tail still gets budget."""
    body = ('Revenue was $1.20 billion this quarter. ' * 400) + (
        'The company expects full-year guidance of $9.9 billion in revenue. '
    )
    packed = pack(body, 4000, ('revenue', 'per share', 'outlook', 'guidance'))
    assert len(packed.text) <= 4000
    # The single guidance sentence sits ~15k characters in; a first-come allocation
    # spends the whole budget on the repeated 'revenue' windows and loses it.
    assert 'full-year guidance' in packed.text


def test_never_exceeds_limit_sweep() -> None:
    """No limit and no phrase set can produce more than `limit` characters.

    Small limits are included deliberately: they are the case where a region does not
    fit at all, which is exactly when a negative budget appeared.
    """
    for limit in (1, 2, 13, 50, 200, 999, 4000, 12000):
        for phrases in ((), ('revenue',), ('revenue', 'guidance', 'per share', 'outlook')):
            packed = pack(TEXT, limit, phrases)
            assert len(packed.text) <= limit, (limit, phrases)


def test_document_order_preserved() -> None:
    """Budget priority decides what is kept, never the order it appears in."""
    packed = pack(TEXT, 4000, ('per share', 'revenue', 'outlook', 'guidance'))
    positions = [packed.text.find(marker) for marker in ('ACME', 'Outlook', 'revenue')]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)


def test_priority_decides_which_window_survives_a_tight_budget() -> None:
    """With room for one window, the higher-priority phrase is the one kept."""
    # The lower-priority phrase comes FIRST in the document and the higher-priority one
    # last, so choosing in document order and choosing by priority give different answers.
    # Both windows exist and only one fits.
    text = (
        ('FILLER ' * 300)
        + 'revenue was $1.2 billion here '
        + ('pad ' * 600)
        + ('guidance: full-year outlook unchanged ' + 'tail ' * 300)
    )
    assert text.index('revenue was') < text.index('guidance:')
    packed = pack(text, 2500, ('revenue', 'guidance'), priority=('guidance', 'revenue'))
    assert len(packed.text) <= 2500
    assert 'full-year outlook' in packed.text
    assert 'revenue was' not in packed.text

    # Reversed priority keeps the revenue window instead.
    other = pack(text, 2500, ('revenue', 'guidance'), priority=('revenue', 'guidance'))
    assert 'revenue was' in other.text
    assert 'full-year outlook' not in other.text
