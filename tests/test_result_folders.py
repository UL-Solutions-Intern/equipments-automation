from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from result_folders import RESULTS_FOLDER_NAME, create_unique_test_folder, default_results_root


class ResultFolderTests(TestCase):
    def test_default_root_is_under_resolved_desktop(self):
        desktop = Path("C:/Users/test/Desktop")
        with patch("result_folders.resolve_desktop_folder", return_value=desktop):
            self.assertEqual(default_results_root(), desktop / RESULTS_FOLDER_NAME)

    def test_each_test_start_gets_unique_date_folder(self):
        with TemporaryDirectory() as directory:
            started_at = datetime(2026, 7, 23, 9, 30)
            first = create_unique_test_folder(directory, started_at)
            second = create_unique_test_folder(directory, started_at)
            third = create_unique_test_folder(directory, started_at)

            self.assertEqual(first.name, "2026-07-23")
            self.assertEqual(second.name, "2026-07-23(2)")
            self.assertEqual(third.name, "2026-07-23(3)")
