"""The Technique block on its own: catalog, multi-select and the variants lock, without a window."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from technique_panel import TechniquePanel  # noqa: E402

CATALOG = [
    {"key": "cot", "name": "Chain of thought", "category": "reasoning", "status": "ready"},
    {"key": "few", "name": "Few-shot", "category": "icl", "status": "ready"},
    {"key": "knn", "name": "KNN selection", "category": "procedure", "status": "procedure"},
]


class TechniquePanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()  # a column to sit in: the panel shows and hides itself only inside one
        QVBoxLayout(self.host).addWidget(panel := TechniquePanel())
        self.panel = panel
        self.panel.set_techniques([dict(item) for item in CATALOG])

    def tearDown(self):
        self.host.deleteLater()

    def test_heading_is_a_field_label_and_built_once(self):
        self.assertEqual(self.panel.heading.text(), "TECHNIQUE")
        self.assertTrue(self.panel.button.isHidden(), "a heading, not a fold toggle")
        self.assertEqual(self.panel.technique.text(), "— automatic —")
        self.assertEqual(self.panel.variants.objectName(), "segmentTrack")
        self.assertEqual({b.objectName() for b in self.panel.variants.buttons.buttons()}, {"segment"})

    def test_catalog_marks_procedures_and_summarises(self):
        labels = {item["key"]: item["label"] for item in self.panel.technique._items}
        self.assertEqual(labels["knn"], "KNN selection (procedure)")
        self.assertEqual(self.panel.catalog_summary, "2 techniques + 1 procedure available")
        self.assertEqual(self.panel.heading.toolTip(), self.panel.catalog_summary)

    def test_a_manual_choice_locks_the_count_and_gives_it_back(self):
        self.panel.variants.setValue(4)
        self.panel.technique.set_current_keys(["cot", "few"], emit=True)
        self.assertEqual(self.panel.variants.value(), 1)
        self.assertTrue(self.panel.variants.isHidden())
        self.assertTrue(self.panel.variants_caption.isHidden())
        self.assertEqual(self.panel.technique_keys(), ["cot", "few"])
        self.panel.technique.set_current_keys([], emit=True)
        self.assertEqual(self.panel.variants.value(), 4, "the user's count comes back")
        self.assertFalse(self.panel.variants.isHidden())

    def test_a_target_hides_the_block_and_ignores_the_catalog(self):
        self.panel.technique.set_current_keys(["cot"], emit=True)
        self.panel.set_target("claude")
        self.assertTrue(self.panel.isHidden())
        self.assertFalse(self.panel.technique.isEnabled())
        self.assertIn("Claude mode uses official rules", self.panel.technique.toolTip())
        self.assertEqual(self.panel.technique_keys(), [], "a target never builds with catalog techniques")
        self.panel.set_target(None)
        self.assertFalse(self.panel.isHidden())
        self.assertEqual(self.panel.technique_keys(), ["cot"])

    def test_without_a_column_it_never_opens_as_a_window(self):
        loose = TechniquePanel()
        loose.set_target(None)
        self.assertFalse(loose.isWindow() and loose.isVisible())
        loose.deleteLater()


if __name__ == "__main__":
    unittest.main()
