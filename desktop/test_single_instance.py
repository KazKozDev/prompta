import os
import uuid
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QCoreApplication, QElapsedTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from single_instance import SingleInstance  # noqa: E402


class SingleInstanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_launch_wakes_the_first_and_backs_off(self):
        name = f"prompta-test-{uuid.uuid4().hex[:8]}"  # never the real app's socket
        first = SingleInstance(name)
        self.assertTrue(first.claim())
        woken = []
        first.activated.connect(lambda: woken.append(True))
        self.assertFalse(SingleInstance(name).claim())
        timer = QElapsedTimer()
        timer.start()
        while not woken and timer.elapsed() < 2000:
            QCoreApplication.processEvents()
        self.assertEqual(woken, [True])
        first.server.close()
        self.assertTrue(SingleInstance(name).claim())  # the name is free again once the first copy is gone


if __name__ == '__main__':
    unittest.main()
