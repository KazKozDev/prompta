"""PromptaWindow: layout, results, editing, dictation and the library (run with QT_QPA_PLATFORM=offscreen)."""

from test_support import WindowTestCase, app_selectable
from pathlib import Path
import json
import re
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QPushButton, QLabel, QListWidget, QPlainTextEdit, QScrollArea
from app import PromptaWindow
from generator_settings import GeneratorSettings
from PyQt6.QtCore import Qt


class DesktopSmokeTest(WindowTestCase):
    def test_about_tab_credits_the_author(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        tabs = window.settings_dialog.tabs
        self.assertEqual(tabs.tabText(tabs.count() - 1), 'About')
        self.assertIn('KazKozDev', window.about.author.text())
        self.assertIn('https://github.com/KazKozDev', window.about.author.text())
        self.assertRegex(
            window.about.how.text(),
            r'^Prompta is an open-source macOS app .* one of \d+ prompting techniques, .*for comparison\.$',
        )
        versions = dict(window.about.versions())
        self.assertRegex(versions['Technique catalog'], r' · 90 entries$')
        self.assertRegex(versions['Claude guidance'], r'^\d+ rules · checked \d{4}-\d{2}-\d{2}$')
        self.assertNotIn('unavailable', versions.values())
        window.library.reload()
        self.assertRegex(window.library.summary.text(), r'^\d+ materials · catalog \S+ · prompts \d{4}-\d{2}-\d{2}$')
        tree = window.library.tree
        rules = next(
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).text(0) == 'OFFICIAL RULES'
        )
        claude = next(rules.child(j) for j in range(rules.childCount()) if rules.child(j).text(0).startswith('Claude'))
        date = re.search(r'\d{4}-\d{2}-\d{2}$', claude.text(0)).group(0)
        tree.setCurrentItem(claude)
        self.assertIn(f'checked {date}', window.library.integrity.text())
        window.close()

    def test_repeated_results_fit_narrow_window_without_stale_rows(self):
        from PyQt6.QtWidgets import QLabel
        from theme import QSS
        from PyQt6.QtCore import QEvent

        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.resize(932, 870)
        window.show()
        result = {
            'brief': {
                'goal': (
                    'Симулировать рабочий день типичного Generative AI Engineer, '
                    'показав стек, задачи, артефакты и взаимодействия.'
                ),
                'task_type': 'generation',
                'language': 'ru',
                'stakes': 'low',
                'output_format': 'Связный рассказ, структурированный план или дневник от первого лица.',
                'assumptions': ['Роль — типичный Generative AI Engineer. ' * 4],
            },
            'choice': {
                'key': 'chatgpt_official',
                'name': 'ChatGPT · official guidance',
                'confidence': 1,
                'reason': 'Official rules. ' * 8,
                'whyNotCheaper': 'Target mode. ' * 6,
            },
            'synthesis': {
                'prompt': 'Example prompt\n' * 40,
                'config': {
                    'temperature': None,
                    'top_p': None,
                    'max_tokens': 'Model-dependent',
                    'rationale': 'Target settings',
                },
                'warnings': ['General guidance. ' * 10],
            },
            'rejected': [],
            'chatgptGuidance': {},
        }
        try:
            for width in (932, 1160, 932):
                window.resize(width, 870)
                window.result_column.render_result(result)
                self.app.processEvents()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                labels = window.result_column.output_holder.findChildren(QLabel)
                self.assertEqual(sum(label.text() == 'PROMPT' for label in labels), 0)
                self.assertEqual(
                    sum(label.objectName() == 'briefMeta' for label in labels),
                    1,
                    'no stale rows from the previous render',
                )
                self.assertEqual(
                    len(
                        [
                            b
                            for b in window.result_column.output_holder.findChildren(QPushButton)
                            if b.objectName() != 'restorePrompt'
                        ]
                    ),
                    4,
                )
                for label in labels:
                    if label.wordWrap():
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.text())
                goal = next(label for label in labels if label.objectName() == 'goal')
                chip = next(label for label in labels if label.objectName() == 'chip')
                self.assertLess(
                    goal.mapTo(window, goal.rect().bottomLeft()).y(), chip.mapTo(window, chip.rect().topLeft()).y()
                )
                self.assertEqual(window.result_column.horizontalScrollBar().maximum(), 0, 'the result fits the width')
        finally:
            window.close()

    def test_step_scroll_limits_jumps_and_ignores_momentum(self):
        from PyQt6.QtWidgets import QScrollArea, QPlainTextEdit, QWidget
        from widgets import use_step_scroll
        from PyQt6.QtCore import QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent

        def wheel(area, angle=0, pixels=0, phase=Qt.ScrollPhase.NoScrollPhase):
            event = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, pixels),
                QPoint(0, angle),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                phase,
                False,
            )
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

    def test_wheel_over_prompt_scrolls_results_instead_of_prompt_text(self):
        from PyQt6.QtWidgets import QScrollArea, QPlainTextEdit, QWidget, QVBoxLayout
        from widgets import use_step_scroll
        from PyQt6.QtCore import QPoint, QPointF
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
                event = QWheelEvent(
                    QPointF(10, 10),
                    QPointF(10, 10),
                    QPoint(),
                    QPoint(0, -120),
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase,
                    False,
                )
                self.app.sendEvent(surface, event)
                self.assertEqual(area.verticalScrollBar().value(), before + 32)
                self.assertEqual(editor.verticalScrollBar().value(), 0)
            editor.verticalScrollBar().setValue(10)
            self.assertEqual(editor.verticalScrollBar().value(), 10)
        finally:
            area.close()

    def test_dropdown_borders_follow_rounded_popup_corners(self):
        from theme import QSS

        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.show()
        try:
            for picker in (window.technique, window.generator.provider, window.generator.model):
                picker._open()
                self.app.processEvents()
                popup = picker._popup
                self.assertTrue(popup.windowFlags() & Qt.WindowType.FramelessWindowHint)
                image = popup.grab().toImage()
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertEqual(image.pixelColor(image.width() // 2, 0).alpha(), 255)
                popup.close()
            window.history.combo.showPopup()
            self.app.processEvents()
            popup = window.history.combo._popup_frame
            self.assertTrue(popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
            self.assertEqual(popup.grab().toImage().pixelColor(0, 0).alpha(), 0)
            window.history.combo.hidePopup()
        finally:
            window.close()

    def test_input_fields_do_not_overlap_when_window_is_shrunk(self):
        from PyQt6.QtWidgets import QLabel
        from theme import QSS

        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.setStyleSheet(QSS)
            window.show()
            for width, height in ((672, 640), (932, 820)):
                window.resize(width, height)
                self.app.processEvents()

                def rect(widget):
                    return widget.geometry().translated(
                        widget.parentWidget().mapTo(window, widget.parentWidget().rect().topLeft())
                    )

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

    def test_library_contains_prompt_sources_only_and_filters_them(self):
        from theme import ROOT
        from library import library_entries, read_material

        entries = library_entries(ROOT)
        paths = {e['path'] for e in entries}
        self.assertIn('catalog/catalog.json', paths)
        self.assertFalse(
            [p for p in paths if p.startswith(('pipeline/', 'eval/', 'desktop/'))], 'no developer code or evaluation'
        )
        self.assertFalse(
            [p for p in paths if p.endswith(('.pdf', 'LICENSE', '.jinja', '.py', 'sources.json', 'coverage.json'))],
            'no snapshots, licences, templates or tooling',
        )
        for target in ('claude', 'chatgpt', 'gemini', 'grok'):
            self.assertIn(f'{target}_prompt_rules/rules.json', paths)
        cot = next(e for e in entries if e['title'].startswith('Chain-of-Thought'))
        self.assertTrue(cot['category'].startswith('Techniques · '))
        self.assertIn('When it hurts', read_material(ROOT, cot)[1], 'techniques read as pages, not JSON')
        claude = next(e for e in entries if e['category'] == 'Official rules' and e['title'] == 'Claude')
        self.assertIn('Applies:', read_material(ROOT, claude)[1])
        for folder, title in (('skill_rules', 'Skill'), ('instructions_rules', 'Project'), ('agent_rules', 'Subagent')):
            entry = next(e for e in entries if e['path'] == f'{folder}/rules.json')
            self.assertEqual((entry['category'], entry['title']), ('File rules', title))
            page = read_material(ROOT, entry)[1]
            self.assertIn(f'{title} mode · the official rules for', page)
            self.assertIn('Source: ', page, 'each rule names the document it came from')
        skill = read_material(ROOT, next(e for e in entries if e['path'] == 'skill_rules/rules.json'))[1]
        self.assertIn('body-plan — For batch, destructive or irreversible operations', skill)
        for entry in entries:
            self.assertTrue((ROOT / entry['path']).is_file(), entry['path'])
            self.assertNotIn('history.sqlite3', entry['path'])
            if entry.get('expected_hash'):
                self.assertIn('Matches saved source hash', read_material(ROOT, entry)[0])
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.settings_dialog.tabs.setCurrentIndex(1)
            self.assertEqual(window.settings_dialog.tabs.tabText(1), 'Library')
            self.assertTrue(window.library.preview.isReadOnly())
            self.assertTrue(window.library.info.text())
            window.library.search.setText('Grok')
            visible = []
            for i in range(window.library.tree.topLevelItemCount()):
                group = window.library.tree.topLevelItem(i)
                visible.extend(
                    group.child(j).text(0) for j in range(group.childCount()) if not group.child(j).isHidden()
                )
            self.assertTrue(any('Grok' in title for title in visible))
            self.assertNotIn('Technique catalog', visible)
        finally:
            window.close()

    def test_open_in_chatgpt_copies_full_prompt_and_uses_default_browser(self):
        from widgets import PromptEdit
        from urllib.parse import urlparse, parse_qs

        text = 'Напиши код: a & b? #1\nSecond line + 100%'
        editor = PromptEdit(text, None, "chatgpt")
        editor.resize(420, 200)
        editor.show()
        self.app.processEvents()
        try:
            with (
                patch('PyQt6.QtGui.QGuiApplication.clipboard') as clipboard,
                patch('PyQt6.QtGui.QDesktopServices.openUrl', return_value=True) as browser,
            ):
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

    def test_a_long_prompt_reaches_chatgpt_through_the_clipboard_not_the_url(self):
        from widgets import MAX_CHAT_URL_TEXT, PromptEdit

        text = 'Проверь отчёт.\n<document path="report.md">' + 'x' * MAX_CHAT_URL_TEXT + '</document>'
        editor = PromptEdit(text, None, "chatgpt")
        try:
            with (
                patch('PyQt6.QtGui.QGuiApplication.clipboard') as clipboard,
                patch('PyQt6.QtGui.QDesktopServices.openUrl', return_value=True) as browser,
            ):
                editor.chat_button.click()
                clipboard.return_value.setText.assert_called_once_with(text)
                self.assertEqual(browser.call_args.args[0].toString(), 'https://chatgpt.com/')
            self.assertIn('Paste it', editor.chat_button.toolTip())
        finally:
            editor.close()

    def test_popups_and_dialogs_share_the_same_animation(self):
        from widgets import PopupAnimation
        from PyQt6.QtWidgets import QDialog, QFrame
        from PyQt6.QtCore import QEvent, QEasingCurve

        animation_filter = PopupAnimation()
        for popup in (QDialog(), QFrame(None, Qt.WindowType.Popup)):
            with (
                patch('PyQt6.QtWidgets.QApplication.platformName', return_value='cocoa'),
                patch('widgets.QPropertyAnimation') as animation,
                patch.object(popup, 'setWindowOpacity'),
            ):
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Show))
                animation.assert_called_once_with(popup, b'windowOpacity', popup)
                animation.return_value.setDuration.assert_called_once_with(160)
                animation.return_value.setEasingCurve.assert_called_once_with(QEasingCurve.Type.OutCubic)
                animation.return_value.start.assert_called_once()
                animation_filter.eventFilter(popup, QEvent(QEvent.Type.Hide))
                animation.return_value.stop.assert_called_once()
            popup.close()

    def test_clear_workspace_preserves_settings_history_and_discards_pending_result(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.thoughts.setPlainText('Draft to clear')
            window.target_picker._choose('chatgpt')
            window.variants.setValue(5)
            window.generator.api_key.setText('synthetic-key')
            window.history.filter('filter')
            window.history.items.append(
                {'label': 'Saved', 'thoughts': 'Saved task', 'payload': {}, 'created_at': '2026-11-06'}
            )
            worker = Mock()
            worker.isRunning.return_value = True
            window.worker = worker
            window.clear_button.click()
            worker.cancel.assert_called_once()
            self.assertEqual(window.thoughts.toPlainText(), '')
            self.assertEqual(window.history.combo.currentIndex(), 0)
            self.assertEqual(len(window.history.items), 1)
            self.assertEqual(window.target_selector.target(), 'chatgpt')
            self.assertEqual(window.variants.value(), 5)
            self.assertEqual(window.generator.api_key.text(), 'synthetic-key')
            self.assertTrue(window.generation_progress.isHidden())
            with (
                patch.object(window.result_column, 'render_result') as render,
                patch.object(window.history, 'push') as save,
            ):
                window.on_finished({'ok': True, 'result': {}})
                render.assert_not_called()
                save.assert_not_called()
            self.assertTrue(window.run_button.isEnabled())
            self.assertNotEqual(window.status.text(), 'Done')
        finally:
            window.worker = None
            window.close()

    def test_whisper_updates_preserve_thoughts_and_restore_microphone(self):
        from widgets import ThoughtsEdit

        editor = ThoughtsEdit()
        editor.setPlainText('Existing thoughts')
        process = Mock()
        chunks = [
            json.dumps({'state': 'recording'}) + '\n',
            json.dumps({'state': 'transcribing'})
            + '\n'
            + json.dumps({'state': 'done', 'text': 'Распознанная речь'})
            + '\n',
        ]
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
        from widgets import ThoughtsEdit

        editor = ThoughtsEdit()
        editor.setPlainText('Existing thoughts')
        process = Mock()
        events = [
            {'state': 'recording'},
            {'state': 'partial', 'text': 'Привет'},
            {'state': 'partial', 'text': 'Привет мир как'},
            {'state': 'transcribing'},
            {'state': 'done', 'text': 'Привет, мир, как дела?'},
        ]
        process.readAllStandardOutput.side_effect = [(json.dumps(e) + '\n').encode() for e in events]
        editor.voice_process = process
        editor._voice_output()
        self.assertTrue(editor.isReadOnly(), 'no typing into text that is still being recognised')
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет')
        editor._voice_output()
        self.assertEqual(
            editor.toPlainText(), 'Existing thoughts\nПривет мир как', 'the live text is replaced, not appended'
        )
        editor._voice_output()
        editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет, мир, как дела?')
        editor._voice_finished()
        self.assertFalse(editor.isReadOnly())
        self.assertEqual(editor.toPlainText(), 'Existing thoughts\nПривет, мир, как дела?')

        editor.setPlainText('Draft')
        process.readAllStandardOutput.side_effect = [
            (json.dumps(e) + '\n').encode()
            for e in [{'state': 'recording'}, {'state': 'partial', 'text': 'шум'}, {'state': 'error', 'message': 'x'}]
        ]
        editor.voice_process = process
        for _ in range(3):
            editor._voice_output()
        self.assertEqual(editor.toPlainText(), 'Draft', 'a failed dictation leaves the request as it was')
        self.assertFalse(editor.isReadOnly())
        editor.close()

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

    def test_assumptions_card_edits_the_brief_and_rebuilds_without_rebriefing(self):
        brief = {
            'goal': 'Find job titles',
            'task_type': 'agentic',
            'language': 'ru',
            'stakes': 'medium',
            'output_format': 'Report',
            'assumptions': ['Leftover assumption', 'Senior roles only'],
            'questions': [{'question': 'Which countries?', 'default': 'all of Europe'}, 'Which period?'],
        }
        result = {
            'brief': brief,
            'choice': {'key': 'zero_shot', 'name': 'Zero-shot', 'reason': 'r', 'confidence': 0.5},
            'synthesis': {
                'prompt': 'Find job titles across Europe and report them with dates.',
                'config': {'temperature': 0.2, 'top_p': 0.95, 'max_tokens': '1024'},
                'warnings': [],
            },
            'rejected': [],
        }
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.thoughts.setPlainText("Find job titles")
        window.result_column.render_result(result)
        card = window.assumptions_card
        self.assertIsNot(card.parentWidget(), window.thoughts, 'its own block under the request, not inside the field')
        self.assertFalse(card.findChildren(QScrollArea), 'no scroll inside the card')
        self.assertFalse(
            [
                e
                for e in window.findChildren(QPlainTextEdit)
                if e.toPlainText() == 'Leftover assumption' and not card.isAncestorOf(e)
            ],
            'no second assumptions box beside the prompt',
        )
        fields = [answer for _, answer in window.result_column.question_answers]
        self.assertEqual([f.text() for f in fields], ['all of Europe', ''], 'the assumed answer is shown as the value')
        self.assertEqual(
            [row['field'].text() for row in window.result_column.assumption_rows],
            ['Leftover assumption', 'Senior roles only'],
        )
        self.assertEqual(window.run_button.text(), window.build_label, 'no edits: an ordinary build')
        self.assertFalse(
            [b for b in window.findChildren(QPushButton) if b.text().startswith('Rebuild')],
            'no separate rebuild button',
        )

        fields[0].setText('Germany')
        window.result_column.assumption_rows[0]['widget'].findChild(QPushButton, 'removeAssumption').click()
        window.result_column.add_assumption_button.click()
        window.result_column.assumption_rows[-1]['field'].setText('Include direct sources')
        fields[1].setText('last 12 months')
        self.assertTrue(
            window.run_button.text().startswith('Rebuild · 4 changes'), 'the one button says what it will do'
        )
        with patch.object(window, 'run_pipeline') as run:
            revised = window._card_revision()
            window.run_button.click()
            run.assert_called_once_with()
            self.assertEqual(
                revised,
                {
                    **brief,
                    'assumptions': ['Senior roles only', 'Include direct sources'],
                    'questions': [
                        {'question': 'Which countries?', 'default': 'Germany'},
                        {'question': 'Which period?', 'default': 'last 12 months'},
                    ],
                },
            )
        self.assertEqual(window.thoughts.toPlainText(), 'Find job titles', 'the request is left as typed')
        fields[0].setText('')
        self.assertEqual(
            window._card_revision()['questions'][0],
            {'question': 'Which countries?'},
            'a cleared answer drops that assumption',
        )
        with patch('app.Worker') as worker:
            window.generator.model.set_current('test-model')
            window.worker = None
            window.run_pipeline()
            self.assertEqual(
                worker.call_args.args[0]['brief']['assumptions'],
                ['Senior roles only', 'Include direct sources'],
                'Build sends the edited brief',
            )
            self.assertEqual(window.run_button.text(), 'Stop', 'the same button stops a running build')
            window.worker = None
        window.thoughts.setPlainText('Find job titles in Asia')
        self.assertEqual(window.run_button.text(), window.build_label, 'a changed request is a fresh build')
        self.assertIsNone(window._card_revision())
        window.clear_workspace()
        self.assertIsNone(window.assumptions_card, 'a new request starts without old questions')
        window.close()

    def test_sources_window_shows_a_short_description_of_each_source(self):
        from PyQt6.QtWidgets import QDialog, QLabel
        from controls import TechniqueItem

        links = json.loads((Path(__file__).resolve().parent.parent / 'catalog' / 'source-links.json').read_text())
        self.assertTrue(
            all(any(s.get('summary') for s in v) for v in links.values()), 'every technique has a described source'
        )
        item = TechniqueItem('chain_of_thought', 'Chain-of-Thought', 'hint', links['chain_of_thought'])
        shown = []
        with patch.object(
            QDialog,
            'exec',
            lambda dialog: shown.extend(
                l.text() for l in dialog.findChildren(QLabel) if l.objectName() == 'sourceSummary'
            ),
        ):
            item._show_sources('Chain-of-Thought')
        self.assertTrue(shown and shown[0].startswith('We explore how generating a chain of thought'), shown[:1])
        self.assertTrue(all(2 <= t.count('. ') + 1 <= 6 for t in shown), 'a few sentences each')

    def test_hover_hints_use_the_app_popup_not_the_system_tooltip(self):
        from widgets import HintFilter
        from PyQt6.QtWidgets import QListWidgetItem, QPushButton
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
        from widgets import PromptEdit
        from PyQt6.QtGui import QGuiApplication

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
        self.assertEqual(editor.verticalScrollBar().maximum(), 0, 'no scrolling inside the block')
        editor._copy()
        self.assertTrue(
            QGuiApplication.clipboard().text().startswith('Original prompt text that is long enough. Edited by me.')
        )
        editor.close()

    def test_each_variant_copies_its_own_prompt(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        config = {'temperature': 0.2, 'top_p': 0.95, 'max_tokens': '1024', 'rationale': 'test'}
        choice = {'name': 'Test', 'key': 'test', 'confidence': 1, 'reason': 'test', 'whyNotCheaper': 'test'}

        def synthesis(text):
            return {'prompt': text, 'config': config, 'warnings': []}

        window.result_column.render_result(
            {
                'brief': {
                    'goal': 'test',
                    'task_type': 'classification',
                    'language': 'ru',
                    'stakes': 'low',
                    'output_format': 'JSON',
                    'assumptions': [],
                },
                'choice': choice,
                'synthesis': synthesis('First prompt'),
                'rejected': [],
                'alternatives': [
                    {'choice': choice, 'synthesis': synthesis('Second prompt')},
                    {'choice': choice, 'synthesis': synthesis('Third prompt')},
                ],
            }
        )
        from PyQt6.QtWidgets import QPlainTextEdit

        editors = window.result_column.output_holder.findChildren(QPlainTextEdit)
        self.assertEqual(len(editors), 4)
        zero = [editor for editor in editors if editor.accessibleName() == 'Zero-shot baseline prompt']
        self.assertEqual(len(zero), 1)
        self.assertNotIn('First prompt', zero[0].toPlainText())
        variants = sorted((editor for editor in editors if editor not in zero), key=lambda editor: editor.toPlainText())
        self.assertEqual(
            [editor.toPlainText() for editor in variants], ['First prompt', 'Second prompt', 'Third prompt']
        )
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
        with patch('PyQt6.QtGui.QGuiApplication.clipboard', return_value=clipboard):
            zero[0].copy_button.click()
            clipboard.setText.assert_called_with(zero[0].toPlainText())
            for index in (2, 0, 1, 2):
                buttons[index].click()
                clipboard.setText.assert_called_with(['First prompt', 'Second prompt', 'Third prompt'][index])
        window.close()

    def test_result_shows_prompt_first_with_variant_tabs_and_folded_details(self):
        from result_view import Disclosure
        from widgets import PromptEdit
        from PyQt6.QtWidgets import QTabWidget

        window = self._prompta_window()
        try:
            synthesis = lambda prompt: {
                'prompt': prompt,
                'warnings': ['careful'],
                'missing': [],
                'config': {'temperature': 0.2, 'top_p': 0.9, 'max_tokens': '1k', 'rationale': 'r'},
            }
            choice = lambda name: {
                'key': name,
                'name': name,
                'reason': 'because',
                'confidence': 0.7,
                'whyNotCheaper': 'w',
            }
            window.result_column.render_result(
                {
                    'brief': {
                        'topic': 'Snake game',
                        'goal': 'Write a snake game',
                        'task_type': 'coding',
                        'language': 'en',
                        'stakes': 'low',
                        'output_format': 'code',
                        'assumptions': [],
                    },
                    'choice': choice('Code prompting'),
                    'synthesis': synthesis('FIRST PROMPT ' * 5),
                    'alternatives': [{'choice': choice('Few-shot'), 'synthesis': synthesis('SECOND PROMPT ' * 5)}],
                    'zeroShotPrompt': 'Task: snake',
                    'rejected': [],
                }
            )
            self.cls_app_process()
            widgets = [
                window.result_column.output_layout.itemAt(i).widget()
                for i in range(window.result_column.output_layout.count())
            ]
            tabs = next(w for w in widgets if isinstance(w, QTabWidget))
            details = next(w for w in widgets if isinstance(w, Disclosure))
            self.assertLess(widgets.index(tabs), widgets.index(details))
            self.assertEqual(
                [tabs.tabText(i) for i in range(tabs.count())], ['Zero-shot', 'Code prompting', 'Few-shot']
            )
            self.assertEqual(tabs.currentIndex(), 1, 'the built prompt is shown first')
            self.assertEqual(tabs.widget(0).toPlainText(), 'Task: snake')
            self.assertIn('FIRST PROMPT', window.result_column.prompt_edit.toPlainText())
            self.assertIn('SECOND PROMPT', tabs.widget(2).toPlainText())
            self.assertTrue(details.body.isVisibleTo(window), 'details are open by default')
            self.assertEqual(details.title(), 'How this prompt was built')
            self.assertEqual(details.body.findChildren(PromptEdit), [], 'zero-shot moved out of the details')

            def shown():
                return [l.text() for l in details.body.findChildren(QLabel) if l.isVisibleTo(window)]

            meta = window.result_column.findChild(QLabel, 'meta')  # in one row with the usage line
            first_reason = [
                l for l in details.body.findChildren(QLabel) if l.text() == 'because' and l.isVisibleTo(window)
            ]
            self.assertEqual(len(first_reason), 1, 'only the shown variant explains itself')
            self.assertTrue(meta.text().startswith('Code prompting'))
            self.assertTrue(tabs.widget(1).spec.text().startswith('Recommended: temp '), 'settings in prompt')
            self.assertIsNone(tabs.widget(0).spec, 'zero-shot has no run settings')
            tabs.setCurrentIndex(2)
            second_reason = [
                l for l in details.body.findChildren(QLabel) if l.text() == 'because' and l.isVisibleTo(window)
            ]
            self.assertEqual(len(second_reason), 1)
            self.assertIsNot(first_reason[0], second_reason[0], 'switching tabs swaps the explanation')
            self.assertTrue(meta.text().startswith('Few-shot · confidence 70%'), 'header names the shown technique')
            tabs.setCurrentIndex(0)
            self.assertTrue(any(t.startswith('Zero-shot:') for t in shown()))
            self.assertNotIn('because', shown())
            self.assertIn('coding · low stakes · en', shown(), 'the shared brief stays under every tab')
        finally:
            window.close()

    def test_routine_notes_stay_folded_and_status_counts_only_visible_warnings(self):
        window = self._prompta_window()
        try:

            def result(warnings, guidance=None):
                data = {
                    'brief': {
                        'goal': 'g',
                        'task_type': 'coding',
                        'language': 'en',
                        'stakes': 'low',
                        'output_format': 'code',
                        'assumptions': [],
                    },
                    'choice': {
                        'key': 'k',
                        'name': 'Gemini · official guidance',
                        'reason': 'r',
                        'confidence': 0.5,
                        'whyNotCheaper': 'w',
                    },
                    'synthesis': {
                        'prompt': 'P' * 50,
                        'warnings': warnings,
                        'missing': [],
                        'config': {'temperature': None, 'top_p': None, 'max_tokens': 'm', 'rationale': 'r'},
                    },
                    'rejected': [],
                }
                if guidance:
                    data['geminiGuidance'] = guidance
                return data

            guidance = {'target': 'Gemini', 'rule_set_version': 'v', 'verified_at': 'd', 'variants': [], 'rules': []}
            note = (
                'General Gemini guidance. Rule usage is model-reported; '
                'source links do not independently prove output compliance.'
            )
            window.on_finished({'ok': True, 'result': result([note], guidance)})
            self.assertEqual(window.status.text(), 'Gemini · official guidance · ready')
            visible = [
                w for w in window.result_column.output_holder.findChildren(QLabel, 'warn') if w.isVisibleTo(window)
            ]
            self.assertEqual(visible, [])
            window.on_finished({'ok': True, 'result': result([note, 'Unfilled placeholders: examples'])})
            self.assertEqual(window.status.text(), 'Gemini · official guidance · 1 warning below the prompt')
            visible = [
                w.text()
                for w in window.result_column.output_holder.findChildren(QLabel, 'warn')
                if w.isVisibleTo(window)
            ]
            self.assertEqual(visible, ['• Unfilled placeholders: examples'])
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


if __name__ == '__main__':
    unittest.main()
