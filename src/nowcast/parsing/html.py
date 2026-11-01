"""HTML to text conversion tuned for SEC filing documents."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment

# EDGAR delivers a filing document as an SGML envelope:
#   <DOCUMENT><TYPE>EX-99.1<SEQUENCE>3<FILENAME>d123dex991.htm<DESCRIPTION>...
#   <TEXT> ...the document... </TEXT></DOCUMENT>
# Everything before <TEXT> is metadata that would otherwise be read as body text.
# The envelope must be the *first* thing in the file: an ordinary HTML page can contain
# an inline SVG <text>, and stripping from that would delete the page before it. Matching
# to the final </TEXT> rather than the first keeps a body that mentions the marker.
SGML_TEXT_RE = re.compile(r'^\s*<DOCUMENT>.*?<TEXT>(.*)</TEXT>', re.S | re.I)
SGML_ENVELOPE_RE = re.compile(r'</?DOCUMENT>', re.I)

BLOCK_TAGS = (
    'p',
    'div',
    'br',
    'tr',
    'li',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'table',
)
DROP_TAGS = ('script', 'style', 'noscript', 'meta', 'link')
WHITESPACE_RE = re.compile(r'[ \t\xa0​]+')
BLANK_LINES_RE = re.compile(r'\n{3,}')


def _insert_breaks(node: object) -> None:
    """Replace block-level elements with their text plus a line break."""
    for tag_name in BLOCK_TAGS:
        for tag in node.find_all(tag_name):  # type: ignore[attr-defined]
            tag.insert_after('\n')


def strip_sgml_wrapper(raw: str) -> str:
    """Return the payload of an SGML filing envelope, or the text unchanged.

    A document served from the EDGAR archive can carry the wrapper even when its
    name ends in `.htm`. Fed to the HTML parser, the `<TYPE>`/`<FILENAME>` header lines
    become the first lines of the "document text" the model sees.
    """
    match = SGML_TEXT_RE.search(raw)
    payload = match.group(1) if match else raw
    if match is not None:
        payload = SGML_ENVELOPE_RE.sub('', payload)
    return payload


def html_to_text(html: str) -> str:
    """Convert an HTML document to plain text with one line per block and table row."""
    html = strip_sgml_wrapper(html)
    soup = BeautifulSoup(html, 'lxml')
    for tag_name in DROP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    _insert_breaks(soup)
    text = soup.get_text(separator=' ')
    lines = [WHITESPACE_RE.sub(' ', line).strip() for line in text.splitlines()]
    cleaned = '\n'.join(line for line in lines if line)
    return BLANK_LINES_RE.sub('\n\n', cleaned).strip()


def text_stats(text: str) -> dict[str, int]:
    """Return simple size statistics used to decide whether a document is usable."""
    words = text.split()
    return {'characters': len(text), 'words': len(words), 'lines': len(text.splitlines())}
