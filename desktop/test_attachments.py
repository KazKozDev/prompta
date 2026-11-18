"""Attached project files: picked or dropped, shown as rows, sent with every mode, cleared with the workspace."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile

os.environ['PROMPTA_STATE_FILE'] = os.path.join(tempfile.mkdtemp(), 'generator.json')  # never the real app state
from PyQt6.QtCore import QSettings

QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())  # never real prefs
os.environ['PROMPTA_LOG_DIR'] = tempfile.mkdtemp()
os.environ['PROMPTA_MODELS_DIR'] = tempfile.mkdtemp()

import gc
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from app import PromptaWindow
from generator_settings import GeneratorSettings
from history import HistoryStore
from skill_mode import AGENT_MODE, INSTRUCTIONS_MODE, PROMPT_MODE, SKILL_MODE
from attachments import MAX_EMBED_CHARS, MAX_FILE_CHARS, Attachments, read_text_file, relative_names


class AttachmentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'src').mkdir()
        (self.root / 'README.md').write_text('# Shop\nRun `npm test`.', encoding='utf-8')
        (self.root / 'src' / 'app.py').write_text('print("hi")\n', encoding='utf-8')
        (self.root / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n\0\0\0')
        self.store = HistoryStore(self.root / 'history.sqlite3')
        self.patches = [
            patch('app.HistoryStore', return_value=self.store),
            patch('app.load_local_providers', return_value={}),
            patch.multiple('keychain', load=Mock(return_value=''), save=Mock(return_value=True), forget=Mock()),
            patch('generator_settings.ModelsLoader'),
            patch.object(GeneratorSettings, 'load_models'),
            patch.object(PromptaWindow, 'load_techniques'),
        ]
        for p in self.patches:
            p.start()
        self.window = PromptaWindow()

    def tearDown(self):
        self.window.close()
        for p in reversed(self.patches):
            p.stop()
        GeneratorSettings._running_loaders.clear()
        gc.collect()
        self.app.processEvents()
        self.temp.cleanup()

    def run_with(self, mode: str) -> dict:
        w = self.window
        w.mode_switch.set_mode(mode)
        w.thoughts.setPlainText('describe the shop')
        with (
            patch.object(w.generator, 'request', return_value=({'provider': 'ollama', 'model': 'm'}, '')),
            patch('app.Worker') as worker,
        ):
            w.worker = None
            w.run_pipeline()
        w.worker = None
        return worker.call_args.args[0]

    def test_text_files_only_with_paths_from_their_common_folder(self):
        self.assertIsNone(read_text_file(self.root / 'logo.png'))
        self.assertEqual(
            relative_names([self.root / 'README.md', self.root / 'src' / 'app.py']), ['README.md', 'src/app.py']
        )
        box = Attachments()
        notices: list[str] = []
        box.notice.connect(notices.append)
        box.add_paths(
            [self.root / 'README.md', self.root / 'src' / 'app.py', self.root / 'logo.png', self.root / 'README.md']
        )
        self.assertEqual([f['path'] for f in box.files()], ['README.md', 'src/app.py'], 'no binary, no duplicate')
        self.assertIn('logo.png', notices[-1])
        self.assertEqual(box.rows.count(), 2)
        box.remove((self.root / 'README.md').resolve())
        self.assertEqual([f['path'] for f in box.files()], ['app.py'])

    def labels(self, box) -> list[str]:
        texts = []
        for i in range(box.rows.count()):
            widget = box.rows.itemAt(i).widget()
            texts.append(widget.text() if isinstance(widget, QLabel) else widget.findChild(QLabel).text())
        return texts

    def test_a_prompt_carries_files_whole_until_its_limit(self):
        long = self.root / 'long.md'
        long.write_text('x' * (MAX_FILE_CHARS + 1), encoding='utf-8')
        box = Attachments()
        box.add_paths([long])
        self.assertEqual(self.labels(box), ['long.md'], 'a prompt carries the whole file')
        paths = []
        for index in range(3):
            paths.append(self.root / f'big{index}.md')
            paths[-1].write_text('x' * (MAX_EMBED_CHARS // 2), encoding='utf-8')
        box.clear()
        box.add_paths(paths + [long])
        self.assertEqual(
            self.labels(box),
            [
                'big0.md',
                'big1.md',
                'big2.md  · left out: over the total limit',
                'long.md  · left out: over the total limit',
            ],
        )

    def test_file_modes_say_when_the_model_reads_a_digest(self):
        long = self.root / 'long.md'
        long.write_text('x' * (MAX_FILE_CHARS + 1), encoding='utf-8')
        w = self.window
        w.attachments.add_paths([self.root / 'README.md'])
        w.mode_switch.set_mode(SKILL_MODE)
        self.assertEqual(self.labels(w.attachments), ['README.md'], 'small files are read whole: no note')
        w.attachments.add_paths([long])
        labels = self.labels(w.attachments)
        self.assertEqual(labels[:2], ['README.md', 'long.md'])
        self.assertIn('outlines of the rest', labels[2])
        w.mode_switch.set_mode(PROMPT_MODE)
        self.assertEqual(self.labels(w.attachments), ['README.md', 'long.md'])

    def test_a_folder_brings_its_text_files_without_ignored_build_or_secret_files(self):
        folder = self.root / 'repo'
        (folder / 'src').mkdir(parents=True)
        (folder / 'node_modules' / 'lib').mkdir(parents=True)
        (folder / '.git').mkdir()
        (folder / 'README.md').write_text('# Repo', encoding='utf-8')
        (folder / 'src' / 'main.py').write_text('def main(): pass', encoding='utf-8')
        (folder / 'node_modules' / 'lib' / 'index.js').write_text('x', encoding='utf-8')
        (folder / '.git' / 'config').write_text('x', encoding='utf-8')
        (folder / '.env').write_text('TOKEN=abc', encoding='utf-8')
        (folder / '.env.example').write_text('TOKEN=', encoding='utf-8')
        (folder / 'server.key').write_text('x', encoding='utf-8')
        (folder / 'package-lock.json').write_text('{}', encoding='utf-8')
        (folder / 'logo.png').write_bytes(b'\x89PNG\0')
        (folder / 'data.bin.txt').write_bytes(b'\0binary under a text name')
        (folder / '.github' / 'workflows').mkdir(parents=True)
        (folder / '.github' / 'workflows' / 'ci.yml').write_text('run: npm test', encoding='utf-8')
        box = Attachments()
        notices: list[str] = []
        box.notice.connect(notices.append)
        with patch('attachments._git_files', return_value=None):  # not a repository: the skip list decides
            box.add_paths([folder])
        self.assertEqual(
            sorted(f['path'] for f in box.files()),
            ['.env.example', '.github/workflows/ci.yml', 'README.md', 'src/main.py'],
        )
        self.assertIn('2 binary or large files skipped', notices[-1], 'logo.png by name, data.bin.txt by content')
        self.assertIn('2 files that may hold secrets', notices[-1])

    def test_inside_a_repository_git_decides_what_is_ignored(self):
        folder = self.root / 'repo'
        (folder / 'generated').mkdir(parents=True)
        (folder / 'README.md').write_text('# Repo', encoding='utf-8')
        (folder / 'generated' / 'out.txt').write_text('x', encoding='utf-8')
        (folder / '.gitignore').write_text('generated/\n', encoding='utf-8')
        import subprocess

        subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
        box = Attachments()
        box.add_paths([folder])
        self.assertEqual(sorted(f['path'] for f in box.files()), ['.gitignore', 'README.md'])

    def test_many_files_collapse_into_one_row_that_removes_them_all(self):
        folder = self.root / 'many'
        folder.mkdir()
        for index in range(30):
            (folder / f'm{index:02}.py').write_text('x = 1', encoding='utf-8')
        w = self.window
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(folder))])
        self.assertTrue(w.thoughts.canInsertFromMimeData(mime), 'a folder can be dropped on the request')
        box = w.attachments
        with patch('attachments._git_files', return_value=None):
            w.thoughts.insertFromMimeData(mime)
        self.assertEqual(len(box.files()), 30)
        labels = self.labels(box)
        self.assertEqual(labels[:6], [f'm{index:02}.py' for index in range(6)])
        self.assertEqual(labels[6:], ['… and 24 more files'])
        more = box.rows.itemAt(6).widget()
        more.findChild(QPushButton).click()
        self.assertEqual(box.files(), [])

    def test_the_total_text_has_a_limit(self):
        paths = []
        for index in range(6):
            paths.append(self.root / f'part{index}.txt')
            paths[-1].write_text('y' * 900_000, encoding='utf-8')
        box = Attachments()
        notices: list[str] = []
        box.notice.connect(notices.append)
        box.add_paths(paths)
        self.assertEqual(len(box.files()), 5)
        self.assertIn('At most 5 MB of text', notices[-1])

    def test_after_a_run_each_row_says_how_the_model_read_the_file(self):
        long = self.root / 'long.md'
        long.write_text('x' * (MAX_FILE_CHARS + 1), encoding='utf-8')
        w = self.window
        w.mode_switch.set_mode(SKILL_MODE)
        w.thoughts.setPlainText('describe the shop')
        w.attachments.add_paths([self.root / 'README.md', long])
        w._active_thoughts = 'describe the shop'
        with patch.object(w.skill_view, 'render_skill'), patch.object(w, '_save_result'):
            used = {'README.md': 'whole', 'long.md': 'outline'}
            w.on_finished({'ok': True, 'skill': {'name': 'shop'}, 'filesUsed': used})
        labels = self.labels(w.attachments)
        self.assertEqual(labels[:2], ['README.md  · read whole', 'long.md  · outline'])
        self.assertIn('The last run read a digest', labels[2])
        w.mode_switch.set_mode(PROMPT_MODE)
        self.assertEqual(self.labels(w.attachments), ['README.md', 'long.md'], 'a prompt carries both whole')
        w.mode_switch.set_mode(SKILL_MODE)
        self.assertEqual(self.labels(w.attachments)[1], 'long.md  · outline')
        w.thoughts.setPlainText('describe the shop and its tests')
        self.assertEqual(self.labels(w.attachments)[:2], ['README.md', 'long.md'], 'a new request: labels forgotten')
        self.assertIn('Too long to read whole', self.labels(w.attachments)[2])

    def test_labels_need_the_same_files_and_a_digest(self):
        box = Attachments()
        box.set_material(False)
        box.add_paths([self.root / 'README.md', self.root / 'src' / 'app.py'])
        box.set_uses({'README.md': 'whole', 'src/app.py': 'whole'})
        self.assertEqual(self.labels(box), ['README.md', 'src/app.py'], 'all whole: nothing to say')
        box.set_uses({'README.md': 'outline'})
        self.assertEqual(self.labels(box), ['README.md', 'src/app.py'], 'not these files: ignored')
        box.set_uses({'README.md': 'tree', 'src/app.py': 'outline'})
        self.assertEqual(self.labels(box), ['README.md  · only in the file tree', 'src/app.py  · outline'])
        box.add_paths([self.root / 'logo.png'])
        box.remove((self.root / 'README.md').resolve())
        self.assertEqual(self.labels(box), ['app.py'], 'the files changed: labels gone')

    def test_the_collapsed_row_counts_how_the_hidden_files_were_read(self):
        folder = self.root / 'many'
        folder.mkdir()
        for index in range(20):
            (folder / f'm{index:02}.py').write_text('x' * 2_000, encoding='utf-8')
        box = Attachments()
        box.set_material(False)
        with patch('attachments._git_files', return_value=None):
            box.add_paths([folder])
        box.set_uses({f'm{index:02}.py': 'outline' if index < 10 else 'tree' for index in range(20)})
        self.assertEqual(self.labels(box)[6], '… and 14 more files  · 4 outline, 10 only in the file tree')

    def test_every_mode_sends_the_files_next_to_the_request(self):
        self.window.attachments.add_paths([self.root / 'README.md'])
        for mode in (PROMPT_MODE, SKILL_MODE, INSTRUCTIONS_MODE, AGENT_MODE):
            with self.subTest(mode=mode):
                payload = self.run_with(mode)
                self.assertEqual(payload['thoughts'], 'describe the shop', 'the request stays the user text')
                self.assertEqual(payload['files'], [{'path': 'README.md', 'content': '# Shop\nRun `npm test`.'}])
                self.assertFalse(self.window.attachments.isHidden())

    def test_no_files_no_field_and_clear_empties_them(self):
        self.assertNotIn('files', self.run_with(SKILL_MODE))
        self.window.attachments.add_paths([self.root / 'README.md'])
        self.window.clear_workspace()
        self.assertEqual(self.window.attachments.files(), [])
        self.assertNotIn('files', self.run_with(SKILL_MODE))

    def test_the_paperclip_left_of_the_microphone_picks_files(self):
        w = self.window
        w.show()
        self.app.processEvents()
        field = w.thoughts.geometry()
        bar = w.thoughts.icon_bar
        origin = bar.mapTo(w.thoughts.parentWidget(), bar.rect().topLeft())
        clip = w.thoughts.attach_icon.geometry().translated(origin)
        mic = w.thoughts.microphone_icon.geometry().translated(origin)
        self.assertIsNot(w.thoughts.microphone_icon.parentWidget(), w.thoughts, 'outside the field')
        self.assertEqual(clip.y(), mic.y(), 'same row as the microphone')
        self.assertLess(clip.right(), mic.x(), 'left of it')
        self.assertGreater(clip.y(), field.bottom(), 'under the field')
        self.assertGreater(mic.right(), field.right() - 30, 'at its right edge')
        margins = w.thoughts.viewportMargins()
        self.assertEqual((margins.top(), margins.right(), margins.bottom()), (0, 0, 0), 'the text has the whole field')
        with patch('attachments.QFileDialog.getOpenFileNames', return_value=([str(self.root / 'README.md')], '')):
            w.thoughts.attach_icon.click()
        self.assertEqual([f['path'] for f in w.attachments.files()], ['README.md'])

    def test_dropped_files_are_attached_not_pasted(self):
        w = self.window
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.root / 'README.md'))])
        self.assertTrue(w.thoughts.canInsertFromMimeData(mime))
        w.thoughts.insertFromMimeData(mime)
        self.assertEqual(w.thoughts.toPlainText(), '')
        self.assertEqual([f['path'] for f in w.attachments.files()], ['README.md'])
        text = QMimeData()
        text.setText('plain words')
        w.thoughts.insertFromMimeData(text)
        self.assertEqual(w.thoughts.toPlainText(), 'plain words')


if __name__ == '__main__':
    unittest.main()
