"""Локальная история результатов; ключи API и настройки запроса не сохраняются."""
from __future__ import annotations

import json
from contextlib import closing
import sqlite3
from datetime import datetime
from pathlib import Path

HISTORY_PATH = Path.home() / 'Library' / 'Application Support' / 'Prompta' / 'history.sqlite3'


def history_topic(thoughts: str, payload: dict, fallback: str = "Saved prompt") -> str:
    """Use the model's topic; preserve complete wording for older saved results."""
    brief = payload.get('brief')
    brief = brief if isinstance(brief, dict) else {}
    for text in (brief.get('topic'), payload.get('topic'), brief.get('goal'), thoughts, fallback):
        if isinstance(text, str) and text.strip():
            return ' '.join(text.split())
    return "Saved prompt"



class HistoryStore:
    def __init__(self, path: Path = HISTORY_PATH):
        self.path = path

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
        encoded = json.dumps(payload, ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                'INSERT INTO history(label, kind, thoughts, payload, created_at) VALUES (?, ?, ?, ?, ?)',
                (label, kind, thoughts, encoded, created_at),
            )
            entry_id = cursor.lastrowid
        return {'id': entry_id, 'label': label, 'kind': kind, 'thoughts': thoughts,
                'payload': payload, 'created_at': created_at}

    def delete(self, entry_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute('DELETE FROM history WHERE id = ?', (entry_id,))

    def update_payload(self, entry_id: int, payload: dict) -> None:
        """Keep the user's edits of a saved result (prompt texts live inside the payload)."""
        with closing(self._connect()) as connection, connection:
            connection.execute('UPDATE history SET payload = ? WHERE id = ?',
                               (json.dumps(payload, ensure_ascii=False), entry_id))
