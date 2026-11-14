#!/usr/bin/env python3
"""Snapshot the explicitly scoped official Google Gemini prompting corpus.

Updates require a manual rule review: changing snapshots does not approve new rules.
"""

import concurrent.futures
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
OFFICIAL_HOSTS = {'ai.google.dev', 'aistudio.google.com', 'docs.cloud.google.com', 'cloud.google.com'}
PAGES = {
    'prompting': 'https://ai.google.dev/gemini-api/docs/prompting-strategies',
    'thinking': 'https://aistudio.google.com/docs/thinking',
    'structured-outputs': 'https://aistudio.google.com/docs/structured-output',
    'safety': 'https://aistudio.google.com/docs/safety-guidance',
    'files': 'https://aistudio.google.com/docs/files',
    'gemini-3-migration': 'https://ai.google.dev/gemini-api/docs/gemini-3',
}


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in OFFICIAL_HOSTS:
            raise ValueError('Redirect outside the allowed official documentation hosts')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sections(text, url):
    result = []
    fence = 0
    pending_anchor = None
    used = {}
    for number, line in enumerate(text.splitlines(), 1):
        code = re.match(r'^\s*(`{3,}|~{3,})', line)
        if code:
            if not fence:
                fence = len(code[1])
            elif len(code[1]) >= fence:
                fence = 0
            continue
        if re.match(r'^#{1,4} .*\{% id=', line):
            fence = 0
        if fence:
            continue
        anchor = re.match(r'^<a id="([^"]+)"[^>]*></a>', line.strip())
        if anchor:
            pending_anchor = anchor[1]
            continue
        match = re.match(r'^(#{1,4}) (.+)', line)
        if match and ('{% id=' in line or (len(match[1]) == 1 and not result)):
            explicit = re.search(r'\{% id="([^"]+)" %\}', match[2])
            heading = re.sub(r'\s*\{%.*?%\}', '', match[2]).strip()
            title = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', heading).strip()
            if explicit:
                pending_anchor = explicit[1]
            slug = re.sub(r'[^\w\s-]', '', title.lower()).strip().replace(' ', '-')
            count = used.get(slug, 0)
            used[slug] = count + 1
            target = pending_anchor or (slug + (f'-{count}' if count else ''))
            result.append({'title': title, 'url': url + '#' + target, 'line': number})
            pending_anchor = None
        elif line.strip():
            pending_anchor = None
    return result


def download(item):
    source_id, url = item
    opener = urllib.request.build_opener(OfficialRedirects())
    with opener.open(
        urllib.request.Request(
            url + '.md', headers={'User-Agent': 'Prompta official documentation snapshot', 'Accept': 'text/markdown'}
        ),
        timeout=40,
    ) as response:
        raw = response.read(2_000_001)
        final_url = response.url
    text = raw.decode('utf-8')
    if (
        len(raw) > 2_000_000
        or not re.search(r'^# ', text, re.M)
        or '<!doctype html' in text[:100].lower()
        or len(raw) < 300
    ):
        raise ValueError('Unexpected Markdown response: ' + url)
    canonical = final_url.split('?')[0].removesuffix('.md')
    title = re.sub(r'\s*\{%.*?%\}', '', re.search(r'^# (.+)', text, re.M)[1]).strip()
    source = {
        'id': source_id,
        'title': title,
        'url': canonical,
        'requested_url': url,
        'download_url': final_url,
        'snapshot': 'snapshots/' + source_id + '.md',
        'sha256': hashlib.sha256(raw).hexdigest(),
        'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'scope': 'reference-only' if source_id == 'gemini-3-migration' else 'general',
        'sections': sections(text, canonical),
    }
    return source, raw


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        downloads = list(pool.map(download, PAGES.items()))
    (ROOT / 'snapshots').mkdir(exist_ok=True)
    for source, raw in downloads:
        (ROOT / source['snapshot']).write_bytes(raw)
    sources = [source for source, _ in downloads]
    (ROOT / 'sources.json').write_text(json.dumps({'sources': sources}, ensure_ascii=False, indent=2) + '\n')
    print('Saved', len(sources), 'official sources and', sum(len(s['sections']) for s in sources), 'sections')


if __name__ == '__main__':
    main()
