"""Native UI and subprocess lifecycle smoke tests (run with QT_QPA_PLATFORM=offscreen)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile as _tempfile
from PyQt6.QtCore import QSettings as _QSettings
_QSettings.setPath(_QSettings.Format.IniFormat, _QSettings.Scope.UserScope, _tempfile.mkdtemp())  # never touch real prefs
import os as _os
_os.environ['PROMPTA_LOG_DIR'] = _tempfile.mkdtemp()  # nor the real dictation log
import subprocess
import tempfile
from pathlib import Path
from history import HistoryStore, history_topic
import unittest
from unittest.mock import Mock, patch

from app import QApplication, PromptaWindow, Worker, QPushButton, QLabel, QModelIndex, QListWidget, QPlainTextEdit, QScrollArea
import app as app_module


def app_flags_enabled():
    from app import Qt
    return Qt.ItemFlag.ItemIsEnabled


def app_selectable():
    from app import Qt
    return Qt.ItemFlag.ItemIsSelectable


class DesktopSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.temp.name) / 'history.sqlite3')
        self.store_patch = patch('app.HistoryStore', return_value=self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp.cleanup()

    def test_history_survives_restart_and_search_restores_correct_query(self):
        def window():
            with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
                return PromptaWindow()
        first = window()
        for query, prompt in [('Чётные числа', 'Первый промпт'), ('Письмо', 'Уникальный второй промпт')]:
            first.thoughts.setPlainText(query)
            first.on_finished({'ok': True, 'manual': {
                'technique': {'key': 'test', 'name': 'Same technique', 'category': 'test'},
                'prompt': prompt,
                'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
                'source_ref': 'test',
            }})
        first.close()
        reopened = window()
        self.assertEqual(reopened.history.count(), 3)
        reopened.history_search.setText('УНИКАЛЬНЫЙ')
        self.assertEqual(reopened.history.count(), 2)
        reopened.history.setCurrentIndex(1)
        self.assertEqual(reopened.prompt_edit.toPlainText(), 'Уникальный второй промпт')
        self.assertEqual(reopened.thoughts.toPlainText(), 'Письмо')
        reopened.history_search.setText('чётные')
        self.assertEqual(reopened.history.count(), 2)
        reopened.history.setCurrentIndex(1)
        self.assertEqual(reopened.prompt_edit.toPlainText(), 'Первый промпт')
        reopened.history_search.setText('нет совпадений')
        self.assertEqual(reopened.history.count(), 1)
        self.assertEqual(len(self.store.load()), 2)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        reopened.close()

    def test_history_settings_limit_prunes_and_persists(self):
        for i in range(5):
            self.store.add(f'q{i}', 'manual', f'q{i}', {'topic': f'q{i}'})
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'), \
                patch.dict('os.environ', {}, clear=False):
            os_env = __import__('os').environ
            os_env.pop('PROMPTA_HISTORY_MAX', None)
            os_env.pop('PROMPTA_HISTORY_DAYS', None)
            window = PromptaWindow()
            window.history_limit.addItem('Keep the newest 2', 2)
            window.history_limit.setCurrentIndex(window.history_limit.count() - 1)
        self.assertEqual([e['label'] for e in self.store.load()], ['q3', 'q4'])
        self.assertEqual(len(window._history_items), 2)
        saved = __import__('json').loads(self.store.path.with_name('settings.json').read_text())
        self.assertEqual(saved['history_max'], 2)
        window.close()

    def test_clear_history_asks_first_and_then_deletes_file(self):
        from app import QMessageBox
        for name in ('Первая', 'Вторая'):
            self.store.add(name, 'manual', name, {'topic': name})
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        with patch('app.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            window.delete_all_history_button.click()
        self.assertEqual(len(self.store.load()), 2, 'cancel keeps everything')
        with patch('app.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            window.delete_all_history_button.click()
        self.assertFalse(self.store.path.exists())
        self.assertEqual(window._history_items, [])
        self.assertEqual(window.history.count(), 1)
        window.close()

    def test_cross_deletes_history_entry_from_list_and_disk(self):
        for name in ('Первая', 'Вторая', 'Третья'):
            self.store.add(name, 'manual', name, {'topic': name})
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.history.setCurrentIndex(3)
        window.history.showPopup()
        listing = window.history._popup_frame.findChild(QListWidget)
        self.assertFalse(listing.item(0).data(app_module.DELETABLE_ROLE))
        self.assertTrue(listing.item(2).data(app_module.DELETABLE_ROLE))
        window.history.deleteRequested.emit(2)
        self.assertEqual([e['label'] for e in self.store.load()], ['Первая', 'Третья'])
        self.assertEqual([window.history.itemText(i) for i in range(window.history.count())],
                         ['— history —', 'Первая', 'Третья'])
        self.assertEqual(window.history.currentText(), 'Третья')
        window.history.hidePopup()
        window.close()

    def test_repeated_results_fit_narrow_window_without_stale_rows(self):
        from app import QLabel, QSS
        from PyQt6.QtCore import QEvent
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.resize(932, 870)
        window.show()
        result = {
            'brief': {'goal': 'Симулировать рабочий день типичного Generative AI Engineer, показав стек, задачи, артефакты и взаимодействия.',
                      'task_type': 'generation', 'language': 'ru', 'stakes': 'low',
                      'output_format': 'Связный рассказ, структурированный план или дневник от первого лица.',
                      'assumptions': ['Роль — типичный Generative AI Engineer. ' * 4]},
            'choice': {'key': 'chatgpt_official', 'name': 'ChatGPT · official guidance',
                       'confidence': 1, 'reason': 'Official rules. ' * 8, 'whyNotCheaper': 'Target mode. ' * 6},
            'synthesis': {'prompt': 'Example prompt\n' * 40,
                          'config': {'temperature': None, 'top_p': None, 'max_tokens': 'Model-dependent', 'rationale': 'Target settings'},
                          'warnings': ['General guidance. ' * 10]},
            'rejected': [], 'chatgptGuidance': {},
        }
        try:
            for width in (932, 1160, 932):
                window.resize(width, 870)
                window.render(result)
                self.app.processEvents()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                labels = window.output_holder.findChildren(QLabel)
                self.assertEqual(sum(label.text() == 'PROMPT' for label in labels), 0)
                self.assertEqual(sum(label.objectName() == 'briefMeta' for label in labels), 1, 'no stale rows from the previous render')
                self.assertEqual(len([b for b in window.output_holder.findChildren(QPushButton) if b.objectName() != 'restorePrompt']), 4)
                for label in labels:
                    if label.wordWrap():
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.text())
                goal = next(label for label in labels if label.objectName() == 'goal')
                chip = next(label for label in labels if label.objectName() == 'chip')
                self.assertLess(goal.mapTo(window, goal.rect().bottomLeft()).y(), chip.mapTo(window, chip.rect().topLeft()).y())
                self.assertEqual(window.output_scroll.horizontalScrollBar().maximum(), 0, 'the result fits the width')
        finally:
            window.close()

    def test_step_scroll_limits_jumps_and_ignores_momentum(self):
        from app import QScrollArea, QPlainTextEdit, QWidget, use_step_scroll
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent

        def wheel(area, angle=0, pixels=0, phase=Qt.ScrollPhase.NoScrollPhase):
            event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, pixels),
                                QPoint(0, angle), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier, phase, False)
            self.app.sendEvent(area.viewport(), event)
            self.assertTrue(event.isAccepted())

        area = QScrollArea()
        content = QWidget()
        content.resize(300, 3000)
        area.setWidget(content)
        area.resize(320, 300)
        use_step_scroll(area)
        editor = QPlainTextEdit()
        use_step_scroll(editor)
        editor.setPlainText('Example line\n' * 200)
        area.show()
        editor.show()
        self.app.processEvents()
        try:
            bar = area.verticalScrollBar()
            bar.setValue(200)
            wheel(area, angle=-1200)
            self.assertEqual(bar.value(), 232)
            wheel(area, pixels=-12, phase=Qt.ScrollPhase.ScrollBegin)
            self.assertEqual(bar.value(), 232)
            wheel(area, pixels=-12, phase=Qt.ScrollPhase.ScrollUpdate)
            self.assertEqual(bar.value(), 264)
            wheel(area, pixels=-500, phase=Qt.ScrollPhase.ScrollMomentum)
            self.assertEqual(bar.value(), 264)
            wheel(area, angle=120)
            self.assertEqual(bar.value(), 232)
            bar.setValue(bar.maximum())
            wheel(area, angle=-120)
            self.assertEqual(bar.value(), bar.maximum())
            wheel(editor, angle=-1200)
            self.assertEqual(editor.verticalScrollBar().value(), 2)
        finally:
            editor.close()
            area.close()

    def test_generation_line_tracks_success_error_and_cancellation(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.show()
        self.app.processEvents()
        try:
            self.assertTrue(window.generation_progress.isHidden())
            window.run_pipeline()
            self.assertTrue(window.generation_progress.isHidden())
            window.thoughts.setPlainText('Synthetic progress test')
            for outcome in ('success', 'error', 'cancel'):
                with self.subTest(outcome=outcome), patch('app.Worker') as worker_type:
                    worker = worker_type.return_value
                    worker.isRunning.return_value = False
                    window.run_pipeline()
                    self.assertTrue(window.generation_progress.isVisible())
                    self.assertEqual(window.generation_progress.maximum(), 100)
                    self.assertEqual(window.generation_progress.value(), 0)
                    window.on_progress(40, 'Technique selected')
                    self.assertEqual(window.generation_progress.value(), 40)
                    window.on_progress(20, 'Late event')
                    self.assertEqual(window.generation_progress.value(), 40)
                    if outcome == 'cancel':
                        worker.isRunning.return_value = True
                        window.cancel_run()
                        worker.cancel.assert_called_once()
                        self.assertTrue(window.generation_progress.isVisible())
                    if outcome == 'success':
                        window.on_finished({'ok': True, 'manual': {
                            'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
                            'prompt': 'Example', 'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
                            'source_ref': 'test'}})
                    else:
                        window.on_finished({'ok': False, 'error': 'Cancelled' if outcome == 'cancel' else 'Test error'})
                    if outcome == 'success':
                        self.assertEqual(window.generation_progress.value(), 100)
                    else:
                        self.assertTrue(window.generation_progress.isHidden())
                    self.assertTrue(window.run_button.isEnabled())
                    window.worker = None
        finally:
            window.close()

    def test_long_saved_topics_do_not_force_window_beyond_screen(self):
        from app import QSS
        topic = 'Создать играбельную простую платформенную игру в духе Super Mario на Python с использованием Pygame. ' * 3
        self.store.add('Old history', 'manual', 'Saved task', {
            'topic': topic, 'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
            'prompt': 'Example', 'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
            'source_ref': 'test'})
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.setStyleSheet(QSS)
            window.resize(932, 760)
            window.show()
            self.app.processEvents()
            window.history.setCurrentIndex(1)
            self.app.processEvents()
            self.assertLessEqual(window.minimumSizeHint().width(), 932)
            self.assertLessEqual(window.width(), 932)
        finally:
            window.close()

    def test_wheel_over_prompt_scrolls_results_instead_of_prompt_text(self):
        from app import QScrollArea, QPlainTextEdit, QWidget, QVBoxLayout, use_step_scroll
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        area = QScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        editor = QPlainTextEdit('Example line\n' * 200)
        editor.setFixedHeight(180)
        layout.addWidget(editor)
        layout.addSpacing(2000)
        area.setWidget(content)
        area.resize(400, 300)
        use_step_scroll(area)
        use_step_scroll(editor, area)
        area.show()
        self.app.processEvents()
        try:
            for surface in (editor.viewport(), editor.verticalScrollBar()):
                before = area.verticalScrollBar().value()
                event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120),
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
                self.app.sendEvent(surface, event)
                self.assertEqual(area.verticalScrollBar().value(), before + 32)
                self.assertEqual(editor.verticalScrollBar().value(), 0)
            editor.verticalScrollBar().setValue(10)
            self.assertEqual(editor.verticalScrollBar().value(), 10)
        finally:
            area.close()

    def test_dropdown_borders_follow_rounded_popup_corners(self):
        from app import QSS
        from PyQt6.QtCore import Qt
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.show()
        try:
            for picker in (window.technique, window.provider, window.model):
                picker._open()
                self.app.processEvents()
                popup = picker._popup
                self.assertTrue(popup.windowFlags() & Qt.WindowType.FramelessWindowHint)
                image = popup.grab().toImage()
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertEqual(image.pixelColor(image.width() // 2, 0).alpha(), 255)
                popup.close()
            window.history.showPopup()
            self.app.processEvents()
            popup = window.history._popup_frame
            self.assertTrue(popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
            self.assertEqual(popup.grab().toImage().pixelColor(0, 0).alpha(), 0)
            window.history.hidePopup()
        finally:
            window.close()

    def test_history_popup_uses_plain_list_without_native_scroll_panels(self):
        from app import QSS, QListWidget
        manual = {'topic': 'Saved topic', 'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
                  'prompt': 'Saved prompt', 'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
                  'source_ref': 'test'}
        self.store.add('Saved topic', 'manual', 'Saved request', manual)
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.show()
        try:
            window.history.showPopup()
            self.app.processEvents()
            popup = window.history._popup_frame
            listing = popup.findChild(QListWidget)
            self.assertEqual(listing.count(), 2)
            listing.itemClicked.emit(listing.item(1))
            self.assertFalse(popup.isVisible())
            self.assertEqual(window.thoughts.toPlainText(), 'Saved request')
            self.assertEqual(window.prompt_edit.toPlainText(), 'Saved prompt')
            window.history.showPopup()
            self.app.processEvents()
            self.assertTrue(window.history._popup_frame.isVisible())
            window.history.hidePopup()
        finally:
            window.close()

    def test_variant_segments_are_exclusive_and_reach_pipeline(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
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
        from app import TechniqueItem, QDialog, QLabel, QTimer
        source = {'title': 'Prompting paper', 'url': 'https://archive.org/download/example/paper.pdf#page=12', 'reference': 'p. 12'}
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

    def test_input_fields_do_not_overlap_when_window_is_shrunk(self):
        from app import QLabel, QSS
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.setStyleSheet(QSS)
            window.show()
            for width, height in ((672, 640), (932, 820)):
                window.resize(width, height)
                self.app.processEvents()
                def rect(widget):
                    return widget.geometry().translated(widget.parentWidget().mapTo(window, widget.parentWidget().rect().topLeft()))
                labels = [x for x in window.thoughts.parent().findChildren(QLabel) if x.isVisible() and x.text()]
                self.assertTrue(labels)
                for label in labels:
                    self.assertFalse(rect(label).intersects(rect(window.thoughts)), label.text())
                    needed = label.heightForWidth(label.width()) if label.wordWrap() else label.sizeHint().height()
                    self.assertGreaterEqual(label.height(), needed, label.text())
                self.assertTrue(window.technique.isVisible())
                self.assertGreater(rect(window.technique).top(), rect(window.thoughts).bottom())
        finally:
            window.close()

    def test_loading_history_does_not_require_write_access(self):
        self.store.add('Test', 'manual', 'Synthetic', {'prompt': 'Saved'})
        before = self.store.path.read_bytes()
        with patch.object(self.store, '_connect', side_effect=AssertionError('Read must not use write connection')):
            self.assertEqual(len(self.store.load()), 1)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_corrupt_history_is_not_overwritten(self):
        self.store.path.write_bytes(b'broken database')
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertFalse(window.history_notice.isHidden())
        self.assertEqual(self.store.path.read_bytes(), b'broken database')
        window.close()

    def test_api_settings_and_thoughts_label(self):
        from app import QLabel, QLineEdit
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        labels = {label.text(): label for label in window.findChildren(QLabel)}
        self.assertNotIn('THOUGHTS', labels)
        self.assertEqual(window.thoughts.placeholderText(), 'Describe what you need')
        self.assertEqual(window.thoughts.accessibleName(), 'Thoughts')
        self.assertFalse(window.settings_button.icon().isNull())
        self.assertTrue(window.settings_dialog.isAncestorOf(window.api_key))
        for control in (window.provider, window.model, window.refresh_button, window.models_hint):
            self.assertTrue(window.settings_dialog.isAncestorOf(control))
            self.assertFalse(control.isVisibleTo(window))
        self.assertEqual(window.api_key.echoMode(), QLineEdit.EchoMode.Password)
        window.settings_button.click()
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertTrue(window.provider.isVisible())
        self.assertTrue(window.model.isVisible())

        window.api_key.setText('synthetic-test-key')
        window.settings_dialog.accept()
        self.assertFalse(window.settings_dialog.isVisible())
        window.thoughts.setPlainText('Synthetic test')
        window.provider.set_current('openai')
        window.model.set_current('synthetic-model')
        with patch('app.Worker') as worker_type:
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertEqual(payload['apiKey'], 'synthetic-test-key')
            self.assertEqual(payload['model'], 'synthetic-model')
            self.assertEqual(payload['provider'], 'openai')
        self.assertFalse(self.store.path.exists())
        window.close()

    def test_library_contains_prompt_sources_only_and_filters_them(self):
        from app import ROOT
        from library import library_entries, read_material
        entries = library_entries(ROOT)
        paths = {e['path'] for e in entries}
        self.assertIn('catalog/catalog.json', paths)
        self.assertFalse([p for p in paths if p.startswith(('pipeline/', 'eval/', 'desktop/'))], 'no developer code or evaluation')
        self.assertFalse([p for p in paths if p.endswith(('.pdf', 'LICENSE', '.jinja', '.py', 'sources.json', 'coverage.json'))],
                         'no snapshots, licences, templates or tooling')
        for target in ('claude', 'chatgpt', 'gemini', 'grok'):
            self.assertIn(f'{target}_prompt_rules/rules.json', paths)
        cot = next(e for e in entries if e['title'].startswith('Chain-of-Thought'))
        self.assertTrue(cot['category'].startswith('Techniques · '))
        self.assertIn('When it hurts', read_material(ROOT, cot)[1], 'techniques read as pages, not JSON')
        claude = next(e for e in entries if e['category'] == 'Official rules' and e['title'] == 'Claude')
        self.assertIn('Applies:', read_material(ROOT, claude)[1])
        for entry in entries:
            self.assertTrue((ROOT / entry['path']).is_file(), entry['path'])
            self.assertNotIn('history.sqlite3', entry['path'])
            if entry.get('expected_hash'):
                self.assertIn('Matches saved source hash', read_material(ROOT, entry)[0])
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.settings_tabs.setCurrentIndex(1)
            self.assertEqual(window.settings_tabs.tabText(1), 'Library')
            self.assertTrue(window.library.preview.isReadOnly())
            self.assertTrue(window.library.info.text())
            window.library.search.setText('Grok')
            visible = []
            for i in range(window.library.tree.topLevelItemCount()):
                group = window.library.tree.topLevelItem(i)
                visible.extend(group.child(j).text(0) for j in range(group.childCount()) if not group.child(j).isHidden())
            self.assertTrue(any('Grok' in title for title in visible))
            self.assertNotIn('Technique catalog', visible)
        finally:
            window.close()

    def test_open_in_chatgpt_copies_full_prompt_and_uses_default_browser(self):
        from app import PromptEdit, QSS
        from urllib.parse import urlparse, parse_qs
        text = 'Напиши код: a & b? #1\nSecond line + 100%'
        editor = PromptEdit(text, None, "chatgpt")
        editor.resize(420, 200)
        editor.show()
        self.app.processEvents()
        try:
            with patch('app.QGuiApplication.clipboard') as clipboard, patch('app.QDesktopServices.openUrl', return_value=True) as browser:
                editor.chat_button.click()
                clipboard.return_value.setText.assert_called_once_with(text)
                url = browser.call_args.args[0].toString()
                self.assertEqual(urlparse(url).netloc, 'chatgpt.com')
                self.assertEqual(parse_qs(urlparse(url).query)['q'], [text])
            self.assertTrue(editor.rect().contains(editor.chat_button.geometry()))
            self.assertGreater(editor.chat_button.x(), editor.viewport().geometry().right())
            self.assertFalse(editor.chat_button.geometry().intersects(editor.copy_button.geometry()))
        finally:
            editor.close()

    def test_browser_button_matches_prompt_target(self):
        from app import PromptEdit
        for target, expected in (
            (None, None),
            ("openModel", None),
            ("claude", "https://claude.ai/new"),
            ("gemini", "https://gemini.google.com/app"),
            ("grok", "https://grok.com/"),
        ):
            with self.subTest(target=target):
                editor = PromptEdit("Prompt text", None, target)
                if expected is None:
                    self.assertFalse(hasattr(editor, "chat_button"))
                else:
                    with patch('app.QGuiApplication.clipboard') as clipboard, patch('app.QDesktopServices.openUrl', return_value=True) as browser:
                        editor.chat_button.click()
                        clipboard.return_value.setText.assert_called_once_with("Prompt text")
                        self.assertEqual(browser.call_args.args[0].toString(), expected)
                editor.close()

    def test_popups_and_dialogs_share_the_same_animation(self):
        from app import PopupAnimation, QDialog, QFrame, Qt, QEvent, QEasingCurve
        animation_filter = PopupAnimation()
        for popup in (QDialog(), QFrame(None, Qt.WindowType.Popup)):
            with patch('app.QApplication.platformName', return_value='cocoa'), patch('widgets.QPropertyAnimation') as animation, patch.object(popup, 'setWindowOpacity'):
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Show))
                animation.assert_called_once_with(popup, b'windowOpacity', popup)
                animation.return_value.setDuration.assert_called_once_with(160)
                animation.return_value.setEasingCurve.assert_called_once_with(QEasingCurve.Type.OutCubic)
                animation.return_value.start.assert_called_once()
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Hide))
                animation.return_value.stop.assert_called_once()
            popup.close()

    def test_clear_workspace_preserves_settings_history_and_discards_pending_result(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.thoughts.setPlainText('Draft to clear')
            window.chatgpt_only.setChecked(True)
            window.variants.setValue(5)
            window.api_key.setText('synthetic-key')
            window.history_search.setText('filter')
            window._history_items.append({'label': 'Saved', 'thoughts': 'Saved task', 'payload': {}, 'created_at': '2026-11-06'})
            worker = Mock()
            worker.isRunning.return_value = True
            window.worker = worker
            window.clear_button.click()
            worker.cancel.assert_called_once()
            self.assertEqual(window.thoughts.toPlainText(), '')
            self.assertEqual(window.history_search.text(), '')
            self.assertEqual(window.history.currentIndex(), 0)
            self.assertEqual(len(window._history_items), 1)
            self.assertTrue(window.chatgpt_only.isChecked())
            self.assertEqual(window.variants.value(), 5)
            self.assertEqual(window.api_key.text(), 'synthetic-key')
            self.assertTrue(window.generation_progress.isHidden())
            with patch.object(window, 'render') as render, patch.object(window, '_push_history') as save:
                window.on_finished({'ok': True, 'result': {}})
                render.assert_not_called()
                save.assert_not_called()
            self.assertTrue(window.run_button.isEnabled())
            self.assertNotEqual(window.status.text(), 'Done')
        finally:
            window.worker = None
            window.close()

    def test_whisper_updates_preserve_thoughts_and_restore_microphone(self):
        from app import ThoughtsEdit
        import json
        editor = ThoughtsEdit()
        editor.setPlainText('Existing thoughts')
        process = Mock()
        chunks = [json.dumps({'state': 'recording'}) + '\n',
                  json.dumps({'state': 'transcribing'}) + '\n' + json.dumps({'state': 'done', 'text': 'Распознанная речь'}) + '\n']
        process.readAllStandardOutput.side_effect = [chunk.encode() for chunk in chunks]
        editor.voice_process = process
        editor._voice_output()
        self.assertEqual(editor.voice_state, 'recording')
        editor._toggle_dictation()
        process.write.assert_called_once_with(b'stop\n')
        self.assertFalse(editor.microphone_icon.isEnabled())
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nРаспознанная речь')
        editor._voice_finished()
        self.assertIsNone(editor.voice_process)
        self.assertTrue(editor.microphone_icon.isEnabled())
        process.deleteLater.assert_called_once()
        editor.close()

    def test_dictation_shows_text_live_and_keeps_only_the_final(self):
        from app import ThoughtsEdit
        import json
        editor = ThoughtsEdit()
        editor.setPlainText('Existing thoughts')
        process = Mock()
        events = [{'state': 'recording'}, {'state': 'partial', 'text': 'Привет'}, {'state': 'partial', 'text': 'Привет мир как'},
                  {'state': 'transcribing'}, {'state': 'done', 'text': 'Привет, мир, как дела?'}]
        process.readAllStandardOutput.side_effect = [(json.dumps(e) + '\n').encode() for e in events]
        editor.voice_process = process
        editor._voice_output()
        self.assertTrue(editor.isReadOnly(), 'no typing into text that is still being recognised')
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет')
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет мир как', 'the live text is replaced, not appended')
        editor._voice_output()
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет, мир, как дела?')
        editor._voice_finished()
        self.assertFalse(editor.isReadOnly())
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет, мир, как дела?')

        editor.setPlainText('Draft')
        process.readAllStandardOutput.side_effect = [(json.dumps(e) + '\n').encode() for e in
                                                     [{'state': 'recording'}, {'state': 'partial', 'text': 'шум'}, {'state': 'error', 'message': 'x'}]]
        editor.voice_process = process
        for _ in range(3):
            editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Draft', 'a failed dictation leaves the request as it was')
        self.assertFalse(editor.isReadOnly())
        editor.close()

    def test_open_model_dropdown_excludes_other_targets_and_routes_request(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            self.assertEqual(sum(1 for i in range(window.prompt_model.count()) if window.prompt_model.itemData(i)), 15)
            window.chatgpt_only.setChecked(True)
            window.prompt_model.setCurrentIndex(window.prompt_model.findData('kimi-k3-1-pro'))
            self.assertFalse(window.chatgpt_only.isChecked())
            self.assertEqual(window._selected_target(), 'openModel')
            self.assertFalse(window.technique.isEnabled())
            window.thoughts.setPlainText('Build a small snake game')
            window.model.set_current('test-model')
            with patch('app.Worker') as worker:
                window.run_pipeline()
                payload = worker.call_args.args[0]
                self.assertEqual(payload['openModel'], window.prompt_model.currentData())
                self.assertFalse(payload['chatgptOnly'])
                self.assertNotIn('manualTechnique', payload)
            window.worker = None
            window.grok_only.setChecked(True)
            self.assertEqual(window.prompt_model.currentIndex(), 0)
            self.assertFalse(window.openModel_only.isChecked())
            window.grok_only.setChecked(False)
            self.assertTrue(window.technique.isEnabled())
        finally:
            window.close()

    def test_open_model_history_entry_restores_target_model(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            model_index = window.prompt_model.findData('glm-5-3')
            name = window.prompt_model.itemText(model_index)
            payload = {
                'brief': {'goal': 'g', 'task_type': 'generation', 'input': '', 'output_format': '',
                          'constraints': [], 'language': 'en', 'modality': 'text', 'stakes': 'low',
                          'assumptions': [], 'budget_calls': None},
                'choice': {'key': 'openModel_official', 'name': 'n', 'reason': 'r', 'confidence': 0.5, 'whyNotCheaper': 'w'},
                'synthesis': {'techniqueKey': 'k', 'prompt': 'p' * 50, 'missing': [], 'warnings': [],
                              'config': {'temperature': None, 'top_p': None, 'max_tokens': 'm', 'rationale': 'r'}},
                'rejected': [], 'trace': [],
                'openModelGuidance': {'target': name, 'rule_set_version': 'v', 'verified_at': '2026-01-01',
                                      'evidence_status': 'model-reported', 'variants': [], 'rules': []},
            }
            entry = {'label': 'x', 'kind': 'pipeline', 'thoughts': 't', 'created_at': '2026-01-01T00:00', 'payload': payload}
            window._history_items = [entry]
            window._filter_history()
            window.history.setCurrentIndex(1)
            self.assertEqual(window._selected_target(), 'openModel')
            self.assertEqual(window.prompt_model.currentIndex(), model_index)
            # An unknown model must not leave the hidden toggle on with an empty dropdown.
            payload['openModelGuidance']['target'] = 'No such model'
            window.history.setCurrentIndex(0)
            window.history.setCurrentIndex(1)
            self.assertIsNone(window._selected_target())
            self.assertEqual(window.prompt_model.currentIndex(), 0)
            self.assertTrue(window.technique.isEnabled())
        finally:
            window.close()

    def test_open_weight_library_has_fifteen_traceable_models(self):
        from app import ROOT
        from library import library_entries
        import json
        import hashlib
        root = ROOT / 'open_model_prompt_guides'
        models = json.loads((root / 'manifest.json').read_text())['models']
        self.assertEqual(len(models), 15)
        self.assertEqual(len({m['id'] for m in models}), 15)
        paths = {e['path'] for e in library_entries(ROOT)}
        for model in models:
            self.assertTrue(model['weight_files_present'])
            self.assertEqual(len(model['revision']), 40)
            self.assertIn(f"open_model_prompt_guides/{model['id']}/README.md", paths, 'the model card the prompt uses')
            for source in model['files']:
                path = root / source['snapshot']
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source['sha256'])
                self.assertTrue(source['url'].startswith('https://'))
                self.assertNotIn(path.suffix, ('.safetensors', '.bin', '.gguf'))

    def test_library_reports_changed_sources_missing_files_and_blocks_path_escape(self):
        from library import read_material, safe_path
        import hashlib
        root = Path(self.temp.name)
        path = root / 'source.md'
        path.write_text('Original')
        entry = {'path': 'source.md', 'expected_hash': hashlib.sha256(path.read_bytes()).hexdigest()}
        self.assertIn('Matches saved source hash', read_material(root, entry)[0])
        path.write_text('Changed')
        self.assertIn('SOURCE HASH MISMATCH', read_material(root, entry)[0])
        self.assertEqual(path.read_text(), 'Changed')
        self.assertIn('missing', read_material(root, {'path': 'missing.md'})[0])
        with self.assertRaises(ValueError):
            safe_path(root, '../outside.md')

    def test_claude_toggle_preserves_generator_and_excludes_generic_techniques(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertFalse(window.claude_only.isChecked())
        model = window.model.current_key()
        provider = window.provider.current_key()
        window.technique.set_current('zero_shot')
        window.claude_only.setChecked(True)
        self.assertFalse(window.technique.isEnabled())
        self.assertEqual(window.model.current_key(), model)
        self.assertEqual(window.provider.current_key(), provider)
        window.thoughts.setPlainText('Synthetic parity test')
        with patch('app.Worker') as worker_type:
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertTrue(payload['claudeOnly'])
            self.assertNotIn('deterministic', payload, 'the app never builds without the model')
            self.assertNotIn('manualTechnique', payload)
        window.claude_only.setChecked(False)
        self.assertTrue(window.technique.isEnabled())
        self.assertEqual(window.technique.current_key(), 'zero_shot')
        window.close()

    def test_assumptions_card_edits_the_brief_and_rebuilds_without_rebriefing(self):
        brief = {'goal': 'Find job titles', 'task_type': 'agentic', 'language': 'ru', 'stakes': 'medium', 'output_format': 'Report',
                 'assumptions': ['Leftover assumption', 'Senior roles only'],
                 'questions': [{'question': 'Which countries?', 'default': 'all of Europe'}, 'Which period?']}
        result = {'brief': brief, 'choice': {'key': 'zero_shot', 'name': 'Zero-shot', 'reason': 'r', 'confidence': 0.5},
                  'synthesis': {'prompt': 'Find job titles across Europe and report them with dates.', 'config': {'temperature': 0.2, 'top_p': 0.95, 'max_tokens': '1024'}, 'warnings': []},
                  'rejected': []}
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.thoughts.setPlainText("Find job titles")
        window.render(result)
        card = window.assumptions_card
        self.assertIsNot(card.parentWidget(), window.thoughts, 'its own block under the request, not inside the field')
        self.assertFalse(card.findChildren(QScrollArea), 'no scroll inside the card')
        self.assertFalse([e for e in window.findChildren(QPlainTextEdit)
                          if e.toPlainText() == 'Leftover assumption' and not card.isAncestorOf(e)],
                         'no second assumptions box beside the prompt')
        fields = [answer for _, answer in window.question_answers]
        self.assertEqual([f.text() for f in fields], ['all of Europe', ''], 'the assumed answer is shown as the value')
        self.assertEqual([row['field'].text() for row in window.assumption_rows], ['Leftover assumption', 'Senior roles only'])
        self.assertEqual(window.run_button.text(), window.build_label, 'no edits: an ordinary build')
        self.assertFalse([b for b in window.findChildren(QPushButton) if b.text().startswith('Rebuild')], 'no separate rebuild button')

        fields[0].setText('Germany')
        window.assumption_rows[0]['widget'].findChild(QPushButton, 'removeAssumption').click()
        window.add_assumption_button.click()
        window.assumption_rows[-1]['field'].setText('Include direct sources')
        fields[1].setText('last 12 months')
        self.assertTrue(window.run_button.text().startswith('Rebuild · 4 changes'), 'the one button says what it will do')
        with patch.object(window, 'run_pipeline') as run:
            revised = window._card_revision()
            window.run_button.click()
            run.assert_called_once_with()
            self.assertEqual(revised, {
                **brief,
                'assumptions': ['Senior roles only', 'Include direct sources'],
                'questions': [{'question': 'Which countries?', 'default': 'Germany'},
                              {'question': 'Which period?', 'default': 'last 12 months'}],
            })
        self.assertEqual(window.thoughts.toPlainText(), 'Find job titles', 'the request is left as typed')
        fields[0].setText('')
        self.assertEqual(window._card_revision()['questions'][0], {'question': 'Which countries?'},
                         'a cleared answer drops that assumption')
        with patch('app.Worker') as worker:
            window.model.set_current('test-model')
            window.worker = None
            window.run_pipeline()
            self.assertEqual(worker.call_args.args[0]['brief']['assumptions'], ['Senior roles only', 'Include direct sources'],
                             'Build sends the edited brief')
            self.assertEqual(window.run_button.text(), 'Stop', 'the same button stops a running build')
            window.worker = None
        window.thoughts.setPlainText('Find job titles in Asia')
        self.assertEqual(window.run_button.text(), window.build_label, 'a changed request is a fresh build')
        self.assertIsNone(window._card_revision())
        window.clear_workspace()
        self.assertIsNone(window.assumptions_card, 'a new request starts without old questions')
        window.close()

    def test_claude_sources_and_mode_survive_history_restart_without_api_key(self):
        from app import QLabel
        config = {'temperature': None, 'top_p': None, 'max_tokens': 'Model-dependent', 'rationale': 'Target-specific'}
        choice = {'key': 'claude_official', 'name': 'Claude guidance', 'reason': 'Official rules', 'confidence': 0.5, 'whyNotCheaper': 'Separate mode'}
        result = {
            'brief': {'goal': 'Parity', 'task_type': 'classification', 'language': 'en', 'stakes': 'low', 'output_format': 'JSON', 'assumptions': []},
            'choice': choice, 'synthesis': {'prompt': 'Classify 2, 3, 4 by parity. Return JSON and acknowledge missing inputs.', 'config': config, 'warnings': []},
            'rejected': [], 'claudeGuidance': {'rule_set_version': 'test-version', 'verified_at': '2026-11-05',
                'variants': [{'rule_ids': ['clear']}],
                'rules': [{'id': 'clear', 'source_section': 'Be clear and direct', 'rule_text': 'Be clear',
                           'source_url': 'https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#be-clear-and-direct'}]},
        }
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            first = PromptaWindow()
        first.thoughts.setPlainText('Synthetic parity request')
        first.api_key.setText('synthetic-secret-not-for-history')
        first.on_finished({'ok': True, 'result': result})
        self.assertTrue(any('href=' in label.text() for label in first.findChildren(QLabel)))
        first.close()
        self.assertNotIn(b'synthetic-secret-not-for-history', self.store.path.read_bytes())
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            reopened = PromptaWindow()
        reopened.history_search.setText('test-version')
        reopened.history.setCurrentIndex(1)
        self.assertTrue(reopened.claude_only.isChecked())
        self.assertFalse(reopened.technique.isEnabled())
        self.assertEqual(reopened.thoughts.toPlainText(), 'Synthetic parity request')
        self.assertEqual(reopened._history_items[0]['payload']['claudeGuidance']['rule_set_version'], 'test-version')
        reopened.close()

    def test_history_shows_short_topic_but_keeps_full_request_searchable(self):
        query = 'Я хочу чтобы нейросеть разбирала заметки встреч и находила уникальный_срок'
        payload = {'brief': {'topic': 'Итоги встреч', 'goal': 'Извлечение решений задач ответственных из заметок встреч'}}
        self.store.add('Old technique label', 'pipeline', query, payload)
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertEqual(window.history.itemText(1), 'Итоги встреч')
        window.history_search.setText('уникальный_срок')
        self.assertEqual(window.history.count(), 2)
        self.assertEqual(self.store.load()[0]['thoughts'], query)
        self.assertEqual(history_topic('I want an AI prompt for meeting notes extraction', {}), 'I want an AI prompt for meeting notes extraction')
        self.assertEqual(history_topic('', {'brief': {'goal': 'Полное название старого результата'}}), 'Полное название старого результата')
        self.assertEqual(history_topic('', {'topic': 'Платформер на Pygame'}), 'Платформер на Pygame')
        self.assertEqual(history_topic('', {}, 'Saved prompt'), 'Saved prompt')
        window.close()

    def test_target_checkboxes_are_exclusive_and_keep_generator_model(self):
        for target in ('chatgpt', 'gemini', 'grok'):
            with self.subTest(target=target):
                with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
                    window = PromptaWindow()
                model, provider = window.model.current_key(), window.provider.current_key()
                self.assertFalse(window.chatgpt_only.isChecked())
                self.assertFalse(window.gemini_only.isChecked())
                window.technique.set_current('zero_shot')
                window.claude_only.setChecked(True)
                getattr(window, f'{target}_only').setChecked(True)
                self.assertFalse(window.claude_only.isChecked())
                self.assertEqual(window._selected_target(), target)
                self.assertFalse(window.technique.isEnabled())
                self.assertEqual(window.model.current_key(), model)
                self.assertEqual(window.provider.current_key(), provider)
                window.thoughts.setPlainText('Synthetic parity task')
                with patch('app.Worker') as worker_type:
                    window.run_pipeline()
                    payload = worker_type.call_args.args[0]
                    for key in ('claude', 'chatgpt', 'gemini', 'grok'):
                        self.assertEqual(payload[f'{key}Only'], key == target)
                    self.assertNotIn('deterministic', payload, 'the app never builds without the model')
                    self.assertNotIn('manualTechnique', payload)
                    self.assertEqual(payload['model'], model)
                getattr(window, f'{target}_only').setChecked(False)
                self.assertTrue(window.technique.isEnabled())
                self.assertEqual(window.technique.current_key(), 'zero_shot')
                window.close()

    def test_chatgpt_and_gemini_history_restore_their_own_sources_and_target(self):
        from app import QLabel
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        for target, source in (
            ('chatgpt', 'https://learn.chatgpt.com/docs/prompting#prompts'),
            ('gemini', 'https://aistudio.google.com/docs/prompting-strategies#clear-and-specific-instructions'),
            ('grok', 'https://docs.x.ai/developers/model-capabilities/text/best-practices#design-the-eval'),
        ):
            window.thoughts.setPlainText(f'{target} synthetic parity task')
            window.api_key.setText('synthetic-key-not-for-storage')
            window.on_finished({'ok': True, 'result': {
                'brief': {'goal': f'{target} parity classification', 'task_type': 'classification', 'language': 'en', 'stakes': 'low', 'output_format': 'JSON', 'assumptions': []},
                'choice': {'key': target + '_official', 'name': target, 'confidence': 0.5, 'reason': 'Official rules', 'whyNotCheaper': 'Target mode'},
                'synthesis': {'prompt': 'Classify the supplied integers and return JSON; flag missing data.', 'config': {'temperature': None, 'top_p': None, 'max_tokens': 'Model-dependent', 'rationale': 'Target settings'}, 'warnings': []},
                'rejected': [], f'{target}Guidance': {'target': target, 'rule_set_version': 'test-version', 'verified_at': '2026-11-05',
                    'variants': [{'rule_ids': ['clear']}], 'rules': [{'id': 'clear', 'rule_text': 'Be clear', 'source_url': source, 'source_section': 'Prompting'}]},
            }})
        window.close()
        self.assertNotIn(b'synthetic-key-not-for-storage', self.store.path.read_bytes())
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            reopened = PromptaWindow()
        for target in ('chatgpt', 'gemini', 'grok'):
            reopened.history_search.setText(target)
            self.assertEqual(reopened.history.count(), 2)
            self.assertLessEqual(len(reopened.history.itemText(1).split()), 4)
            reopened.history.setCurrentIndex(1)
            self.assertEqual(reopened._selected_target(), target)
            self.assertEqual(reopened.thoughts.toPlainText(), f'{target} synthetic parity task')
            self.assertTrue(any('href=' in label.text() for label in reopened.output_holder.findChildren(QLabel) if label.isVisibleTo(reopened.output_holder)))
        reopened.close()

    def test_cancel_before_launch_does_not_spawn(self):
        worker = Worker({})
        responses = []
        worker.finished_ok.connect(responses.append)
        worker.cancel()
        with patch('app.subprocess.Popen') as spawn:
            worker.run()
        spawn.assert_not_called()
        self.assertEqual(responses, [{'ok': False, 'error': 'Cancelled'}])

    def test_worker_streams_real_progress_before_result(self):
        import sys
        from PyQt6.QtCore import Qt
        spawn = subprocess.Popen
        script = """
