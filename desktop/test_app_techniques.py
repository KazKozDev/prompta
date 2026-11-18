"""Technique and variant controls and the requests they make."""

from test_support import WindowTestCase
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QPushButton, QLabel
from app import PromptaWindow
from generator_settings import GeneratorSettings


class TechniqueTest(WindowTestCase):
    def test_variant_segments_are_exclusive_and_reach_pipeline(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            self.assertEqual(window.variants.value(), 1)
            window.variants.buttons.button(5).click()
            self.assertEqual(window.variants.value(), 5)
            self.assertEqual(sum(b.isChecked() for b in window.variants.buttons.buttons()), 1)
            window.thoughts.setPlainText('Synthetic count test')
            with patch('app.Worker') as worker:
                window.run_pipeline()
                self.assertEqual(worker.call_args.args[0]['variants'], 5)
            window.variants.buttons.button(1).click()
            self.assertEqual(window.variants.value(), 1)
        finally:
            window.close()

    def test_article_icon_opens_sources_without_selecting_technique(self):
        from controls import TechniqueItem
        from PyQt6.QtWidgets import QDialog, QLabel
        from PyQt6.QtCore import QTimer

        source = {
            'title': 'Prompting paper',
            'url': 'https://archive.org/download/example/paper.pdf#page=12',
            'reference': 'p. 12',
        }
        item = TechniqueItem('example', 'Example', sources=[source, {'title': 'Bad', 'url': 'javascript:alert(1)'}])
        chosen = Mock()
        item.clicked.connect(chosen)
        item.show()
        observed = []

        def inspect_dialog():
            dialog = self.app.activeModalWidget()
            if isinstance(dialog, QDialog):
                observed.extend(label.text() for label in dialog.findChildren(QLabel))
                dialog.accept()

        QTimer.singleShot(0, inspect_dialog)
        item.findChild(QPushButton, 'articleLink').click()
        self.assertEqual(len(item.sources), 1)
        self.assertTrue(any(source['url'] in text for text in observed))
        chosen.assert_not_called()
        item.close()

    def test_runs_in_has_its_own_label_and_plain_choices(self):
        window = self._prompta_window()
        try:
            labels = [label.text() for label in window.findChildren(QLabel)]
            self.assertIn('RUNS IN', labels)
            self.assertEqual(window.execution_profile.text(), '— any chat —')
            self.assertFalse(hasattr(window, 'one_shot'), 'no worked-example toggle: few-shot covers it')
            window.execution_profile.set_current('agent')
            self.assertEqual(window.execution_profile.text(), 'Agent with tools')
            window.execution_profile.set_current('local')
            self.assertEqual(window.execution_profile.text(), 'Local model, no tools')
        finally:
            window.close()

    def test_advanced_section_holds_technique_and_variants(self):
        window = self._prompta_window()
        try:
            self.assertIs(window.technique.parentWidget(), window.technique_panel.body)
            self.assertIs(window.variants.parentWidget(), window.technique_panel.body)
            self.assertTrue(window.technique_panel.body.isVisibleTo(window), 'Advanced never folds')
            self.assertEqual(window.technique_panel.title(), 'Technique')
            window.variants.buttons.button(2).click()
            self.assertEqual(window.technique_panel.title(), 'Technique', 'the heading stays put')
            self.assertEqual(window.variants.value(), 2)
            window.target_picker._choose('claude')
            self.assertFalse(window.technique_panel.isVisibleTo(window), 'techniques exist only for Any')
            self.assertEqual(window.variants.value(), 1)
            window.target_picker._choose('general')  # back to Any
            self.assertTrue(window.technique_panel.isVisibleTo(window))
            self.assertTrue(window.variants.isVisibleTo(window))
            self.assertEqual(window.variants.value(), 2, 'the count comes back')
            self.assertTrue(window.run_button.text().startswith('Build prompt'))
            self.assertEqual(window.status.text(), '')
        finally:
            window.close()

    def test_technique_popup_selects_several_and_builds_one_prompt_each(self):
        from PyQt6.QtWidgets import QTabWidget
        from controls import TechniqueItem

        window = self._prompta_window()
        try:
            window._on_techniques_loaded(
                [
                    {'key': 'cot', 'name': 'Chain of thought', 'category': 'reasoning', 'status': 'ready'},
                    {'key': 'few', 'name': 'Few-shot', 'category': 'icl', 'status': 'ready'},
                    {'key': 'knn', 'name': 'KNN selection', 'category': 'procedure', 'status': 'procedure'},
                ]
            )
            window.technique._open()
            popup = window.technique._popup
            items = {w.key: w for w in popup.findChildren(TechniqueItem)}
            items['cot'].clicked.emit('cot')
            items['few'].clicked.emit('few')
            self.assertTrue(popup.isVisible(), 'multi-select keeps the panel open')
            self.assertEqual(window.technique.current_keys(), ['cot', 'few'])
            self.assertTrue(items['few'].property('selected'))
            self.assertEqual(
                window.technique_panel.button.text(), 'TECHNIQUE', 'the selection shows in the field, not the heading'
            )
            self.assertFalse(
                [label for label in window.findChildren(QLabel) if label.text().startswith('TECHNIQUE ·')],
                'no separate counted label: the catalog size is in the heading tooltip',
            )
            self.assertFalse(window.variants.isVisibleTo(window), 'the 1–5 count shows only for automatic choice')
            saved = window.technique.current_keys()
            window.technique.set_current_keys([], emit=True)
            self.assertTrue(window.variants.isVisibleTo(window))
            window.technique.set_current_keys(saved, emit=True)
            items['knn'].clicked.emit('knn')
            self.assertEqual(window.technique.current_keys(), ['knn'], 'procedures are exclusive')
            items['cot'].clicked.emit('cot')
            self.assertEqual(window.technique.current_keys(), ['cot'])
            items['few'].clicked.emit('few')
            items['cot'].clicked.emit('cot')
            self.assertEqual(window.technique.current_keys(), ['few'], 'a second click deselects')
            items['cot'].clicked.emit('cot')
            popup.close()

            window.thoughts.setPlainText('Explain recursion')
            window.generator.model.set_current('test-model')
            with patch('app.Worker') as worker:
                window.run_pipeline()
                payload = worker.call_args.args[0]
            self.assertEqual(payload['manualTechniques'], ['few', 'cot'])
            self.assertNotIn('manualTechnique', payload)
            window.worker = None

            variant = lambda key, name: {
                'technique': {'key': key, 'name': name, 'category': 'x'},
                'prompt': f'{name} prompt ' * 6,
                'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'},
                'source_ref': 'src',
            }
            variants = [variant('few', 'Few-shot'), variant('cot', 'Chain of thought')]
            window.on_finished(
                {
                    'ok': True,
                    'manual': {
                        **variants[0],
                        'topic': 'Recursion',
                        'zeroShotPrompt': 'Task',
                        'variants': variants,
                        'failed': [{'key': 'x', 'name': 'ToT', 'error': 'timeout'}],
                    },
                }
            )
            tabs = window.result_column.output_holder.findChild(QTabWidget, 'variantTabs')
            self.assertEqual(
                [tabs.tabText(i) for i in range(tabs.count())], ['Zero-shot', 'Few-shot', 'Chain of thought']
            )
            self.assertIn('Chain of thought prompt', tabs.widget(2).toPlainText())
            self.assertEqual(tabs.widget(0).toPlainText(), 'Task')
            self.assertEqual(window.status.text(), '2 techniques built · 1 failed, see below the prompt')
            warn = [
                w.text()
                for w in window.result_column.output_holder.findChildren(QLabel, 'warn')
                if w.isVisibleTo(window)
            ]
            self.assertEqual(warn, ['• Not built — ToT: timeout'])
            window.technique.set_current_keys(['cot'])
            with patch('app.Worker') as worker:
                window.run_pipeline()
                self.assertEqual(worker.call_args.args[0]['manualTechnique'], 'cot')
        finally:
            window.close()

    def test_select_all_toggles_shown_techniques_and_skips_procedures(self):
        from PyQt6.QtWidgets import QLineEdit

        window = self._prompta_window()
        try:
            window._on_techniques_loaded(
                [
                    {'key': 'cot', 'name': 'Chain of thought', 'category': 'reasoning', 'status': 'ready'},
                    {'key': 'few', 'name': 'Few-shot', 'category': 'icl', 'status': 'ready'},
                    {'key': 'tot', 'name': 'Tree of thoughts', 'category': 'reasoning', 'status': 'ready'},
                    {'key': 'knn', 'name': 'KNN selection', 'category': 'procedure', 'status': 'procedure'},
                ]
            )
            dropdown = window.technique
            dropdown.set_current_keys(['knn'])
            dropdown._open()
            button = dropdown._select_all_button
            self.assertEqual(button.text(), 'Select all')
            button.click()
            self.assertEqual(
                dropdown.current_keys(), ['cot', 'tot', 'few'], 'procedure dropped, all others selected in panel order'
            )
            self.assertEqual(button.text(), 'Deselect all')
            button.click()
            self.assertEqual(dropdown.current_keys(), [])
            self.assertEqual(button.text(), 'Select all')

            dropdown._popup.findChild(QLineEdit).setText('thought')  # filter: CoT and ToT only
            dropdown._toggle('few')
            button.click()
            self.assertEqual(dropdown.current_keys(), ['few', 'cot', 'tot'])
            self.assertEqual(button.text(), 'Deselect all')
            button.click()
            self.assertEqual(dropdown.current_keys(), ['few'], 'deselect touches only the shown ones')
            dropdown._popup.close()
        finally:
            window.close()

    def test_picking_techniques_resets_count_to_one_and_restores_it(self):
        window = self._prompta_window()
        try:
            window._on_techniques_loaded(
                [{'key': 'sc', 'name': 'Self-consistency', 'category': 'x', 'status': 'ready'}]
            )
            window.variants.buttons.button(4).click()
            self.assertEqual(window.variants.value(), 4)
            window.technique.set_current_keys(['sc'], emit=True)
            self.assertEqual(window.variants.value(), 1)
            self.assertFalse(window.variants.isEnabled())
            window.technique.set_current_keys([], emit=True)
            self.assertEqual(window.variants.value(), 4)
            self.assertTrue(window.variants.isEnabled())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
