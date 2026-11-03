"""Online-only link audit of the README."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


def main() -> int:
    paths = [Path('README.md')]
    links = sorted(
        {
            url.rstrip('.,;')
            for path in paths
            for url in re.findall(r'https://[^\s)>`]+', path.read_text())
        }
    )

    def check(url: str) -> tuple[str, int]:
        try:
            with httpx.Client(follow_redirects=True, timeout=20) as client:
                return url, client.get(url).status_code
        except httpx.HTTPError:
            return url, 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, links))
    for url, status in results:
        print(f'{status}: {url}')
    return int(any(status < 200 or status >= 400 for _, status in results))


if __name__ == '__main__':
    raise SystemExit(main())
