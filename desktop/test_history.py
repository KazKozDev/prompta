"""Политика хранения истории: лимит записей, срок, полная очистка, выключение."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from .history import HistoryStore
except ImportError:
    from history import HistoryStore


class HistoryRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'history.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_keeps_only_newest_entries_over_limit(self):
        store = HistoryStore(self.path, max_entries=3, max_age_days=0)
        for i in range(5):
            store.add(f'q{i}', 'pipeline', f'мысли {i}', {'n': i})
        self.assertEqual([e['label'] for e in store.load()], ['q2', 'q3', 'q4'])

    def test_drops_entries_older_than_max_age(self):
        store = HistoryStore(self.path, max_entries=0, max_age_days=30)
        store.add('fresh', 'pipeline', 'x', {})
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO history(label, kind, thoughts, payload, created_at) VALUES ('old', 'pipeline', 'x', '{}', '2020-01-01T00:00:00+00:00')")
        self.assertEqual(store.prune(), 1)
        self.assertEqual([e['label'] for e in store.load()], ['fresh'])

    def test_clear_removes_the_database_file(self):
        store = HistoryStore(self.path)
        store.add('q', 'pipeline', 'секрет', {})
        store.clear()
        self.assertFalse(self.path.exists())
        self.assertEqual(store.load(), [])

    def test_disabled_history_never_touches_disk(self):
        store = HistoryStore(self.path, max_entries=-1)
        entry = store.add('q', 'pipeline', 'x', {'a': 1})
        self.assertIsNone(entry['id'])
        self.assertFalse(self.path.exists())

    def test_file_is_private_to_the_owner(self):
        HistoryStore(self.path).add('q', 'pipeline', 'x', {})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class QtLogFilterTest(unittest.TestCase):
    def test_only_known_accessibility_noise_is_hidden(self):
        try:
            from .qt_log import is_known_noise
        except ImportError:
            from qt_log import is_known_noise
        self.assertTrue(is_known_noise("QTextCursor::setPosition: Position '59' out of range"))
        self.assertTrue(is_known_noise('Cell requested for row 1 is out of bounds for table with 0 rows! Resizing table model.',
                                       'qt.accessibility.table'))
        self.assertFalse(is_known_noise('QPainter::begin: Paint device returned engine == 0'))
        self.assertFalse(is_known_noise("QTextCursor::setPosition: Position '59' out of range", 'qt.text.custom'))
        self.assertFalse(is_known_noise('Traceback (most recent call last):'))


if __name__ == '__main__':
    unittest.main()
