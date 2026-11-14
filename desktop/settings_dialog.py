"""The Settings dialog: a title, one tab per page, and a Done row that carries the open page's footer.

Pages are added from outside with what the dialog needs to know about each: its footer, what to refresh when
it is shown, which field takes the focus on open, and whether the window's photo shows behind it (About).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from controls import BackgroundWidget, Dropdown
from result_view import CONTROL_HEIGHT
from settings_ui import SECTION_GAP
from widgets import title_font


@dataclass
class _Page:
    footer: QWidget | None
    on_show: Callable[[], None] | None
    focus: QWidget | None
    backdrop: bool


def fit_controls(root: QWidget) -> None:
    """One control height for every field, picker and action button, as in the main window."""
    for child in [root, *root.findChildren(QWidget)]:
        if (
            (isinstance(child, QLineEdit) and not isinstance(child.parentWidget(), QComboBox))
            or isinstance(child, (QComboBox, Dropdown))
            or (isinstance(child, QPushButton) and child.objectName() in ("ghost", "primary"))
        ):
            child.ensurePolished()  # a later first polish would reset the minimum height from the stylesheet
            child.setFixedHeight(CONTROL_HEIGHT)


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.resize(860, 640)
        self._pages: list[_Page] = []
        self._footers = 0  # footers stand left on the Done row, before its stretch
        # About shows the window's photo over the whole dialog, clearly visible: the veil thins out to the right.
        self.backdrop = BackgroundWidget(veil=(236, 120))
        self.backdrop.setParent(self)
        self.backdrop.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)
        title = QLabel("SETTINGS")
        title.setObjectName("title")  # same face as the main window header, spaced capitals (app.qss)
        title.setAccessibleName("Settings")
        title.setFont(title_font())
        outer.addWidget(title)
        self.tabs = QTabWidget()
        self.setObjectName("settingsDialog")
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setAccessibleName("Settings sections")
        bar = self.tabs.tabBar()
        assert bar is not None
        bar.setDrawBase(False)
        bar.setExpanding(False)
        bar.setElideMode(Qt.TextElideMode.ElideNone)
        bar.setUsesScrollButtons(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        outer.addWidget(self.tabs, 1)
        outer.addSpacing(SECTION_GAP - outer.spacing())  # the Done row stands apart like a section
        self._actions = QHBoxLayout()
        self._actions.addStretch(1)
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("primary")
        self.done_button.clicked.connect(self.accept)
        self._actions.addWidget(self.done_button)
        fit_controls(self.done_button)
        outer.addLayout(self._actions)

    def add_page(
        self,
        page: QWidget,
        title: str,
        *,
        footer: QWidget | None = None,
        on_show: Callable[[], None] | None = None,
        focus: QWidget | None = None,
        backdrop: bool = False,
    ) -> None:
        """`footer` sits on the Done row while the page is open; `on_show` runs on open and on switching to it."""
        fit_controls(page)
        if footer is not None:
            fit_controls(footer)
            self._actions.insertWidget(self._footers, footer, 0, Qt.AlignmentFlag.AlignVCenter)
            self._footers += 1
        self._pages.append(_Page(footer, on_show, focus, backdrop))
        self.tabs.addTab(page, title)
        self._sync_footer(self.tabs.currentIndex())

    def open(self) -> None:
        super().open()
        page = self._page(self.tabs.currentIndex())
        if page is not None:
            if page.on_show is not None:
                page.on_show()
            if page.focus is not None:
                page.focus.setFocus()

    def _page(self, index: int) -> _Page | None:
        return self._pages[index] if 0 <= index < len(self._pages) else None

    def _tab_changed(self, index: int) -> None:
        self._sync_footer(index)
        page = self._page(index)
        if page is not None and page.on_show is not None:
            page.on_show()

    def _sync_footer(self, index: int) -> None:
        """The Done row carries the open tab's footer: Library's summary, MCP's copy link,
        History's delete link, About's links and credits."""
        for position, page in enumerate(self._pages):
            if page.footer is not None:
                page.footer.setVisible(position == index)
        current = self._page(index)
        self.backdrop.setVisible(current is not None and current.backdrop)
        self.backdrop.setGeometry(self.rect())
        self.backdrop.lower()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.backdrop.setGeometry(self.rect())  # the About photo covers the whole dialog
