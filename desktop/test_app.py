"""Native UI and subprocess lifecycle smoke tests (run with QT_QPA_PLATFORM=offscreen)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import tempfile
from pathlib import Path
from history import HistoryStore, history_topic
import unittest
from unittest.mock import Mock, patch

from app import QApplication, MainWindow, PromptaWindow, Worker, QPushButton


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
            with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
                return MainWindow()
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

    def test_repeated_results_fit_narrow_window_without_stale_rows(self):
        from app import QLabel, QSS
        from PyQt6.QtCore import QEvent
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
                self.assertEqual(sum(label.text() == 'type: generation' for label in labels), 1)
                self.assertEqual(len(window.output_holder.findChildren(QPushButton)), 3)
                for label in labels:
                    if label.wordWrap():
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.text())
                goal = next(label for label in labels if label.objectName() == 'goal')
                chip = next(label for label in labels if label.objectName() == 'chip')
                self.assertLess(goal.geometry().bottom(), chip.geometry().top())
                self.assertGreater(window.output_scroll.verticalScrollBar().maximum(), 0)
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        try:
            self.assertEqual(window.variants.value(), 3)
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        try:
            window.setStyleSheet(QSS)
            window.show()
            for width, height in ((672, 640), (932, 820)):
                window.resize(width, height)
                self.app.processEvents()
                label = next(x for x in window.thoughts.parent().findChildren(QLabel)
                             if x.text() == 'TECHNIQUE')
                self.assertGreaterEqual(label.geometry().top() - window.thoughts.geometry().bottom(), 10)
                self.assertGreaterEqual(label.height(), label.sizeHint().height())
                self.assertGreater(window.technique.geometry().top(), label.geometry().bottom())
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        self.assertFalse(window.history_notice.isHidden())
        self.assertEqual(self.store.path.read_bytes(), b'broken database')
        window.close()

    def test_api_settings_and_thoughts_label(self):
        from app import QLabel, QLineEdit
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        labels = {label.text(): label for label in window.findChildren(QLabel)}
        self.assertNotIn('THOUGHTS', labels)
        self.assertTrue(window.thoughts.placeholderText().startswith('Thoughts\n'))
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

    def test_library_contains_actual_sources_and_pipeline_and_filters_them(self):
        from app import ROOT
        from library import library_entries, read_material
        entries = library_entries(ROOT)
        paths = {e['path'] for e in entries}
        self.assertIn('catalog/catalog.json', paths)
        self.assertIn('catalog/source-links.json', paths)
        self.assertIn('pipeline/prompt-defaults.ts', paths)
        self.assertIn('pipeline/official.ts', paths)
        for target in ('claude', 'chatgpt', 'gemini', 'grok'):
            self.assertIn(f'{target}_prompt_rules/rules.json', paths)
        for entry in entries:
            self.assertTrue((ROOT / entry['path']).is_file(), entry['path'])
            self.assertNotIn('history.sqlite3', entry['path'])
            if entry.get('expected_hash'):
                self.assertIn('Matches saved source hash', read_material(ROOT, entry)[0])
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        try:
            window.settings_tabs.setCurrentIndex(1)
            self.assertEqual(window.settings_tabs.tabText(1), 'Library')
            self.assertTrue(window.library.preview.isReadOnly())
            self.assertIn('catalog.json', window.library.info.text())
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
            with patch('app.QApplication.platformName', return_value='cocoa'), patch('app.QPropertyAnimation') as animation, patch.object(popup, 'setWindowOpacity'):
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Show))
                animation.assert_called_once_with(popup, b'windowOpacity', popup)
                animation.return_value.setDuration.assert_called_once_with(160)
                animation.return_value.setEasingCurve.assert_called_once_with(QEasingCurve.Type.OutCubic)
                animation.return_value.start.assert_called_once()
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Hide))
                animation.return_value.stop.assert_called_once()
            popup.close()

    def test_clear_workspace_preserves_settings_history_and_discards_pending_result(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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

    def test_open_model_dropdown_excludes_other_targets_and_routes_request(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        try:
            self.assertEqual(window.prompt_model.count(), 16)
            window.chatgpt_only.setChecked(True)
            window.prompt_model.setCurrentIndex(1)
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        try:
            name = window.prompt_model.itemText(2)
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
            self.assertEqual(window.prompt_model.currentIndex(), 2)
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
            self.assertIn(f"open_model_prompt_guides/{model['id']}/prompting-manual.md", paths)
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
        self.assertFalse(window.claude_only.isChecked())
        model = window.model.current_key()
        provider = window.provider.current_key()
        window.technique.set_current('zero_shot')
        window.deterministic.setChecked(True)
        window.claude_only.setChecked(True)
        self.assertFalse(window.technique.isEnabled())
        self.assertFalse(window.deterministic.isEnabled())
        self.assertEqual(window.model.current_key(), model)
        self.assertEqual(window.provider.current_key(), provider)
        window.thoughts.setPlainText('Synthetic parity test')
        with patch('app.Worker') as worker_type:
            window.run_pipeline()
            payload = worker_type.call_args.args[0]
            self.assertTrue(payload['claudeOnly'])
            self.assertFalse(payload['deterministic'])
            self.assertNotIn('manualTechnique', payload)
        window.claude_only.setChecked(False)
        self.assertTrue(window.technique.isEnabled())
        self.assertEqual(window.technique.current_key(), 'zero_shot')
        self.assertTrue(window.deterministic.isChecked())
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            first = MainWindow()
        first.thoughts.setPlainText('Synthetic parity request')
        first.api_key.setText('synthetic-secret-not-for-history')
        first.on_finished({'ok': True, 'result': result})
        self.assertTrue(any('href=' in label.text() for label in first.findChildren(QLabel)))
        first.close()
        self.assertNotIn(b'synthetic-secret-not-for-history', self.store.path.read_bytes())
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            reopened = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
                with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
                    window = MainWindow()
                model, provider = window.model.current_key(), window.provider.current_key()
                self.assertFalse(window.chatgpt_only.isChecked())
                self.assertFalse(window.gemini_only.isChecked())
                window.technique.set_current('zero_shot')
                window.deterministic.setChecked(True)
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
                    self.assertFalse(payload['deterministic'])
                    self.assertNotIn('manualTechnique', payload)
                    self.assertEqual(payload['model'], model)
                getattr(window, f'{target}_only').setChecked(False)
                self.assertTrue(window.technique.isEnabled())
                self.assertTrue(window.deterministic.isChecked())
                self.assertEqual(window.technique.current_key(), 'zero_shot')
                window.close()

    def test_chatgpt_and_gemini_history_restore_their_own_sources_and_target(self):
        from app import QLabel
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            reopened = MainWindow()
        for target in ('chatgpt', 'gemini', 'grok'):
            reopened.history_search.setText(target)
            self.assertEqual(reopened.history.count(), 2)
            self.assertLessEqual(len(reopened.history.itemText(1).split()), 4)
            reopened.history.setCurrentIndex(1)
            self.assertEqual(reopened._selected_target(), target)
            self.assertEqual(reopened.thoughts.toPlainText(), f'{target} synthetic parity task')
            labels = [reopened.output_layout.itemAt(i).widget() for i in range(reopened.output_layout.count())]
            self.assertTrue(any(isinstance(label, QLabel) and 'href=' in label.text() for label in labels))
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

    def test_each_variant_copies_its_own_prompt(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        self.assertEqual(editors[0].accessibleName(), 'Zero-shot baseline prompt')
        self.assertNotIn('First prompt', editors[0].toPlainText())
        buttons = [editor.copy_button for editor in editors[1:]]
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
            zero_copy = editors[0].copy_button
            zero_copy.click()
            clipboard.setText.assert_called_with(editors[0].toPlainText())
            for index in (2, 0, 1, 2):
                buttons[index].click()
                clipboard.setText.assert_called_with(['First prompt', 'Second prompt', 'Third prompt'][index])
        window.close()

    def test_manual_history_error_and_input_validation(self):
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            window = MainWindow()
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
        with patch.object(MainWindow, 'load_models'), patch.object(MainWindow, 'load_techniques'):
            return PromptaWindow()

    def test_target_switch_drives_hidden_toggles_and_request(self):
        window = self._prompta_window()
        try:
            window.thoughts.setPlainText('Build a snake game')
            window.model.set_current('test-model')
            buttons = {b.property('target'): b for b in window.segments.buttons()}
            self.assertEqual([b.text() for b in window.segments.buttons()], ['Any', 'Claude', 'ChatGPT', 'Gemini', 'Grok'])
            self.assertTrue(buttons['general'].isChecked())

            def payload():
                with patch('app.Worker') as worker:
                    window.worker = None
                    window.run_pipeline()
                    return worker.call_args.args[0]

            buttons['claude'].click()
            self.assertTrue(payload()['claudeOnly'])
            self.assertFalse(window.technique.isEnabled())
            buttons['grok'].click()
            request = payload()
            self.assertTrue(request['grokOnly'])
            self.assertFalse(request['claudeOnly'])
            window.prompt_model.setCurrentIndex(2)
            request = payload()
            self.assertEqual(request['openModel'], window.prompt_model.currentData())
            self.assertFalse(any(b.isChecked() for b in window.segments.buttons()))
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
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Variant 1', 'Variant 2'])
            self.assertIn('FIRST PROMPT', window.prompt_edit.toPlainText())
            self.assertIn('SECOND PROMPT', tabs.widget(1).toPlainText())
            self.assertFalse(details.body.isVisibleTo(window))
            self.assertEqual(details.title(), 'How this prompt was built')
            zero_shot = [e for e in details.body.findChildren(PromptEdit)]
            self.assertEqual([e.toPlainText() for e in zero_shot], ['Task: snake'])
        finally:
            window.close()

    def test_advanced_section_holds_technique_and_variants(self):
        window = self._prompta_window()
        try:
            self.assertIs(window.technique.parentWidget(), window.advanced.body)
            self.assertIs(window.variants.parentWidget(), window.advanced.body)
            self.assertFalse(window.advanced.body.isVisibleTo(window))
            self.assertEqual(window.advanced.title(), 'Advanced')
            window.variants.buttons.button(1).click()
            self.assertEqual(window.advanced.title(), 'Advanced · variants: 1')
            self.assertTrue(window.run_button.text().startswith('Build prompt'))
            self.assertEqual(window.status.text(), '')
        finally:
            window.close()

    def cls_app_process(self):
        for _ in range(2):
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
