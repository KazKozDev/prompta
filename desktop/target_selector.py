"""The "Written for" picker: the model the prompt is written for, one dropdown with one current key.

Keys: "general" (any LLM, the technique catalog), an official target ("claude", "chatgpt", …) or
"open:<id>" for an open-weight model. The generator model in Settings is a separate choice.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from controls import Dropdown
from result_view import CONTROL_HEIGHT, GENERAL_TARGET
from settings_ui import field_label
from theme import PROMPT_TARGETS
from widgets import MODEL_FAMILIES

OPEN_MODEL = "openModel"
OPEN_PREFIX = "open:"
OFFICIAL_TARGETS = [key for key in PROMPT_TARGETS if key != OPEN_MODEL]


def target_items(open_models: list[dict]) -> list[dict]:
    """Picker items: any LLM, the official targets, then open-weight models by family, both sorted by name."""
    items = [{"key": GENERAL_TARGET, "label": "— any LLM —", "category": "General"}]
    items += [
        {"key": key, "label": PROMPT_TARGETS[key][0], "category": "Official guidance"} for key in OFFICIAL_TARGETS
    ]
    families: dict[str, list[dict]] = {}
    for model in open_models:
        org = model["repo"].split("/")[0]
        families.setdefault(MODEL_FAMILIES.get(org) or org, []).append(model)
    for family in sorted(families, key=str.casefold):
        for model in sorted(families[family], key=lambda m: m["name"].casefold()):
            items.append(
                {
                    "key": OPEN_PREFIX + model["id"],
                    "label": model["name"],
                    "category": f"{family.upper()} · open-weight",
                }
            )
    return items


class TargetSelector(QWidget):
    """A field label over one dropdown. `changed` fires on every new choice, by the user or by `set_target`."""

    changed = pyqtSignal()

    def __init__(self, open_models: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(field_label("Written for"))
        self.picker = Dropdown("— any LLM —", searchable=True, popup_width=380, search_placeholder="Filter models")
        self.picker.setAccessibleName("Written for: LLM model")
        self.picker.setToolTip("The model the prompt is written for. Your generator model stays the same.")
        self.picker.set_items(target_items(open_models), keep=GENERAL_TARGET)
        self.picker.ensurePolished()  # its own stylesheet would reset the minimum height when polished later
        self.picker.setFixedHeight(CONTROL_HEIGHT)
        self.picker.changed.connect(lambda *_: self.changed.emit())
        layout.addWidget(self.picker)

    def target(self) -> str | None:
        """None for any LLM, an official target key, or "openModel"."""
        key = self.picker.current_key()
        if key.startswith(OPEN_PREFIX):
            return OPEN_MODEL
        return key if key in OFFICIAL_TARGETS else None

    def open_model(self) -> str:
        """The chosen open-weight model's id, or "" when the target is not an open-weight model."""
        key = self.picker.current_key()
        return key.removeprefix(OPEN_PREFIX) if key.startswith(OPEN_PREFIX) else ""

    def open_model_label(self) -> str:
        return self.picker.text() if self.open_model() else ""

    def open_model_id(self, label: str) -> str:
        """The id of the open-weight model with this display name (history stores the name), or ""."""
        return next(
            (
                item["key"].removeprefix(OPEN_PREFIX)
                for item in self.picker._items
                if item["key"].startswith(OPEN_PREFIX) and item["label"] == label
            ),
            "",
        )

    def set_target(self, target: str | None, open_model: str = "") -> None:
        """Choose a target; an open-weight target needs a known model, otherwise it falls back to any LLM."""
        key = GENERAL_TARGET
        if target == OPEN_MODEL:
            if any(item["key"] == OPEN_PREFIX + open_model for item in self.picker._items):
                key = OPEN_PREFIX + open_model
        elif target in OFFICIAL_TARGETS:
            key = target
        self.picker.set_current(key, emit=True)

    def request_field(self) -> dict[str, str]:
        """The bridge's `target` (pipeline/target.ts): an official key or "open:<id>"; nothing for any LLM."""
        key = self.picker.current_key()
        return {"target": key} if key in OFFICIAL_TARGETS or key.startswith(OPEN_PREFIX) else {}
