"""One look for every Settings tab.

Type scale: section labels are 10 px caps (#74694f); values, list rows and controls are 13 px (#4a4232);
intros, hints and descriptions are 12 px grey (#665d49); links are 13 px gold, never underlined.

A tab is: a one-line intro, then sections. A section is a small caps label, its controls and an optional
grey hint, always with the same gaps. Lists sit straight on the dialog, without a plate. Actions are text links; a destructive one is
rust-coloured. Build tabs with these helpers instead of spacing widgets by hand.
"""
from __future__ import annotations


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget

PAGE_TOP = 18      # air under the tab bar
SECTION_GAP = 28   # between sections
LABEL_GAP = 6      # label → control
HINT_GAP = 8       # control → its grey hint
LIST_GAP = 14      # search field → the list it filters

# Rich-text links (About) look like the link buttons: gold, medium weight, no underline.
LINK_STYLE = 'style="color:#806a3d; font-weight:500; text-decoration:none;"'


def field_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("fieldLabel")
    return label


def body(text: str = "") -> QLabel:
    """A value or a statement the reader acts on: regular text colour, 13 px."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def text_link(text: str, danger: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("textLink")
    button.setFlat(True)
    if danger:
        button.setProperty("danger", True)  # red link in app.qss
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("settingsCard")
    return frame


def settings_page(intro: str = "", right_margin: int = 0, page: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
    """A tab body with the standard top gap and its intro line; `page` lets a tab bring its own painted widget."""
    page = page or QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, PAGE_TOP, right_margin, 0)
    layout.setSpacing(0)
    if intro:
        layout.addWidget(muted(intro))
    return page, layout


def add_section(layout: QVBoxLayout, label: str | QLabel | QLayout | None, *items, hint: str | QLabel | None = None,
                stretch_last: bool = False) -> None:
    """Label, controls, hint — with the shared gaps. `label` may be a ready layout that already holds its label."""
    if layout.count():
        layout.addSpacing(SECTION_GAP)
    if isinstance(label, QLayout):
        layout.addLayout(label)
    elif label is not None:
        layout.addWidget(field_label(label) if isinstance(label, str) else label)
    for index, item in enumerate(items):
        if label is not None or index:
            layout.addSpacing(LABEL_GAP)
        stretch = 1 if stretch_last and index == len(items) - 1 else 0
        if isinstance(item, QLayout):
            layout.addLayout(item, stretch)
        elif isinstance(item, QPushButton) and item.objectName() == "textLink":
            layout.addWidget(item, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            layout.addWidget(item, stretch)
    if hint is not None:
        layout.addSpacing(HINT_GAP)
        layout.addWidget(muted(hint) if isinstance(hint, str) else hint)

