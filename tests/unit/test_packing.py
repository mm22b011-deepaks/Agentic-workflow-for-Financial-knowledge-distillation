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
