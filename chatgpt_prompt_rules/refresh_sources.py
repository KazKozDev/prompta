#!/usr/bin/env python3
"""Snapshot the explicitly scoped official OpenAI/ChatGPT prompting corpus.

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
OFFICIAL_HOSTS = {'developers.openai.com', 'platform.openai.com', 'learn.chatgpt.com'}
PAGES = {
    'chatgpt-prompting': 'https://learn.chatgpt.com/docs/prompting',
    'prompt-engineering': 'https://developers.openai.com/api/docs/guides/prompt-engineering',
    'reasoning': 'https://developers.openai.com/api/docs/guides/reasoning-best-practices',
    'prompting': 'https://developers.openai.com/api/docs/guides/prompting',
    'enterprise-guide': 'https://developers.openai.com/cookbook/examples/chatgpt/chatgpt_prompt_guide/chatgpt_prompt_guide',
    'prompt-generation': 'https://developers.openai.com/api/docs/guides/prompt-generation',
    'structured-outputs': 'https://developers.openai.com/api/docs/guides/structured-outputs',
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
        if fence:
            continue
        anchor = re.match(r'^<a id="([^"]+)"[^>]*></a>', line.strip())
        if anchor:
            pending_anchor = anchor[1]
            continue
        match = re.match(r'^(#{1,4}) (.+)', line)
        if match:
            title = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', match[2]).strip()
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
    with opener.open(urllib.request.Request(url + '.md', headers={'User-Agent': 'Prompta official documentation snapshot'}), timeout=40) as response:
        raw = response.read(2_000_001)
        final_url = response.url
    text = raw.decode('utf-8')
    if len(raw) > 2_000_000 or not text.startswith('# ') or len(raw) < 300:
        raise ValueError('Unexpected Markdown response: ' + url)
    source = {'id': source_id, 'title': text.splitlines()[0].lstrip('# '), 'url': url,
              'download_url': final_url, 'snapshot': 'snapshots/' + source_id + '.md',
              'sha256': hashlib.sha256(raw).hexdigest(),
              'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'scope': 'reference-only' if source_id == 'prompt-generation' else 'general',
              'sections': sections(text, url)}
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
