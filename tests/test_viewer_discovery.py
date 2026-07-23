"""Universal Viewer 후보 창 탐지 테스트."""

import unittest

from integrations.universal_viewer.config import UNIVERSAL_VIEWER_PROFILE
from integrations.universal_viewer.viewer_discovery import (
    WindowInfo,
    classify_windows,
    format_viewer_candidate,
    is_helper_window,
    is_main_window,
    is_viewer_candidate,
)


class ViewerDiscoveryTests(unittest.TestCase):
    def test_profile_contains_verified_main_window_rule(self) -> None:
        self.assertEqual(UNIVERSAL_VIEWER_PROFILE.name, "universal_viewer")
        self.assertEqual(UNIVERSAL_VIEWER_PROFILE.main_window_title, "Universal Viewer")
        self.assertEqual(UNIVERSAL_VIEWER_PROFILE.main_class_prefix, "Universal_Viewer")
        self.assertEqual(UNIVERSAL_VIEWER_PROFILE.verified_backend, "win32")

    def test_korean_and_english_titles_are_candidates(self) -> None:
        korean = WindowInfo("데이터보기", 1234, "Unknown", "win32")
        english = WindowInfo("SMARTDAC+ STANDARD Universal Viewer", 5678, "Unknown", "uia")
        self.assertTrue(is_viewer_candidate(korean, UNIVERSAL_VIEWER_PROFILE))
        self.assertTrue(is_viewer_candidate(english, UNIVERSAL_VIEWER_PROFILE))

    def test_main_window_is_prioritized_and_automation_target(self) -> None:
        main = WindowInfo("Universal Viewer", 1234, "Universal_Viewer R3.12.01", "win32")
        keyword_candidate = WindowInfo("데이터보기", 1234, "AfxWnd", "win32")
        general = WindowInfo("메모장", 5678, "Notepad", "uia")
        result = classify_windows((general, keyword_candidate, main), UNIVERSAL_VIEWER_PROFILE)
        self.assertEqual(result.viewer_candidates[0].title, "Universal Viewer")
        self.assertTrue(result.viewer_candidates[0].main_window)
        self.assertEqual(result.automation_targets, (result.viewer_candidates[0],))
        self.assertIn("main_window=true", format_viewer_candidate(result.viewer_candidates[0]))

    def test_gdi_helper_window_is_excluded_from_automation_targets(self) -> None:
        helper = WindowInfo(
            "GDI+ Window (UnivViewer.exe)",
            1234,
            "GDI+ Hook Window Class",
            "win32",
        )
        main = WindowInfo("Universal Viewer", 1234, "Universal_Viewer R3.12.01", "win32")
        result = classify_windows((helper, main), UNIVERSAL_VIEWER_PROFILE)
        helper_result = next(window for window in result.viewer_candidates if window.helper_window)
        self.assertTrue(is_helper_window(helper, UNIVERSAL_VIEWER_PROFILE))
        self.assertFalse(is_main_window(helper, UNIVERSAL_VIEWER_PROFILE))
        self.assertNotIn(helper_result, result.automation_targets)
        self.assertIn("helper_window=true", format_viewer_candidate(helper_result))

    def test_gdi_window_from_other_pid_is_not_viewer_helper(self) -> None:
        main = WindowInfo("Universal Viewer", 1234, "Universal_Viewer R3.12.01", "win32")
        unrelated = WindowInfo("GDI+ Window (Other.exe)", 9999, "GDI+ Hook Window Class", "win32")
        result = classify_windows((unrelated, main), UNIVERSAL_VIEWER_PROFILE)
        self.assertFalse(next(window for window in result.general_windows if window.pid == 9999).helper_window)


if __name__ == "__main__":
    unittest.main()
