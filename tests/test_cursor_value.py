"""커서값 창 clipboard 읽기 테스트."""

from __future__ import annotations

import logging
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from integrations.universal_viewer.cursor_value import (
    AB_CURSOR_ACCEPT_MAX_SECONDS,
    AB_CURSOR_ACCEPT_MIN_SECONDS,
    AB_CURSOR_A_CANDIDATE_REL,
    AB_CURSOR_A_FIXED_Y_REL,
    AB_CURSOR_A_MAX_X_REL,
    AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL,
    AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL,
    AB_CURSOR_B_RELEASE_REL,
    AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL,
    AB_CURSOR_PROFILE_C_768x399,
    ABCursorAdjustmentResult,
    ABCursorAdjustmentAttempt,
    ABCursorDragReadResult,
    CURSOR_VALUE_WINDOW_CLICK_REL,
    CURSOR_VALUE_DISPLAY_MENU_ITEM_REL,
    CURSOR_VALUE_TITLE_KEYWORD,
    CURSOR_VALUE_WINDOW_MENU_REL,
    UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT,
    UNIVERSAL_VIEWER_WINDOW_MENU_REL,
    UNIVERSAL_VIEWER_NORMALIZED_HEIGHT,
    UNIVERSAL_VIEWER_NORMALIZED_LEFT,
    UNIVERSAL_VIEWER_NORMALIZED_RECT,
    UNIVERSAL_VIEWER_NORMALIZED_TOP,
    UNIVERSAL_VIEWER_NORMALIZED_WIDTH,
    CursorValueError,
    CursorValueReadResult,
    CursorValueWindow,
    adjust_ab_cursors_to_30min,
    classify_ab_cursor_seconds,
    cursor_value_window_center,
    duration_text_to_seconds,
    extract_absolute_time_difference,
    find_cursor_value_window,
    find_universal_viewer_main_window,
    drag_ab_cursor_from_a_to_b,
    interpolate_a_cursor_candidate_rel,
    is_ab_cursor_seconds_accepted,
    move_cursor_value_window_below_graph_or_safe_area,
    normalize_universal_viewer_main_window,
    open_cursor_value_window_from_universal_viewer_main_window,
    open_cursor_value_window_via_toolbar_button,
    point_from_relative,
    preview_ab_cursor_profile,
    read_cursor_value_absolute_time_difference,
    select_ab_cursor_coordinate_profile,
    test_ab_cursor_drag_read,
)
from integrations.universal_viewer.main import build_parser, main


class FakeCursorUiaWrapper:
    def __init__(
        self,
        name: str,
        *,
        control_type: str = "Button",
        pid: int = 1111,
        children: tuple["FakeCursorUiaWrapper", ...] = (),
        calls: list[tuple[str, str]] | None = None,
    ) -> None:
        self._name = name
        self._control_type = control_type
        self._pid = pid
        self._children = children
        self.calls = calls if calls is not None else []
        self.element_info = SimpleNamespace(name=name, control_type=control_type, process_id=pid)

    def window_text(self) -> str:
        return self._name

    def friendly_class_name(self) -> str:
        return self._control_type

    def descendants(self) -> tuple["FakeCursorUiaWrapper", ...]:
        return self._children

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def set_focus(self) -> None:
        self.calls.append(("focus", self._name))

    def invoke(self) -> None:
        self.calls.append(("invoke", self._name))

    def click_input(self) -> None:
        self.calls.append(("click_input", self._name))


class FakeCursorUiaDesktop:
    def __init__(self, main_window: FakeCursorUiaWrapper, windows: tuple[FakeCursorUiaWrapper, ...] = ()) -> None:
        self._main_window = main_window
        self._windows = windows

    def window(self, *, handle: int) -> FakeCursorUiaWrapper:
        return self._main_window

    def windows(self) -> tuple[FakeCursorUiaWrapper, ...]:
        return self._windows


class CursorValueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"cursor-value-test-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def _window(self, *, title: str = "커서값", visible: bool = True, enabled: bool = True) -> CursorValueWindow:
        return CursorValueWindow(
            hwnd=100,
            title=title,
            class_name="#32770",
            pid=1111,
            rectangle=(400, 200, 700, 500),
            visible=visible,
            enabled=enabled,
        )

    def _main_window(self) -> CursorValueWindow:
        return CursorValueWindow(
            hwnd=200,
            title="Universal Viewer",
            class_name="Universal_Viewer R3.12.01",
            pid=1111,
            rectangle=(20, 83, 1460, 830),
            visible=True,
            enabled=True,
        )

    def _cursor_read_result(self, duration: str) -> CursorValueReadResult:
        return CursorValueReadResult(
            window=self._window(),
            click_point=(550, 350),
            clipboard_text=f"절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:04:34.000\t{duration}",
            absolute_time_difference=duration,
        )

    def test_detects_cursor_value_window_by_title(self) -> None:
        found = find_cursor_value_window(
            window_enum_fn=lambda: (
                self._window(title="Universal Viewer"),
                self._window(title="커서값"),
            )
        )

        self.assertEqual(found.title, "커서값")

    def test_detects_universal_viewer_main_window(self) -> None:
        found = find_universal_viewer_main_window(
            window_enum_fn=lambda: (
                self._window(title="커서값"),
                self._main_window(),
            )
        )

        self.assertEqual(found.title, "Universal Viewer")
        self.assertEqual(found.class_name, "Universal_Viewer R3.12.01")

    def test_ab_cursor_profile_selects_by_class_and_size_not_computername(self) -> None:
        main_window = CursorValueWindow(
            hwnd=300,
            title="Universal Viewer",
            class_name="Universal_Viewer R3.12.01",
            pid=1111,
            rectangle=(10, 20, 778, 419),
            visible=True,
            enabled=True,
        )

        self.assertIs(select_ab_cursor_coordinate_profile(main_window), AB_CURSOR_PROFILE_C_768x399)

    def test_ab_cursor_profile_uses_unified_y_value(self) -> None:
        self.assertEqual(AB_CURSOR_PROFILE_C_768x399["ab_a_start"], (0.341146, 0.621554))
        self.assertEqual(AB_CURSOR_PROFILE_C_768x399["ab_a_max"], (0.475260, 0.621554))
        self.assertEqual(AB_CURSOR_PROFILE_C_768x399["ab_b_release_target"], (0.514323, 0.621554))

    def test_preview_ab_cursor_profile_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--preview-ab-cursor-profile"])

        self.assertTrue(args.preview_ab_cursor_profile)

    def test_preview_ab_cursor_profile_moves_points_without_click_or_drag(self) -> None:
        main_window = CursorValueWindow(
            hwnd=300,
            title="Universal Viewer",
            class_name="Universal_Viewer R3.12.01",
            pid=1111,
            rectangle=(10, 20, 778, 419),
            visible=True,
            enabled=True,
        )
        moves: list[tuple[int, int]] = []

        result = preview_ab_cursor_profile(
            self.logger,
            window_enum_fn=lambda: (main_window,),
            move_fn=moves.append,
            wait_fn=lambda _seconds: None,
        )

        self.assertIs(result.profile, AB_CURSOR_PROFILE_C_768x399)
        self.assertEqual(result.a_start_rel, (0.341146, 0.621554))
        self.assertEqual(result.a_max_rel, (0.475260, 0.621554))
        self.assertEqual(result.b_release_rel, (0.514323, 0.621554))
        self.assertEqual(moves, [result.a_start_abs, result.a_max_abs, result.b_release_abs])

    def test_ignores_invisible_or_disabled_cursor_windows(self) -> None:
        with self.assertRaisesRegex(CursorValueError, "커서값 창"):
            find_cursor_value_window(
                window_enum_fn=lambda: (
                    self._window(title="커서값", visible=False),
                    self._window(title="커서값", enabled=False),
                )
            )

    def test_click_point_is_current_window_center_not_failed_abs_coordinate(self) -> None:
        point = cursor_value_window_center((400, 200, 700, 500))

        self.assertEqual(CURSOR_VALUE_WINDOW_CLICK_REL, (0.50, 0.50))
        self.assertEqual(point, (550, 350))
        self.assertNotEqual(point, (546, 309))

    def test_move_cursor_value_window_below_graph_or_safe_area_moves_only_cursor_window(self) -> None:
        moved_rect: tuple[int, int, int, int] | None = None
        move_calls: list[tuple[int, int, int, int, int]] = []

        def cursor_window() -> CursorValueWindow:
            return CursorValueWindow(
                hwnd=100,
                title="커서값",
                class_name="#32770",
                pid=1111,
                rectangle=moved_rect or (400, 200, 700, 500),
                visible=True,
                enabled=True,
            )

        def enum_windows() -> tuple[CursorValueWindow, ...]:
            return (self._main_window(), cursor_window())

        def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
            nonlocal moved_rect
            move_calls.append((hwnd, x, y, width, height))
            moved_rect = (x, y, x + width, y + height)

        result = move_cursor_value_window_below_graph_or_safe_area(
            self.logger,
            window_enum_fn=enum_windows,
            move_window_fn=move_window,
            screen_rect_fn=lambda: (0, 0, 1920, 1080),
            wait_fn=lambda _seconds: None,
        )

        self.assertEqual(move_calls, [(100, 40, 510, 300, 300)])
        self.assertEqual(result.old_window.rectangle, (400, 200, 700, 500))
        self.assertEqual(result.new_window.rectangle, (40, 510, 340, 810))
        self.assertEqual(result.target_rectangle, (40, 510, 340, 810))
        self.assertEqual(result.main_window.rectangle, self._main_window().rectangle)
        self.assertNotEqual(move_calls[0][0], self._main_window().hwnd)

    def test_open_cursor_value_window_returns_existing_window_without_clicking(self) -> None:
        events: list[tuple[str, object]] = []

        result = open_cursor_value_window_from_universal_viewer_main_window(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            move_fn=lambda point: events.append(("move", point)),
            click_fn=lambda point: events.append(("click", point)),
            focus_window_fn=lambda hwnd: events.append(("focus", hwnd)),
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertEqual(result.hwnd, self._window().hwnd)
        self.assertEqual(events, [])

    def test_open_cursor_value_window_uses_uia_window_menu_path_without_coordinate_fallback(self) -> None:
        calls: list[tuple[str, str]] = []
        cursor_opened = False
        cursor_value_item = FakeCursorUiaWrapper("커서값 표시", control_type="MenuItem", calls=calls)
        popup = FakeCursorUiaWrapper("윈도우 popup", control_type="Menu", children=(cursor_value_item,), calls=calls)
        window_menu = FakeCursorUiaWrapper("윈도우(W)", control_type="MenuItem", calls=calls)
        main_wrapper = FakeCursorUiaWrapper("Universal Viewer", control_type="Window", children=(window_menu,), calls=calls)
        desktop = FakeCursorUiaDesktop(main_wrapper, windows=(popup,))

        def enum_windows() -> tuple[CursorValueWindow, ...]:
            return (self._main_window(), self._window(title=CURSOR_VALUE_TITLE_KEYWORD)) if cursor_opened else (self._main_window(),)

        def click_cursor_value_item() -> None:
            nonlocal cursor_opened
            calls.append(("click_input", "커서값 표시"))
            cursor_opened = True

        cursor_value_item.click_input = click_cursor_value_item  # type: ignore[method-assign]

        result = open_cursor_value_window_from_universal_viewer_main_window(
            self.logger,
            window_enum_fn=enum_windows,
            move_fn=lambda _point: self.fail("coordinate move fallback must not be used"),
            click_fn=lambda _point: self.fail("coordinate click fallback must not be used"),
            focus_window_fn=lambda _hwnd: None,
            desktop_factory=lambda _backend: desktop,
            wait_fn=lambda _seconds: None,
        )

        self.assertEqual(UNIVERSAL_VIEWER_WINDOW_MENU_REL, (0.288, 0.079))
        self.assertEqual(CURSOR_VALUE_WINDOW_MENU_REL, (0.288, 0.079))
        self.assertEqual(CURSOR_VALUE_DISPLAY_MENU_ITEM_REL, (0.387, 0.530))
        self.assertEqual(result.hwnd, self._window().hwnd)
        self.assertIn(("click_input", "윈도우(W)"), calls)
        self.assertIn(("click_input", "커서값 표시"), calls)
        self.assertNotIn(("invoke", "윈도우(W)"), calls)
        self.assertNotIn(("invoke", "커서값 표시"), calls)

    def test_open_cursor_value_window_via_toolbar_button_uses_semantic_uia(self) -> None:
        calls: list[tuple[str, str]] = []
        cursor_opened = False
        cursor_button = FakeCursorUiaWrapper(UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT, control_type="Button", calls=calls)
        main_wrapper = FakeCursorUiaWrapper("Universal Viewer", control_type="Window", children=(cursor_button,), calls=calls)
        desktop = FakeCursorUiaDesktop(main_wrapper)

        def enum_windows() -> tuple[CursorValueWindow, ...]:
            return (self._main_window(), self._window(title=CURSOR_VALUE_TITLE_KEYWORD)) if cursor_opened else (self._main_window(),)

        def invoke() -> None:
            nonlocal cursor_opened
            calls.append(("invoke", UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT))
            cursor_opened = True

        cursor_button.invoke = invoke  # type: ignore[method-assign]

        result = open_cursor_value_window_via_toolbar_button(
            self.logger,
            window_enum_fn=enum_windows,
            desktop_factory=lambda _backend: desktop,
            wait_fn=lambda _seconds: None,
        )

        self.assertEqual(result.title, CURSOR_VALUE_TITLE_KEYWORD)
        self.assertIn(("invoke", UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT), calls)

    def test_normalize_universal_viewer_window_uses_default_calibrated_rect_and_restores_first(self) -> None:
        events: list[tuple[str, object]] = []
        current_rect = (127, 127, 2047, 1154)

        def get_rectangle(_hwnd: int) -> tuple[int, int, int, int]:
            return current_rect

        def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
            nonlocal current_rect
            events.append(("move", (hwnd, x, y, width, height)))
            current_rect = (x, y, x + width, y + height)

        result = normalize_universal_viewer_main_window(
            self.logger,
            main_window=self._main_window(),
            restore_window_fn=lambda hwnd: events.append(("restore", hwnd)),
            move_window_fn=move_window,
            get_window_rectangle_fn=get_rectangle,
            focus_window_fn=lambda hwnd: events.append(("focus", hwnd)),
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertEqual((UNIVERSAL_VIEWER_NORMALIZED_LEFT, UNIVERSAL_VIEWER_NORMALIZED_TOP), (-6, 6))
        self.assertEqual((UNIVERSAL_VIEWER_NORMALIZED_WIDTH, UNIVERSAL_VIEWER_NORMALIZED_HEIGHT), (1152, 598))
        self.assertEqual(UNIVERSAL_VIEWER_NORMALIZED_RECT, (-6, 6, 1146, 604))
        self.assertEqual(result.before_rectangle, (127, 127, 2047, 1154))
        self.assertEqual(result.after_rectangle, UNIVERSAL_VIEWER_NORMALIZED_RECT)
        self.assertEqual(
            events,
            [
                ("restore", self._main_window().hwnd),
                ("wait", 0.2),
                ("move", (self._main_window().hwnd, -6, 6, 1152, 598)),
                ("wait", 0.3),
                ("focus", self._main_window().hwnd),
                ("wait", 0.2),
            ],
        )

    def test_reads_cursor_window_by_center_click_then_ctrl_a_ctrl_c(self) -> None:
        events: list[tuple[str, object]] = []
        clipboard_text = "항목\tA\tB\t차\n절대시간\t00:00:00.000\t00:29:59.000\t00:29:59.000\n"

        result = read_cursor_value_absolute_time_difference(
            self.logger,
            window_enum_fn=lambda: (self._window(),),
            move_fn=lambda point: events.append(("move", point)),
            click_fn=lambda point: events.append(("click", point)),
            hotkey_fn=lambda first, second: events.append(("hotkey", (first, second))),
            clipboard_reader=lambda: clipboard_text,
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertEqual(result.click_point, (550, 350))
        self.assertEqual(result.absolute_time_difference, "00:29:59.000")
        self.assertEqual(
            events,
            [
                ("move", (550, 350)),
                ("click", (550, 350)),
                ("hotkey", ("ctrl", "a")),
                ("hotkey", ("ctrl", "c")),
                ("wait", 0.5),
            ],
        )

    def test_ab_cursor_drag_read_uses_main_window_relative_points_and_drag_sequence(self) -> None:
        events: list[tuple[str, object]] = []
        clipboard_text = (
            "항목\tA\tB\t차\n"
            "절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:04:34.000\t00:29:55.000\n"
        )

        result = test_ab_cursor_drag_read(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            move_to_fn=lambda point, duration: events.append(("moveTo", (point, duration))),
            move_fn=lambda point: events.append(("move", point)),
            mouse_down_fn=lambda button: events.append(("mouseDown", button)),
            mouse_up_fn=lambda button: events.append(("mouseUp", button)),
            click_fn=lambda point: events.append(("click", point)),
            hotkey_fn=lambda first, second: events.append(("hotkey", (first, second))),
            clipboard_reader=lambda: clipboard_text,
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertEqual(result.a_candidate_rel, AB_CURSOR_A_CANDIDATE_REL)
        self.assertEqual(result.a_search_left_limit_rel, AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL)
        self.assertEqual(result.a_search_right_limit_rel, AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL)
        self.assertEqual(result.b_release_rel, AB_CURSOR_B_RELEASE_REL)
        self.assertEqual(result.b_release_overshoot_target_rel, AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL)
        self.assertEqual(result.a_candidate_abs, point_from_relative(self._main_window().rectangle, (0.265, 0.607)))
        self.assertEqual(result.a_search_right_limit_abs, point_from_relative(self._main_window().rectangle, (0.573, 0.607)))
        self.assertEqual(result.b_release_abs, point_from_relative(self._main_window().rectangle, (0.651, 0.607)))
        self.assertEqual(result.absolute_time_difference, "00:29:55.000")
        self.assertEqual(result.difference_seconds, 1795)
        self.assertEqual(events[0], ("moveTo", (result.a_candidate_abs, 0.2)))
        self.assertEqual(events[1], ("mouseDown", "left"))
        self.assertEqual(events[2], ("moveTo", (result.b_release_abs, 0.5)))
        self.assertEqual(events[3], ("mouseUp", "left"))
        self.assertFalse(any(event[0] == "dragTo" for event in events))
        self.assertIn(("click", (550, 350)), events)
        self.assertNotIn(("click", result.a_candidate_abs), events)
        self.assertNotIn(("click", result.b_release_abs), events)

    def test_ab_cursor_drag_helper_releases_left_button_if_move_to_b_fails(self) -> None:
        events: list[tuple[str, object]] = []
        a_point = (181, 337)
        b_point = (622, 386)

        def move_to(point: tuple[int, int], duration: float) -> None:
            events.append(("moveTo", (point, duration)))
            if point == b_point:
                raise RuntimeError("moveTo B failed")

        with self.assertRaisesRegex(RuntimeError, "moveTo B failed"):
            drag_ab_cursor_from_a_to_b(
                a_point,
                b_point,
                self.logger,
                move_to_fn=move_to,
                mouse_down_fn=lambda button: events.append(("mouseDown", button)),
                mouse_up_fn=lambda button: events.append(("mouseUp", button)),
            )

        self.assertEqual(
            events,
            [
                ("moveTo", (a_point, 0.2)),
                ("mouseDown", "left"),
                ("moveTo", (b_point, 0.5)),
                ("mouseUp", "left"),
            ],
        )

    def test_ab_cursor_drag_read_requires_cursor_value_window_before_dragging(self) -> None:
        events: list[tuple[str, object]] = []

        with self.assertRaisesRegex(CursorValueError, "커서값"):
            test_ab_cursor_drag_read(
                self.logger,
                window_enum_fn=lambda: (self._main_window(),),
                move_to_fn=lambda point, duration: events.append(("moveTo", (point, duration))),
                mouse_down_fn=lambda button: events.append(("mouseDown", button)),
                mouse_up_fn=lambda button: events.append(("mouseUp", button)),
            )

        self.assertEqual(events, [])

    def test_adjust_ab_cursor_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--adjust-ab-cursors-to-30min"])
        help_text = build_parser().format_help()

        self.assertTrue(args.adjust_ab_cursors_to_30min)
        self.assertIn("--adjust-ab-cursors-to-30min", help_text)

    def test_adjust_ab_cursor_and_print_pdf_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--adjust-ab-cursors-to-30min-and-print-pdf"])
        help_text = build_parser().format_help()

        self.assertTrue(args.adjust_ab_cursors_to_30min_and_print_pdf)
        self.assertIn("--adjust-ab-cursors-to-30min-and-print-pdf", help_text)

    def test_adjust_ab_cursor_uses_latest_calibration_constants(self) -> None:
        self.assertEqual(AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL, (0.265, 0.607))
        self.assertEqual(AB_CURSOR_A_FIXED_Y_REL, 0.607)
        self.assertEqual(AB_CURSOR_A_MAX_X_REL, 0.573)
        self.assertEqual(AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL, (0.573, 0.607))
        self.assertEqual(AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL, (0.651, 0.607))
        self.assertEqual(interpolate_a_cursor_candidate_rel(0.0), AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL)
        self.assertEqual(interpolate_a_cursor_candidate_rel(1.0), AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL)

    def test_adjust_ab_cursor_acceptance_boundaries(self) -> None:
        self.assertEqual((AB_CURSOR_ACCEPT_MIN_SECONDS, AB_CURSOR_ACCEPT_MAX_SECONDS), (1795, 1805))
        self.assertTrue(is_ab_cursor_seconds_accepted(1795))
        self.assertTrue(is_ab_cursor_seconds_accepted(1805))
        self.assertFalse(is_ab_cursor_seconds_accepted(1806))
        self.assertFalse(is_ab_cursor_seconds_accepted(1794))
        self.assertEqual(classify_ab_cursor_seconds(1806), "too long, move A right")
        self.assertEqual(classify_ab_cursor_seconds(1794), "too short, move A left")

    def test_adjust_ab_cursor_accepts_initial_1795_or_1805(self) -> None:
        for duration in ("00:29:55.000", "00:30:05.000"):
            with self.subTest(duration=duration):
                result = adjust_ab_cursors_to_30min(
                    self.logger,
                    window_enum_fn=lambda: (self._main_window(), self._window()),
                    attempt_reader_fn=lambda *_args, duration=duration: self._cursor_read_result(duration),
                )

                self.assertTrue(result.success)
                self.assertEqual(len(result.attempts), 1)

    def test_adjust_ab_cursor_coarse_scan_and_binary_after_bracket(self) -> None:
        calls: list[tuple[str, float]] = []
        responses = {
            0.265: "00:41:40.000",
            0.315: "00:35:00.000",
            0.345: "00:31:40.000",
            0.36: "00:29:40.000",
            0.3525: "00:29:58.000",
        }

        def attempt_reader(
            _attempt_number: int,
            phase: str,
            candidate_x: float,
            *_args: object,
        ) -> CursorValueReadResult:
            rounded_x = round(candidate_x, 4)
            calls.append((phase, rounded_x))
            return self._cursor_read_result(responses[rounded_x])

        result = adjust_ab_cursors_to_30min(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            attempt_reader_fn=attempt_reader,
        )

        self.assertTrue(result.success)
        self.assertEqual(
            calls,
            [
                ("initial", 0.265),
                ("coarse", 0.315),
                ("coarse", 0.345),
                ("coarse", 0.36),
                ("binary", 0.3525),
            ],
        )
        self.assertEqual(result.best_attempt.phase, "binary")  # type: ignore[union-attr]

    def test_adjust_ab_cursor_fails_when_right_limit_is_still_too_long(self) -> None:
        calls: list[tuple[str, float]] = []

        def attempt_reader(
            _attempt_number: int,
            phase: str,
            candidate_x: float,
            *_args: object,
        ) -> CursorValueReadResult:
            calls.append((phase, round(candidate_x, 3)))
            return self._cursor_read_result("00:41:00.000")

        result = adjust_ab_cursors_to_30min(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            attempt_reader_fn=attempt_reader,
        )

        self.assertFalse(result.success)
        self.assertIn("max_a_x", result.reason)
        self.assertEqual([progress for phase, progress in calls if phase == "coarse"], [0.315, 0.365, 0.415, 0.465, 0.515, 0.565])

    def test_adjust_ab_cursor_runs_drag_and_reads_after_every_attempt(self) -> None:
        events: list[tuple[str, object]] = []
        result = adjust_ab_cursors_to_30min(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            move_to_fn=lambda point, duration: events.append(("moveTo", (point, duration))),
            move_fn=lambda point: events.append(("move", point)),
            mouse_down_fn=lambda button: events.append(("mouseDown", button)),
            mouse_up_fn=lambda button: events.append(("mouseUp", button)),
            click_fn=lambda point: events.append(("click", point)),
            hotkey_fn=lambda first, second: events.append(("hotkey", (first, second))),
            clipboard_reader=lambda: (
                "항목\tA\tB\t차\n"
                "절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:04:34.000\t00:29:55.000\n"
            ),
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertTrue(result.success)
        self.assertEqual(events[0], ("moveTo", (point_from_relative(self._main_window().rectangle, (0.265, 0.607)), 0.2)))
        self.assertEqual(events[1], ("mouseDown", "left"))
        self.assertEqual(events[2], ("moveTo", (point_from_relative(self._main_window().rectangle, (0.651, 0.607)), 0.5)))
        self.assertEqual(events[3], ("mouseUp", "left"))
        self.assertIn(("click", (550, 350)), events)
        self.assertIn(("hotkey", ("ctrl", "a")), events)
        self.assertIn(("hotkey", ("ctrl", "c")), events)
        self.assertFalse(any(event[0] == "dragTo" for event in events))

    def test_adjust_ab_cursor_next_attempt_uses_stored_graph_coordinates_after_cursor_read(self) -> None:
        events: list[tuple[str, object]] = []
        clipboard_values = iter(
            (
                "항목\tA\tB\t차\n절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:05:39.000\t00:31:00.000\n",
                "항목\tA\tB\t차\n절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:04:34.000\t00:29:55.000\n",
            )
        )

        result = adjust_ab_cursors_to_30min(
            self.logger,
            window_enum_fn=lambda: (self._main_window(), self._window()),
            move_to_fn=lambda point, duration: events.append(("moveTo", (point, duration))),
            move_fn=lambda point: events.append(("move", point)),
            mouse_down_fn=lambda button: events.append(("mouseDown", button)),
            mouse_up_fn=lambda button: events.append(("mouseUp", button)),
            click_fn=lambda point: events.append(("click", point)),
            hotkey_fn=lambda first, second: events.append(("hotkey", (first, second))),
            clipboard_reader=lambda: next(clipboard_values),
            mouse_position_fn=lambda: (550, 350),
            wait_fn=lambda seconds: events.append(("wait", seconds)),
        )

        self.assertTrue(result.success)
        move_to_events = [event for event in events if event[0] == "moveTo"]
        first_a = point_from_relative(self._main_window().rectangle, (0.265, 0.607))
        b_release = point_from_relative(self._main_window().rectangle, (0.651, 0.607))
        second_a = point_from_relative(self._main_window().rectangle, (0.28, 0.607))
        self.assertEqual(move_to_events[0], ("moveTo", (first_a, 0.2)))
        self.assertEqual(move_to_events[1], ("moveTo", (b_release, 0.5)))
        self.assertEqual(move_to_events[2], ("moveTo", (second_a, 0.2)))
        self.assertEqual(move_to_events[3], ("moveTo", (b_release, 0.5)))
        self.assertIn(("click", (550, 350)), events)
        self.assertNotEqual(move_to_events[2], ("moveTo", ((550, 350), 0.2)))

    def test_extracts_absolute_time_difference_from_tabular_clipboard(self) -> None:
        text = "항목\t커서A\t커서B\t차\n절대시간\t12:00:00.000\t12:29:59.000\t00:29:59.000\n"

        self.assertEqual(extract_absolute_time_difference(text), "00:29:59.000")

    def test_extracts_difference_from_tabular_absolute_time_row_with_dates(self) -> None:
        text = (
            "항목\t커서A\t커서B\t차\n"
            "절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:05:10.000\t00:30:31.000\n"
        )

        self.assertEqual(extract_absolute_time_difference(text), "00:30:31.000")
        self.assertNotEqual(extract_absolute_time_difference(text), "12:05:10.000")

    def test_extracts_difference_from_space_separated_absolute_time_row_with_dates(self) -> None:
        text = (
            "절대시간  A time: 2026/06/11 11:34:39.000  "
            "B time: 2026/06/11 12:05:10.000  차: 00:30:31.000"
        )

        self.assertEqual(extract_absolute_time_difference(text), "00:30:31.000")
        self.assertNotEqual(extract_absolute_time_difference(text), "12:05:10.000")

    def test_extracts_absolute_time_difference_from_inline_clipboard(self) -> None:
        text = "절대시간  커서A=12:00:00.000  커서B=12:29:59.000  차  00:29:59.000"

        self.assertEqual(extract_absolute_time_difference(text), "00:29:59.000")

    def test_raises_when_absolute_time_difference_is_missing(self) -> None:
        with self.assertRaisesRegex(CursorValueError, "절대시간"):
            extract_absolute_time_difference("채널\tA\tB\t차\nCH001\t1\t2\t1\n")

    def test_raises_when_absolute_time_row_has_only_date_times_without_difference(self) -> None:
        text = "절대시간  A 2026/06/11 11:34:39.000  B 2026/06/11 12:05:10.000"

        with self.assertRaisesRegex(CursorValueError, "절대시간"):
            extract_absolute_time_difference(text)

    def test_duration_text_to_seconds(self) -> None:
        self.assertEqual(duration_text_to_seconds("00:29:59.000"), 1799)
        self.assertEqual(duration_text_to_seconds("00:30:31.000"), 1831)
        self.assertEqual(duration_text_to_seconds("01:02:03.000"), 3723)

    def test_inspect_cursor_value_difference_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--inspect-cursor-value-difference"])
        help_text = build_parser().format_help()

        self.assertTrue(args.inspect_cursor_value_difference)
        self.assertIn("--inspect-cursor-value-difference", help_text)
        self.assertIn("커서값", help_text)

    def test_test_ab_cursor_drag_read_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--test-ab-cursor-drag-read"])
        help_text = build_parser().format_help()

        self.assertTrue(args.test_ab_cursor_drag_read)
        self.assertIn("--test-ab-cursor-drag-read", help_text)

    def test_open_cursor_value_window_test_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--open-cursor-value-window-test"])
        help_text = build_parser().format_help()

        self.assertTrue(args.open_cursor_value_window_test)
        self.assertIn("--open-cursor-value-window-test", help_text)

    def test_inspect_cursor_value_difference_cli_prints_value_and_seconds(self) -> None:
        result = CursorValueReadResult(
            window=self._window(),
            click_point=(550, 350),
            clipboard_text=(
                "절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:05:10.000\t00:30:31.000"
            ),
            absolute_time_difference="00:30:31.000",
        )
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.read_cursor_value_absolute_time_difference", return_value=result) as reader:
            with patch("integrations.universal_viewer.main.resolve_input_files") as resolve_inputs:
                with patch("integrations.universal_viewer.main.inspect_display_group_settings") as inspect_display:
                    with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_pdf:
                        with redirect_stdout(stdout):
                            exit_code = main(["--inspect-cursor-value-difference"])

        self.assertEqual(exit_code, 0)
        reader.assert_called_once()
        resolve_inputs.assert_not_called()
        inspect_display.assert_not_called()
        print_pdf.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("cursor value window found", output)
        self.assertIn("cursor value window rectangle: (400, 200, 700, 500)", output)
        self.assertIn("clipboard copied", output)
        self.assertIn("absolute time difference: 00:30:31.000", output)
        self.assertIn("difference seconds: 1831", output)

    def test_open_cursor_value_window_test_cli_opens_window_and_does_not_open_other_flows(self) -> None:
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.open_cursor_value_window_from_universal_viewer_main_window", return_value=self._window()) as opener:
            with patch("integrations.universal_viewer.main.resolve_input_files") as resolve_inputs:
                with patch("integrations.universal_viewer.main.inspect_display_group_settings") as inspect_display:
                    with patch("integrations.universal_viewer.main.adjust_ab_cursors_to_30min") as adjust:
                        with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_pdf:
                            with redirect_stdout(stdout):
                                exit_code = main(["--open-cursor-value-window-test"])

        self.assertEqual(exit_code, 0)
        opener.assert_called_once()
        resolve_inputs.assert_not_called()
        inspect_display.assert_not_called()
        adjust.assert_not_called()
        print_pdf.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("cursor value window opened", output)
        self.assertIn("cursor value window rectangle: (400, 200, 700, 500)", output)

    def test_inspect_cursor_value_difference_cli_rejects_raw_files(self) -> None:
        stderr = StringIO()

        with patch("integrations.universal_viewer.main.read_cursor_value_absolute_time_difference") as reader:
            with redirect_stderr(stderr):
                exit_code = main(["--inspect-cursor-value-difference", ".\\input\\sample.DAE"])

        self.assertEqual(exit_code, 1)
        reader.assert_not_called()
        self.assertIn("raw", stderr.getvalue())

    def test_inspect_cursor_value_difference_cli_reports_helper_error(self) -> None:
        stderr = StringIO()

        with patch(
            "integrations.universal_viewer.main.read_cursor_value_absolute_time_difference",
            side_effect=CursorValueError("커서값 창을 찾지 못했습니다."),
        ):
            with redirect_stderr(stderr):
                exit_code = main(["--inspect-cursor-value-difference"])

        self.assertEqual(exit_code, 1)
        self.assertIn("커서값", stderr.getvalue())

    def test_test_ab_cursor_drag_read_cli_prints_difference_and_does_not_open_other_flows(self) -> None:
        read_result = CursorValueReadResult(
            window=self._window(),
            click_point=(550, 350),
            clipboard_text="절대시간\t2026/06/11 11:34:39.000\t2026/06/11 12:04:34.000\t00:29:55.000",
            absolute_time_difference="00:29:55.000",
        )
        result = ABCursorDragReadResult(
            main_window=self._main_window(),
            cursor_window=self._window(),
            a_candidate_rel=(0.265, 0.607),
            a_candidate_abs=(402, 536),
            b_release_rel=(0.651, 0.607),
            b_release_abs=(957, 536),
            cursor_value_result=read_result,
            a_search_right_limit_rel=(0.573, 0.607),
            a_search_right_limit_abs=(845, 536),
        )
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.test_ab_cursor_drag_read", return_value=result) as runner:
            with patch("integrations.universal_viewer.main.resolve_input_files") as resolve_inputs:
                with patch("integrations.universal_viewer.main.inspect_display_group_settings") as inspect_display:
                    with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_pdf:
                        with redirect_stdout(stdout):
                            exit_code = main(["--test-ab-cursor-drag-read"])

        self.assertEqual(exit_code, 0)
        runner.assert_called_once()
        resolve_inputs.assert_not_called()
        inspect_display.assert_not_called()
        print_pdf.assert_not_called()
        output = stdout.getvalue()
        self.assertIn("AB cursor drag test completed", output)
        self.assertIn("a_search_left_limit_rel=(0.265,0.607)", output)
        self.assertIn("a_search_left_limit_abs=(402, 536)", output)
        self.assertIn("a_search_right_limit_rel=(0.573,0.607)", output)
        self.assertIn("a_search_right_limit_abs=(845, 536)", output)
        self.assertIn("b_release_overshoot_target_rel=(0.651,0.607)", output)
        self.assertIn("b_release_overshoot_target_abs=(957, 536)", output)
        self.assertIn("absolute time difference: 00:29:55.000", output)
        self.assertIn("difference seconds: 1795", output)

    def test_adjust_ab_cursor_cli_prints_success_and_does_not_open_other_flows(self) -> None:
        attempt = ABCursorAdjustmentAttempt(
            attempt_number=1,
            phase="initial",
            progress=0.0,
            a_candidate_rel=(0.265, 0.607),
            a_candidate_abs=(402, 536),
            b_release_rel=(0.651, 0.607),
            b_release_abs=(957, 536),
            absolute_time_difference="00:29:55.000",
            seconds=1795,
            decision="success",
        )
        result = ABCursorAdjustmentResult(True, (attempt,), attempt, "success")
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.adjust_ab_cursors_to_30min", return_value=result) as runner:
            with patch("integrations.universal_viewer.main.resolve_input_files") as resolve_inputs:
                with patch("integrations.universal_viewer.main.inspect_display_group_settings") as inspect_display:
                    with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_pdf:
                        with patch("integrations.universal_viewer.main.move_cursor_value_window_below_graph_or_safe_area") as mover:
                            with redirect_stdout(stdout):
                                exit_code = main(["--adjust-ab-cursors-to-30min"])

        self.assertEqual(exit_code, 0)
        runner.assert_called_once()
        resolve_inputs.assert_not_called()
        inspect_display.assert_not_called()
        print_pdf.assert_not_called()
        mover.assert_called_once()
        output = stdout.getvalue()
        self.assertIn("AB cursor 30min adjustment completed", output)
        self.assertIn("a_candidate_rel=(0.265,0.607)", output)
        self.assertIn("b_release_rel=(0.651,0.607)", output)
        self.assertIn("absolute time difference: 00:29:55.000", output)
        self.assertIn("difference seconds: 1795", output)
        self.assertIn("accepted range: 1795-1805 seconds", output)
        self.assertIn("PDF was not printed", output)

    def test_adjust_ab_cursor_cli_rejects_raw_files(self) -> None:
        stderr = StringIO()

        with patch("integrations.universal_viewer.main.adjust_ab_cursors_to_30min") as runner:
            with redirect_stderr(stderr):
                exit_code = main(["--adjust-ab-cursors-to-30min", ".\\input\\sample.DAE"])

        self.assertEqual(exit_code, 1)
        runner.assert_not_called()
        self.assertIn("raw", stderr.getvalue())

    def test_adjust_ab_cursor_and_print_pdf_does_not_print_if_adjustment_fails(self) -> None:
        attempt = ABCursorAdjustmentAttempt(
            attempt_number=1,
            phase="initial",
            progress=0.265,
            a_candidate_rel=(0.265, 0.607),
            a_candidate_abs=(402, 536),
            b_release_rel=(0.651, 0.607),
            b_release_abs=(957, 536),
            absolute_time_difference="00:31:00.000",
            seconds=1860,
            decision="too long, move A right",
        )
        result = ABCursorAdjustmentResult(False, (attempt,), attempt, "not adjusted")
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.adjust_ab_cursors_to_30min", return_value=result) as adjust:
            with patch("integrations.universal_viewer.main.move_cursor_value_window_below_graph_or_safe_area") as mover:
                with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_pdf:
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "--adjust-ab-cursors-to-30min-and-print-pdf",
                                "--output-pdf",
                                ".\\output\\after_ab.pdf",
                            ]
                        )

        self.assertEqual(exit_code, 1)
        adjust.assert_called_once()
        mover.assert_not_called()
        print_pdf.assert_not_called()
        self.assertIn("PDF was not printed", stdout.getvalue())

    def test_adjust_ab_cursor_and_print_pdf_prints_after_success_without_reopening_raw(self) -> None:
        attempt = ABCursorAdjustmentAttempt(
            attempt_number=1,
            phase="initial",
            progress=0.265,
            a_candidate_rel=(0.265, 0.607),
            a_candidate_abs=(402, 536),
            b_release_rel=(0.651, 0.607),
            b_release_abs=(957, 536),
            absolute_time_difference="00:29:55.000",
            seconds=1795,
            decision="success",
        )
        adjustment = ABCursorAdjustmentResult(True, (attempt,), attempt, "success")
        pdf_result = SimpleNamespace(
            output_pdf_path=Path("output/after_ab.pdf"),
            pdf_size_bytes=1234,
            pdf_page_count=1,
            validation_warning="",
        )
        stdout = StringIO()
        events: list[str] = []

        def adjust_side_effect(*_args: object, **_kwargs: object) -> ABCursorAdjustmentResult:
            events.append("adjust")
            return adjustment

        def print_side_effect(*_args: object, **_kwargs: object) -> object:
            events.append("print")
            return pdf_result

        with patch("integrations.universal_viewer.main.adjust_ab_cursors_to_30min", side_effect=adjust_side_effect) as adjust:
            with patch("integrations.universal_viewer.main.move_cursor_value_window_below_graph_or_safe_area") as mover:
                with patch("integrations.universal_viewer.main.focus_universal_viewer_main_window", return_value=self._main_window()) as focus:
                    with patch("integrations.universal_viewer.main.print_raw_file_to_pdf", side_effect=print_side_effect) as print_pdf:
                        with redirect_stdout(stdout):
                            exit_code = main(
                                [
                                    "--adjust-ab-cursors-to-30min-and-print-pdf",
                                    "--output-pdf",
                                    ".\\output\\after_ab.pdf",
                                ]
                            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["adjust", "print"])
        adjust.assert_called_once()
        mover.assert_called_once()
        focus.assert_called_once()
        print_pdf.assert_called_once()
        open_raw_file_fn = print_pdf.call_args.kwargs["open_raw_file_fn"]
        opened = open_raw_file_fn()
        self.assertEqual(opened.main_window.handle, self._main_window().hwnd)
        self.assertTrue(opened.hint_verified)
        output = stdout.getvalue()
        self.assertIn("AB cursor 30min adjustment completed", output)
        self.assertIn("PDF 출력 파일", output)

    def test_test_ab_cursor_drag_read_cli_rejects_raw_files(self) -> None:
        stderr = StringIO()

        with patch("integrations.universal_viewer.main.test_ab_cursor_drag_read") as runner:
            with redirect_stderr(stderr):
                exit_code = main(["--test-ab-cursor-drag-read", ".\\input\\sample.DAE"])

        self.assertEqual(exit_code, 1)
        runner.assert_not_called()
        self.assertIn("raw", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
