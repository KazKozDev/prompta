"""Локальная история результатов; ключи API и настройки запроса не сохраняются.

Политика хранения: файл доступен только владельцу (0600), записи старше срока и сверх лимита
удаляются при каждом сохранении. Лимиты задаются переменными окружения:
PROMPTA_HISTORY_MAX (по умолчанию 500 записей, 0 — без лимита) и
PROMPTA_HISTORY_DAYS (по умолчанию 0 — без срока). Отключить историю: PROMPTA_HISTORY_MAX=-1.
"""
from __future__ import annotations

import json
import os
from contextlib import closing
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_PATH = Path.home() / 'Library' / 'Application Support' / 'Prompta' / 'history.sqlite3'
DEFAULT_MAX_ENTRIES = 500


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def retention_from_env() -> tuple[int, int]:
    """(максимум записей, срок в днях); 0 — без ограничения, -1 записей — история выключена."""
    return _env_int('PROMPTA_HISTORY_MAX', DEFAULT_MAX_ENTRIES), max(0, _env_int('PROMPTA_HISTORY_DAYS', 0))


def history_topic(thoughts: str, payload: dict, fallback: str = "Saved prompt") -> str:
    """Use the model's topic; preserve complete wording for older saved results."""
    brief = payload.get('brief')
    brief = brief if isinstance(brief, dict) else {}
    for text in (brief.get('topic'), payload.get('topic'), brief.get('goal'), thoughts, fallback):
        if isinstance(text, str) and text.strip():
            return ' '.join(text.split())
    return "Saved prompt"



class HistoryStore:
    def __init__(self, path: Path = HISTORY_PATH, max_entries: int | None = None, max_age_days: int | None = None):
        self.path = path
        env_max, env_days = retention_from_env()
        self.max_entries = env_max if max_entries is None else max_entries
        self.max_age_days = env_days if max_age_days is None else max_age_days

    @property
    def enabled(self) -> bool:
        return self.max_entries >= 0

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=5)
        self.path.chmod(0o600)
        connection.execute('''CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL,
            thoughts TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        )''')
        return connection

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            rows = connection.execute('SELECT id, label, kind, thoughts, payload, created_at FROM history ORDER BY id').fetchall()
        entries = []
        for row in rows:
            payload = json.loads(row[4])
            if row[2] not in ('pipeline', 'manual', 'procedure') or not isinstance(payload, dict):
                raise ValueError('неверный формат записи истории')
            entries.append(dict(zip(('id', 'label', 'kind', 'thoughts', 'payload', 'created_at'), (*row[:4], payload, row[5]))))
        return entries

    def add(self, label: str, kind: str, thoughts: str, payload: dict) -> dict:
        created_at = datetime.now().astimezone().isoformat(timespec='seconds')
        entry = {'id': None, 'label': label, 'kind': kind, 'thoughts': thoughts,
                 'payload': payload, 'created_at': created_at}
        if not self.enabled:
            return entry  # история выключена: результат показывается, но не пишется на диск
        encoded = json.dumps(payload, ensure_ascii=False)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                'INSERT INTO history(label, kind, thoughts, payload, created_at) VALUES (?, ?, ?, ?, ?)',
                (label, kind, thoughts, encoded, created_at),
            )
            entry['id'] = cursor.lastrowid
            self._prune(connection)
        return entry

    def _prune(self, connection) -> int:
        """Удаляет записи старше срока и сверх лимита; возвращает, сколько удалено."""
        removed = 0
        if self.max_age_days > 0:
            cutoff = (datetime.now().astimezone() - timedelta(days=self.max_age_days)).isoformat(timespec='seconds')
            removed += connection.execute('DELETE FROM history WHERE created_at < ?', (cutoff,)).rowcount
        if self.max_entries > 0:
            removed += connection.execute(
                'DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)',
                (self.max_entries,),
            ).rowcount
        return removed

    def prune(self) -> int:
        if not self.path.exists():
            return 0
        with closing(self._connect()) as connection, connection:
            return self._prune(connection)

    def clear(self) -> None:
        """Стереть всю историю: удаляет файл базы, а не только строки, чтобы текст не остался в свободных страницах."""
        for suffix in ('', '-wal', '-shm', '-journal'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def delete(self, entry_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute('DELETE FROM history WHERE id = ?', (entry_id,))

    def update_payload(self, entry_id: int, payload: dict) -> None:
        """Keep the user's edits of a saved result (prompt texts live inside the payload)."""
        with closing(self._connect()) as connection, connection:
            connection.execute('UPDATE history SET payload = ? WHERE id = ?',
                               (json.dumps(payload, ensure_ascii=False), entry_id))
