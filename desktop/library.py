"""Read-only inventory of the sources Prompta builds prompts from."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


CATEGORY_TITLES = {
    "context": "Context and framing", "reasoning": "Reasoning", "thought_generation": "Thought generation",
    "decomposition": "Decomposition", "icl": "Examples", "zero_shot_boost": "Zero-shot boosts", "ensembling": "Ensembles",
    "self_critique": "Self-critique", "optimization": "Prompt optimization", "answer_engineering": "Answer extraction",
    "agents": "Agents", "rag": "Retrieval", "automation": "Automation and code", "pedagogy": "Teaching",
    "procedure": "Procedures", "security": "Security",
}
OFFICIAL_TARGETS = [("claude_prompt_rules", "Claude", "Anthropic"), ("chatgpt_prompt_rules", "ChatGPT", "OpenAI"),
                    ("gemini_prompt_rules", "Gemini", "Google"), ("grok_prompt_rules", "Grok", "xAI"),
                    ("hermes_agent_prompt_guides", "Hermes Agent", "Nous Research")]


def _ts_object(text: str, name: str) -> dict:
    """The JSON object literal assigned to `name` in a generated .ts file ({} when absent)."""
    match = re.search(r'export const ' + name + r'[^=]*=\s*', text)
    if not match:
        return {}
    start = match.end()
    end = text.rfind('};')
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}


def _ts_strings(text: str, name: str) -> dict:
    """key: 'value' pairs of a hand-written string map in a .ts file."""
    block = re.search(r'export const ' + name + r'[^{]*\{(.*?)\n\};', text, re.S)
    if not block:
        return {}
    return {key: value.replace("\\'", "'") for key, value in re.findall(r"^\s*(\w+):\s*'((?:[^'\\]|\\.)*)',?\s*$", block.group(1), re.M)}


def _technique_page(technique: dict, hint: str, sources: dict) -> str:
    lines = [technique['name'], '']
    if hint:
        lines += ['When to use', hint, '']
    if technique.get('when_to_use'):
        lines += ['How it helps', technique['when_to_use'], '']
    if technique.get('when_not'):
        lines += ['When it hurts', technique['when_not'], '']
    if technique.get('template'):
        lines += ['Prompt skeleton', technique['template'], '']
    if technique.get('procedure'):
        lines += ['Steps'] + [f'{i}. {step}' for i, step in enumerate(technique['procedure'], 1)] + ['']
    if technique.get('example'):
        lines += ['Example', technique['example'], '']
    for excerpt in sources.get('excerpts', []):
        lines += [f"From the sources · {excerpt['source']} ({excerpt['ref']})", excerpt['text'].strip(), '']
    if sources.get('paper'):
        lines += ['Original paper', sources['paper'], '']
    return '\n'.join(lines).strip() + '\n'


def _rules_page(label: str, organization: str, data: dict) -> str:
    rules = [rule for rule in data.get('rules', []) if rule.get('status') == 'active']
    lines = [f'{label} · official {organization} prompting rules', f"Checked {data.get('verified_at', 'unknown')} · {len(rules)} rules", '']
    for rule in rules:
        lines.append(f"{rule.get('id')} — {rule.get('rule_text', '').strip()}")
        condition = rule.get('condition', 'always')
        lines.append(f"  Applies: {'always' if condition == 'always' else condition}")
        if rule.get('source_url'):
            lines.append(f"  Source: {rule.get('source_section', 'section')} · {rule['source_url']}")
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def library_entries(root: Path) -> list[dict]:
    """Only what prompts are built from, in readable form: techniques, official rules, open-model cards.
    Snapshots, registries, licences, scripts, PDFs and code are not prompt material and stay in the repository."""
    entries: list[dict] = []

    def add(category: str, title: str, relative: str, use: str, **metadata) -> None:
        if (root / relative).is_file():
            entries.append(dict(category=category, title=title, path=relative, use=use, **metadata))

    try:
        catalog = json.loads((root / 'catalog/catalog.json').read_text(encoding='utf-8'))
        display = (root / 'catalog/display.en.ts').read_text(encoding='utf-8')
        excerpts = _ts_object((root / 'catalog/source-excerpts.ts').read_text(encoding='utf-8'), 'sourceExcerpts')
    except (OSError, ValueError):
        catalog, display, excerpts = {'techniques': []}, '', {}
    hints, names = _ts_strings(display, 'hints'), _ts_strings(display, 'names')
    usable = [t for t in catalog.get('techniques', []) if t.get('status') in ('ready', 'procedure')
              and t.get('kind') in ('technique', 'prompt_type', 'procedure')]
    for technique in sorted(usable, key=lambda t: (CATEGORY_TITLES.get(t.get('category'), 'Other'), names.get(t['key'], t['name']).casefold())):
        technique = {**technique, 'name': names.get(technique['key'], technique['name'])}
        hint = hints.get(technique['key'], '')
        add('Techniques · ' + CATEGORY_TITLES.get(technique.get('category'), 'Other'), technique['name'], 'catalog/catalog.json',
            hint or 'Prompting technique from the catalog.', content=_technique_page(technique, hint, excerpts.get(technique['key'], {})),
            catalog_version=catalog.get('version', ''))

    for folder, label, organization in OFFICIAL_TARGETS:
        try:
            data = json.loads((root / folder / 'rules.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        add('Official rules', label, f'{folder}/rules.json',
            f'The rules used when the prompt is written for {label}.', content=_rules_page(label, organization, data),
            checked=data.get('verified_at', ''))

    try:
        manifest = json.loads((root / 'open_model_prompt_guides/manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {'models': []}
    for model in sorted(manifest.get('models', []), key=lambda m: m['name'].casefold()):
        card = next((f for f in model.get('files', []) if f.get('snapshot') == f"{model['id']}/README.md"), None)
        if card:
            add('Open-weight models', model['name'], 'open_model_prompt_guides/' + card['snapshot'],
                'Official model card, used in full when the prompt is written for this model.',
                url=card.get('url') or model.get('url'), expected_hash=card.get('sha256'))
    return entries


def read_material(root: Path, entry: dict) -> tuple[str, str]:
    if entry.get('content') is not None:  # a readable page built from the data the pipeline uses
        details = [f"Built from {entry['path']}"]
        if entry.get('catalog_version'):
            details.append(f"catalog {entry['catalog_version']}")
        if entry.get('checked'):
            details.append(f"checked {entry['checked']}")
        return ' · '.join(details), entry['content']
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

try:
    from .settings_ui import LABEL_GAP, LIST_GAP, PAGE_TOP, SECTION_GAP, muted
    from .theme import ROOT
except ImportError:
    from settings_ui import LABEL_GAP, LIST_GAP, PAGE_TOP, SECTION_GAP, muted
    from theme import ROOT

RULE_SETS = (("Claude", "claude_prompt_rules"), ("ChatGPT", "chatgpt_prompt_rules"),
             ("Gemini", "gemini_prompt_rules"), ("Grok", "grok_prompt_rules"),
             ("Hermes", "hermes_agent_prompt_guides"))


def data_versions(root: Path) -> list[tuple[str, str]]:
    """What results are built from, read from the bundled files; a missing file reads 'unavailable'."""
    rows = []
    try:
        catalog = json.loads((root / "catalog/catalog.json").read_text(encoding="utf-8"))
        rows.append(("Technique catalog", f"{catalog['version']} · {len(catalog['techniques'])} entries"))
    except (OSError, ValueError, KeyError, TypeError):
        rows.append(("Technique catalog", "unavailable"))
    for label, folder in RULE_SETS:
        try:
            bundle = json.loads((root / folder / "rules.json").read_text(encoding="utf-8"))
            rows.append((f"{label} guidance", f"{len(bundle['rules'])} rules · checked {bundle['verified_at']}"))
        except (OSError, ValueError, KeyError, TypeError):
            rows.append((f"{label} guidance", "unavailable"))
    try:
        match = re.search(r"PROMPT_SET = '([^']+)'", (root / "pipeline/prompt-version.ts").read_text(encoding="utf-8"))
        rows.append(("Pipeline prompts", match.group(1) if match else "unavailable"))
    except OSError:
        rows.append(("Pipeline prompts", "unavailable"))
    return rows


class LibraryWidget(QWidget):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.entries: list[dict] = []
        self.current: dict | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, PAGE_TOP, 0, 0)  # the shared Settings look (settings_ui.py)
        outer.setSpacing(0)
        outer.addWidget(muted('What Prompta builds prompts from: the prompting techniques, the official rules for each '
                              'model and the open-weight model cards.'))
        outer.addSpacing(SECTION_GAP)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)  # same gap as the model field and its refresh button
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a technique, rule or model')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('Search library')
        # Lay out by the visible box, not the macOS focus-ring margins, so it lines up with the refresh square.
        self.search.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1, Qt.AlignmentFlag.AlignVCenter)
        refresh = QPushButton()
        refresh.setObjectName('ghost')
        refresh.setIcon(QIcon(str(ROOT / 'desktop' / 'refresh.svg')))
        refresh.setIconSize(QSize(15, 15))
        refresh.setFixedSize(28, 28)  # same square as the model refresh button and as tall as the search field
        refresh.setToolTip('Refresh library')
        refresh.setAccessibleName('Refresh library')
        refresh.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)  # a macOS push button pads its layout box too
        refresh.clicked.connect(self.reload)
        search_row.addWidget(refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(search_row)
        outer.addSpacing(LIST_GAP)
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
        self.summary = muted()  # the Settings dialog places it on its bottom row, next to Done
        self.summary.setWordWrap(False)

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
            # Official rules carry the date they were last checked; a second column would squeeze the technique names.
            title = f"{entry['title']}  ·  {entry['checked']}" if entry.get('checked') else entry['title']
            item = QTreeWidgetItem(groups[entry['category']], [title])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, entry['path'])
        versions = dict(data_versions(self.root))
        catalog = versions.get('Technique catalog', '').split(' · ')[0]
        self.summary.setText(f"{len(self.entries)} materials · catalog {catalog} · prompts {versions.get('Pipeline prompts', 'unavailable')}")
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
        where = '' if entry.get('content') is not None else f'<br><span style="color:#8a7d60">{escape(entry["path"])}</span>'
        self.info.setText(f'<b>{escape(entry["title"])}</b><br>{escape(entry["use"])}{where}{source}')
        metadata, content = read_material(self.root, entry)
        self.integrity.setText(metadata)
        self.preview.setPlainText(content)
        self.open_button.setVisible(entry.get('content') is None)  # a built page has no file of its own to open
        self.open_button.setEnabled(safe_path(self.root, entry['path']).is_file())
        self.open_button.setText('Open file' if Path(entry['path']).suffix.lower() in ('.pdf', '.md', '.txt', '.json') else 'Open folder')

    def _open(self) -> None:
        if self.current:
            path = safe_path(self.root, self.current['path'])
            if path.is_file():
                target = path if path.suffix.lower() in ('.pdf', '.md', '.txt', '.json') else path.parent
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
