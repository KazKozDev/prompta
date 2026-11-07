#!/usr/bin/env python3
"""Download the explicitly scoped official Claude documentation corpus.

Snapshots and hashes are evidence, never executable instructions. Run manually to
refresh; reviewed rules must be rechecked after a snapshot changes.
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
BASE = 'https://platform.claude.com/docs/en/'
PAGES = {
    'overview': 'build-with-claude/prompt-engineering/overview',
    'best-practices': 'build-with-claude/prompt-engineering/claude-prompting-best-practices',
    'hallucinations': 'test-and-evaluate/strengthen-guardrails/reduce-hallucinations',
    'consistency': 'test-and-evaluate/strengthen-guardrails/increase-consistency',
    'injection': 'test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks',
    'prompt-leak': 'test-and-evaluate/strengthen-guardrails/reduce-prompt-leak',
    'evaluations': 'test-and-evaluate/develop-tests',
}
for name in ('fable-5-1', 'fable-5', 'opus-5-5', 'opus-5', 'opus-4-8', 'sonnet-5-5', 'sonnet-5', 'haiku-5-5'):
    PAGES[name] = 'build-with-claude/prompt-engineering/prompting-claude-' + name

class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != 'https' or urlparse(newurl).hostname != 'platform.claude.com':
            raise ValueError('Redirect outside the verified official documentation host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(item):
    source_id, path = item
    url = BASE + path
    opener = urllib.request.build_opener(OfficialRedirects())
    with opener.open(urllib.request.Request(url + '.md', headers={'User-Agent': 'Prompta documentation snapshot'}), timeout=40) as response:
        raw = response.read(2_000_000)
        final_url = response.url
    text = raw.decode('utf-8')
    if not text.startswith('---\n') or '\ntitle:' not in text[:1000] or len(raw) < 300:
        raise ValueError('Unexpected documentation response: ' + url)
    snapshot = 'snapshots/' + source_id + '.md'
    (ROOT / snapshot).write_bytes(raw)
    sections = []
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), 1):
        if re.match(r'^\s*`{3,}', line):
            in_fence = not in_fence
        if not in_fence and (match := re.match(r'^(#{2,4}) (.+)', line)):
            title = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', match[2]).strip()
            anchor = re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')
            sections.append({'title': title, 'url': url + '#' + anchor, 'line': line_no})
    return {'id': source_id, 'title': re.search(r'^title: (.+)$', text, re.M)[1],
            'url': url, 'download_url': final_url, 'snapshot': snapshot,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'sections': sections,
            'scope': 'model-specific' if source_id in PAGES and source_id not in ('overview','best-practices','hallucinations','consistency','injection','prompt-leak','evaluations') else 'general'}


def main():
    (ROOT / 'snapshots').mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(download, PAGES.items()))
    (ROOT / 'sources.json').write_text(json.dumps({'sources': sources}, ensure_ascii=False, indent=2) + '\n')
    print('Saved', len(sources), 'official sources;', sum(len(s['sections']) for s in sources), 'sections')

if __name__ == '__main__':
    main()
