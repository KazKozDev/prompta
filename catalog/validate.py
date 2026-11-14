#!/usr/bin/env python3
"""Checks catalog.json: structure, completeness, consistency.

Run:  python3 catalog/validate.py [--quiet]
Exit code 1 on errors (not on warnings).
"""
import json
import sys
from collections import Counter
from pathlib import Path

PATH = Path(__file__).parent / 'catalog.json'
REQUIRED = ('key', 'name', 'kind', 'category', 'execution', 'when_to_use', 'cost_calls',
            'config', 'template', 'example', 'source_ref', 'source_docs', 'related', 'status',
            'task_types', 'task_types_source')


def main() -> int:
    quiet = '--quiet' in sys.argv
    data = json.loads(PATH.read_text(encoding='utf-8'))
    errors, warnings = [], []

    techs = data.get('techniques', [])
    if not techs:
        print('ERROR: empty techniques')
        return 1

    for field in ('kind', 'execution', 'status'):
        if field not in data.get('enums', {}):
            errors.append(f'enums has no {field}')

    keys = [t.get('key') for t in techs]
    for key, count in Counter(keys).items():
        if count > 1:
            errors.append(f'duplicate key: {key}')
    for key in keys:
        if not key or not key.isascii():
            errors.append(f'key is not Latin: {key!r}')

    for t in techs:
        key = t.get('key', '<no key>')
        for field in REQUIRED:
            if field not in t:
                errors.append(f'{key}: missing field {field}')

        if not t.get('when_to_use'):
            errors.append(f'{key}: empty when_to_use')
        if not t.get('source_ref'):
            errors.append(f'{key}: empty source_ref')
        if not t.get('source_docs'):
            warnings.append(f'{key}: empty source_docs (nothing to confirm the source)')

        allowed_types = set(data['enums'].get('task_types', []))
        ttypes = t.get('task_types')
        if not isinstance(ttypes, list):
            errors.append(f'{key}: task_types must be a list')
        else:
            unknown = [x for x in ttypes if x not in allowed_types]
            if unknown:
                errors.append(f'{key}: unknown task_types {unknown}')
            if len(set(ttypes)) != len(ttypes):
                errors.append(f'{key}: repeat in task_types')
            if t.get('kind') in ('setting', 'risk') and ttypes:
                errors.append(f'{key}: a {t["kind"]} must not have task_types')
        if t.get('task_types_source') not in ('explicit', 'category-default'):
            errors.append(f'{key}: task_types_source={t.get("task_types_source")!r}')

        if t.get('kind') not in data['enums']['kind']:
            errors.append(f'{key}: kind={t.get("kind")!r}')
        if t.get('execution') not in data['enums']['execution']:
            errors.append(f'{key}: execution={t.get("execution")!r}')
        if t.get('status') not in data['enums']['status']:
            errors.append(f'{key}: status={t.get("status")!r}')

        cfg = t.get('config') or {}
        if 'rationale' not in cfg or not cfg.get('rationale'):
            errors.append(f'{key}: config without rationale')
        if t.get('kind') in ('setting', 'risk') and cfg.get('temperature') is not None:
            errors.append(f'{key}: temperature set for {t["kind"]}')

        if t.get('status') == 'procedure':
            steps = t.get('procedure')
            if not isinstance(steps, list) or not steps:
                errors.append(f'{key}: procedure without steps')
            if t.get('template'):
                errors.append(f'{key}: a procedure must not have a template')
        elif t.get('status') == 'ready':
            if '{{' not in (t.get('template') or ''):
                errors.append(f'{key}: ready, but the template is empty or has no {{{{placeholders}}}}')
            if not t.get('when_not'):
                errors.append(f'{key}: ready, but no when_not')
            if not t.get('related'):
                warnings.append(f'{key}: ready, but no related')
            if t.get('execution') == 'none':
                errors.append(f'{key}: ready, but execution=none')
        elif t.get('status') == 'index-only':
            if t.get('template'):
                errors.append(f'{key}: index-only, but a template is set')
            if t.get('kind') not in ('setting', 'risk'):
                warnings.append(f'{key}: index-only, but it is a {t.get("kind")} — check whether a template was forgotten')

    if not quiet:
        print(f'entries: {len(techs)}')
        print('by status:', dict(Counter(t['status'] for t in techs)))
        print('by category:', dict(Counter(t['category'] for t in techs)))
        print('by execution:', dict(Counter(t['execution'] for t in techs)))

    for w in warnings:
        print('  warning:', w)
    for e in errors:
        print('  ERROR:', e)
    print('result:', 'OK' if not errors else f'{len(errors)} errors')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
