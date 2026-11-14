"""Window building blocks tested on their own: controls, result layout helpers and Settings page helpers."""

import glob
import importlib
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

from controls import Dropdown, ExecutionProfileDropdown, VariantSelector  # noqa: E402
from result_view import Disclosure, FlowLayout, find_layout, keyed_label, note_chip, spec_text, split_warnings  # noqa: E402
from settings_ui import LABEL_GAP, SECTION_GAP, add_section, field_label, settings_page  # noqa: E402


class ImportsTest(unittest.TestCase):
    def test_every_module_imports(self):
        """Ruff cannot see a name imported from a module that no longer defines it; importing can."""
        for path in sorted(glob.glob(str(HERE / "*.py"))):
            name = Path(path).stem
            if name.startswith("test_") or name in {
                "voice_input",
                "make_icon",
                "screenshots",
            }:  # scripts; screenshots swaps HOME on import
                continue
            with self.subTest(module=name):
                importlib.import_module(name)


class ResultHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_split_warnings_keeps_routine_notes_apart_and_dedupes(self):
        shown, notes = split_warnings(["Check the date", "High stakes: verify", "Check the date", "General advice"])
        self.assertEqual(shown, ["Check the date"])
        self.assertEqual(notes, ["High stakes: verify", "General advice"])

    def test_spec_text_line_and_tooltip(self):
        line, tooltip = spec_text(
            {"temperature": 0.2, "top_p": None, "max_tokens": "1024 (short answer)", "rationale": "Terse."}
        )
        self.assertEqual(line, "temp 0.2 · top_p default · max 1024")
        self.assertEqual(tooltip, "max_tokens: 1024 (short answer). Terse.")

    def test_note_chip_shows_the_head_and_keeps_the_note_on_hover(self):
        chip = note_chip("Kimi K3.1: use thinking mode for code")
        self.assertEqual(chip.text(), "Kimi K3.1")
        self.assertEqual(chip.toolTip(), "Kimi K3.1: use thinking mode for code")
        self.assertTrue(note_chip("x" * 60 + ": tail").text().endswith("…"))

    def test_keyed_label_escapes_text(self):
        label = keyed_label("Format", "<table> & more")
        self.assertIn("&lt;table&gt; &amp; more", label.text())
        self.assertIn("<br>", keyed_label("Items", "a", stacked=True).text())

    def test_find_layout_searches_nested_layouts(self):
        host = QWidget()
        outer = QVBoxLayout(host)
        inner = QHBoxLayout()
        outer.addLayout(inner)
        target = QLabel("x")
        inner.addWidget(target)
        self.assertIs(find_layout(outer, target), inner)
        self.assertIsNone(find_layout(outer, QLabel("elsewhere")))

    def test_disclosure_toggles_and_fixed_heading(self):
        folding = Disclosure("Details")
        self.assertTrue(folding.body.isHidden())
        self.assertEqual(folding.button.text(), "▸  Details")
        folding.button.click()
        self.assertFalse(folding.body.isHidden())
        heading = Disclosure("Technique", field_label=True, collapsible=False)
        self.assertEqual(heading.button.text(), "TECHNIQUE")
        self.assertFalse(heading.body.isHidden(), "a heading never folds")

    def test_flow_layout_wraps_to_width(self):
        host = QWidget()
        flow = FlowLayout()
        host.setLayout(flow)
        for text in ("one", "two", "three", "four"):
            flow.addWidget(QLabel(text))
        self.assertEqual(flow.count(), 4)
        self.assertGreater(flow.heightForWidth(40), flow.heightForWidth(1000), "narrow means more rows")


class ControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dropdown_single_choice(self):
        picker = Dropdown("— pick —")
        seen = []
        picker.changed.connect(seen.append)
        picker.set_items([{"key": "a", "label": "Alpha"}, {"key": "b", "label": "Beta"}], keep="b")
        self.assertEqual((picker.current_key(), picker.text()), ("b", "Beta"))
        picker.set_items([{"key": "a", "label": "Alpha"}])
        self.assertEqual(picker.current_key(), "b", "a vanished key is not replaced silently")
        picker._choose("a")
        self.assertEqual(seen, ["a"], "only a choice emits, not a programmatic set")
        picker.set_current("")
        self.assertEqual(picker.text(), "— pick —")

    def test_dropdown_multi_choice_drops_unknown_keys(self):
        picker = Dropdown("— automatic —")
        picker.set_multi(True)
        picker.set_items([{"key": "cot", "label": "Chain of thought"}, {"key": "few", "label": "Few-shot"}])
        picker.set_current_keys(["cot", "few", "cot"])
        self.assertEqual(picker.current_keys(), ["cot", "few"])
        picker.set_items([{"key": "few", "label": "Few-shot"}])
        self.assertEqual(picker.current_keys(), ["few"])

    def test_execution_profile_defaults_to_any_chat(self):
        profile = ExecutionProfileDropdown()
        self.assertEqual(profile.current_key(), "universal")
        self.assertEqual([item["key"] for item in profile._items], ["universal", "web", "local", "agent"])

    def test_variant_selector_clamps_to_one_through_five(self):
        selector = VariantSelector()
        self.assertEqual(selector.value(), 1)
        selector.setValue(9)
        self.assertEqual(selector.value(), 5)
        selector.setValue(0)
        self.assertEqual(selector.value(), 1)


class SettingsHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_field_label_is_caps(self):
        label = field_label("Base URL")
        self.assertEqual((label.text(), label.objectName()), ("BASE URL", "fieldLabel"))

    def test_add_section_spacing(self):
        _, layout = settings_page()
        field = QLabel("field")
        add_section(layout, "Provider", field, hint="A hint")
        add_section(layout, "Model", QLabel("other"))
        spacers = [layout.itemAt(i).spacerItem() for i in range(layout.count())]
        gaps = [s.sizeHint().height() for s in spacers if s is not None]
        self.assertEqual(gaps[0], LABEL_GAP, "label to its field")
        self.assertIn(SECTION_GAP, gaps, "sections stand apart")
        self.assertEqual(layout.itemAt(0).widget().text(), "PROVIDER")


if __name__ == "__main__":
    unittest.main()
