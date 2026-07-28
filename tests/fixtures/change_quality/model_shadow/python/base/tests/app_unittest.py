import unittest

from src.app import normalize_tag


class NormalizeTagTest(unittest.TestCase):
    def test_normalizes_tag(self) -> None:
        self.assertEqual(normalize_tag("  Ready "), "ready")


if __name__ == "__main__":
    unittest.main()
