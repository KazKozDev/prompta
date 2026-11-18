"""History: saving, restoring, searching and deleting requests."""

from test_support import WindowTestCase
from history import history_topic
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QLabel, QListWidget
from app import PromptaWindow
from generator_settings import GeneratorSettings
from PyQt6.QtCore import Qt
from widgets import DELETABLE_ROLE


class HistoryTest(WindowTestCase):
    def test_settings_history_lists_opens_and_deletes_requests(self):
        def window():
            with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
                return PromptaWindow()

        first = window()
        for query, prompt in [('Чётные числа', 'Первый промпт'), ('Письмо коллеге', 'Второй промпт')]:
            first.thoughts.setPlainText(query)
            first.on_finished(
                {
                    'ok': True,
                    'manual': {
                        'technique': {'key': 'test', 'name': 'Same technique', 'category': 'test'},
                        'prompt': prompt,
                        'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
                        'source_ref': 'test',
                    },
                }
            )
        first.close()
        second = window()
        listing = second.history.settings_list

        def rows():  # request rows, without the day headers
            return [
                r for r in range(listing.count()) if isinstance(listing.item(r).data(Qt.ItemDataRole.UserRole), int)
            ]

        self.assertEqual(listing.item(0).text(), 'Today')  # a day header, not a request
        self.assertEqual(len(rows()), 2)
        self.assertEqual(second.history.settings_title.text(), 'REQUESTS · 2')
        self.assertIn('Письмо', listing.item(rows()[0]).text())  # newest first
        second.history.settings_search.setText('Чётные')
        self.assertEqual(len(rows()), 1)
        second.history.settings_search.setText('')
        second.history._open_from_settings_list(listing.item(rows()[1]))
        self.assertEqual(second.thoughts.toPlainText(), 'Чётные числа')
        second.history._delete_from_settings_list(rows()[0])
        self.assertEqual(len(rows()), 1)
        self.assertEqual(len(self.store.load()), 1)
        second.close()

    def test_history_survives_restart_and_search_restores_correct_query(self):
        def window():
            with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
                return PromptaWindow()

        first = window()
        for query, prompt in [('Чётные числа', 'Первый промпт'), ('Письмо', 'Уникальный второй промпт')]:
            first.thoughts.setPlainText(query)
            first.on_finished(
                {
                    'ok': True,
                    'manual': {
                        'technique': {'key': 'test', 'name': 'Same technique', 'category': 'test'},
                        'prompt': prompt,
                        'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'test'},
                        'source_ref': 'test',
                    },
                }
            )
        first.close()
        reopened = window()
        self.assertEqual(reopened.history.combo.count(), 3)
        reopened.history.filter('УНИКАЛЬНЫЙ')
        self.assertEqual(reopened.history.combo.count(), 2)
        reopened.history.combo.setCurrentIndex(1)
        self.assertEqual(reopened.result_column.prompt_edit.toPlainText(), 'Уникальный второй промпт')
        self.assertEqual(reopened.thoughts.toPlainText(), 'Письмо')
        reopened.history.filter('чётные')
        self.assertEqual(reopened.history.combo.count(), 2)
        reopened.history.combo.setCurrentIndex(1)
        self.assertEqual(reopened.result_column.prompt_edit.toPlainText(), 'Первый промпт')
        reopened.history.filter('нет совпадений')
        self.assertEqual(reopened.history.combo.count(), 1)
        self.assertEqual(len(self.store.load()), 2)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        reopened.close()

    def test_history_settings_limit_prunes_and_persists(self):
        for i in range(5):
            self.store.add(f'q{i}', 'manual', f'q{i}', {'topic': f'q{i}'})
        with (
            patch.object(GeneratorSettings, 'load_models'),
            patch.object(PromptaWindow, 'load_techniques'),
            patch.dict('os.environ', {}, clear=False),
        ):
            os_env = __import__('os').environ
            os_env.pop('PROMPTA_HISTORY_MAX', None)
            os_env.pop('PROMPTA_HISTORY_DAYS', None)
            window = PromptaWindow()
            window.history.limit.set_items(window.history.limit._items + [{'key': '2', 'label': 'Keep the newest 2'}])
            window.history.limit.set_current('2', emit=True)
        self.assertEqual([e['label'] for e in self.store.load()], ['q3', 'q4'])
        self.assertEqual(len(window.history.items), 2)
        saved = __import__('json').loads(self.store.path.with_name('settings.json').read_text())
        self.assertEqual(saved['history_max'], 2)
        window.close()

    def test_clear_history_asks_first_and_then_deletes_file(self):
        from PyQt6.QtWidgets import QMessageBox

        for name in ('Первая', 'Вторая'):
            self.store.add(name, 'manual', name, {'topic': name})
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        with patch('PyQt6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            window.history.delete_all_button.click()
        self.assertEqual(len(self.store.load()), 2, 'cancel keeps everything')
        with patch('PyQt6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            window.history.delete_all_button.click()
        self.assertFalse(self.store.path.exists())
        self.assertEqual(window.history.items, [])
        self.assertEqual(window.history.combo.count(), 1)
        window.close()

    def test_cross_deletes_history_entry_from_list_and_disk(self):
        for name in ('Первая', 'Вторая', 'Третья'):
            self.store.add(name, 'manual', name, {'topic': name})
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.history.combo.setCurrentIndex(3)
        window.history.combo.showPopup()
        listing = window.history.combo._popup_frame.findChild(QListWidget)
        self.assertFalse(listing.item(0).data(DELETABLE_ROLE))
        self.assertTrue(listing.item(2).data(DELETABLE_ROLE))
        window.history.combo.deleteRequested.emit(2)
        self.assertEqual([e['label'] for e in self.store.load()], ['Первая', 'Третья'])
        self.assertEqual(
            [window.history.combo.itemText(i) for i in range(window.history.combo.count())],
            ['— history —', 'Первая', 'Третья'],
        )
        self.assertEqual(window.history.combo.currentText(), 'Третья')
        window.history.combo.hidePopup()
        window.close()

    def test_long_saved_topics_do_not_force_window_beyond_screen(self):
        from theme import QSS

        topic = (
            'Создать играбельную простую платформенную игру в духе Super Mario на Python с использованием Pygame. ' * 3
        )
        self.store.add(
            'Old history',
            'manual',
            'Saved task',
            {
                'topic': topic,
                'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
                'prompt': 'Example',
                'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
                'source_ref': 'test',
            },
        )
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        try:
            window.setStyleSheet(QSS)
            window.resize(932, 760)
            window.show()
            self.app.processEvents()
            window.history.combo.setCurrentIndex(1)
            self.app.processEvents()
            self.assertLessEqual(window.minimumSizeHint().width(), 932)
            self.assertLessEqual(window.width(), 932)
        finally:
            window.close()

    def test_history_popup_uses_plain_list_without_native_scroll_panels(self):
        from theme import QSS
        from PyQt6.QtWidgets import QListWidget

        manual = {
            'topic': 'Saved topic',
            'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
            'prompt': 'Saved prompt',
            'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
            'source_ref': 'test',
        }
        self.store.add('Saved topic', 'manual', 'Saved request', manual)
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        window.setStyleSheet(QSS)
        window.show()
        try:
            window.history.combo.showPopup()
            self.app.processEvents()
            popup = window.history.combo._popup_frame
            listing = popup.findChild(QListWidget)
            self.assertEqual(listing.count(), 2)
            listing.itemClicked.emit(listing.item(1))
            self.assertFalse(popup.isVisible())
            self.assertEqual(window.thoughts.toPlainText(), 'Saved request')
            self.assertEqual(window.result_column.prompt_edit.toPlainText(), 'Saved prompt')
            window.history.combo.showPopup()
            self.app.processEvents()
            self.assertTrue(window.history.combo._popup_frame.isVisible())
            window.history.combo.hidePopup()
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
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertFalse(window.history.notice.isHidden())
        self.assertEqual(self.store.path.read_bytes(), b'broken database')
        window.close()

    def test_history_shows_short_topic_but_keeps_full_request_searchable(self):
        query = 'Я хочу чтобы нейросеть разбирала заметки встреч и находила уникальный_срок'
        payload = {
            'brief': {'topic': 'Итоги встреч', 'goal': 'Извлечение решений задач ответственных из заметок встреч'}
        }
        self.store.add('Old technique label', 'pipeline', query, payload)
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
            window = PromptaWindow()
        self.assertEqual(window.history.combo.itemText(1), 'Итоги встреч')
        window.history.filter('уникальный_срок')
        self.assertEqual(window.history.combo.count(), 2)
        self.assertEqual(self.store.load()[0]['thoughts'], query)
        self.assertEqual(
            history_topic('I want an AI prompt for meeting notes extraction', {}),
            'I want an AI prompt for meeting notes extraction',
        )
        self.assertEqual(
            history_topic('', {'brief': {'goal': 'Полное название старого результата'}}),
            'Полное название старого результата',
        )
        self.assertEqual(history_topic('', {'topic': 'Платформер на Pygame'}), 'Платформер на Pygame')
        self.assertEqual(history_topic('', {}, 'Saved prompt'), 'Saved prompt')
        window.close()

    def test_manual_history_error_and_input_validation(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
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
        self.assertEqual(window.history.combo.count(), 2)
        self.assertEqual(window.result_column.prompt_edit.toPlainText(), manual['prompt'])
        window.on_finished({'ok': False, 'error': 'synthetic error'})
        self.assertTrue(window.run_button.isEnabled())
        self.assertEqual(window.run_button.text(), window.build_label)
        window.history._on_selected(1)
        self.assertEqual(window.result_column.prompt_edit.toPlainText(), manual['prompt'])
        window.close()

    def test_prompt_edits_are_saved_to_history_and_survive_restart(self):
        from PyQt6.QtWidgets import QTabWidget

        manual = {
            'zeroShotPrompt': 'Task: original baseline prompt for the saved task.',
            'topic': 'Saved task',
            'technique': {'key': 'a', 'name': 'Alpha', 'category': 'test'},
            'prompt': 'ALPHA original prompt text, long enough.',
            'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'},
            'source_ref': 's',
            'variants': [
                {
                    'technique': {'key': 'a', 'name': 'Alpha', 'category': 'test'},
                    'prompt': 'ALPHA original prompt text, long enough.',
                    'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'},
                    'source_ref': 's',
                },
                {
                    'technique': {'key': 'b', 'name': 'Beta', 'category': 'test'},
                    'prompt': 'BETA original prompt text, long enough.',
                    'config': {'temperature': 0.2, 'top_p': 0.95, 'rationale': 'r'},
                    'source_ref': 's',
                },
            ],
        }
        window = self._prompta_window()
        try:
            window.thoughts.setPlainText('Saved task')
            window.on_finished({'ok': True, 'manual': manual})
            tabs = window.result_column.widget().findChild(QTabWidget)
            tabs.widget(2).setPlainText('BETA edited by the user, long enough to keep.')
            tabs.widget(0).setPlainText('Zero-shot edited by the user, long enough.')
            window.history._edit_timer.stop()
            window.history.save_edits()
        finally:
            window.close()
        saved = self.store.load()[-1]['payload']
        self.assertEqual(saved['variants'][1]['prompt'], 'BETA edited by the user, long enough to keep.')
        self.assertEqual(saved['zeroShotPrompt'], 'Zero-shot edited by the user, long enough.')
        self.assertEqual(
            saved['prompt'], 'ALPHA original prompt text, long enough.', 'untouched variants stay as built'
        )
        reopened = self._prompta_window()
        try:
            reopened.history.combo.setCurrentIndex(reopened.history.combo.findData(len(reopened.history.items) - 1))
            tabs = reopened.result_column.widget().findChild(QTabWidget)
            self.assertEqual(tabs.widget(2).toPlainText(), 'BETA edited by the user, long enough to keep.')
            self.assertTrue(tabs.widget(2).is_edited() and tabs.widget(2).restore.isVisibleTo(tabs.widget(2)))
            self.assertTrue(tabs.tabText(2).endswith('•'), 'the tab shows the variant was edited')
            self.assertFalse(tabs.widget(1).is_edited())
            tabs.widget(2).restore.click()
            self.assertEqual(tabs.widget(2).toPlainText(), 'BETA original prompt text, long enough.')
            self.assertFalse(tabs.tabText(2).endswith('•'))
            reopened.history._edit_timer.stop()
            reopened.history.save_edits()
        finally:
            reopened.close()
        saved = self.store.load()[-1]['payload']
        self.assertEqual(saved['variants'][1]['prompt'], 'BETA original prompt text, long enough.')
        self.assertEqual(
            saved['originalPrompts'],
            {'0': 'Task: original baseline prompt for the saved task.'},
            'only the still-edited variant keeps an original',
        )

    def test_history_built_under_older_rules_says_so(self):
        window = self._prompta_window()
        try:
            notes = lambda: [
                l for l in window.findChildren(QLabel) if l.text().startswith('Built with earlier Prompta rules')
            ]
            column = window.result_column
            column.flag_outdated({'promptVersion': 'v1'}, '')
            self.assertFalse(notes(), 'unknown current version: no claim')
            column.flag_outdated({'promptVersion': 'v2'}, 'v2')
            self.assertFalse(notes())
            column.flag_outdated({'promptVersion': 'v1'}, 'v2')
            self.assertEqual(len(notes()), 1)
            column.flag_outdated({}, 'v2')
            self.assertEqual(len(notes()), 2, 'results saved before versions were recorded are old too')
        finally:
            window.close()

    def test_history_is_a_standard_picker_searchable_by_prompt_text(self):
        from PyQt6.QtWidgets import QLineEdit
        from controls import Dropdown

        window = self._prompta_window()
        try:
            for thoughts, prompt in [
                ('игра змейка в питоне', 'Snake prompt with pygame'),
                ('прогноз офиса в Барселоне', 'Forecast prompt'),
            ]:
                window.thoughts.setPlainText(thoughts)
                window.on_finished(
                    {
                        'ok': True,
                        'manual': {
                            'technique': {'key': 't', 'name': 'Tech', 'category': 'x'},
                            'prompt': prompt,
                            'topic': thoughts.title(),
                            'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'},
                            'source_ref': 's',
                        },
                    }
                )
            window.clear_workspace()
            picker = window.history.picker
            self.assertIsInstance(picker, Dropdown, 'the same picker as every other dropdown')
            self.assertEqual(
                [item['label'] for item in picker._items], ['Прогноз Офиса В Барселоне', 'Игра Змейка В Питоне']
            )
            picker._open()
            search = picker._popup.findChild(QLineEdit)
            search.setText('PYGAME')  # matches the prompt text, case-insensitive
            shown = [key for key, widget in picker._item_widgets.items() if not widget.isHidden()]
            self.assertEqual(shown, ['0'])
            picker._choose('0')
            self.assertEqual(window.thoughts.toPlainText(), 'игра змейка в питоне')
            self.assertIn('Snake prompt', window.result_column.prompt_edit.toPlainText())
            self.assertEqual(picker.current_key(), '0', 'the opened entry is the current one')
            self.assertEqual(picker.text(), '', 'a toolbar icon, no label')
        finally:
            window.close()

    def test_history_picker_rows_can_be_deleted(self):
        window = self._prompta_window()
        try:
            for thoughts in ('first request', 'second request'):
                window.thoughts.setPlainText(thoughts)
                window.on_finished(
                    {
                        'ok': True,
                        'manual': {
                            'technique': {'key': 't', 'name': 'Tech', 'category': 'x'},
                            'prompt': 'A prompt for ' + thoughts + ' with detail.',
                            'topic': thoughts,
                            'config': {'temperature': 0.2, 'top_p': 0.9, 'rationale': 'r'},
                            'source_ref': 's',
                        },
                    }
                )
            picker = window.history.picker
            self.assertTrue(all(item.get('deletable') for item in picker._items))
            with patch.object(window.history.combo, 'showPopup') as native_popup:
                picker.deleteRequested.emit('0')
                native_popup.assert_not_called()  # the hidden old list must not pop up
            self.assertEqual([entry['thoughts'] for entry in window.history.items], ['second request'])
            self.assertEqual([item['label'] for item in picker._items], ['second request'])
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
