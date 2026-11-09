"""Read-only inventory of Promptа's source corpus and pipeline implementation."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


PIPELINE_MATERIALS = {
    'brief.ts': 'Thoughts → structured brief: compiler instructions, schema and validation.',
    'catalog.ts': 'Load the catalog and English display metadata; filter techniques by task, modality, budget and available input.',
    'select.ts': 'Brief + eligible techniques → ranked technique choices.',
    'synthesize.ts': 'Selected technique + brief → final prompt and settings.',
    'manual.ts': 'Manual technique generation and output validation.',
    'official.ts': 'Official-rule compiler, source validation and rule-usage metadata.',
    'claude.ts': 'Claude target scope and compiler policy.',
    'chatgpt.ts': 'ChatGPT target scope and compiler policy.',
    'gemini.ts': 'Gemini target scope and compiler policy.',
    'grok.ts': 'Grok target scope and compiler policy.',
    'open-model.ts': 'Model-specific compilation from pinned official open-weight model cards with integrity verification.',
    'prompt-defaults.ts': 'Product default: opening worked example. This is a product instruction, not a source recommendation.',
    'zero-shot.ts': 'Additional standalone baseline prompt built from the task.',
    'index.ts': 'Pipeline orchestration, routing, variants and progress.',
    'json.ts': 'JSON parsing, repair and validation helpers.',
    'llm.ts': 'Generator adapters and request settings; no API keys are stored in this file.',
    'types.ts': 'Brief, technique, result and provenance data contracts.',
    'render.ts': 'Result rendering and source-link validation.',
    'cli.ts': 'Command-line pipeline entry point. Reference; not the desktop generation route.',
    'preview.ts': 'Prompt preview tooling. Reference; not the normal generation call.',
    'README.md': 'Pipeline overview and usage documentation.',
}


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def library_entries(root: Path) -> list[dict]:
    entries: list[dict] = []

    def add(category: str, title: str, relative: str, use: str, **metadata) -> None:
        try:
            safe_path(root, relative)
        except (ValueError, OSError):
            return
        entries.append(dict(category=category, title=title, path=relative, use=use, **metadata))

    for file, title, use in (
        ('catalog.json', 'Technique catalog', 'Active general-mode input: templates, applicability, costs, settings and source references.'),
        ('display.en.ts', 'English technique labels', 'Names and hints displayed in the picker and supplied to technique selection.'),
        ('source-links.json', 'Technique → source links', 'Source documents and page references for every technique; used by article icons.'),
    ):
        add('Technique catalog', title, 'catalog/' + file, use)
    add('Technique catalog', 'Technique source map', 'archive-org-prompting/techniques-map.md', 'Human-readable technique → document/page map. Reference material behind the catalog.')
    add('Technique catalog', 'Archive collection notes', 'archive-org-prompting/README.md', 'Acquisition method, document list and limitations. Reference only.')

    for path in sorted((root / 'archive-org-prompting/md').glob('*.md')):
        text = path.read_text(encoding='utf-8')
        front = text.split('---', 2)[1] if text.startswith('---') else ''
        def field(name: str) -> str:
            match = re.search(r'^' + name + r':\s*(.+)$', front, re.M)
            return match.group(1).strip().strip('"') if match else ''
        title = field('title') or path.stem
        add('Technique documents', title, str(path.relative_to(root)), 'Extracted source text supporting catalog entries; not injected wholesale into generation.', url=field('archive_item') or field('source'), reference=field('year'))
        add('Technique documents', title + ' · original PDF', f'archive-org-prompting/pdf/{path.stem}.pdf', 'Original document for checking the extracted text, tables and cited pages.', url=field('pdf_url'))

    for target, label in [('claude', 'Claude'), ('chatgpt', 'ChatGPT'), ('gemini', 'Gemini'), ('grok', 'Grok')]:
        folder = f'{target}_prompt_rules'
        category = label + ' official sources'
        for name, use in (
            ('rules.json', 'Active prompt-level rules are supplied to this target compiler. Status, condition and application fields determine eligibility.'),
            ('sources.json', 'Source registry: URLs, sections, retrieval dates and expected SHA-256 hashes.'),
            ('sections.json', 'Archived full sections and examples for tracing each recommendation. Reference, not injected wholesale.'),
            ('coverage.json', 'Scope, exclusions and review criteria; explains what is not covered.'),
            ('README.md', 'Bundle scope, provenance and usage notes.'),
        ):
            add(category, label + ' · ' + name, folder + '/' + name, use)
        for name in ('official-manual.md', 'llms.txt', 'refresh_sources.py'):
            if (root / folder / name).exists():
                add(category, label + ' · ' + name, folder + '/' + name, 'Reference or source-maintenance material; not a separate generation rule.')
        try:
            registry = json.loads(safe_path(root, folder + '/sources.json').read_text())
            for source in registry['sources']:
                add(category, source['title'], folder + '/' + source['snapshot'],
                    'Downloaded original. Rules derived from this source are listed in rules.json; scope: ' + source.get('scope', 'see rule conditions') + '.',
                    url=source.get('url', ''), expected_hash=source.get('sha256'), reference=source.get('retrieved_at', ''))
        except (OSError, ValueError, KeyError, TypeError):
            add(category, 'Source registry unavailable', folder + '/sources.json', 'Registry could not be read. Inspect the saved file; no source checks are claimed.')

    open_models = root / 'open_model_prompt_guides/manifest.json'
    if open_models.exists():
        add('Open-weight models · collection', 'Selection, versions & provenance', 'open_model_prompt_guides/manifest.json', 'Dated selection of 15 leading models, not an absolute benchmark ranking. Records official repositories, licenses, revisions and download limitations.')
        add('Open-weight models · collection', 'Collection scope & model list', 'open_model_prompt_guides/README.md', 'Scope and acquisition notes. Select a model on the main screen to enable its model-card prompting mode.')
        try:
            manifest = json.loads(open_models.read_text())
            for model in manifest['models']:
                category = model['name'] + ' · open weights'
                folder = 'open_model_prompt_guides/' + model['id']
                summary = f"{model['role']}. License: {model.get('license', 'unknown')}. Revision: {model['revision']}. Available to model-specific prompting when explicitly selected on the main screen."
                add(category, 'Prompting manual · source excerpts', folder + '/prompting-manual.md', model['guidance_kind'] + '. ' + summary, url=model['url'])
                add(category, 'Model version, license & download status', folder + '/model.json', summary, url=model['url'])
                add(category, 'Prompting sections & source references', folder + '/prompting-sections.json', 'Verbatim excerpts with source line numbers and hashes; no invented recommendations.', url=model['url'])
                for source in model['files']:
                    add(category, source['title'], 'open_model_prompt_guides/' + source['snapshot'],
                        source.get('scope', source.get('extraction', 'Original file from the developer-owned model repository, pinned to a commit.')) + ' ' + summary,
                        url=source['url'], expected_hash=source['sha256'], reference=model['retrieved_at'])
        except (OSError, ValueError, KeyError, TypeError):
            add('Open-weight models · collection', 'Collection registry unavailable', 'open_model_prompt_guides/manifest.json', 'Inspect the saved manifest; no verification is claimed.')

    for name, use in PIPELINE_MATERIALS.items():
        add('Pipeline instructions & logic', name, 'pipeline/' + name, use)
    add('Pipeline instructions & logic', 'Desktop bridge', 'desktop/bridge.ts', 'UI requests → validation, source-mode routing and generator invocation.')
    add('Runtime & traceability', 'Desktop application', 'desktop/app.py', 'Request flags, UI defaults, result rendering and source links. Runtime code, not an LLM source document.')
    add('Runtime & traceability', 'History storage', 'desktop/history.py', 'History and source metadata persistence. Code only; saved user queries are excluded from this library.')
    for relative in ('catalog/README.md', 'catalog/build_catalog.py', 'catalog/validate.py'):
        add('Catalog maintenance', Path(relative).name, relative, 'Catalog construction or validation material; not an LLM instruction.')
    for path in sorted((root / 'eval').glob('*')):
        if path.suffix in ('.ts', '.json', '.md') and not path.name.endswith('.test.ts'):
            add('Evaluation · separate from generation', path.name, str(path.relative_to(root)), 'Evaluation harness, grading criteria or fixtures; not used by the normal generation call.')
    return entries


def read_material(root: Path, entry: dict) -> tuple[str, str]:
    path = safe_path(root, entry['path'])
    try:
        data = path.read_bytes()
    except OSError:
        return 'File missing or unreadable', 'This material is declared but cannot be opened.'
    digest = hashlib.sha256(data).hexdigest()
    expected = entry.get('expected_hash')
    status = ('Matches saved source hash' if digest == expected else 'SOURCE HASH MISMATCH') if expected else 'Local fingerprint (no saved source hash)'
    metadata = f"{status}\nSHA-256: {digest}\nSize: {len(data):,} bytes"
    if path.suffix.lower() == '.pdf':
        return metadata, 'Original PDF. Use Open file to inspect the document in your PDF viewer.'
    text = data.decode('utf-8', errors='replace')
    if len(text) > 250_000:
        text = text[:250_000] + '\n\n[Preview shortened. Open file to read the complete material.]'
    return metadata, text


from html import escape
from urllib.parse import urlparse
from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QSplitter, QTreeWidget, QTreeWidgetItem, QPlainTextEdit, QPushButton)


class LibraryWidget(QWidget):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.entries: list[dict] = []
        self.current: dict | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 18, 0, 0)  # air under the tab bar, same on every Settings tab
        outer.setSpacing(10)
        intro = QLabel('Inspect the saved sources, rules and instructions used by Promptа. Source hashes verify saved copies, not the truth of a recommendation.')
        intro.setWordWrap(True)
        intro.setObjectName('muted')
        outer.addWidget(intro)
        outer.addSpacing(6)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a source, rule bundle or pipeline stage')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('Search library')
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1)
        refresh = QPushButton()
        refresh.setObjectName('ghost')
        refresh.setIcon(QIcon(str(Path(__file__).with_name('refresh.svg'))))
        refresh.setIconSize(QSize(15, 15))
        refresh.setFixedSize(34, 34)  # same square as the model refresh button
        refresh.setToolTip('Refresh library')
        refresh.setAccessibleName('Refresh library')
        refresh.clicked.connect(self.reload)
        search_row.addWidget(refresh)
        outer.addLayout(search_row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(10)
        self.tree.setObjectName('libraryTree')
        self.tree.setMinimumWidth(180)
        self.tree.setAccessibleName('Library materials')
        self.tree.currentItemChanged.connect(self._selected)
        split.addWidget(self.tree)
        detail = QWidget()
        body = QVBoxLayout(detail)
        body.setContentsMargins(12, 0, 0, 0)
        self.info = QLabel('Select a material to see its purpose, provenance and content.')
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.info.setOpenExternalLinks(True)
        body.addWidget(self.info)
        self.integrity = QLabel()
        self.integrity.setWordWrap(True)
        self.integrity.setObjectName('muted')
        self.integrity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.integrity)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName('Material content preview')
        body.addWidget(self.preview, 1)
        self.open_button = QPushButton('Open file')
        self.open_button.setObjectName('ghost')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open)
        body.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)
        split.addWidget(detail)
        split.setSizes([250, 450])
        outer.addWidget(split, 1)
        self.summary = QLabel()
        self.summary.setObjectName('muted')
        outer.addWidget(self.summary)

    def reload(self) -> None:
        # Rebuilding is cheap, but keep the reader's place: re-select the material that was open.
        keep_path = self.current['path'] if self.current else None
        self.entries = library_entries(self.root)
        self.current = None
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for index, entry in enumerate(self.entries):
            if entry['category'] not in groups:
                group = QTreeWidgetItem(self.tree, [entry['category'].upper()])
                group.setExpanded(True)
                # Section label, like the category headers in the technique panel: not a material.
                group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = QFont(group.font(0))
                font.setPointSizeF(max(8.0, font.pointSizeF() - 3))
                font.setWeight(QFont.Weight.DemiBold)
                font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
                group.setFont(0, font)
                group.setForeground(0, QColor('#74694f'))
                groups[entry['category']] = group
            item = QTreeWidgetItem(groups[entry['category']], [entry['title']])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, entry['path'])
        self.summary.setText(f'{len(self.entries)} materials · local, read-only library')
        if keep_path:
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                for j in range(group.childCount()):
                    if self.entries[group.child(j).data(0, Qt.ItemDataRole.UserRole)]['path'] == keep_path:
                        self.tree.setCurrentItem(group.child(j))
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        needle = text.casefold().strip()
        first = None
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                item = group.child(j)
                entry = self.entries[item.data(0, Qt.ItemDataRole.UserRole)]
                item.setHidden(needle not in ' '.join(str(v) for v in entry.values()).casefold())
                if not item.isHidden() and first is None:
                    first = item
            group.setHidden(all(group.child(j).isHidden() for j in range(group.childCount())))
        current = self.tree.currentItem()
        if first is not None and (current is None or current.isHidden()):
            self.tree.setCurrentItem(first)
        if first is None:
            self.current = None
            self.info.setText('No matching materials.')
            self.integrity.clear()
            self.preview.clear()
            self.open_button.setEnabled(False)

    def _selected(self, item, previous=None) -> None:
        index = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(index, int):
            return
        entry = self.entries[index]
        self.current = entry
        source = ''
        url = entry.get('url', '')
        parsed = urlparse(url)
        if parsed.scheme == 'https' and not parsed.username and not parsed.password and parsed.hostname in (
            'archive.org', 'arxiv.org', 'platform.claude.com', 'docs.anthropic.com',
            'developers.openai.com', 'platform.openai.com', 'learn.chatgpt.com',
            'ai.google.dev', 'aistudio.google.com', 'docs.cloud.google.com', 'cloud.google.com', 'docs.x.ai', 'huggingface.co',
            'docs.mistral.ai', 'docs.z.ai',
        ):
            source = f'<br><a href="{escape(url, quote=True)}">Original source ↗</a>'
        self.info.setText(f'<b>{escape(entry["title"])}</b><br>{escape(entry["use"])}<br>'
                          f'<span style="color:#8a7d60">{escape(entry["path"])}<br>{escape(entry.get("reference", ""))}</span>{source}')
        metadata, content = read_material(self.root, entry)
        self.integrity.setText(metadata)
        self.preview.setPlainText(content)
        self.open_button.setEnabled(safe_path(self.root, entry['path']).is_file())
        self.open_button.setText('Open file' if Path(entry['path']).suffix.lower() in ('.pdf', '.md', '.txt', '.json') else 'Open folder')

    def _open(self) -> None:
        if self.current:
            path = safe_path(self.root, self.current['path'])
            if path.is_file():
                target = path if path.suffix.lower() in ('.pdf', '.md', '.txt', '.json') else path.parent
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
