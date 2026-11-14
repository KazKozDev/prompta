"""The result column on its own: rendering, the assumptions card it hands out, prompt edits as signals."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from result_column import AssumptionsCard, ResultColumn  # noqa: E402

BRIEF = {
    "goal": "Find job titles",
    "task_type": "agentic",
    "language": "en",
    "stakes": "medium",
    "output_format": "Report",
    "assumptions": ["Senior roles only"],
    "questions": [{"question": "Which countries?", "default": "all of Europe"}],
}


def result(**extra) -> dict:
    synthesis = {"prompt": "Find job titles.", "config": {"temperature": 0.2}, "warnings": ["Check the dates"]}
    alternative = {
        "choice": {"key": "cot", "name": "Chain of thought", "reason": "steps"},
        "synthesis": {"prompt": "Think, then find.", "config": {}, "warnings": []},
    }
    return {
        "brief": BRIEF,
        "choice": {"key": "zero", "name": "Contextual prompting", "reason": "fits", "confidence": 0.8},
        "synthesis": synthesis,
        "alternatives": [alternative],
        "rejected": [],
        **extra,
    }


class ResultColumnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.request = "Find job titles"
        self.column = ResultColumn(lambda: self.request)
        self.cards: list = []
        self.edits: list[tuple[int, str]] = []
        self.rebuilds: list[bool] = []
        self.column.assumptionsCard.connect(self.cards.append)
        self.column.promptEdited.connect(lambda variant, text: self.edits.append((variant, text)))
        self.column.rebuildRequested.connect(lambda: self.rebuilds.append(True))

    def tearDown(self):
        self.column.deleteLater()

    def labels(self) -> list[str]:
        return [label.text() for label in self.column.output_holder.findChildren(QLabel)]

    def test_placeholder_then_result_replaces_it(self):
        self.column.show_placeholder()
        self.assertEqual(self.column.wordmark.text(), "PROMPTA")
        self.assertEqual(self.cards, [None], "an empty column has no assumptions card")
        self.column.render_result(result())
        self.assertIn("Find job titles", self.labels())
        self.assertEqual(self.column.prompt_edit.toPlainText(), "Find job titles.")
        self.assertEqual(self.column.visible_warnings, ["Check the dates"])

    def test_the_assumptions_card_goes_to_the_window_and_reads_edits(self):
        self.column.render_result(result())
        card = self.cards[-1]
        self.assertIsInstance(card, AssumptionsCard)
        self.assertEqual(card.change_count(), 0)
        self.assertIsNone(card.revised_brief())
        self.column.assumption_rows[0]["field"].setText("Junior roles too")
        self.assertEqual(card.change_count(), 1)
        self.assertEqual(card.revised_brief()["assumptions"], ["Junior roles too"])
        self.request = "Something else entirely"
        self.assertEqual(card.change_count(), 0, "edits belong to the request they were made for")
        self.request = "Find job titles"
        self.column.assumption_rows[0]["field"].returnPressed.emit()
        self.assertEqual(self.rebuilds, [True], "Enter in a card field asks for a rebuild")

    def test_prompt_edits_are_reported_with_their_variant(self):
        self.column.render_result(result())
        self.column.prompt_edit.setPlainText("My own prompt")
        self.assertEqual(self.edits[-1], (1, "My own prompt"))

    def test_error_and_outdated_note(self):
        self.column.show_error("model unavailable")
        self.assertIn("Error: model unavailable", self.labels())
        self.column.render_result(result(promptVersion="v1"))
        self.column.flag_outdated(result(promptVersion="v1"), "v2")
        self.assertTrue(any(text.startswith("Built with earlier Prompta rules") for text in self.labels()))


if __name__ == "__main__":
    unittest.main()
