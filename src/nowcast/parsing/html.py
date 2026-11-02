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


def _span(value: object, maximum: int) -> int:
    """Apply HTML span limits without trusting malformed or unbounded integers."""
    text = str(value)
    if not text.isdecimal():
        return 1
    text = text.lstrip('0') or '1'
    return min(maximum, int(text)) if len(text) <= 5 else maximum


def _table_rows(table: object) -> list[str]:
    """Expand HTML spans and bind each financial cell to its physical period column."""
    rows: list[str] = []
    header: dict[int, str] = {}
    carried: dict[int, tuple[str, int]] = {}
    for row in table.find_all('tr'):  # type: ignore[attr-defined]
        cells = row.find_all(['td', 'th'], recursive=False)
        raw = [WHITESPACE_RE.sub(' ', cell.get_text(' ', strip=True)) for cell in cells]
        nonempty = [value for value in raw if value]
        if not nonempty:
            continue
        has_year = any(re.search(r'\b20\d{2}\b', value) for value in raw)
        amounts = any(
            re.fullmatch(r'\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?', value)
            and not re.fullmatch(r'20\d{2}', value)
            for value in raw
        )
        is_header = (
            not amounts
            and not any(re.search(r'[$€£]', value) for value in raw)
            and (
                any(cell.name == 'th' for cell in cells)
                or (
                    has_year
                    and (
                        re.search(r'\b20\d{2}\b', nonempty[0])
                        or re.search(
                            r'ended|quarter|months?|in millions|in thousands', nonempty[0], re.I
                        )
                    )
                )
            )
        )
        grid = {column: value for column, (value, _) in carried.items()}
        pending = {
            column: (value, remaining - 1)
            for column, (value, remaining) in carried.items()
            if remaining > 1
        }
        column = 0
        for cell, value in zip(cells, raw, strict=True):
            while column in grid:
                column += 1
            colspan = _span(cell.get('colspan', 1), 1000)
            rowspan = _span(cell.get('rowspan', 1), 65534)
            for offset in range(colspan):
                text = value if is_header or offset == 0 else ''
                grid[column + offset] = text
                if rowspan > 1:
                    pending[column + offset] = (text, rowspan - 1)
            column += colspan
        carried = pending
        if is_header:
            for column, value in grid.items():
                if value:
                    prefix = header.get(column, '')
                    header[column] = (
                        (prefix + ' ' + value).strip()
                        if not re.search(r'\b20\d{2}\b', prefix)
                        else value
                    )
            rows.append(' '.join(nonempty))
            continue
        bands: list[tuple[str, str]] = []
        for column, value in sorted(grid.items()):
            period = header.get(column, '')
            if not re.search(r'\b20\d{2}\b', period):
                period = ''
            if bands and bands[-1][0] == period:
                bands[-1] = (period, (bands[-1][1] + ' ' + value).strip())
            else:
                bands.append((period, value))
        rows.append(
            ' | '.join(
                f'[{period}] {value}' if period else value for period, value in bands if value
            )
        )
    return rows


def html_to_text(html: str) -> str:
    """Convert an HTML document to plain text with one line per block and table row."""
    html = strip_sgml_wrapper(html)
    soup = BeautifulSoup(html, 'lxml')
    for tag_name in DROP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # Convert leaf financial tables; enclosing layout tables retain their paragraphs.
    tables = [table for table in soup.find_all('table') if table.find('table') is None]
    for table in reversed(tables):
        unit_match = re.search(
            r'\bin (?:thousands|millions|billions)\b', table.get_text(' ', strip=True), re.I
        )
        rows = ['[table units: ' + (unit_match.group() if unit_match else '') + ']']
        rows.extend(_table_rows(table))
        table.replace_with('\n' + '\n'.join(rows) + '\n')
    _insert_breaks(soup)
    text = soup.get_text(separator=' ')
    lines = [WHITESPACE_RE.sub(' ', line).strip() for line in text.splitlines()]
    cleaned = '\n'.join(line for line in lines if line)
    return BLANK_LINES_RE.sub('\n\n', cleaned).strip()


def text_stats(text: str) -> dict[str, int]:
    """Return simple size statistics used to decide whether a document is usable."""
    words = text.split()
    return {'characters': len(text), 'words': len(words), 'lines': len(text.splitlines())}
