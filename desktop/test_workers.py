"""Model-list fetching: network failures give an empty list; anything odd still ends the loader thread."""

import http.client
import unittest
from unittest.mock import patch

import workers


class ModelListTest(unittest.TestCase):
    def test_network_failures_give_an_empty_list(self):
        for error in (OSError('refused'), TimeoutError(), http.client.IncompleteRead(b''), ValueError('not json')):
            with self.subTest(error=type(error).__name__), patch('urllib.request.urlopen', side_effect=error):
                self.assertEqual(workers.fetch_ollama_models(), [])
                self.assertEqual(workers.fetch_cloud_models('openai', 'key'), [])

    def test_loader_always_emits_even_on_an_unexpected_error(self):
        loader = workers.ModelsLoader('ollama')
        got = []
        loader.loaded.connect(got.append)
        with patch('workers.fetch_ollama_models', side_effect=TypeError('odd answer')):
            loader.run()  # the thread body, called directly
        self.assertEqual(got, [[]])


if __name__ == '__main__':
    unittest.main()
