"""Prompta controls: the dropdown, technique cards and the variant-count selector."""

from __future__ import annotations

from html import escape
from urllib.parse import urlparse


from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QIcon, QLinearGradient, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from theme import ROOT

from widgets import POPUP_MARGIN, RoundedPopupBorder, use_step_scroll


CATEGORY_LABELS = {
    "context": "Context and framing",
    "reasoning": "Reasoning",
    "thought_generation": "Thought generation",
    "decomposition": "Decomposition",
    "icl": "Examples (ICL)",
    "zero_shot_boost": "Zero-shot enhancement",
    "ensembling": "Ensembles",
    "self_critique": "Self-critique",
    "optimization": "Prompt optimization",
    "answer_engineering": "Answer extraction",
    "agents": "Agents",
    "rag": "RAG",
    "automation": "Automation and code",
    "pedagogy": "Teaching",
    "procedure": "Procedures",
    "security": "Security",
    "generation_config": "Settings",
}


class TechniqueItem(QFrame):
    clicked = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)

    def __init__(
        self, key: str, name: str, hint: str = "", sources: list | None = None, deletable: bool = False
    ) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("techItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)  # same as a list-row padding
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(name)
        title.setObjectName("techName")
        title.setWordWrap(True)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        self.sources = [source for source in (sources or []) if self._valid_source(source)]
        if self.sources:
            article = QPushButton()
            article.setObjectName("articleLink")
            article.setIcon(QIcon(str(ROOT / "desktop" / "external-link.svg")))
            article.setIconSize(QSize(14, 14))
            article.setFixedSize(20, 20)
            article.setAccessibleName(f"Sources for {name}")
            article.setToolTip("Read the source article\n" + "\n".join(s['title'] for s in self.sources))
            article.clicked.connect(lambda: self._show_sources(name))
            title_row.addWidget(article, 0, Qt.AlignmentFlag.AlignTop)
        if deletable:  # e.g. history rows: the same cross as elsewhere in the app
            remove = QPushButton()
            remove.setObjectName("deleteItem")
            remove.setIcon(QIcon(str(ROOT / "desktop" / "close.svg")))
            remove.setIconSize(QSize(10, 10))
            remove.setFixedSize(22, 22)
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setToolTip("Delete")
            remove.setAccessibleName(f"Delete {name}")
            remove.clicked.connect(lambda: self.deleteRequested.emit(self.key))
            title_row.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        if hint:
            note = QLabel(hint)
            note.setObjectName("techHint")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.key)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def _valid_source(source: object) -> bool:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            return False
        url = urlparse(source["url"])
        return (
            url.scheme == "https"
            and url.hostname in ("archive.org", "arxiv.org")
            and not url.username
            and not url.password
            and bool(source.get("title"))
        )

    def _show_sources(self, name: str) -> None:
        dialog = QDialog(QApplication.activeWindow())
        dialog.setWindowTitle(f"{name} — sources")
        dialog.setMinimumWidth(560)  # room for the source descriptions
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        # Descriptions make the list long: it scrolls, the Done button stays in view.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("clearScroll")
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(12)
        scroll.setWidget(holder)
        use_step_scroll(scroll)
        outer.addWidget(scroll, 1)
        for source in self.sources:
            block = QVBoxLayout()
            block.setSpacing(4)
            label = QLabel(
                f'<a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a><br>'
                f'<span style="color: #7b8799">{escape(source.get("reference", ""))}</span>'
            )
            label.setWordWrap(True)
            label.setOpenExternalLinks(True)
            block.addWidget(label)
            if source.get("summary"):  # 3-4 sentences: the abstract's claim, or the cited passage
                about = QLabel(source["summary"])
                about.setObjectName("sourceSummary")
                about.setWordWrap(True)
                about.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                block.addWidget(about)
            layout.addLayout(block)
        layout.addStretch(1)
        close = QPushButton("Done")
        close.setObjectName("ghost")
        close.clicked.connect(dialog.accept)
        outer.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        width = 600
        content_width = width - outer.contentsMargins().left() - outer.contentsMargins().right()
        chrome_height = (
            outer.contentsMargins().top()
            + outer.contentsMargins().bottom()
            + outer.spacing()
            + close.sizeHint().height()
        )
        dialog.resize(width, min(640, layout.totalHeightForWidth(content_width) + chrome_height))
        dialog.exec()


