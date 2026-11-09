"""Константы оформления и целей Prompta: стили Qt, адреса чатов, цели промптов."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROMPT_TARGETS = {
    "claude": ("Claude", ("platform.claude.com",)),
    "chatgpt": ("ChatGPT", ("developers.openai.com", "platform.openai.com", "learn.chatgpt.com")),
    "gemini": ("Gemini", ("ai.google.dev", "aistudio.google.com", "docs.cloud.google.com", "cloud.google.com")),
    "grok": ("Grok", ("docs.x.ai",)),
    "openModel": ("Open-weight model", ("huggingface.co",)),
}


CHAT_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
    "grok": "https://grok.com/",
}


QSS = """
QWidget { font-family: 'Helvetica Neue'; font-size: 13px; color: #4a4232; }
QMainWindow { background: #f5f6f8; }
QWidget#root { background: transparent; }
QDialog { background: #fff8e7; }
QPushButton#settings { background: transparent; border: 1px solid transparent; border-radius: 9px; }
QPushButton#settings:hover { background: #e7edf5; border-color: #d8c593; }
QPushButton#settings:pressed { background: #f2eddc; }
QPushButton#settings:focus { border-color: #c69b12; }
QFrame#tech { background: transparent; border: none; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #f2e6c5; color: #74839a; padding: 8px 18px; margin-right: 5px; border: 1px solid #dfcfa6; border-radius: 7px; }
QTabBar::tab:selected { background: #fffbed; color: #6f5710; border-color: #efe3b9; }
QTreeWidget#libraryTree { background: #fffdf5; border: 1px solid #d8c593; border-radius: 9px; padding: 5px; outline: none; }
QTreeWidget#libraryTree::item { padding: 5px 2px; }
QTreeWidget#libraryTree::item:selected { background: #fffae9; color: #6f5710; }
QFrame#card { background: #fff8e7; border: 1px solid #d8c593; border-radius: 16px; }
QFrame#mainColumn { background: transparent; border: none; }
QScrollArea#outputScroll, QWidget#outputContent { background: transparent; border: none; }
QLabel#title { font-family: 'Avenir Next'; font-size: 17px; letter-spacing: -0.2px; color: #202632; }
QLabel#subtitle { color: #74694f; font-size: 13px; }
QLabel#section { font-weight: 600; color: #332e24; font-size: 13px; }
QLabel#fieldLabel { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; }
QLabel#muted { color: #665d49; font-size: 12px; }
QLabel#oneShotHint { color: #8a7d5c; font-size: 11px; }
QLabel#goal { font-size: 15px; font-weight: 600; color: #332e24; }
QLabel#chip { color: #5b6574; background: #f2e6c5; border: 1px solid #dfd0a8; border-radius: 8px; padding: 3px 8px; font-size: 11px; }
QLabel#warn { color: #8a5300; background: #fffaf0; border: 1px solid #f6e2bd; border-radius: 8px; padding: 8px 10px; font-size: 12px; }
QLabel#error { color: #b03a2e; background: #fff5f5; border: 1px solid #f5c2c2; border-radius: 8px; padding: 8px 10px; }
QLabel#status { color: #74694f; font-size: 12px; }
QPlainTextEdit { font-size: 13px; background: rgba(255, 248, 226, 232); border: 1px solid #d8c593; border-radius: 10px; padding: 10px; selection-background-color: #fff9e3; }
QPlainTextEdit:focus { border-color: #c69b12; }
QPlainTextEdit#prompt { padding: 10px; background: #454545; color: #f5f5f5; border: 1px solid #565656; font-family: 'Helvetica Neue'; font-size: 13px; selection-background-color: #675b32; selection-color: #ffffff; }
QLineEdit, QComboBox { font-size: 13px; background: rgba(255, 248, 226, 240); border: 1px solid #d8c593; border-radius: 8px; padding: 7px 10px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
  font-size: 13px; background: transparent; color: #4a4232; border: none; outline: none;
  selection-background-color: #fff9e3; selection-color: #6f5710;
}
QListWidget#historyList { background: #fff8e7; color: #4a4232; border: none; outline: none; font-size: 13px; }
QListWidget#historyList::item { padding: 7px 30px 7px 10px; border: none; border-radius: 5px; }
QListWidget#historyList::item:hover, QListWidget#historyList::item:selected { background: #f6e5b3; color: #4a4232; }
QFrame#variantCount { background: rgba(245, 231, 191, 225); border: 1px solid #d8c593; border-radius: 10px; }
QPushButton#variantOption { background: transparent; border: 1px solid transparent; border-radius: 7px; color: #827456; padding: 0; font-size: 13px; font-weight: 500; }
QPushButton#variantOption:hover { color: #34465f; background: #f4e4b7; }
QPushButton#variantOption:checked { background: #fff8e7; border-color: #d8c593; color: #6f5710; font-weight: 600; }
QPushButton#variantOption:focus { border-color: #c69b12; }
QCheckBox#targetOption { background: rgba(255, 245, 214, 222); border: 1px solid #d8c593; border-radius: 9px; padding: 9px 10px; spacing: 8px; color: #665b42; font-size: 12px; }
QCheckBox#targetOption:hover { background: #fff0c6; border-color: #ede6cc; }
QCheckBox#targetOption:checked { background: #fffbee; border-color: #f1e5ba; color: #6f5710; }
QCheckBox#targetOption:focus { border-color: #c69b12; }
QCheckBox#targetOption:disabled { color: #bab5a3; background: #fafbfc; border-color: #edf0f4; }
QFrame#inputDivider { background: rgba(151, 119, 40, 40); border: none; }
QLabel#variantsLabel { color: #665b42; font-size: 12px; font-weight: 500; }
QPushButton#buildPrompt { background: #f4ca38; color: #352b10; border: 1px solid #f4ca38; border-radius: 10px; padding: 0 18px; font-size: 13px; font-weight: 600; }
QPushButton#buildPrompt:hover { background: #e9bc24; border-color: #e9bc24; }
QPushButton#buildPrompt:pressed { background: #d9aa16; border-color: #d9aa16; }
QPushButton#buildPrompt:focus { border: 2px solid #fceaa9; }
QPushButton#buildPrompt:disabled { background: #e8cc72; color: #796225; border-color: #d8bc62; }
QPushButton#copyPrompt { background: transparent; border: none; border-radius: 6px; padding: 0; }
QPushButton#copyPrompt:hover { background: #575757; }
QPushButton#copyPrompt:pressed { background: #646464; }
QPushButton#copyPrompt:focus { border: 1px solid #c69b12; }
QPushButton#articleLink { background: transparent; border: none; border-radius: 5px; padding: 0; }
QPushButton#articleLink:hover { background: #f8f4e7; }
QPushButton#articleLink:focus { border: 1px solid #c69b12; }
QPushButton#picker {
  font-size: 13px; background: rgba(255, 248, 226, 240); color: #4a4232; border: 1px solid #d8c593; border-radius: 8px;
  padding: 7px 10px; min-height: 18px; text-align: left;
}
QPushButton#picker:hover { border-color: #d6cfb5; }
QPushButton#picker:pressed { background: #f6f0dc; }
QPushButton#picker:disabled { color: #afaa9a; background: #f8f9fb; border-color: #e9ecf1; }
QFrame#techniquePopup, QFrame#historyPopup { background: #fff8e7; border: 1px solid #d8c593; border-radius: 12px; }
QFrame#techItem { background: #fff9ed; border: 1px solid #e5d9bb; border-radius: 10px; }
QFrame#techItem:hover { background: #f8edcf; border-color: #c9ae70; }
QLabel#techName { font-weight: 600; color: #262e3c; font-size: 13px; }
QLabel#techHint { color: #82745a; font-size: 12px; }
QLabel#catHeader { color: #74694f; font-size: 10px; font-weight: 500; letter-spacing: 1px; }
QLineEdit:focus, QComboBox:focus { border-color: #c69b12; }
QPushButton#primary { background: #fff9e5; color: #6f5710; border: 1px solid #d8c593; border-radius: 8px; min-height: 18px; padding: 7px 18px; font-weight: 500; }
QPushButton#primary:hover { background: #faf6e7; border-color: #e9deb8; }
QPushButton#primary:pressed { background: #f6f0dc; border-color: #e1d5a8; }
QPushButton:focus { border: 1px solid #c69b12; }
QLineEdit:hover, QComboBox:hover { border-color: #d6cfb5; }
QPushButton#primary:disabled { background: #f4ead4; color: #b5af9a; border-color: #e5e8ef; }
QPushButton#ghost { background: #f6ebd0; color: #6f5710; border: 1px solid #d8c593; border-radius: 8px; min-height: 18px; padding: 7px 11px; font-size: 12px; }
QPushButton#ghost:hover { background: #f5e5bc; }
QPushButton#ghost:pressed { background: #f5f2e5; }
QPushButton#ghost:disabled { color: #a69f84; background: #f4ead0; border-color: #e1d4b0; }
QProgressBar { background: #f7f3e4; border: none; border-radius: 1px; max-height: 2px; min-height: 2px; }
QProgressBar::chunk { background: #c69b12; border-radius: 1px; }
QProgressBar#generationProgress { background: #e9d8a0; min-height: 3px; max-height: 3px; border-radius: 1px; }
QProgressBar#generationProgress::chunk { background: #e1b72c; border-radius: 1px; }
QScrollArea { border: none; background: #fff8e7; }
QScrollArea#inputScroll, QWidget#inputViewport { background: transparent; }
QWidget#scrollContent { background: #fff8e7; }
QCheckBox { color: #626d7d; font-size: 12px; spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #d8c593; border-radius: 4px; background: #fff8e7; }
QCheckBox::indicator:hover { border-color: #c69b12; background: #fffbec; }
QCheckBox::indicator:checked { background: #f4ca38; border-color: #c69b12; image: url(CHECK_ICON); }
QCheckBox::indicator:disabled { background: #f2f4f7; border-color: #e0e4eb; }
QSplitter::handle:horizontal { width: 24px; background: transparent; }
QSplitter::handle:horizontal:hover { background: #f3efe2; border-radius: 4px; }
/* Keep the scrollbar hit area usable while the visible handle stays slim. */
QScrollBar:vertical { border: none; background: #f4ead0; width: 12px; margin: 3px 2px; border-radius: 4px; }
QScrollBar:horizontal { border: none; background: #f4ead0; height: 12px; margin: 2px 3px; border-radius: 4px; }
QScrollBar::handle:vertical { border: none; background: #d8d5c9; min-height: 32px; border-radius: 4px; }
QScrollBar::handle:horizontal { border: none; background: #d8d5c9; min-width: 32px; border-radius: 4px; }
QScrollBar::handle:hover { background: #c4bfad; }
QScrollBar::handle:pressed { background: #ada790; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; }
""".replace("CHECK_ICON", (ROOT / "desktop" / "check-yellow.svg").as_posix()).replace("UP_ICON", (ROOT / "desktop" / "chevron-up.svg").as_posix()).replace("DOWN_ICON", (ROOT / "desktop" / "chevron-down.svg").as_posix())


DARK_SCROLL_QSS = """
QScrollBar:vertical, QScrollBar:horizontal { background: #3e3e3e; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #606060; }
QScrollBar::handle:hover { background: #797979; }
QScrollBar::handle:pressed { background: #929292; }
"""
