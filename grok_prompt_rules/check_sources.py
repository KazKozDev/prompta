#!/usr/bin/env python3
"""Check whether the saved official Grok documentation snapshots still match docs.x.ai.

Read-only: downloads each source as Markdown, compares its SHA-256 with sources.json and
reports changes. It never rewrites snapshots; changed rules must be reviewed by hand.
Exit code 1 when any source changed or could not be checked.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = 'docs.x.ai'


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != 'https' or urlparse(newurl).hostname != HOST:
            raise ValueError('Redirect outside the official documentation host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> bytes:
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != HOST:
        raise ValueError('Not an official Grok documentation URL: ' + url)
    request = urllib.request.Request(url, headers={'User-Agent': 'Prompta documentation snapshot', 'Accept': 'text/markdown'})
    with urllib.request.build_opener(OfficialRedirects()).open(request, timeout=40) as response:
        if 'markdown' not in response.headers.get('Content-Type', ''):
            raise ValueError('Expected Markdown, got ' + response.headers.get('Content-Type', '?'))
        return response.read(2_000_000)


def main() -> int:
    sources = json.loads((ROOT / 'sources.json').read_text())['sources']
    problems = 0
    for source in sources:
        try:
            digest = hashlib.sha256(fetch(source['download_url'])).hexdigest()
        except Exception as error:  # network or format problem: report, do not hide
            print(f"? {source['id']}: {error}")
            problems += 1
            continue
        if digest == source['sha256']:
            print(f"= {source['id']}")
        else:
            print(f"! {source['id']}: changed ({source['sha256'][:12]} -> {digest[:12]}) {source['url']}")
            problems += 1
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