import json, sys, time
request = json.load(sys.stdin)
print('PROMPTA_PROGRESS {"percent":20,"stage":"Brief ready"}', file=sys.stderr, flush=True)
print('PROMPTA_PROGRESS invalid', file=sys.stderr, flush=True)
time.sleep(0.15)
print(json.dumps({'ok': True, 'streaming': request['reportProgress']}), flush=True)
"""
        worker = Worker({})
        progress, responses = [], []
        worker.progress.connect(lambda value, stage: progress.append((value, stage, worker.proc.poll())),
                                Qt.ConnectionType.DirectConnection)
        worker.finished_ok.connect(responses.append)
        def child(*args, **kwargs):
            return spawn([sys.executable, '-c', script], **kwargs)
        with patch('app.subprocess.Popen', side_effect=child):
            worker.run()
        self.assertEqual(progress, [(20, 'Brief ready', None)])
        self.assertEqual(responses, [{'ok': True, 'streaming': True}])

    def test_timeout_kills_and_reaps_process(self):
        from io import StringIO
        proc = Mock()
        proc.stderr = StringIO('')
        proc.communicate.side_effect = [subprocess.TimeoutExpired('node', 900), ('', '')]
        proc.poll.side_effect = [None, 0]
        worker = Worker({})
        responses = []
        worker.finished_ok.connect(responses.append)
        with patch('app.subprocess.Popen', return_value=proc):
            worker.run()
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.call_count, 2)
        self.assertFalse(responses[0]['ok'])

    def test_sources_window_shows_a_short_description_of_each_source(self):
        import json
        from app import QDialog, QLabel, TechniqueItem
        links = json.loads((Path(__file__).resolve().parent.parent / 'catalog' / 'source-links.json').read_text())
        self.assertTrue(all(any(s.get('summary') for s in v) for v in links.values()), 'every technique has a described source')
        item = TechniqueItem('chain_of_thought', 'Chain-of-Thought', 'hint', links['chain_of_thought'])
        shown = []
        with patch.object(QDialog, 'exec', lambda dialog: shown.extend(l.text() for l in dialog.findChildren(QLabel) if l.objectName() == 'sourceSummary')):
            item._show_sources('Chain-of-Thought')
        self.assertTrue(shown and shown[0].startswith('We explore how generating a chain of thought'), shown[:1])
        self.assertTrue(all(2 <= t.count('. ') + 1 <= 6 for t in shown), 'a few sentences each')

    def test_hover_hints_use_the_app_popup_not_the_system_tooltip(self):
        from app import HintFilter, QListWidget, QListWidgetItem, QPushButton
        from PyQt6.QtCore import QEvent, QPoint
        from PyQt6.QtGui import QHelpEvent
        hints = HintFilter(self.app)
        button = QPushButton('Build')
        button.setToolTip('Build a prompt from the official documentation.')
        button.show()
        event = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), button.mapToGlobal(QPoint(5, 5)))
        self.assertTrue(hints.eventFilter(button, event), 'the system tooltip is suppressed')
        self.assertTrue(hints.popup.isVisible())
        self.assertEqual(hints.popup.text(), 'Build a prompt from the official documentation.')
        hints.eventFilter(button, QEvent(QEvent.Type.Leave))
        self.assertFalse(hints.popup.isVisible())
        listing = QListWidget()
        item = QListWidgetItem('Row', listing)
        item.setToolTip('Row details')
        listing.show()
        self.cls_app_process()
        pos = listing.visualItemRect(item).center()
        hints.eventFilter(listing.viewport(), QHelpEvent(QEvent.Type.ToolTip, pos, listing.viewport().mapToGlobal(pos)))
        self.assertEqual(hints.popup.text(), 'Row details', 'list rows get the same hint')
        hints.hide()
        button.close()
        listing.close()

    def test_prompt_block_is_editable_and_copies_the_edit(self):
        from app import PromptEdit, QGuiApplication
        editor = PromptEdit('Original prompt text that is long enough.', None)
        self.assertFalse(editor.isReadOnly())
        editor.fit_to_content()
        editor.resize(420, 200)
        editor.show()
        self.cls_app_process()
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        editor.insertPlainText(' Edited by me.' + '\nline' * 30)
        self.cls_app_process()
        self.assertGreater(editor.height(), PromptEdit.FIT_MIN, 'the block grows with the edit')
        editor._copy()
        self.assertTrue(QGuiApplication.clipboard().text().startswith('Original prompt text that is long enough. Edited by me.'))
        editor.close()

    def test_each_variant_copies_its_own_prompt(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        config = {'temperature': 0.2, 'top_p': 0.95, 'max_tokens': '1024', 'rationale': 'test'}
        choice = {'name': 'Test', 'key': 'test', 'confidence': 1, 'reason': 'test', 'whyNotCheaper': 'test'}
        def synthesis(text):
            return {'prompt': text, 'config': config, 'warnings': []}
        window.render({
            'brief': {'goal': 'test', 'task_type': 'classification', 'language': 'ru',
                      'stakes': 'low', 'output_format': 'JSON', 'assumptions': []},
            'choice': choice, 'synthesis': synthesis('First prompt'), 'rejected': [],
            'alternatives': [
                {'choice': choice, 'synthesis': synthesis('Second prompt')},
                {'choice': choice, 'synthesis': synthesis('Third prompt')},
            ],
        })
        from app import QPlainTextEdit
        editors = window.output_holder.findChildren(QPlainTextEdit)
        self.assertEqual(len(editors), 4)
        zero = [editor for editor in editors if editor.accessibleName() == 'Zero-shot baseline prompt']
        self.assertEqual(len(zero), 1)
        self.assertNotIn('First prompt', zero[0].toPlainText())
        variants = sorted((editor for editor in editors if editor not in zero), key=lambda editor: editor.toPlainText())
        self.assertEqual([editor.toPlainText() for editor in variants], ['First prompt', 'Second prompt', 'Third prompt'])
        buttons = [editor.copy_button for editor in variants]
        self.assertEqual(len(buttons), 3)
        window.show()
        self.app.processEvents()
        for editor in editors:
            button = editor.copy_button
            self.assertEqual(button.text(), '')
            self.assertFalse(button.icon().isNull())
            self.assertTrue(editor.rect().contains(button.geometry()))
            self.assertGreater(button.geometry().left(), editor.viewport().geometry().right())
            self.assertLess(editor.viewport().geometry().top(), 20)
        clipboard = Mock()
        with patch('app.QGuiApplication.clipboard', return_value=clipboard):
            zero[0].copy_button.click()
            clipboard.setText.assert_called_with(zero[0].toPlainText())
            for index in (2, 0, 1, 2):
                buttons[index].click()
                clipboard.setText.assert_called_with(['First prompt', 'Second prompt', 'Third prompt'][index])
        window.close()

    def test_manual_history_error_and_input_validation(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.run_pipeline()
        self.assertIsNone(window.worker)
        self.assertEqual(window.status.text(), 'Enter your thoughts')
        manual = {
            'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
            'prompt': 'Синтетический промпт для классификации чётных и нечётных чисел.',
            'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
            'source_ref': 'test',
        }
        window.on_finished({'ok': True, 'manual': manual})
        self.assertEqual(window.history.count(), 2)
        self.assertEqual(window.prompt_edit.toPlainText(), manual['prompt'])
        window.on_finished({'ok': False, 'error': 'synthetic error'})
        self.assertTrue(window.run_button.isEnabled())
        self.assertFalse(window.cancel_button.isEnabled())
        window._on_history_selected(1)
        self.assertEqual(window.prompt_edit.toPlainText(), manual['prompt'])
        window.close()

    def _prompta_window(self):
        with patch.object(PromptaWindow, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            return PromptaWindow()

    def test_prompt_edits_are_saved_to_history_and_survive_restart(self):
        from PyQt6.QtWidgets import QTabWidget
        manual = {'zeroShotPrompt': 'Task: original baseline prompt for the saved task.', 'topic': 'Saved task',
                  'technique': {'key': 'a', 'name': 'Alpha', 'category': 'test'}, 'prompt': 'ALPHA original prompt text, long enough.',
                  'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'}, 'source_ref': 's',
                  'variants': [{'technique': {'key': 'a', 'name': 'Alpha', 'category': 'test'}, 'prompt': 'ALPHA original prompt text, long enough.',
                                'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'}, 'source_ref': 's'},
                               {'technique': {'key': 'b', 'name': 'Beta', 'category': 'test'}, 'prompt': 'BETA original prompt text, long enough.',
                                'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'}, 'source_ref': 's'}]}
        window = self._prompta_window()
        try:
            window.thoughts.setPlainText('Saved task')
            window.on_finished({'ok': True, 'manual': manual})
            tabs = window.output_scroll.widget().findChild(QTabWidget)
            tabs.widget(2).setPlainText('BETA edited by the user, long enough to keep.')
            tabs.widget(0).setPlainText('Zero-shot edited by the user, long enough.')
            window._edit_timer.stop()
            window._save_prompt_edits()
        finally:
            window.close()
        saved = self.store.load()[-1]['payload']
        self.assertEqual(saved['variants'][1]['prompt'], 'BETA edited by the user, long enough to keep.')
        self.assertEqual(saved['zeroShotPrompt'], 'Zero-shot edited by the user, long enough.')
        self.assertEqual(saved['prompt'], 'ALPHA original prompt text, long enough.', 'untouched variants stay as built')
        reopened = self._prompta_window()
        try:
            reopened.history.setCurrentIndex(reopened.history.findData(len(reopened._history_items) - 1))
            tabs = reopened.output_scroll.widget().findChild(QTabWidget)
            self.assertEqual(tabs.widget(2).toPlainText(), 'BETA edited by the user, long enough to keep.')
            self.assertTrue(tabs.widget(2).is_edited() and tabs.widget(2).restore.isVisibleTo(tabs.widget(2)))
            self.assertTrue(tabs.tabText(2).endswith('•'), 'the tab shows the variant was edited')
            self.assertFalse(tabs.widget(1).is_edited())
            tabs.widget(2).restore.click()
            self.assertEqual(tabs.widget(2).toPlainText(), 'BETA original prompt text, long enough.')
            self.assertFalse(tabs.tabText(2).endswith('•'))
            reopened._edit_timer.stop()
            reopened._save_prompt_edits()
        finally:
            reopened.close()
        saved = self.store.load()[-1]['payload']
        self.assertEqual(saved['variants'][1]['prompt'], 'BETA original prompt text, long enough.')
        self.assertEqual(saved['originalPrompts'], {'0': 'Task: original baseline prompt for the saved task.'}, 'only the still-edited variant keeps an original')

    def test_target_switch_drives_hidden_toggles_and_request(self):
        window = self._prompta_window()
        try:
            window.thoughts.setPlainText('Build a snake game')
            window.model.set_current('test-model')
            buttons = {b.property('target'): b for b in window.segments.buttons()}
            self.assertEqual([b.text() for b in window.segments.buttons()], ['Any', 'Claude', 'ChatGPT', 'Gemini', 'Grok', 'Hermes', 'Open'])
            self.assertTrue(buttons['general'].isChecked())

            def payload():
                with patch('app.Worker') as worker:
                    window.worker = None
                    window.run_pipeline()
                    return worker.call_args.args[0]

            request = payload()
            self.assertEqual(request['executionProfile'], 'universal')
            self.assertNotIn('agentCapabilities', request)
            window.execution_profile.set_current('agent')
            self.assertEqual(payload()['agentCapabilities'], ['code', 'files', 'integrations', 'web'], 'an agent has every tool')
            window.execution_profile.set_current('universal')
            buttons['claude'].click()
            self.assertTrue(payload()['claudeOnly'])
            self.assertFalse(window.technique.isEnabled())
            buttons['grok'].click()
            request = payload()
            self.assertTrue(request['grokOnly'])
            self.assertFalse(request['claudeOnly'])
            buttons['hermes'].click()
            request = payload()
            self.assertTrue(request['hermesOnly'])
            self.assertFalse(request['grokOnly'])
            self.assertFalse(window.technique.isEnabled())
            window.prompt_model.setCurrentIndex(window.prompt_model.findData('glm-5-3'))
            request = payload()
            self.assertFalse(request['hermesOnly'])
            self.assertEqual(request['openModel'], window.prompt_model.currentData())
            self.assertEqual([b.property('target') for b in window.segments.buttons() if b.isChecked()], ['openModel'])
            self.assertFalse(window.prompt_model.isVisibleTo(window), 'one control: no second open-model field')
            self.assertIn(window.prompt_model.currentText(), window.open_caption.text(), 'the chosen model is named under the switch')
            self.assertTrue(window.open_caption.isVisibleTo(window))
            buttons['general'].click()
            request = payload()
            self.assertFalse(any(request[k] for k in ('claudeOnly', 'chatgptOnly', 'geminiOnly', 'grokOnly')))
            self.assertNotIn('openModel', request)
            self.assertTrue(window.technique.isEnabled())
            # History restore sets the hidden toggles directly; the switch must follow.
            window.chatgpt_only.setChecked(True)
            self.assertTrue(buttons['chatgpt'].isChecked())
        finally:
            window.close()

    def test_result_shows_prompt_first_with_variant_tabs_and_folded_details(self):
        from app import Disclosure, PromptEdit, QTabWidget
        window = self._prompta_window()
        try:
            synthesis = lambda prompt: {'prompt': prompt, 'warnings': ['careful'], 'missing': [],
                                        'config': {'temperature': 0.2, 'top_p': 0.9, 'max_tokens': '1k', 'rationale': 'r'}}
            choice = lambda name: {'key': name, 'name': name, 'reason': 'because', 'confidence': 0.7, 'whyNotCheaper': 'w'}
            window.render({
                'brief': {'topic': 'Snake game', 'goal': 'Write a snake game', 'task_type': 'coding', 'language': 'en',
                          'stakes': 'low', 'output_format': 'code', 'assumptions': []},
                'choice': choice('Code prompting'), 'synthesis': synthesis('FIRST PROMPT ' * 5),
                'alternatives': [{'choice': choice('Few-shot'), 'synthesis': synthesis('SECOND PROMPT ' * 5)}],
                'zeroShotPrompt': 'Task: snake', 'rejected': [],
            })
            self.cls_app_process()
            widgets = [window.output_layout.itemAt(i).widget() for i in range(window.output_layout.count())]
            tabs = next(w for w in widgets if isinstance(w, QTabWidget))
            details = next(w for w in widgets if isinstance(w, Disclosure))
            self.assertLess(widgets.index(tabs), widgets.index(details))
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['No technique', 'Code prompting', 'Few-shot'])
            self.assertEqual(tabs.currentIndex(), 1, 'the built prompt is shown first')
            self.assertEqual(tabs.widget(0).toPlainText(), 'Task: snake')
            self.assertIn('FIRST PROMPT', window.prompt_edit.toPlainText())
            self.assertIn('SECOND PROMPT', tabs.widget(2).toPlainText())
            self.assertTrue(details.body.isVisibleTo(window), 'details are open by default')
            self.assertEqual(details.title(), 'How this prompt was built')
            self.assertEqual(details.body.findChildren(PromptEdit), [], 'zero-shot moved out of the details')
            def shown():
                return [l.text() for l in details.body.findChildren(QLabel) if l.isVisibleTo(window)]
            meta = next(w for w in widgets if isinstance(w, QLabel) and w.objectName() == 'meta')
            first_reason = [l for l in details.body.findChildren(QLabel) if l.text() == 'because' and l.isVisibleTo(window)]
            self.assertEqual(len(first_reason), 1, 'only the shown variant explains itself')
            self.assertTrue(meta.text().startswith('Code prompting'))
            self.assertTrue(tabs.widget(1).spec.text().startswith('temp '), 'run settings sit in the prompt block')
            self.assertIsNone(tabs.widget(0).spec, 'zero-shot has no run settings')
            tabs.setCurrentIndex(2)
            second_reason = [l for l in details.body.findChildren(QLabel) if l.text() == 'because' and l.isVisibleTo(window)]
            self.assertEqual(len(second_reason), 1)
            self.assertIsNot(first_reason[0], second_reason[0], 'switching tabs swaps the explanation')
            self.assertTrue(meta.text().startswith('Few-shot · confidence 70%'), 'header names the shown technique')
            tabs.setCurrentIndex(0)
            self.assertTrue(any(t.startswith('Zero-shot:') for t in shown()))
            self.assertNotIn('because', shown())
            self.assertIn('coding · low stakes · en', shown(), 'the shared brief stays under every tab')
        finally:
            window.close()

    def test_api_key_is_remembered_per_provider_only_when_asked(self):
        saved = {}
        fake = Mock(load=lambda provider: saved.get(provider, ''),
                    save=lambda provider, key: saved.__setitem__(provider, key) or True,
                    forget=lambda provider: saved.pop(provider, None))
        with patch.object(app_module, 'keychain', fake):
            window = self._prompta_window()
            try:
                window.provider.set_current('gemini', emit=True)
                self.assertEqual(window.api_key.text(), '')
                self.assertFalse(window.remember_key.isChecked(), 'off until the user asks')
                window.api_key.setText('gemini-key')
                window.remember_key.setChecked(True)
                self.assertEqual(saved, {'gemini': 'gemini-key'})
                window.provider.set_current('openai', emit=True)
                self.assertEqual(window.api_key.text(), '', 'each provider has its own key')
                window.provider.set_current('gemini', emit=True)
                self.assertEqual(window.api_key.text(), 'gemini-key')
                self.assertTrue(window.remember_key.isChecked())
                window.remember_key.setChecked(False)
                self.assertEqual(saved, {}, 'unchecking removes the saved key')
            finally:
                window.close()

    def test_history_built_under_older_rules_says_so(self):
        window = self._prompta_window()
        try:
            notes = lambda: [l for l in window.findChildren(QLabel) if l.text().startswith('Built with earlier Prompta rules')]
            window._flag_outdated({'promptVersion': 'v1'})
            self.assertFalse(notes(), 'unknown current version: no claim')
            window.prompt_version = 'v2'
            window._flag_outdated({'promptVersion': 'v2'})
            self.assertFalse(notes())
            window._flag_outdated({'promptVersion': 'v1'})
            self.assertEqual(len(notes()), 1)
            window._flag_outdated({})
            self.assertEqual(len(notes()), 2, 'results saved before versions were recorded are old too')
        finally:
            window.close()

    def test_open_needs_a_model_and_one_button_runs_and_stops(self):
        window = self._prompta_window()
        try:
            self.assertFalse([b for b in window.findChildren(QPushButton) if b.objectName() == 'example'], 'no empty-state examples')
            self.assertTrue(window.model_line.text())
            self.assertFalse(window.cancel_button.isVisibleTo(window), 'one button: Build turns into Stop')
            open_segment = window.segments.buttons()[-1]
            with patch.object(window.prompt_model, 'showPopup'):
                open_segment.click()
                self.assertFalse(window.advanced.isVisibleTo(window), 'techniques are for Any only')
                window.model.set_current('test-model')
                with patch('app.Worker') as worker:
                    window.run_pipeline()
                    worker.assert_not_called()
                self.assertEqual(window.status.text(), 'Choose an open-weight model')
        finally:
            window.close()

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
            self.assertIs(window.technique.parentWidget(), window.advanced.body)
            self.assertIs(window.variants.parentWidget(), window.advanced.body)
            self.assertTrue(window.advanced.body.isVisibleTo(window), 'Advanced never folds')
            self.assertEqual(window.advanced.title(), 'Technique')
            window.variants.buttons.button(2).click()
            self.assertEqual(window.advanced.title(), 'Technique', 'the heading stays put')
            self.assertEqual(window.variants.value(), 2)
            window.segments.buttons()[1].click()  # Claude
            self.assertFalse(window.advanced.isVisibleTo(window), 'techniques exist only for Any')
            self.assertEqual(window.variants.value(), 1)
            window.segments.buttons()[0].click()  # back to Any
            self.assertTrue(window.advanced.isVisibleTo(window))
            self.assertTrue(window.variants.isVisibleTo(window))
            self.assertEqual(window.variants.value(), 2, 'the count comes back')
            self.assertTrue(window.run_button.text().startswith('Build prompt'))
            self.assertEqual(window.status.text(), '')
        finally:
            window.close()

    def test_routine_notes_stay_folded_and_status_counts_only_visible_warnings(self):
        window = self._prompta_window()
        try:
            def result(warnings, guidance=None):
                data = {
                    'brief': {'goal': 'g', 'task_type': 'coding', 'language': 'en', 'stakes': 'low', 'output_format': 'code', 'assumptions': []},
                    'choice': {'key': 'k', 'name': 'Gemini · official guidance', 'reason': 'r', 'confidence': 0.5, 'whyNotCheaper': 'w'},
                    'synthesis': {'prompt': 'P' * 50, 'warnings': warnings, 'missing': [],
                                  'config': {'temperature': None, 'top_p': None, 'max_tokens': 'm', 'rationale': 'r'}},
                    'rejected': [],
                }
                if guidance:
                    data['geminiGuidance'] = guidance
                return data
            guidance = {'target': 'Gemini', 'rule_set_version': 'v', 'verified_at': 'd', 'variants': [], 'rules': []}
            note = 'General Gemini guidance. Rule usage is model-reported; source links do not independently prove output compliance.'
            window.on_finished({'ok': True, 'result': result([note], guidance)})
            self.assertEqual(window.status.text(), 'Gemini · official guidance · ready')
            visible = [w for w in window.output_holder.findChildren(QLabel, 'warn') if w.isVisibleTo(window)]
            self.assertEqual(visible, [])
            window.on_finished({'ok': True, 'result': result([note, 'Unfilled placeholders: examples'])})
            self.assertEqual(window.status.text(), 'Gemini · official guidance · 1 warning below the prompt')
            visible = [w.text() for w in window.output_holder.findChildren(QLabel, 'warn') if w.isVisibleTo(window)]
            self.assertEqual(visible, ['• Unfilled placeholders: examples'])
        finally:
            window.close()

    def test_technique_popup_selects_several_and_builds_one_prompt_each(self):
        from app import QTabWidget, TechniqueItem
        window = self._prompta_window()
        try:
            window._on_techniques_loaded([
                {'key': 'cot', 'name': 'Chain of thought', 'category': 'reasoning', 'status': 'ready'},
                {'key': 'few', 'name': 'Few-shot', 'category': 'icl', 'status': 'ready'},
                {'key': 'knn', 'name': 'KNN selection', 'category': 'procedure', 'status': 'procedure'},
            ])
            window.technique._open()
            popup = window.technique._popup
            items = {w.key: w for w in popup.findChildren(TechniqueItem)}
            items['cot'].clicked.emit('cot')
            items['few'].clicked.emit('few')
            self.assertTrue(popup.isVisible(), 'multi-select keeps the panel open')
            self.assertEqual(window.technique.current_keys(), ['cot', 'few'])
            self.assertTrue(items['few'].property('selected'))
            self.assertEqual(window.advanced.button.text(), 'TECHNIQUE', 'the selection shows in the field, not the heading')
            self.assertFalse(window.technique_label.isVisibleTo(window))
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
            window.model.set_current('test-model')
            with patch('app.Worker') as worker:
                window.run_pipeline()
                payload = worker.call_args.args[0]
            self.assertEqual(payload['manualTechniques'], ['few', 'cot'])
            self.assertNotIn('manualTechnique', payload)
            window.worker = None

            variant = lambda key, name: {'technique': {'key': key, 'name': name, 'category': 'x'}, 'prompt': f'{name} prompt ' * 6,
                                         'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'}, 'source_ref': 'src'}
            variants = [variant('few', 'Few-shot'), variant('cot', 'Chain of thought')]
            window.on_finished({'ok': True, 'manual': {**variants[0], 'topic': 'Recursion', 'zeroShotPrompt': 'Task',
                                                       'variants': variants, 'failed': [{'key': 'x', 'name': 'ToT', 'error': 'timeout'}]}})
            tabs = window.output_holder.findChild(QTabWidget, 'variantTabs')
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['No technique', 'Few-shot', 'Chain of thought'])
            self.assertIn('Chain of thought prompt', tabs.widget(2).toPlainText())
            self.assertEqual(tabs.widget(0).toPlainText(), 'Task')
            self.assertEqual(window.status.text(), '2 techniques built · 1 failed, see below the prompt')
            warn = [w.text() for w in window.output_holder.findChildren(QLabel, 'warn') if w.isVisibleTo(window)]
            self.assertEqual(warn, ['• Not built — ToT: timeout'])
            window.technique.set_current_keys(['cot'])
            with patch('app.Worker') as worker:
                window.run_pipeline()
                self.assertEqual(worker.call_args.args[0]['manualTechnique'], 'cot')
        finally:
            window.close()

    def test_history_is_a_standard_picker_searchable_by_prompt_text(self):
        from app import QLineEdit, Dropdown
        window = self._prompta_window()
        try:
            for thoughts, prompt in [('игра змейка в питоне', 'Snake prompt with pygame'), ('прогноз офиса в Барселоне', 'Forecast prompt')]:
                window.thoughts.setPlainText(thoughts)
                window.on_finished({'ok': True, 'manual': {
                    'technique': {'key': 't', 'name': 'Tech', 'category': 'x'}, 'prompt': prompt, 'topic': thoughts.title(),
                    'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'}, 'source_ref': 's'}})
            window.clear_workspace()
            picker = window.history_picker
            self.assertIsInstance(picker, Dropdown, 'the same picker as every other dropdown')
            self.assertFalse(window.history_search.isVisibleTo(window))
            self.assertEqual([item['label'] for item in picker._items], ['Прогноз Офиса В Барселоне', 'Игра Змейка В Питоне'])
            picker._open()
            search = picker._popup.findChild(QLineEdit)
            search.setText('PYGAME')  # matches the prompt text, case-insensitive
            shown = [key for key, widget in picker._item_widgets.items() if not widget.isHidden()]
            self.assertEqual(shown, ['0'])
            picker._choose('0')
            self.assertEqual(window.thoughts.toPlainText(), 'игра змейка в питоне')
            self.assertIn('Snake prompt', window.prompt_edit.toPlainText())
            self.assertEqual(picker.current_key(), '0', 'the opened entry is the current one')
            self.assertEqual(picker.text(), '', 'a toolbar icon, no label')
        finally:
            window.close()

    def test_history_picker_rows_can_be_deleted(self):
        window = self._prompta_window()
        try:
            for thoughts in ('first request', 'second request'):
                window.thoughts.setPlainText(thoughts)
                window.on_finished({'ok': True, 'manual': {
                    'technique': {'key': 't', 'name': 'Tech', 'category': 'x'}, 'prompt': 'A prompt for ' + thoughts + ' with detail.',
                    'topic': thoughts, 'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'}, 'source_ref': 's'}})
            picker = window.history_picker
            self.assertTrue(all(item.get('deletable') for item in picker._items))
            with patch.object(window.history, 'showPopup') as native_popup:
                picker.deleteRequested.emit('0')
                native_popup.assert_not_called()  # the hidden old list must not pop up
            self.assertEqual([entry['thoughts'] for entry in window._history_items], ['second request'])
            self.assertEqual([item['label'] for item in picker._items], ['second request'])
        finally:
            window.close()

    def test_select_all_toggles_shown_techniques_and_skips_procedures(self):
        from app import QLineEdit
        window = self._prompta_window()
        try:
            window._on_techniques_loaded([
                {'key': 'cot', 'name': 'Chain of thought', 'category': 'reasoning', 'status': 'ready'},
                {'key': 'few', 'name': 'Few-shot', 'category': 'icl', 'status': 'ready'},
                {'key': 'tot', 'name': 'Tree of thoughts', 'category': 'reasoning', 'status': 'ready'},
                {'key': 'knn', 'name': 'KNN selection', 'category': 'procedure', 'status': 'procedure'},
            ])
            dropdown = window.technique
            dropdown.set_current_keys(['knn'])
            dropdown._open()
            button = dropdown._select_all_button
            self.assertEqual(button.text(), 'Select all')
            button.click()
            self.assertEqual(dropdown.current_keys(), ['cot', 'tot', 'few'], 'procedure dropped, all others selected in panel order')
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

    def test_open_weight_models_are_grouped_by_family_with_unselectable_headers(self):
        from app import GROUP_HEADER_ROLE, QListWidget
        window = self._prompta_window()
        try:
            combo = window.prompt_model
            texts = [combo.itemText(i) for i in range(combo.count())]
            headers = [t for i, t in enumerate(texts) if combo.itemData(i, GROUP_HEADER_ROLE)]
            self.assertEqual(headers, sorted(headers, key=str.casefold))
            self.assertIn('QWEN · ALIBABA', headers)
            qwen = texts.index('QWEN · ALIBABA')
            self.assertEqual(texts[qwen + 1:qwen + 4], ['Qwen3-Coder-Next', 'Qwen3.8 2.4T A95B', 'Qwen3.8 Flash Next'])
            combo.showPopup()
            listing = combo._popup_frame.findChild(QListWidget)
            header_row = listing.item(qwen)
            self.assertFalse(header_row.flags() & app_flags_enabled())
            listing.itemClicked.emit(header_row)
            self.assertIsNone(window._selected_target(), 'a header is not a model')
            listing.itemClicked.emit(listing.item(qwen + 1))
            self.assertEqual(window._selected_target(), 'openModel')
            self.assertEqual(combo.currentData(), 'qwen3-coder-next')
        finally:
            window.close()

    def test_picking_techniques_resets_count_to_one_and_restores_it(self):
        window = self._prompta_window()
        try:
            window._on_techniques_loaded([{'key': 'sc', 'name': 'Self-consistency', 'category': 'x', 'status': 'ready'}])
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

    def test_library_keeps_the_open_material_and_headers_are_not_materials(self):
        window = self._prompta_window()
        try:
            library = window.library
            library.reload()
            tree = library.tree
            group = tree.topLevelItem(1)
            self.assertEqual(group.text(0), group.text(0).upper(), 'group headers are section labels')
            self.assertFalse(group.flags() & app_selectable())
            target = group.child(2)
            path = library.entries[target.data(0, 256)]['path']
            tree.setCurrentItem(target)
            library.reload()  # e.g. leaving and re-entering the Library tab
            self.assertEqual(library.current['path'], path)
            self.assertTrue(library.preview.toPlainText().strip())
        finally:
            window.close()

    def cls_app_process(self):
        for _ in range(2):
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
