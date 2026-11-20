"""The bridge subprocess: progress, cancellation and timeouts."""

from test_support import WindowTestCase
import subprocess
import unittest
from unittest.mock import Mock, patch

from app import PromptaWindow
from generator_settings import GeneratorSettings
from PyQt6.QtCore import Qt
from workers import Worker


class WorkerTest(WindowTestCase):
    def test_generation_line_tracks_success_error_and_cancellation(self):
        with patch.object(GeneratorSettings, 'load_models'), patch.object(PromptaWindow, 'load_techniques'):
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
                    window.on_progress(40, 'Writing your prompt…')
                    self.assertEqual(window.generation_progress.value(), 40)
                    window.on_progress(20, 'Late event')
                    self.assertEqual(window.generation_progress.value(), 40)
                    self.assertEqual(window.status.text(), 'Writing your prompt…')
                    if outcome == 'cancel':
                        worker.isRunning.return_value = True
                        window.cancel_run()
                        worker.cancel.assert_called_once()
                        self.assertTrue(window.generation_progress.isVisible())
                    if outcome == 'success':
                        window.on_finished(
                            {
                                'ok': True,
                                'manual': {
                                    'technique': {'key': 'test', 'name': 'Test', 'category': 'test'},
                                    'prompt': 'Example',
                                    'config': {'temperature': 0.2, 'top_p': 1, 'rationale': 'Test'},
                                    'source_ref': 'test',
                                },
                            }
                        )
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

    def test_cancel_before_launch_does_not_spawn(self):
        worker = Worker({})
        responses = []
        worker.finished_ok.connect(responses.append)
        worker.cancel()
        with patch('subprocess.Popen') as spawn:
            worker.run()
        spawn.assert_not_called()
        self.assertEqual(responses, [{'ok': False, 'error': 'Cancelled'}])

    def test_worker_streams_real_progress_before_result(self):
        import sys

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
        worker.progress.connect(
            lambda value, stage: progress.append((value, stage, worker.proc.poll())), Qt.ConnectionType.DirectConnection
        )
        worker.finished_ok.connect(responses.append)

        def child(*args, **kwargs):
            return spawn([sys.executable, '-c', script], **kwargs)

        with patch('subprocess.Popen', side_effect=child):
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
        with patch('subprocess.Popen', return_value=proc):
            worker.run()
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.call_count, 2)
        self.assertFalse(responses[0]['ok'])


if __name__ == '__main__':
    unittest.main()
