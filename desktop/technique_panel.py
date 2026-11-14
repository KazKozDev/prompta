"""The Technique block of the request column: the catalog picker and the 1–5 variants switch.

Built once, in its final form. Techniques apply to Any LLM only: an official target or an open-weight model
hides the block and locks the count at one prompt, and the user's count comes back with Any.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from controls import Dropdown, VariantSelector
from result_view import CONTROL_HEIGHT, Disclosure, muted_label
from settings_ui import field_label
from theme import PROMPT_TARGETS


class TechniquePanel(Disclosure):
    """A fixed field-label heading, the technique picker (several at once; procedures alone) and the count."""

    def __init__(self) -> None:
        super().__init__("Technique", field_label=True, collapsible=False)
        self.catalog_summary = ""
        self._target: str | None = None
        self._count_before_lock: int | None = None  # the user's 1–5 while a target or a manual choice locks it
        # It never folds: a plain field label like "Written for" and "Runs in", not the padded toggle button.
        self.button.hide()
        body = self.body_layout
        body.setContentsMargins(0, 0, 0, 8)
        body.setSpacing(6)
        self.heading = field_label("Technique")
        self.heading.setContentsMargins(0, 0, 0, 2)  # 8px to its field, as in the rows above
        body.addWidget(self.heading)
        self.technique = Dropdown(
            "— automatic —",
            columns=2,
            searchable=True,
            popup_width=820,
            search_placeholder="Filter techniques",
        )
        self.technique.set_multi(True)
        body.addWidget(self.technique)
        # Full-width segmented switch under the technique picker, with a plain caption saying what the numbers are.
        body.addSpacing(6)
        self.variants_caption = muted_label(
            "Variants · prompts built with different techniques to compare", "variantsCaption"
        )
        body.addWidget(self.variants_caption)
        self.variants = VariantSelector()
        self.variants.setToolTip("How many of the best-fitting techniques to pick; each gives one prompt")
        body.addWidget(self.variants)
        # One control height for fields and segmented tracks so rows line up.
        for field in (self.technique, self.variants):
            field.ensurePolished()  # its own stylesheet would reset the minimum height when polished later
            field.setFixedHeight(CONTROL_HEIGHT)
        for option in self.variants.buttons.buttons():
            option.setFixedHeight(CONTROL_HEIGHT - 4)
            option.setCursor(Qt.CursorShape.PointingHandCursor)
        # Bound methods, not lambdas: Qt drops them with the panel, so a dying child cannot call into it.
        self.technique.changed.connect(self._sync)
        self.variants.buttons.idClicked.connect(self._sync)
        self.set_target(None)

    def technique_keys(self) -> list[str]:
        """The techniques to build with: none means automatic choice, and a target never uses the catalog."""
        return self.technique.current_keys() if self._target is None else []

    def set_target(self, target: str | None) -> None:
        """The target the prompt is written for; None is Any LLM."""
        self._target = target
        self.technique.setEnabled(target is None)
        self.technique.setToolTip(
            f"{PROMPT_TARGETS[target][0]} mode uses official rules instead of the technique catalog."
            if target
            else "Choose a technique to build a prompt using its method"
        )
        self._sync()

    def set_techniques(self, techniques: list[dict]) -> None:
        """The catalog from the pipeline; procedures are marked in their names and counted apart."""
        if not techniques:
            return
        for item in techniques:
            if item.get("status") == "procedure":
                item["name"] = f"{item.get('name', item['key'])} (procedure)"
            item["label"] = item.get("name", item["key"])
        self.technique.set_items(techniques, keep=self.technique.current_key())
        procedures = sum(1 for item in techniques if item.get("status") == "procedure")
        ready = len(techniques) - procedures
        self.catalog_summary = (
            f"{ready} technique{'s' if ready != 1 else ''}"
            + (f" + {procedures} procedure{'s' if procedures != 1 else ''}" if procedures else "")
            + " available"
        )
        self._sync()

    def _sync(self, *_: object) -> None:
        # The 1–5 count is only for Any + automatic technique choice. Otherwise one prompt is built:
        # show 1 while locked, then restore the user's count.
        locked = self._target is not None or bool(self.technique.current_keys())
        if locked and self._count_before_lock is None:
            self._count_before_lock = self.variants.value()
            self.variants.setValue(1)
        elif not locked and self._count_before_lock is not None:
            self.variants.setValue(self._count_before_lock)
            self._count_before_lock = None
        self.variants.setEnabled(not locked)
        self.variants.setVisible(not locked)
        self.variants_caption.setVisible(not locked)
        # Techniques exist only for Any: official targets and open-weight models follow their own guidance.
        if self._target is not None:
            self.hide()
        elif self.parentWidget() is not None:  # without a parent, show() would open it as a window
            self.show()
        self.button.setToolTip(self.catalog_summary)
        self.heading.setToolTip(self.catalog_summary)
