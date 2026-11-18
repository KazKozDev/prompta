"""The Written for picker on its own: no window, no manifest file, synthetic models."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from target_selector import OFFICIAL_TARGETS, TargetSelector, target_items  # noqa: E402

MODELS = [
    {"id": "qwen-b", "name": "qwen B", "repo": "Qwen/B"},
    {"id": "qwen-a", "name": "Qwen A", "repo": "Qwen/A"},
    {"id": "glm", "name": "GLM 5", "repo": "zai-org/GLM"},
    {"id": "solo", "name": "Solo", "repo": "unknown-org/Solo"},
]


class TargetItemsTest(unittest.TestCase):
    def test_any_then_official_then_open_models_by_family(self):
        items = target_items(MODELS)
        self.assertEqual([i["key"] for i in items[: 1 + len(OFFICIAL_TARGETS)]], ["general", *OFFICIAL_TARGETS])
        open_items = [(i["category"], i["label"]) for i in items if i["key"].startswith("open:")]
        self.assertEqual(
            open_items,
            [
                ("GLM · Z.AI · open-weight", "GLM 5"),
                ("QWEN · ALIBABA · open-weight", "Qwen A"),
                ("QWEN · ALIBABA · open-weight", "qwen B"),  # names sort without case
                ("UNKNOWN-ORG · open-weight", "Solo"),  # an unknown organization is its own family
            ],
        )

    def test_no_manifest_still_offers_any_and_official(self):
        self.assertEqual(len(target_items([])), 1 + len(OFFICIAL_TARGETS))


class TargetSelectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.selector = TargetSelector(MODELS)
        self.changes = []
        self.selector.changed.connect(lambda: self.changes.append(self.selector.target()))

    def tearDown(self):
        self.selector.deleteLater()

    def test_starts_on_any_llm(self):
        self.assertIsNone(self.selector.target())
        self.assertEqual(self.selector.open_model(), "")
        self.assertEqual(self.selector.picker.text(), "— any LLM —")
        self.assertEqual(self.selector.request_field(), {})

    def test_official_target_is_the_request_target(self):
        self.selector.picker._choose("grok")
        self.assertEqual(self.selector.target(), "grok")
        self.assertEqual(self.selector.request_field(), {"target": "grok"})
        self.assertEqual(self.changes, ["grok"])

    def test_open_model_target(self):
        self.selector.picker._choose("open:glm")
        self.assertEqual(self.selector.target(), "openModel")
        self.assertEqual(self.selector.open_model(), "glm")
        self.assertEqual(self.selector.open_model_label(), "GLM 5")
        self.assertEqual(self.selector.request_field(), {"target": "open:glm"})

    def test_set_target_restores_and_falls_back(self):
        self.selector.set_target("openModel", self.selector.open_model_id("Qwen A"))
        self.assertEqual(self.selector.open_model(), "qwen-a")
        self.selector.set_target("openModel", self.selector.open_model_id("Gone from the manifest"))
        self.assertIsNone(self.selector.target(), "an unknown open model means any LLM, never an empty open target")
        self.selector.set_target("claude")
        self.assertEqual(self.selector.target(), "claude")
        self.selector.set_target("not-a-target")
        self.assertIsNone(self.selector.target())
        self.assertEqual(self.changes, ["openModel", None, "claude", None], "every restore tells the window")


if __name__ == "__main__":
    unittest.main()
