"""One version for the whole project: APP_VERSION in app.py (the bundle and the About page read it) and package.json."""

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def app_version() -> str:
    tree = ast.parse((ROOT / "desktop" / "app.py").read_text(encoding="utf-8"))
    return next(n.value.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_VERSION")


class VersionTest(unittest.TestCase):
    def test_package_json_matches_app_version(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], app_version(), "bump APP_VERSION in desktop/app.py and package.json together")

    def test_version_is_semver(self):
        parts = app_version().split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))


if __name__ == "__main__":
    unittest.main()