class Dropdown(QPushButton):
    """One dropdown for everything: one panel for provider, model, variants and techniques.

    Supports one or two columns, category headers, hints and search within the list.
    """

    changed = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)  # a row's cross, for lists with "deletable" items

    def __init__(
        self,
        placeholder: str = "—",
        columns: int = 1,
        searchable: bool = False,
        popup_width: int = 380,
        search_placeholder: str = "Filter",
    ) -> None:
        super().__init__(placeholder)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("picker")
        self._placeholder = placeholder
        self._items: list[dict] = []
        self._current = ""
        self._columns = columns
        self._searchable = searchable
        self._popup_width = popup_width
        self._search_placeholder = search_placeholder
        self._popup: QFrame | None = None
        self._multi = False
        self._selected: list[str] = []
        self._item_widgets: dict[str, TechniqueItem] = {}
        self._align_right = False  # icon pickers at the right edge open their panel leftwards
        self.clicked.connect(self._open)
        # Every picker shows it opens a list: one chevron at the right edge (text keeps clear of it via padding).
        chevron = QLabel()
        chevron.setObjectName("pickerChevron")
        chevron.setPixmap(QIcon(str(ROOT / "desktop" / "chevron-down.svg")).pixmap(12, 12))
        chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chevron_row = QHBoxLayout(self)
        chevron_row.setContentsMargins(0, 0, 10, 0)
        chevron_row.addStretch(1)
        chevron_row.addWidget(chevron, 0, Qt.AlignmentFlag.AlignVCenter)

    # ── data ─────────────────────────────────────────────────────
    def set_multi(self, multi: bool) -> None:
        """Multi mode: clicks toggle items and the panel stays open. Items with status
        "procedure" are exclusive: they cannot be combined with anything else."""
        self._multi = multi
        self._selected = [self._current] if multi and self._current else []

    def set_items(self, items: list[dict], keep: str = "") -> None:
        self._items = items
        if self._multi:
            known = {item.get("key") for item in items}
            self.set_current_keys([key for key in self._selected if key in known])
            return
        want = keep or self._current
        if want and any(item.get("key") == want for item in items):
            self.set_current(want)

    def current_key(self) -> str:
        return self._current

    def current_keys(self) -> list[str]:
        if self._multi:
            return list(self._selected)
        return [self._current] if self._current else []

    def _label(self, key: str) -> str:
        item = next((i for i in self._items if i.get("key") == key), None)
        return (item.get("label") or item.get("name") or key) if item else key

    def set_current(self, key: str, emit: bool = False) -> None:
        if self._multi:
            self.set_current_keys([key] if key else [], emit)
            return
        self._current = key
        self.setText(self._label(key) if key else self._placeholder)
        if emit:
            self.changed.emit(key)

    def set_current_keys(self, keys: list[str], emit: bool = False) -> None:
        self._selected = list(dict.fromkeys(k for k in keys if k))
        self._current = self._selected[0] if self._selected else ""
        if not self._selected:
            text = self._placeholder
        elif len(self._selected) == 1:
            text = self._label(self._current)
        else:
            text = f"{len(self._selected)} techniques: " + ", ".join(self._label(k) for k in self._selected)
        self.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(120, self.width() - 28)))
        self.setToolTip("\n".join(self._label(k) for k in self._selected))
        for key, widget in self._item_widgets.items():
            widget.set_selected(key in self._selected)
        if self._popup is not None and hasattr(self, "_selection_label"):
            self._selection_label.setText(
                f"{len(self._selected)} selected" if self._selected else "Click techniques to select"
            )
            self._update_select_all()
        if emit:
            self.changed.emit(self._current)

    def _is_procedure(self, key: str) -> bool:
        return any(i.get("key") == key and i.get("status") == "procedure" for i in self._items)

    def _selectable_keys(self) -> list[str]:
        """Techniques that "Select all" covers: shown by the current filter, procedures excluded."""
        return [
            key for key, widget in self._item_widgets.items() if not widget.isHidden() and not self._is_procedure(key)
        ]

    def _all_selected(self) -> bool:
        keys = self._selectable_keys()
        return bool(keys) and all(key in self._selected for key in keys)

    def _update_select_all(self) -> None:
        if button := getattr(self, "_select_all_button", None):
            button.setText("Deselect all" if self._all_selected() else "Select all")
            button.setEnabled(bool(self._selectable_keys()))

    def _toggle_select_all(self) -> None:
        keys = self._selectable_keys()
        if self._all_selected():
            remaining = [k for k in self._selected if k not in keys]
        else:
            remaining = [k for k in self._selected if not self._is_procedure(k)] + [
                k for k in keys if k not in self._selected
            ]
        self.set_current_keys(remaining, emit=True)

    def _toggle(self, key: str) -> None:
        if key in self._selected:
            keys = [k for k in self._selected if k != key]
        elif self._is_procedure(key):
            keys = [key]
        else:
            keys = [k for k in self._selected if not self._is_procedure(k)] + [key]
        self.set_current_keys(keys, emit=True)

    # ── panel ────────────────────────────────────────────────────
    def _open(self) -> None:
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.rounded_border = RoundedPopupBorder(popup)  # type: ignore[attr-defined]  # keeps it alive
        popup.setObjectName("techniquePopup")
        self._popup = popup

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN, POPUP_MARGIN)
        outer.setSpacing(8)

        search: QLineEdit | None = None
        if self._searchable:
            search = QLineEdit()
            search.setPlaceholderText(self._search_placeholder)
            search.setClearButtonEnabled(True)
            search.setObjectName("listSearch")  # app.qss: the window style's min-height 0 collapsed it to a line
            outer.addWidget(search)

        scroll = QScrollArea(popup)
        use_step_scroll(scroll)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("scrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        entries: list[tuple[TechniqueItem, str]] = []
        headers: list[tuple[QLabel, list[TechniqueItem]]] = []
        self._item_widgets = {}

        grouped: dict[str, list[dict]] = {}
        for item in self._items:
            grouped.setdefault(item.get("category") or "", []).append(item)

        multi_group = any(key for key in grouped)

        for category, items in grouped.items():
            if multi_group:
                header = QLabel(CATEGORY_LABELS.get(category, category).upper() if category else "GENERAL")
                header.setObjectName("catHeader")
                header.setContentsMargins(10, 6, 10, 2)
                body.addWidget(header)

            grid = QGridLayout()
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(1)
            grid_items: list[TechniqueItem] = []
            for index, item in enumerate(items):
                label = item.get("label") or item.get("name") or item["key"]
                widget = TechniqueItem(
                    item["key"], label, item.get("hint", ""), item.get("sources"), bool(item.get("deletable"))
                )
                widget.deleteRequested.connect(self.deleteRequested.emit)
                widget.clicked.connect(self._toggle if self._multi else self._choose)
                self._item_widgets[item["key"]] = widget
                widget.set_selected(item["key"] in self.current_keys())  # single mode marks the current one too
                grid.addWidget(widget, index // self._columns, index % self._columns)
                entries.append((widget, f"{label} {item.get('hint', '')} {category} {item.get('search', '')}".lower()))
                grid_items.append(widget)
            for column in range(self._columns):
                grid.setColumnStretch(column, 1)
            body.addLayout(grid)
            if multi_group:
                headers.append((header, grid_items))

        body.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        if self._multi:
            footer = QHBoxLayout()
            self._selection_label = QLabel()
            self._selection_label.setObjectName("muted")
            footer.addWidget(self._selection_label, 1)
            self._select_all_button = QPushButton("Select all")
            self._select_all_button.setObjectName("ghost")
            self._select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._select_all_button.setToolTip(
                "Select every technique shown (procedures excluded); click again to deselect"
            )
            self._select_all_button.clicked.connect(self._toggle_select_all)
            footer.addWidget(self._select_all_button)
            clear = QPushButton("Clear")
            clear.setObjectName("ghost")
            clear.setCursor(Qt.CursorShape.PointingHandCursor)
            clear.clicked.connect(lambda: self.set_current_keys([], emit=True))
            footer.addWidget(clear)
            done = QPushButton("Done")
            done.setObjectName("primary")
            done.setCursor(Qt.CursorShape.PointingHandCursor)
            done.clicked.connect(popup.close)
            footer.addWidget(done)
            outer.addLayout(footer)
            self.set_current_keys(self._selected)

        def apply_filter(text: str) -> None:
            needle = text.strip().lower()
            for widget, haystack in entries:
                widget.setVisible(needle in haystack)
            for header, grid_items in headers:
                header.setVisible(any(not w.isHidden() for w in grid_items))
            self._update_select_all()

        if search is not None:
            search.textChanged.connect(apply_filter)

        # Height follows the content: an empty full-screen panel looks sloppy.
        width = min(self._popup_width, self.screen().availableGeometry().width() - 24)
        body.activate()
        height = content.heightForWidth(width - 2 * POPUP_MARGIN) if content.hasHeightForWidth() else -1
        # The size hint is measured at the natural (narrow) width, where wrapped hints run tall: trust the real width.
        height = (height if height > 0 else content.sizeHint().height()) + 2 * POPUP_MARGIN + 2
        if self._searchable:
            height += search.sizeHint().height() + outer.spacing()
        if self._multi:
            height += 44
        available = self.screen().availableGeometry()
        popup.resize(
            min(self._popup_width, available.width() - 24), min(560, max(120, height), available.height() - 24)
        )
        position = self.mapToGlobal(QPoint(self.width() - popup.width() if self._align_right else 0, self.height() + 6))
        if position.y() + popup.height() > available.bottom() - 12:
            above = self.mapToGlobal(QPoint(0, -popup.height() - 6)).y()
            position.setY(max(available.top() + 12, above))
        position.setX(max(available.left() + 12, min(position.x(), available.right() - popup.width() - 12)))
        popup.move(position)
        popup.show()
        if search is not None:
            search.setFocus()

    def _choose(self, key: str) -> None:
        self.set_current(key, emit=True)
        if self._popup is not None:
            self._popup.close()


class IconDropdown(Dropdown):
    """A picker shown as a toolbar icon: the same panel as every dropdown, no label or chevron on the button."""

    def __init__(self, icon: str, tooltip: str, **options) -> None:
        super().__init__("", **options)
        self.setObjectName("settings")  # the toolbar icon style, like trash and settings
        self.setIcon(QIcon(str(ROOT / "desktop" / icon)))
        self.setIconSize(QSize(17, 17))
        self.setFixedSize(28, 28)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self._align_right = True
        chevron = self.findChild(QLabel, "pickerChevron")
        if chevron is not None:
            chevron.hide()

    def set_current(self, key: str, emit: bool = False) -> None:
        super().set_current(key, emit)
        self.setText("")  # an icon, never a label


class ExecutionProfileDropdown(Dropdown):
    """Where the finished prompt runs. Each choice says what it means; an agent is assumed to have every tool."""

    AGENT_CAPABILITIES = ("code", "files", "integrations", "web")

    def __init__(self) -> None:
        super().__init__("— any chat —", popup_width=300)
        self.set_items(
            [
                {"key": "universal", "label": "— any chat —", "hint": "Unknown environment"},
                {"key": "web", "label": "Chat with web access", "hint": "Web search and opening links"},
                {"key": "local", "label": "Local model, no tools", "hint": "Only what is in the prompt"},
                {"key": "agent", "label": "Agent with tools", "hint": "Web, files, code and integrations"},
            ],
            keep="universal",
        )


class BackgroundWidget(QWidget):
    """The photo under a cream veil. `veil` is the veil's alpha at the left and right edges:
    higher = fainter photo. The main window keeps it faint; About lets it show on the right."""

    def __init__(self, veil: tuple[int, int] = (242, 242)) -> None:
        super().__init__()
        self.image = QPixmap(str(ROOT / "desktop/background.png"))
        self.veil = veil

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if not self.image.isNull():
            image = self.image.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap((self.width() - image.width()) // 2, (self.height() - image.height()) // 2, image)
            left, right = self.veil
            if left == right:
                painter.fillRect(self.rect(), QColor(255, 248, 222, left))
            else:
                gradient = QLinearGradient(0, 0, self.width(), 0)
                gradient.setColorAt(0.0, QColor(255, 248, 222, left))
                gradient.setColorAt(0.45, QColor(255, 248, 222, left))  # text column stays readable
                gradient.setColorAt(1.0, QColor(255, 248, 222, right))
                painter.fillRect(self.rect(), gradient)
        else:
            painter.fillRect(self.rect(), QColor("#f5f6f8"))


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")

    def vbox(self) -> QVBoxLayout:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)
        return layout


class VariantSelector(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("variantCount")
        self.setAccessibleName("Number of prompt variants")
        self.setFixedSize(184, 36)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.buttons = QButtonGroup(self)
        self.buttons.setExclusive(True)
        for count in range(1, 6):
            button = QPushButton(str(count))
            button.setObjectName("variantOption")
            button.setFixedHeight(28)
            button.setCheckable(True)
            button.setAccessibleName(f"{count} prompt variant{'s' if count > 1 else ''}")
            button.setToolTip(button.accessibleName())
            self.buttons.addButton(button, count)
            row.addWidget(button, 1)
        self.setValue(1)

    def value(self) -> int:
        return self.buttons.checkedId()

    def setValue(self, value: int) -> None:
        self.buttons.button(max(1, min(5, value))).setChecked(True)
