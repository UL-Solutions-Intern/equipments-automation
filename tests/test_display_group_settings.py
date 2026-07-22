"""표시 그룹 설정창 안전 조사(Stage 5A) 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import inspect
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from integrations.universal_viewer.config import AppConfig
import integrations.universal_viewer.display_group_settings as display_group_settings_module
from integrations.universal_viewer.display_group_settings import (
    ActualClickTestStep,
    DISPLAY_GROUP_MENU_PATH,
    DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736,
    DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    DisplayGroupDialogSnapshot,
    DisplayGroupInspectionError,
    DisplayGroupInspectionResult,
    UiaElementSnapshot,
    Win32WindowSnapshot,
    TimeAxisFullDisplayResult,
    UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL,
    UNIVERSAL_VIEWER_GROUP_SETTING_BUTTON_TEXT,
    UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL,
    apply_display_group_geometry_actions_confirmed,
    apply_display_group_geometry_actions_test,
    apply_display_group_max_48_confirmed,
    apply_time_axis_full_display_by_coordinates,
    apply_time_axis_full_display_by_uia,
    build_display_group_max_48_confirmed_sequence,
    build_display_group_max_48_confirmed_sequence_from_coordinate_profile,
    calculate_display_group_max_48_action_preview,
    calculate_time_axis_full_display_points,
    calculate_display_group_geometry_action_preview,
    calculate_display_group_geometry,
    close_display_group_dialog_without_applying,
    collect_uia_elements_with_attempt_logs,
    enum_descendant_hwnds_with_depth,
    execute_actual_click_test_step,
    filter_display_group_dialog_candidates,
    heating_point_to_group_position,
    inspect_display_group_geometry,
    inspect_display_group_scrollbar_points_pause,
    inspect_display_group_settings,
    is_forbidden_commit_button_title,
    is_display_top_menu_text,
    is_safe_close_button_title,
    open_display_group_settings_dialog_via_menu,
    open_display_group_settings_dialog_via_toolbar_button,
    open_display_group_settings_dialog_via_uia_menu,
    point_from_coordinate_profile,
    preview_display_group_geometry_actions,
    preview_display_group_max_48_actions,
    scrollbar_up_click_coordinate,
    select_display_group_coordinate_profile,
)
from integrations.universal_viewer.main import build_parser, main
from integrations.universal_viewer.viewer_discovery import WindowInfo
from integrations.universal_viewer.viewer_launcher import ViewerOpenResult


class FakeUiaWrapper:
    def __init__(
        self,
        name: str,
        *,
        control_type: str = "Button",
        class_name: str = "",
        pid: int = 1111,
        children: tuple["FakeUiaWrapper", ...] = (),
        calls: list[tuple[str, str]] | None = None,
    ) -> None:
        self._name = name
        self._control_type = control_type
        self._class_name = class_name
        self._pid = pid
        self._children = children
        self.calls = calls if calls is not None else []
        self.element_info = SimpleNamespace(
            name=name,
            control_type=control_type,
            class_name=class_name,
            process_id=pid,
        )

    def window_text(self) -> str:
        return self._name

    def friendly_class_name(self) -> str:
        return self._control_type

    def class_name(self) -> str:
        return self._class_name

    def process_id(self) -> int:
        return self._pid

    def descendants(self) -> tuple["FakeUiaWrapper", ...]:
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


class FakeUiaDesktop:
    def __init__(self, main_window: FakeUiaWrapper, windows: tuple[FakeUiaWrapper, ...]) -> None:
        self._main_window = main_window
        self._windows = windows

    def window(self, *, handle: int) -> FakeUiaWrapper:
        return self._main_window

    def windows(self) -> tuple[FakeUiaWrapper, ...]:
        return self._windows


class DisplayGroupSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"display-group-test-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def _opened(self, root: Path, *, hint_verified: bool = True) -> ViewerOpenResult:
        work_copy = root / "output" / "work" / "sample_DAE.DAE"
        viewer_exe = root / "UnivViewer.exe"
        work_copy.parent.mkdir(parents=True, exist_ok=True)
        work_copy.write_bytes(b"raw-data")
        viewer_exe.write_bytes(b"exe")
        return ViewerOpenResult(
            source_path=root / "input" / "sample.DAE",
            work_copy_path=work_copy,
            viewer_exe_path=viewer_exe,
            planned_pdf_path=root / "output" / "sample_DAE.pdf",
            process_id=1111,
            main_window=WindowInfo(
                "Universal Viewer",
                1111,
                "Universal_Viewer R3.12.01",
                "win32",
                handle=100,
                main_window=True,
            ),
            raw_file_hints=(work_copy.name,) if hint_verified else ("other.DAE",),
            hint_verified=hint_verified,
            matched_raw_file_hints=(work_copy.name,) if hint_verified else (),
            warning_message="" if hint_verified else "확인 실패",
        )

    def _dialog(self) -> DisplayGroupDialogSnapshot:
        return DisplayGroupDialogSnapshot(
            top_level=Win32WindowSnapshot(200, "표시 그룹 설정", "#32770", 1111, True, True, "(1, 2, 3, 4)"),
            win32_children=(
                Win32WindowSnapshot(201, "확인", "Button", 1111, True, True, "(1, 1, 2, 2)", 1),
                Win32WindowSnapshot(202, "적용", "Button", 1111, True, True, "(1, 1, 2, 2)", 2),
                Win32WindowSnapshot(203, "저장", "Button", 1111, True, True, "(1, 1, 2, 2)", 3),
                Win32WindowSnapshot(204, "취소", "Button", 1111, True, True, "(1, 1, 2, 2)", 4),
                Win32WindowSnapshot(205, "CH001", "Static", 1111, True, True, "(1, 1, 2, 2)", 5),
            ),
            uia_elements=(
                UiaElementSnapshot("Group 1", "TabItem", "", "", True, "(1, 2, 3, 4)"),
                UiaElementSnapshot("CH002", "CheckBox", "", "", True, "(1, 2, 3, 4)"),
            ),
        )

    def test_c_display_group_profile_selects_by_title_class_and_size(self) -> None:
        dialog = Win32WindowSnapshot(
            200,
            "표시 그룹 설정",
            "#32770",
            1111,
            True,
            True,
            "(99, 0, 1041, 736)",
        )

        self.assertIs(select_display_group_coordinate_profile(dialog), DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736)

        wrong_size = Win32WindowSnapshot(200, "표시 그룹 설정", "#32770", 1111, True, True, "(10, 20, 638, 511)")
        self.assertIsNone(select_display_group_coordinate_profile(wrong_size))

    def test_c_display_group_profile_relative_to_absolute_conversion(self) -> None:
        point = point_from_coordinate_profile((0, 0, 942, 736), DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "ok")

        self.assertAlmostEqual(point[0], 153, delta=1)
        self.assertAlmostEqual(point[1], 709, delta=1)

    def test_display_group_workflow_has_no_dialog_resize_move_call(self) -> None:
        source = inspect.getsource(display_group_settings_module)

        self.assertNotIn("MoveWindow", source)
        self.assertNotIn("SetWindowPos", source)
        self.assertFalse(hasattr(display_group_settings_module, "normalize_display_group_dialog_to_coordinate_profile"))

    def test_c_display_group_profile_sequence_contains_group05_scroll_up_order(self) -> None:
        sequence = build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            (0, 0, 942, 736),
            DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736,
        )
        action_types = tuple(step.action_type for step in sequence)
        descriptions = tuple(step.description for step in sequence)
        tab_05_index = action_types.index("tab_05_click")
        scroll_up_index = action_types.index("scrollbar_up_click")
        group05_source_index = next(
            index
            for index, description in enumerate(descriptions)
            if "source group/page 05 W01~W08" in description
        )
        copy_after_group05 = action_types.index("copy_detail_click", group05_source_index)
        tab_01_after_group05 = action_types.index("tab_01_click", copy_after_group05)
        second_scroll_down = [index for index, action_type in enumerate(action_types) if action_type == "scrollbar_down_click"][1]
        w41_destination_index = next(
            index
            for index, description in enumerate(descriptions)
            if "destination group/page 01 W41~W48" in description
        )
        paste_after_w41 = action_types.index("paste_click", w41_destination_index)

        self.assertLess(tab_05_index, scroll_up_index)
        self.assertLess(scroll_up_index, group05_source_index)
        self.assertLess(group05_source_index, copy_after_group05)
        self.assertLess(copy_after_group05, tab_01_after_group05)
        self.assertLess(tab_01_after_group05, second_scroll_down)
        self.assertLess(second_scroll_down, w41_destination_index)
        self.assertLess(w41_destination_index, paste_after_w41)
        self.assertEqual(action_types[-1], "ok_click")

    def test_max_48_confirmed_matching_c_dialog_uses_c_profile_coordinates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                str(DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_title"]),
                "#32770",
                1111,
                True,
                True,
                "(99, 0, 1041, 736)",
            )
            dialog_rect = (99, 0, 1041, 736)
            clicks: list[tuple[str, tuple[int, int]]] = []
            drags: list[tuple[str, tuple[tuple[int, int], tuple[int, int]]]] = []

            result = apply_display_group_max_48_confirmed(
                opened.source_path,
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                dialog_ready_fn=lambda _dialog, _logger: dialog,
                raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
                click_fn=lambda point: clicks.append(("click", point)),
                drag_fn=lambda start, end: drags.append(("drag", (start, end))),
                move_fn=lambda _point: None,
                scroll_fn=lambda _amount: None,
                wait_fn=lambda _seconds: None,
                close_dialog_fn=lambda _logger: "OK",
                popup_detector_fn=lambda _pid: (),
                time_axis_full_display_fn=lambda *_args, **_kwargs: None,
                message_printer=lambda _message: None,
            )

        self.assertIn(("click", point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "tab_02")), clicks)
        self.assertIn(
            (
                "drag",
                (
                    point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "source_w01_start"),
                    point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "source_w10_end"),
                ),
            ),
            drags,
        )
        self.assertIn(("click", point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "scroll_up")), clicks)
        self.assertIn(
            (
                "drag",
                (
                    point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w41_start"),
                    point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w48_end"),
                ),
            ),
            drags,
        )
        self.assertEqual(clicks[-1], ("click", point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "ok")))
        self.assertEqual(result.executed_actions[-1].action_type, "ok_click")

    def test_max_48_confirmed_does_not_fallback_after_c_profile_was_selected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            initial_dialog = Win32WindowSnapshot(
                200,
                str(DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_title"]),
                "#32770",
                1111,
                True,
                True,
                "(99, 0, 1041, 736)",
            )
            mismatched_fresh_dialog = Win32WindowSnapshot(
                200,
                str(DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_title"]),
                "#32770",
                1111,
                True,
                True,
                "(10, 20, 638, 511)",
            )
            clicks: list[tuple[str, tuple[int, int]]] = []

            with self.assertRaisesRegex(DisplayGroupInspectionError, "fallback coordinates"):
                apply_display_group_max_48_confirmed(
                    opened.source_path,
                    config,
                    self.logger,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                    dialog_detector_fn=lambda _pid, _baseline, _logger: initial_dialog,
                    dialog_ready_fn=lambda _dialog, _logger: mismatched_fresh_dialog,
                    raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
                    click_fn=lambda point: clicks.append(("click", point)),
                    drag_fn=lambda _start, _end: None,
                    move_fn=lambda _point: None,
                    scroll_fn=lambda _amount: None,
                    wait_fn=lambda _seconds: None,
                    close_dialog_fn=lambda _logger: "ESC",
                    popup_detector_fn=lambda _pid: (),
                    time_axis_full_display_fn=lambda *_args, **_kwargs: None,
                    message_printer=lambda _message: None,
                )

        self.assertEqual(clicks, [])

    def test_max_48_confirmed_rejects_initial_non_c_profile_without_old_fallback(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            old_admin_size_dialog = Win32WindowSnapshot(
                200,
                str(DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_title"]),
                "#32770",
                1111,
                True,
                True,
                "(10, 20, 638, 511)",
            )
            clicks: list[tuple[str, tuple[int, int]]] = []

            with self.assertRaisesRegex(DisplayGroupInspectionError, "aborting instead of using old coordinates"):
                apply_display_group_max_48_confirmed(
                    opened.source_path,
                    config,
                    self.logger,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                    dialog_detector_fn=lambda _pid, _baseline, _logger: old_admin_size_dialog,
                    dialog_ready_fn=lambda _dialog, _logger: old_admin_size_dialog,
                    raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
                    click_fn=lambda point: clicks.append(("click", point)),
                    drag_fn=lambda _start, _end: None,
                    move_fn=lambda _point: None,
                    scroll_fn=lambda _amount: None,
                    wait_fn=lambda _seconds: None,
                    close_dialog_fn=lambda _logger: "ESC",
                    popup_detector_fn=lambda _pid: (),
                    time_axis_full_display_fn=lambda *_args, **_kwargs: None,
                    message_printer=lambda _message: None,
                )

        self.assertEqual(clicks, [])

    def test_preview_display_group_profile_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["sample.DAE", "--preview-display-group-profile"])

        self.assertTrue(args.preview_display_group_profile)

    def test_time_axis_semantic_uia_invokes_menu_and_full_display_without_coordinate_clicks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            opened = self._opened(Path(temp_dir))
            calls: list[tuple[str, str]] = []
            time_axis = FakeUiaWrapper("시간축", control_type="MenuItem", calls=calls)
            full_display = FakeUiaWrapper("전부 표시", control_type="MenuItem", calls=calls)
            main = FakeUiaWrapper("Universal Viewer", control_type="Window", children=(time_axis,), calls=calls)
            popup = FakeUiaWrapper("popup", control_type="Menu", class_name="#32768", children=(full_display,), calls=calls)
            desktop = FakeUiaDesktop(main, (main, popup))

            result = apply_time_axis_full_display_by_coordinates(
                opened,
                self.logger,
                snapshot_fn=lambda _hwnd: Win32WindowSnapshot(100, "Universal Viewer", "Universal_Viewer", 1111, True, True, "(20, 83, 1460, 830)"),
                desktop_factory=lambda _backend: desktop,
                move_fn=lambda _point: self.fail("semantic success should not move by coordinates"),
                click_fn=lambda _point: self.fail("semantic success should not click by coordinates"),
                wait_fn=lambda _seconds: None,
            )

        self.assertEqual(result.main_window_rect, (20, 83, 1460, 830))
        self.assertIn(("invoke", "시간축"), calls)
        self.assertIn(("invoke", "전부 표시"), calls)

    def test_display_group_settings_opens_via_group_setting_toolbar_button(self) -> None:
        with TemporaryDirectory() as temp_dir:
            opened = self._opened(Path(temp_dir))
            calls: list[tuple[str, str]] = []
            group_setting = FakeUiaWrapper(UNIVERSAL_VIEWER_GROUP_SETTING_BUTTON_TEXT, control_type="Button", calls=calls)
            main = FakeUiaWrapper("Universal Viewer", control_type="Window", children=(group_setting,), calls=calls)
            desktop = FakeUiaDesktop(main, (main,))
            dialog = Win32WindowSnapshot(200, "표시 그룹 설정", "#32770", 1111, True, True, "(10, 10, 900, 700)")
            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=(dialog,)):
                menu_path = open_display_group_settings_dialog_via_toolbar_button(
                    opened,
                    self.logger,
                    desktop_factory=lambda _backend: desktop,
                    wait_fn=lambda _seconds: None,
                )

        self.assertEqual(menu_path, DISPLAY_GROUP_MENU_PATH)
        self.assertIn(("invoke", UNIVERSAL_VIEWER_GROUP_SETTING_BUTTON_TEXT), calls)

    def test_display_group_default_does_not_use_group_setting_toolbar_primary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            opened = self._opened(Path(temp_dir))
            with patch(
                "integrations.universal_viewer.display_group_settings.open_display_group_settings_dialog_via_toolbar_button",
                side_effect=AssertionError("toolbar primary must not be used"),
            ) as toolbar:
                with patch(
                    "integrations.universal_viewer.display_group_settings.open_display_group_settings_dialog_via_uia_menu",
                    return_value=DISPLAY_GROUP_MENU_PATH,
                ) as menu:
                    result = open_display_group_settings_dialog_via_menu(opened, self.logger)

        self.assertEqual(result, DISPLAY_GROUP_MENU_PATH)
        toolbar.assert_not_called()
        menu.assert_called_once()

    def test_display_group_menu_path_clicks_display_and_group_setting_menu_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            opened = self._opened(Path(temp_dir))
            calls: list[tuple[str, str]] = []
            top_menu = FakeUiaWrapper("표시(V)", control_type="MenuItem", calls=calls)
            group_setting = FakeUiaWrapper("표시 그룹 설정(D)...", control_type="MenuItem", calls=calls)
            main = FakeUiaWrapper("Universal Viewer", control_type="Window", children=(top_menu,), calls=calls)
            popup = FakeUiaWrapper("popup", control_type="Menu", class_name="#32768", children=(group_setting,), calls=calls)
            desktop = FakeUiaDesktop(main, (main, popup))
            dialog = Win32WindowSnapshot(200, "표시 그룹 설정", "#32770", 1111, True, True, "(10, 10, 948, 737)")

            with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely", side_effect=lambda: calls.append(("esc", ""))):
                with patch(
                    "integrations.universal_viewer.display_group_settings.read_win32_window_snapshot",
                    return_value=Win32WindowSnapshot(100, "Universal Viewer", "Universal_Viewer", 1111, True, True, "(-6, 6, 1146, 604)"),
                ):
                    with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=(dialog,)):
                        result = open_display_group_settings_dialog_via_uia_menu(
                            opened,
                            self.logger,
                            desktop_factory=lambda _backend: desktop,
                            normalize_window_fn=lambda *_args, **_kwargs: calls.append(("normalize", "")),
                            wait_fn=lambda _seconds: None,
                        )

        self.assertEqual(result, DISPLAY_GROUP_MENU_PATH)
        self.assertIn(("normalize", ""), calls)
        self.assertIn(("esc", ""), calls)
        self.assertIn(("click_input", "표시(V)"), calls)
        self.assertIn(("click_input", "표시 그룹 설정(D)..."), calls)
        self.assertNotIn(("invoke", "표시(V)"), calls)
        self.assertNotIn(("invoke", "표시 그룹 설정(D)..."), calls)

    def _apply_test_call(
        self,
        *,
        heating_point_count: int,
        profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
        click_log: list[tuple[str, object]] | None = None,
        move_log: list[tuple[str, object]] | None = None,
        scroll_log: list[tuple[str, object]] | None = None,
        wait_log: list[float] | None = None,
        close_log: list[str] | None = None,
        ready_log: list[int] | None = None,
        pause_log: list[str] | None = None,
        pause_after_paste: bool = False,
        pause_after_scroll: bool = False,
        continue_without_pause: bool = False,
        pause_before_button_clicks: bool = False,
        sequence_builder_fn=None,
    ):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config = AppConfig(project_root=root)
        config.ensure_directories()
        opened = self._opened(root)
        clicks = click_log if click_log is not None else []
        moves = move_log if move_log is not None else []
        scrolls = scroll_log if scroll_log is not None else []
        waits = wait_log if wait_log is not None else []
        closes = close_log if close_log is not None else []
        ready = ready_log if ready_log is not None else []
        pauses = pause_log if pause_log is not None else []

        return apply_display_group_geometry_actions_test(
            opened.source_path,
            config,
            self.logger,
            heating_point_count=heating_point_count,
            open_raw_file_fn=lambda *_args, **_kwargs: opened,
            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
            dialog_detector_fn=lambda _pid, _baseline, _logger: Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            ),
            raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
            profile=profile,
            click_fn=lambda point: clicks.append(("click", point)),
            drag_fn=lambda start, end: clicks.append(("drag", (start, end))),
            move_fn=lambda point: moves.append(("move", point)),
            scroll_fn=lambda amount: scrolls.append(("scroll", amount)),
            wait_fn=lambda seconds: waits.append(seconds),
            dialog_ready_fn=lambda dialog, _logger: ready.append(dialog.hwnd),
            close_dialog_fn=lambda _logger: closes.append("ESC") or "ESC",
            sequence_builder_fn=sequence_builder_fn,
            pause_after_paste=pause_after_paste,
            pause_after_scroll=pause_after_scroll,
            continue_without_pause=continue_without_pause,
            pause_before_button_clicks=pause_before_button_clicks,
            pause_input_fn=lambda _prompt: pauses.append("input") or "",
            message_printer=lambda message: pauses.append(message)
            if (
                (pause_after_paste and message.startswith("붙임 후"))
                or (pause_after_scroll and message.startswith("스크롤 후"))
                or (pause_before_button_clicks and message.startswith("마우스가 "))
            )
            else None,
        )

    def _confirmed_apply_call(
        self,
        *,
        heating_point_count: int,
        click_log: list[tuple[str, object]] | None = None,
        move_log: list[tuple[str, object]] | None = None,
        scroll_log: list[tuple[str, object]] | None = None,
        wait_log: list[float] | None = None,
        close_log: list[str] | None = None,
        ready_log: list[int] | None = None,
        popup_detector_fn=None,
        time_axis_log: list[str] | None = None,
        time_axis_fn=None,
    ):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config = AppConfig(project_root=root)
        config.ensure_directories()
        opened = self._opened(root)
        clicks = click_log if click_log is not None else []
        moves = move_log if move_log is not None else []
        scrolls = scroll_log if scroll_log is not None else []
        waits = wait_log if wait_log is not None else []
        closes = close_log if close_log is not None else []
        ready = ready_log if ready_log is not None else []
        time_axis_events = time_axis_log if time_axis_log is not None else []
        apply_time_axis = time_axis_fn or (
            lambda *_args, **_kwargs: time_axis_events.append("time_axis")
            or TimeAxisFullDisplayResult((-6, 6, 1146, 604), (163, 51), (183, 148))
        )
        open_menu = (
            lambda _opened, _logger: time_axis_events.append("open_display_group") or DISPLAY_GROUP_MENU_PATH
        )

        return apply_display_group_geometry_actions_confirmed(
            opened.source_path,
            config,
            self.logger,
            heating_point_count=heating_point_count,
            open_raw_file_fn=lambda *_args, **_kwargs: opened,
            menu_open_fn=open_menu,
            dialog_detector_fn=lambda _pid, _baseline, _logger: Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(8, 50, 946, 777)",
            ),
            raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
            click_fn=lambda point: clicks.append(("click", point)),
            drag_fn=lambda start, end: clicks.append(("drag", (start, end))),
            move_fn=lambda point: moves.append(("move", point)),
            scroll_fn=lambda amount: scrolls.append(("scroll", amount)),
            wait_fn=lambda seconds: waits.append(seconds),
            dialog_ready_fn=lambda dialog, _logger: ready.append(dialog.hwnd),
            close_dialog_fn=lambda _logger: closes.append("ESC") or "ESC",
            popup_detector_fn=popup_detector_fn or (lambda _pid: ()),
            time_axis_full_display_fn=apply_time_axis,
            message_printer=lambda _message: None,
        )

    def _max_48_confirmed_call(
        self,
        *,
        click_log: list[tuple[str, object]] | None = None,
        move_log: list[tuple[str, object]] | None = None,
        scroll_log: list[tuple[str, object]] | None = None,
        wait_log: list[float] | None = None,
        close_log: list[str] | None = None,
        ready_log: list[int] | None = None,
        popup_detector_fn=None,
        time_axis_log: list[str] | None = None,
        time_axis_fn=None,
    ):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config = AppConfig(project_root=root)
        config.ensure_directories()
        opened = self._opened(root)
        clicks = click_log if click_log is not None else []
        moves = move_log if move_log is not None else []
        scrolls = scroll_log if scroll_log is not None else []
        waits = wait_log if wait_log is not None else []
        closes = close_log if close_log is not None else []
        ready = ready_log if ready_log is not None else []
        time_axis_events = time_axis_log if time_axis_log is not None else []
        apply_time_axis = time_axis_fn or (
            lambda *_args, **_kwargs: time_axis_events.append("time_axis")
            or TimeAxisFullDisplayResult((-6, 6, 1146, 604), (163, 51), (183, 148))
        )
        open_menu = (
            lambda _opened, _logger: time_axis_events.append("open_display_group") or DISPLAY_GROUP_MENU_PATH
        )

        return apply_display_group_max_48_confirmed(
            opened.source_path,
            config,
            self.logger,
            open_raw_file_fn=lambda *_args, **_kwargs: opened,
            menu_open_fn=open_menu,
            dialog_detector_fn=lambda _pid, _baseline, _logger: Win32WindowSnapshot(
                200,
                str(DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_title"]),
                "#32770",
                1111,
                True,
                True,
                "(99, 0, 1041, 736)",
            ),
            raw_hint_collector=lambda _handle: (opened.work_copy_path.name,),
            click_fn=lambda point: clicks.append(("click", point)),
            drag_fn=lambda start, end: clicks.append(("drag", (start, end))),
            move_fn=lambda point: moves.append(("move", point)),
            scroll_fn=lambda amount: scrolls.append(("scroll", amount)),
            wait_fn=lambda seconds: waits.append(seconds),
            dialog_ready_fn=lambda dialog, _logger: ready.append(dialog.hwnd) or dialog,
            close_dialog_fn=lambda _logger: closes.append("ESC") or "ESC",
            popup_detector_fn=popup_detector_fn or (lambda _pid: ()),
            time_axis_full_display_fn=apply_time_axis,
            message_printer=lambda _message: None,
        )

    def test_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--inspect-display-group-settings", ".\\input\\sample.DAE"])

        self.assertTrue(args.inspect_display_group_settings)
        self.assertEqual(args.raw_files, [Path(".\\input\\sample.DAE")])

    def test_pause_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--inspect-display-group-settings-pause", ".\\input\\sample.DAE"])

        self.assertTrue(args.inspect_display_group_settings_pause)
        self.assertEqual(args.raw_files, [Path(".\\input\\sample.DAE")])

    def test_geometry_cli_options_are_registered(self) -> None:
        args = build_parser().parse_args(["--inspect-display-group-geometry", ".\\input\\sample.DAE"])
        pause_args = build_parser().parse_args(["--inspect-display-group-geometry-pause", ".\\input\\sample.DAE"])

        self.assertTrue(args.inspect_display_group_geometry)
        self.assertTrue(pause_args.inspect_display_group_geometry_pause)

    def test_scrollbar_points_pause_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["--inspect-display-group-scrollbar-points-pause", ".\\input\\sample.DAE"])

        self.assertTrue(args.inspect_display_group_scrollbar_points_pause)
        self.assertEqual(args.raw_files, [Path(".\\input\\sample.DAE")])

    def test_preview_geometry_actions_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(
            ["--preview-display-group-geometry-actions", ".\\input\\sample.DAE", "--heating-point-count", "11"]
        )

        self.assertTrue(args.preview_display_group_geometry_actions)
        self.assertEqual(args.heating_point_count, 11)

    def test_apply_geometry_actions_test_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(
            [
                "--apply-display-group-geometry-actions-test",
                ".\\input\\sample.DAE",
                "--heating-point-count",
                "16",
                "--pause-after-display-group-paste",
                "--pause-after-display-group-scroll",
                "--pause-before-display-group-button-clicks",
            ]
        )

        self.assertTrue(args.apply_display_group_geometry_actions_test)
        self.assertEqual(args.heating_point_count, 16)
        self.assertTrue(args.pause_after_display_group_paste)
        self.assertTrue(args.pause_after_display_group_scroll)
        self.assertTrue(args.pause_before_display_group_button_clicks)

    def test_continue_without_display_group_pause_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(
            [
                "--apply-display-group-geometry-actions-test",
                ".\\input\\sample.DAE",
                "--heating-point-count",
                "38",
                "--continue-without-display-group-pause",
            ]
        )

        self.assertTrue(args.apply_display_group_geometry_actions_test)
        self.assertEqual(args.heating_point_count, 38)
        self.assertTrue(args.continue_without_display_group_pause)

    def test_confirmed_apply_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(
            [
                "--apply-display-group-geometry-actions-confirmed",
                ".\\input\\sample.DAE",
                "--heating-point-count",
                "38",
            ]
        )

        self.assertTrue(args.apply_display_group_geometry_actions_confirmed)
        self.assertEqual(args.heating_point_count, 38)

    def test_max_48_confirmed_cli_option_is_registered_without_heating_point_count(self) -> None:
        args = build_parser().parse_args(
            [
                "--apply-display-group-max-48-confirmed",
                ".\\input\\sample.DAE",
            ]
        )

        self.assertTrue(args.apply_display_group_max_48_confirmed)
        self.assertIsNone(args.heating_point_count)

    def test_preview_max_48_cli_option_is_registered_without_heating_point_count(self) -> None:
        args = build_parser().parse_args(
            [
                "--preview-display-group-max-48-actions",
                ".\\input\\sample.GEV",
            ]
        )

        self.assertTrue(args.preview_display_group_max_48_actions)
        self.assertIsNone(args.heating_point_count)

    def test_geometry_calculation_from_sample_dialog_rectangle(self) -> None:
        report = calculate_display_group_geometry((430, 50, 1368, 777))

        self.assertEqual(report.width, 938)
        self.assertEqual(report.height, 727)
        areas = {area.name: area for area in report.areas}
        lines = {line.name: line for line in report.lines}
        self.assertEqual(areas["estimated_top_tab_row_area"].absolute_rect, (439, 72, 1359, 123))
        self.assertEqual(areas["estimated_grid_area"].absolute_rect, (449, 195, 1349, 675))
        self.assertEqual(lines["estimated_first_row_y"].absolute_value, 195)
        self.assertEqual(lines["estimated_row_height"].absolute_value, 16)
        self.assertEqual(lines["estimated_checkbox_column_x"].absolute_value, 448)
        self.assertEqual(lines["estimated_channel_column_x"].absolute_value, 571)

    def test_bottom_button_geometry_uses_calibrated_centers(self) -> None:
        report = calculate_display_group_geometry((430, 50, 1368, 777))
        areas = {area.name: area for area in report.areas}

        def center(area_name: str) -> tuple[int, int]:
            rel_left, rel_top, rel_right, rel_bottom = areas[area_name].relative_rect
            return (
                round(430 + 938 * ((rel_left + rel_right) / 2)),
                round(50 + 727 * ((rel_top + rel_bottom) / 2)),
            )

        self.assertEqual(center("estimated_OK_button_area"), (569, 749))
        self.assertEqual(center("estimated_Cancel_button_area"), (755, 749))
        self.assertEqual(center("estimated_scale_calculation_button_area"), (929, 749))
        self.assertEqual(center("estimated_copy_detail_button_area"), (1099, 749))
        self.assertEqual(center("estimated_paste_button_area"), (1267, 749))
        self.assertNotEqual(center("estimated_copy_detail_button_area"), (1232, 733))
        self.assertNotEqual(center("estimated_paste_button_area"), (1316, 733))

    def test_heating_point_count_mapping_boundaries(self) -> None:
        expected = {
            1: (1, 1),
            10: (1, 10),
            11: (2, 1),
            20: (2, 10),
            21: (3, 1),
            40: (4, 10),
            41: (5, 1),
            48: (5, 8),
        }

        for index, (group_no, row_no) in expected.items():
            with self.subTest(index=index):
                position = heating_point_to_group_position(index)
                self.assertEqual((position.group_no, position.row_no), (group_no, row_no))

    def test_preview_for_ten_or_less_has_no_copy_paste_actions(self) -> None:
        geometry = calculate_display_group_geometry((430, 50, 1368, 777))
        preview = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=10,
        )
        action_types = {action.action_type for action in preview.actions}

        self.assertNotIn("copy_detail_candidate", action_types)
        self.assertNotIn("paste_candidate", action_types)

    def test_preview_for_more_than_ten_includes_copy_paste_actions(self) -> None:
        geometry = calculate_display_group_geometry((430, 50, 1368, 777))
        preview = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=11,
        )
        action_types = {action.action_type for action in preview.actions}

        self.assertIn("copy_detail_candidate", action_types)
        self.assertIn("paste_candidate", action_types)
        self.assertIn("drag_select_insertion_area_candidate", action_types)

    def test_preview_coordinates_are_derived_from_dialog_rectangle(self) -> None:
        geometry_a = calculate_display_group_geometry((430, 50, 1368, 777))
        geometry_b = calculate_display_group_geometry((530, 150, 1468, 877))
        preview_a = calculate_display_group_geometry_action_preview(geometry_a, DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE, 1)
        preview_b = calculate_display_group_geometry_action_preview(geometry_b, DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE, 1)
        row_a = next(action for action in preview_a.actions if action.action_type == "row_candidate")
        row_b = next(action for action in preview_b.actions if action.action_type == "row_candidate")

        self.assertEqual(row_b.point[0] - row_a.point[0], 100)  # type: ignore[index]
        self.assertEqual(row_b.point[1] - row_a.point[1], 100)  # type: ignore[index]

    def test_preview_uses_calibrated_profile_and_scrolled_destination_model(self) -> None:
        geometry = calculate_display_group_geometry((430, 50, 1368, 777))
        preview = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=40,
        )
        drag_actions = {
            action.row_no: action
            for action in preview.actions
            if action.action_type == "drag_select_insertion_area_candidate"
        }

        self.assertEqual(preview.tab_coordinates[0], (1, (447, 91)))
        self.assertEqual(preview.tab_coordinates[4], (5, (545, 91)))
        self.assertEqual(drag_actions[11].drag_start[1], 355)  # type: ignore[index]
        self.assertEqual(drag_actions[11].drag_end[1], 499)  # type: ignore[index]
        self.assertEqual(drag_actions[21].drag_start[1], 515)  # type: ignore[index]
        self.assertEqual(drag_actions[21].drag_end[1], 659)  # type: ignore[index]
        self.assertEqual(drag_actions[31].drag_start, (473, 374))
        self.assertEqual(drag_actions[31].drag_end, (1330, 518))
        scroll_actions = [
            action
            for action in preview.actions
            if action.action_type == "scrollbar_down_click_candidate"
        ]
        self.assertEqual(len(scroll_actions), 1)
        self.assertEqual(scroll_actions[0].point, (1345, 684))
        self.assertIsNone(scroll_actions[0].drag_start)
        self.assertIsNone(scroll_actions[0].drag_end)
        self.assertNotEqual(scroll_actions[0].point, (1321, 450))
        self.assertNotEqual(scroll_actions[0].point, (602, 217))
        self.assertIn("scrollbar_down_click_rel=(0.975, 0.872)", scroll_actions[0].description)
        self.assertIn("W20~W50", scroll_actions[0].description)
        self.assertIn("destination_start_rel=(0.046, 0.446)", drag_actions[31].description)
        ok_action = next(action for action in preview.actions if action.action_type == "ok_button_candidate")
        self.assertEqual(ok_action.point, (569, 749))
        self.assertIn("ok_button_rel=(0.148, 0.961)", ok_action.description)
        self.assertLessEqual(drag_actions[31].drag_end[1], 777)  # type: ignore[index]
        self.assertEqual(preview.warnings, ())

        for action in preview.actions:
            for point in (action.point, action.drag_start, action.drag_end):
                if point is None:
                    continue
                self.assertGreaterEqual(point[0], 430)
                self.assertLessEqual(point[0], 1368)
                self.assertGreaterEqual(point[1], 50)
                self.assertLessEqual(point[1], 777)

    def test_preview_n48_includes_group05_and_w41_to_w48_scrolled_destination(self) -> None:
        geometry = calculate_display_group_geometry((430, 50, 1368, 777))
        preview = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=48,
        )

        self.assertEqual(dict(preview.tab_coordinates)[5], (545, 91))
        group05_source = next(
            action
            for action in preview.actions
            if action.action_type == "source_drag_select_candidate" and action.group_no == 5
        )
        destination_w41 = next(
            action
            for action in preview.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 41
        )
        scroll_actions = [
            action
            for action in preview.actions
            if action.action_type == "scrollbar_down_click_candidate"
        ]

        self.assertEqual(group05_source.drag_start, (482, 195))
        self.assertEqual(group05_source.drag_end, (1330, 307))
        self.assertEqual(destination_w41.drag_start, (474, 533))
        self.assertEqual(destination_w41.drag_end, (1330, 645))
        self.assertIn("destination_start_rel=(0.047, 0.664)", destination_w41.description)
        self.assertEqual(len(scroll_actions), 1)
        self.assertTrue(all(action.point == (1345, 684) for action in scroll_actions))
        ok_action = next(action for action in preview.actions if action.action_type == "ok_button_candidate")
        self.assertEqual(ok_action.point, (569, 749))
        self.assertIn("ok_button_rel=(0.148, 0.961)", ok_action.description)

    def test_preview_uses_latest_measured_scroll_and_ok_points_for_reference_dialog(self) -> None:
        geometry = calculate_display_group_geometry((8, 50, 946, 777))
        preview_38 = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=38,
        )
        preview_48 = calculate_display_group_geometry_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            heating_point_count=48,
        )

        scroll_38 = [action for action in preview_38.actions if action.action_type == "scrollbar_down_click_candidate"]
        scroll_48 = [action for action in preview_48.actions if action.action_type == "scrollbar_down_click_candidate"]
        destination_w31_38 = next(
            action
            for action in preview_38.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 31
        )
        destination_w31_48 = next(
            action
            for action in preview_48.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 31
        )
        destination_w41_48 = next(
            action
            for action in preview_48.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 41
        )
        ok_48 = next(action for action in preview_48.actions if action.action_type == "ok_button_candidate")

        self.assertEqual(len(scroll_38), 1)
        self.assertEqual(scroll_38[0].point, (923, 684))
        self.assertIn("scrollbar_down_click_rel=(0.975, 0.872)", scroll_38[0].description)
        self.assertEqual(len(scroll_48), 1)
        self.assertEqual(scroll_48[0].point, (923, 684))
        self.assertEqual(destination_w31_38.drag_start, (51, 374))
        self.assertEqual(destination_w31_38.drag_end, (908, 486))
        self.assertIn("destination_start_rel=(0.046, 0.446)", destination_w31_38.description)
        self.assertEqual(destination_w31_48.drag_start, (51, 374))
        self.assertEqual(destination_w31_48.drag_end, (908, 518))
        self.assertEqual(destination_w41_48.drag_start, (52, 533))
        self.assertEqual(destination_w41_48.drag_end, (908, 645))
        self.assertIn("destination_start_rel=(0.047, 0.664)", destination_w41_48.description)
        self.assertEqual(ok_48.point, (147, 749))
        self.assertIn("ok_button_rel=(0.148, 0.961)", ok_48.description)

    def test_preview_max_48_includes_down_up_down_scroll_plan(self) -> None:
        geometry = calculate_display_group_geometry((8, 50, 946, 777))
        preview = calculate_display_group_max_48_action_preview(
            geometry,
            profile=DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
        )
        descriptions = "\n".join(action.description for action in preview.actions)
        scroll_down_actions = [
            action for action in preview.actions if action.action_type == "scrollbar_down_click_candidate"
        ]
        scroll_up_actions = [
            action for action in preview.actions if action.action_type == "scrollbar_up_click_candidate"
        ]
        destination_w31 = next(
            action
            for action in preview.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 31
        )
        destination_w41 = next(
            action
            for action in preview.actions
            if action.action_type == "drag_select_insertion_area_candidate" and action.row_no == 41
        )
        ok_action = next(action for action in preview.actions if action.action_type == "ok_button_candidate")

        self.assertIn("source group/page 02", descriptions)
        self.assertIn("source group/page 03", descriptions)
        self.assertIn("source group/page 04", descriptions)
        self.assertIn("source group/page 05", descriptions)
        self.assertEqual(len(scroll_down_actions), 2)
        self.assertEqual([action.point for action in scroll_down_actions], [(923, 684), (923, 684)])
        self.assertTrue(all("scrollbar_down_click_rel=(0.975, 0.872)" in action.description for action in scroll_down_actions))
        self.assertEqual(len(scroll_up_actions), 1)
        self.assertEqual(scroll_up_actions[0].point, (922, 183))
        self.assertIn("scrollbar_up_click_rel=(0.974, 0.183)", scroll_up_actions[0].description)
        self.assertNotIn("scrollbar_up_click_rel=(0.935, 0.173)", scroll_up_actions[0].description)
        self.assertNotIn("scrollbar_up_click_rel=(0.525, 0.133)", scroll_up_actions[0].description)
        self.assertEqual(destination_w31.drag_start, (51, 374))
        self.assertEqual(destination_w31.drag_end, (908, 518))
        self.assertIn("destination_start_rel=(0.046, 0.446)", destination_w31.description)
        self.assertEqual(destination_w41.drag_start, (52, 533))
        self.assertEqual(destination_w41.drag_end, (908, 645))
        self.assertIn("destination_start_rel=(0.047, 0.664)", destination_w41.description)
        self.assertEqual(ok_action.point, (147, 749))
        self.assertIn("ok_button_rel=(0.148, 0.961)", ok_action.description)

    def test_time_axis_coordinates_are_calculated_from_main_window_rect(self) -> None:
        result = calculate_time_axis_full_display_points((-6, 6, 1146, 604))

        self.assertEqual(UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL, (0.147, 0.075))
        self.assertEqual(UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL, (0.164, 0.237))
        self.assertLessEqual(abs(result.time_axis_menu_point[0] - 163), 1)
        self.assertLessEqual(abs(result.time_axis_menu_point[1] - 51), 1)
        self.assertLessEqual(abs(result.time_axis_full_display_point[0] - 183), 1)
        self.assertLessEqual(abs(result.time_axis_full_display_point[1] - 148), 1)

    def test_scrollbar_up_click_uses_latest_right_scrollbar_calibration(self) -> None:
        point = scrollbar_up_click_coordinate((271, 93, 1209, 820))

        self.assertLessEqual(abs(point[0] - 1185), 1)
        self.assertLessEqual(abs(point[1] - 226), 1)

    def test_time_axis_coordinates_are_not_based_on_display_group_dialog_rect(self) -> None:
        main_result = calculate_time_axis_full_display_points((-6, 6, 1146, 604))
        dialog_result = calculate_time_axis_full_display_points((38, 118, 976, 845))

        self.assertNotEqual(main_result.time_axis_menu_point, dialog_result.time_axis_menu_point)
        self.assertNotEqual(main_result.time_axis_full_display_point, dialog_result.time_axis_full_display_point)

    def test_apply_time_axis_full_display_moves_and_clicks_expected_points(self) -> None:
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        opened = self._opened(root)
        events: list[tuple[str, object]] = []
        waits: list[float] = []

        result = apply_time_axis_full_display_by_coordinates(
            opened,
            self.logger,
            click_fn=lambda point: events.append(("click", point)),
            move_fn=lambda point: events.append(("move", point)),
            wait_fn=lambda seconds: waits.append(seconds),
            snapshot_fn=lambda _hwnd: Win32WindowSnapshot(
                100,
                "Universal Viewer",
                "Universal_Viewer R3.12.01",
                1111,
                True,
                True,
                "(-6, 6, 1146, 604)",
            ),
        )

        self.assertEqual(result.main_window_rect, (-6, 6, 1146, 604))
        self.assertEqual(result.time_axis_menu_point, (163, 51))
        self.assertEqual(result.time_axis_full_display_point, (183, 148))
        self.assertEqual(events[0], ("move", result.time_axis_menu_point))
        self.assertEqual(events[1], ("click", result.time_axis_menu_point))
        self.assertEqual(events[2], ("move", result.time_axis_full_display_point))
        self.assertEqual(events[3], ("click", result.time_axis_full_display_point))
        self.assertEqual(waits, [0.3, 0.5])

    def test_confirmed_n_based_mode_runs_time_axis_before_opening_display_group(self) -> None:
        events: list[str] = []

        self._confirmed_apply_call(heating_point_count=16, time_axis_log=events)

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[:2], ["time_axis", "open_display_group"])

    def test_max_48_confirmed_runs_time_axis_before_opening_display_group(self) -> None:
        events: list[str] = []

        self._max_48_confirmed_call(time_axis_log=events)

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[:2], ["time_axis", "open_display_group"])

    def test_time_axis_failure_aborts_before_display_group_and_ok(self) -> None:
        events: list[str] = []
        clicks: list[tuple[str, object]] = []

        def fail_time_axis(*_args, **_kwargs):
            events.append("time_axis")
            raise DisplayGroupInspectionError("time-axis failure")

        with self.assertRaisesRegex(DisplayGroupInspectionError, "time-axis failure"):
            self._max_48_confirmed_call(
                click_log=clicks,
                time_axis_log=events,
                time_axis_fn=fail_time_axis,
            )

        self.assertEqual(events, ["time_axis"])
        self.assertNotIn(("click", (147, 749)), clicks)

    def test_apply_geometry_actions_test_n16_executes_expected_sequence(self) -> None:
        clicks: list[tuple[str, object]] = []
        moves: list[tuple[str, object]] = []
        closes: list[str] = []
        ready: list[int] = []

        result = self._apply_test_call(
            heating_point_count=16,
            click_log=clicks,
            move_log=moves,
            close_log=closes,
            ready_log=ready,
        )

        self.assertEqual(
            clicks,
            [
                ("click", (470, 91)),
                ("drag", ((482, 195), (1330, 275))),
                ("click", (1099, 749)),
                ("click", (447, 91)),
                ("drag", ((482, 355), (1330, 435))),
                ("click", (1267, 749)),
            ],
        )
        self.assertEqual(
            [action.action_type for action in result.executed_actions],
            [
                "tab_02_click",
                "source_drag_select",
                "copy_detail_click",
                "tab_01_click",
                "destination_drag_select",
                "paste_click",
                "close_esc",
            ],
        )
        self.assertEqual(moves, [("move", (1099, 749)), ("move", (1267, 749))])
        self.assertEqual(closes, ["ESC"])
        self.assertEqual(len(ready), 6)
        self.assertNotIn("ok_button_candidate", [action.action_type for action in result.executed_actions])
        self.assertIn("OK was not clicked", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_apply_geometry_actions_test_n20_selects_w11_to_w20(self) -> None:
        clicks: list[tuple[str, object]] = []

        self._apply_test_call(heating_point_count=20, click_log=clicks)

        self.assertIn(("drag", ((482, 195), (1330, 339))), clicks)
        self.assertIn(("drag", ((482, 355), (1330, 499))), clicks)

    def test_apply_geometry_actions_test_n25_copies_group02_and_group03_partial(self) -> None:
        clicks: list[tuple[str, object]] = []

        result = self._apply_test_call(heating_point_count=25, click_log=clicks)

        self.assertEqual(
            clicks,
            [
                ("click", (470, 91)),
                ("drag", ((482, 195), (1330, 339))),
                ("click", (1099, 749)),
                ("click", (447, 91)),
                ("drag", ((482, 355), (1330, 499))),
                ("click", (1267, 749)),
                ("click", (496, 91)),
                ("drag", ((482, 195), (1330, 259))),
                ("click", (1099, 749)),
                ("click", (447, 91)),
                ("drag", ((482, 515), (1330, 579))),
                ("click", (1267, 749)),
            ],
        )
        self.assertEqual([action.action_type for action in result.executed_actions].count("copy_detail_click"), 2)
        self.assertEqual([action.action_type for action in result.executed_actions].count("paste_click"), 2)

    def test_apply_geometry_actions_test_n30_copies_group02_and_group03_full_ranges(self) -> None:
        clicks: list[tuple[str, object]] = []

        self._apply_test_call(heating_point_count=30, click_log=clicks)

        self.assertIn(("click", (496, 91)), clicks)
        self.assertIn(("drag", ((482, 195), (1330, 339))), clicks)
        self.assertIn(("drag", ((482, 515), (1330, 659))), clicks)

    def test_apply_geometry_actions_test_n38_uses_scrolled_destination_for_group04(self) -> None:
        clicks: list[tuple[str, object]] = []
        scrolls: list[tuple[str, object]] = []

        result = self._apply_test_call(
            heating_point_count=38,
            click_log=clicks,
            scroll_log=scrolls,
            pause_after_scroll=True,
        )
        action_types = [action.action_type for action in result.executed_actions]

        self.assertIn(("click", (520, 91)), clicks)
        self.assertIn(("drag", ((482, 195), (1330, 307))), clicks)
        self.assertIn(("click", (1345, 684)), clicks)
        self.assertNotIn(("click", (602, 217)), clicks)
        self.assertNotIn(("drag", ((945, 456), (945, 654))), clicks)
        self.assertNotIn(("click", (945, 654)), clicks)
        self.assertIn(("drag", ((473, 374), (1330, 486))), clicks)
        self.assertEqual(scrolls, [])
        self.assertLess(
            action_types.index("scrollbar_down_click"),
            action_types.index("destination_drag_select", action_types.index("scrollbar_down_click")),
        )
        self.assertEqual(action_types.count("copy_detail_click"), 3)
        self.assertEqual(action_types.count("paste_click"), 3)
        self.assertEqual(action_types.count("scrollbar_down_click"), 1)

    def test_apply_geometry_actions_test_n38_continue_without_pause_is_allowed(self) -> None:
        clicks: list[tuple[str, object]] = []
        waits: list[float] = []
        pauses: list[str] = []

        result = self._apply_test_call(
            heating_point_count=38,
            click_log=clicks,
            wait_log=waits,
            pause_log=pauses,
            continue_without_pause=True,
        )

        self.assertIn(("click", (520, 91)), clicks)
        self.assertIn(("drag", ((473, 374), (1330, 486))), clicks)
        self.assertIn(("click", (1345, 684)), clicks)
        self.assertNotIn(("click", (602, 217)), clicks)
        self.assertNotIn(("drag", ((945, 456), (945, 654))), clicks)
        self.assertNotIn(("click", (945, 654)), clicks)
        self.assertEqual(waits.count(0.8), 3)
        self.assertNotIn("input", pauses)
        self.assertIn("continuous no-pause mode was used", result.safety_summary)
        self.assertIn("OK was not clicked", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_apply_geometry_actions_test_n48_includes_group05_and_single_scroll_block(self) -> None:
        clicks: list[tuple[str, object]] = []
        scrolls: list[tuple[str, object]] = []

        result = self._apply_test_call(
            heating_point_count=48,
            click_log=clicks,
            scroll_log=scrolls,
            pause_after_scroll=True,
        )
        action_types = [action.action_type for action in result.executed_actions]

        self.assertIn(("click", (545, 91)), clicks)
        self.assertIn(("drag", ((482, 195), (1330, 307))), clicks)
        self.assertIn(("click", (1345, 684)), clicks)
        self.assertNotIn(("click", (602, 217)), clicks)
        self.assertNotIn(("drag", ((945, 456), (945, 654))), clicks)
        self.assertNotIn(("click", (945, 654)), clicks)
        self.assertIn(("drag", ((474, 533), (1330, 645))), clicks)
        self.assertEqual(scrolls, [])
        self.assertEqual(action_types.count("copy_detail_click"), 4)
        self.assertEqual(action_types.count("paste_click"), 4)
        self.assertEqual(action_types.count("scrollbar_down_click"), 1)
        self.assertEqual(action_types[-1], "close_esc")

        for index, action_type in enumerate(action_types):
            if action_type == "copy_detail_click":
                self.assertEqual(action_types[index - 1], "source_drag_select")
            if action_type == "paste_click":
                self.assertEqual(action_types[index - 1], "destination_drag_select")

    def test_apply_geometry_actions_test_n48_continue_without_pause_keeps_full_sequence(self) -> None:
        clicks: list[tuple[str, object]] = []
        scrolls: list[tuple[str, object]] = []
        waits: list[float] = []
        pauses: list[str] = []

        with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
            result = self._apply_test_call(
                heating_point_count=48,
                click_log=clicks,
                scroll_log=scrolls,
                wait_log=waits,
                pause_log=pauses,
                continue_without_pause=True,
            )
        print_to_pdf.assert_not_called()
        action_types = [action.action_type for action in result.executed_actions]
        descriptions = [action.description for action in result.executed_actions]

        self.assertIn("source group/page 02 to destination W11~W20", "\n".join(descriptions))
        self.assertIn("source group/page 03 to destination W21~W30", "\n".join(descriptions))
        self.assertIn("source group/page 04 to destination W31~W40", "\n".join(descriptions))
        self.assertIn("source group/page 05 to destination W41~W48", "\n".join(descriptions))
        self.assertIn(("click", (545, 91)), clicks)
        self.assertIn(("drag", ((474, 533), (1330, 645))), clicks)
        self.assertIn(("click", (1345, 684)), clicks)
        self.assertNotIn(("click", (602, 217)), clicks)
        self.assertNotIn(("drag", ((945, 456), (945, 654))), clicks)
        self.assertNotIn(("click", (945, 654)), clicks)
        self.assertEqual(scrolls, [])
        self.assertEqual(waits.count(0.8), 4)
        self.assertNotIn("input", pauses)
        self.assertEqual(action_types.count("copy_detail_click"), 4)
        self.assertEqual(action_types.count("paste_click"), 4)
        self.assertEqual(action_types.count("scrollbar_down_click"), 1)
        self.assertNotIn("ok_click", action_types)
        for index, action_type in enumerate(action_types):
            if action_type == "scrollbar_down_click":
                self.assertEqual(action_types[index + 1], "destination_drag_select")
        self.assertIn("continuous no-pause mode was used", result.safety_summary)
        self.assertIn("OK was not clicked", result.safety_summary)
        self.assertIn("Apply was not clicked", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_confirmed_apply_n38_uses_scrollbar_down_click_and_clicks_ok(self) -> None:
        clicks: list[tuple[str, object]] = []
        closes: list[str] = []
        waits: list[float] = []

        with patch("builtins.input", side_effect=AssertionError("confirmed apply must not prompt")):
            with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                result = self._confirmed_apply_call(
                    heating_point_count=38,
                    click_log=clicks,
                    wait_log=waits,
                    close_log=closes,
                )

        print_to_pdf.assert_not_called()
        action_types = [action.action_type for action in result.executed_actions]
        descriptions = "\n".join(action.description for action in result.executed_actions)

        self.assertIn("source group/page 02 to destination W11~W20", descriptions)
        self.assertIn("source group/page 03 to destination W21~W30", descriptions)
        self.assertIn("source group/page 04 to destination W31~W38", descriptions)
        self.assertIn(("click", (923, 684)), clicks)
        self.assertNotIn(("click", (602, 217)), clicks)
        self.assertNotIn(("drag", ((945, 456), (945, 654))), clicks)
        self.assertNotIn(("click", (523, 654)), clicks)
        self.assertIn(("drag", ((51, 374), (908, 486))), clicks)
        self.assertEqual(action_types[-1], "ok_click")
        self.assertEqual(clicks[-1], ("click", (147, 749)))
        self.assertEqual(closes, [])
        self.assertEqual(result.close_method, "OK")
        self.assertIn("OK was clicked intentionally in confirmed apply mode", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_confirmed_apply_n48_uses_single_scrollbar_down_click_and_clicks_ok(self) -> None:
        clicks: list[tuple[str, object]] = []
        scrolls: list[tuple[str, object]] = []

        with patch("builtins.input", side_effect=AssertionError("confirmed apply must not prompt")):
            with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                result = self._confirmed_apply_call(
                    heating_point_count=48,
                    click_log=clicks,
                    scroll_log=scrolls,
                )

        print_to_pdf.assert_not_called()
        action_types = [action.action_type for action in result.executed_actions]
        descriptions = "\n".join(action.description for action in result.executed_actions)

        self.assertIn("source group/page 02 to destination W11~W20", descriptions)
        self.assertIn("source group/page 03 to destination W21~W30", descriptions)
        self.assertIn("source group/page 04 to destination W31~W40", descriptions)
        self.assertIn("source group/page 05 to destination W41~W48", descriptions)
        self.assertEqual(clicks.count(("click", (923, 684))), 1)
        self.assertIn(("drag", ((51, 374), (908, 518))), clicks)
        self.assertIn(("drag", ((52, 533), (908, 645))), clicks)
        self.assertEqual(scrolls, [])
        self.assertEqual(action_types.count("scrollbar_down_click"), 1)
        self.assertEqual(action_types[-1], "ok_click")
        self.assertEqual(clicks[-1], ("click", (147, 749)))
        self.assertEqual(result.close_method, "OK")
        self.assertIn("OK was clicked intentionally in confirmed apply mode", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_confirmed_apply_aborts_before_ok_when_channel_popup_detected(self) -> None:
        clicks: list[tuple[str, object]] = []
        closes: list[str] = []
        popup = Win32WindowSnapshot(999, "채널", "#32770", 1111, True, True, "(1, 1, 2, 2)")

        with self.assertRaisesRegex(DisplayGroupInspectionError, "채널"):
            self._confirmed_apply_call(
                heating_point_count=38,
                click_log=clicks,
                close_log=closes,
                popup_detector_fn=lambda _pid: (popup,),
            )

        self.assertNotIn(("click", (147, 749)), clicks)
        self.assertEqual(closes, ["ESC"])

    def test_max_48_confirmed_runs_all_blocks_with_down_up_down_and_clicks_ok(self) -> None:
        clicks: list[tuple[str, object]] = []
        scrolls: list[tuple[str, object]] = []
        waits: list[float] = []

        with patch("builtins.input", side_effect=AssertionError("max-48 confirmed apply must not prompt")):
            with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                result = self._max_48_confirmed_call(
                    click_log=clicks,
                    scroll_log=scrolls,
                    wait_log=waits,
                )

        print_to_pdf.assert_not_called()
        action_types = [action.action_type for action in result.executed_actions]
        descriptions = "\n".join(action.description for action in result.executed_actions)
        dialog_rect = (99, 0, 1041, 736)
        scroll_down = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "scroll_down")
        scroll_up = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "scroll_up")
        ok = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "ok")
        dest_w31 = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w31_start")
        dest_w40 = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w40_end")
        dest_w41 = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w41_start")
        dest_w48 = point_from_coordinate_profile(dialog_rect, DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736, "dest_w48_end")

        self.assertIn("source group/page 02 to destination W11~W20", descriptions)
        self.assertIn("source group/page 03 to destination W21~W30", descriptions)
        self.assertIn("source group/page 04 to destination W31~W40", descriptions)
        self.assertIn("source group/page 05 to destination W41~W48", descriptions)
        self.assertEqual(action_types.count("scrollbar_down_click"), 2)
        self.assertEqual(action_types.count("scrollbar_up_click"), 1)
        self.assertEqual(clicks.count(("click", scroll_down)), 2)
        self.assertIn(("click", scroll_up), clicks)
        self.assertIn(("drag", (dest_w31, dest_w40)), clicks)
        self.assertIn(("drag", (dest_w41, dest_w48)), clicks)
        self.assertEqual(scrolls, [])
        self.assertEqual(action_types[-1], "ok_click")
        self.assertEqual(clicks[-1], ("click", ok))
        self.assertEqual(result.close_method, "OK")
        self.assertIn("max-48 confirmed mode completed", result.safety_summary)
        self.assertIn("PDF was not printed", result.safety_summary)

    def test_max_48_confirmed_scroll_order_is_group05_up_then_second_down_before_w41(self) -> None:
        result = self._max_48_confirmed_call()
        action_types = [action.action_type for action in result.executed_actions]
        tab_05_index = action_types.index("tab_05_click")
        up_index = action_types.index("scrollbar_up_click")
        source_after_05 = action_types.index("source_drag_select", tab_05_index)
        down_indices = [index for index, action_type in enumerate(action_types) if action_type == "scrollbar_down_click"]
        destination_w41_index = next(
            index
            for index, action in enumerate(result.executed_actions)
            if action.action_type == "destination_drag_select" and "W41~W48" in action.description
        )

        self.assertLess(tab_05_index, up_index)
        self.assertLess(up_index, source_after_05)
        self.assertLess(down_indices[1], destination_w41_index)

    def test_max_48_scrollbar_up_click_moves_mouse_before_click(self) -> None:
        events: list[tuple[str, object]] = []
        result = self._max_48_confirmed_call(click_log=events, move_log=events)
        tab_05 = next(action for action in result.executed_actions if action.action_type == "tab_05_click")
        scrollbar_up = next(action for action in result.executed_actions if action.action_type == "scrollbar_up_click")
        source_group_05 = next(
            action
            for action in result.executed_actions
            if action.action_type == "source_drag_select" and "source group/page 05 W01~W08" in action.description
        )

        tab_05_click_index = events.index(("click", tab_05.point))
        scrollbar_up_move_index = events.index(("move", scrollbar_up.point))
        scrollbar_up_click_index = events.index(("click", scrollbar_up.point))
        source_group_05_drag_index = events.index(("drag", (source_group_05.drag_start, source_group_05.drag_end)))

        self.assertLess(tab_05_click_index, scrollbar_up_move_index)
        self.assertLess(scrollbar_up_move_index, scrollbar_up_click_index)
        self.assertLess(scrollbar_up_click_index, source_group_05_drag_index)

    def test_execute_scrollbar_up_action_type_moves_then_clicks(self) -> None:
        events: list[tuple[str, object]] = []
        step = ActualClickTestStep(
            1,
            "scrollbar_up_click",
            "group/page 05 scrollbar up area click before source W01~W08",
            point=(922, 183),
        )

        executed = execute_actual_click_test_step(
            step,
            click_fn=lambda point: events.append(("click", point)),
            drag_fn=lambda start, end: events.append(("drag", (start, end))),
            move_fn=lambda point: events.append(("move", point)),
            scroll_fn=lambda amount: events.append(("scroll", amount)),
        )

        self.assertEqual(events, [("move", (922, 183)), ("click", (922, 183))])
        self.assertEqual(executed.action_type, "scrollbar_up_click")

    def test_max_48_sequence_abort_if_group05_source_drag_precedes_scrollbar_up(self) -> None:
        clicks: list[tuple[str, object]] = []
        valid_sequence = build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            (99, 0, 1041, 736),
            DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736,
        )
        bad_sequence = tuple(step for step in valid_sequence if step.action_type != "scrollbar_up_click")

        with patch(
            "integrations.universal_viewer.display_group_settings.build_display_group_max_48_confirmed_sequence_from_coordinate_profile",
            return_value=bad_sequence,
        ):
            with self.assertRaisesRegex(DisplayGroupInspectionError, "scrollbar_up_click"):
                self._max_48_confirmed_call(click_log=clicks)

        self.assertEqual(clicks, [])

    def test_max_48_confirmed_aborts_before_ok_when_channel_popup_detected(self) -> None:
        clicks: list[tuple[str, object]] = []
        closes: list[str] = []
        popup = Win32WindowSnapshot(999, "梨꾨꼸", "#32770", 1111, True, True, "(1, 1, 2, 2)")

        with self.assertRaisesRegex(DisplayGroupInspectionError, "popup/dialog"):
            self._max_48_confirmed_call(
                click_log=clicks,
                close_log=closes,
                popup_detector_fn=lambda _pid: (popup,),
            )

        self.assertNotIn(("click", (147, 749)), clicks)
        self.assertEqual(closes, ["ESC"])

    def test_apply_geometry_actions_test_pause_after_paste(self) -> None:
        pauses: list[str] = []
        closes: list[str] = []

        self._apply_test_call(
            heating_point_count=16,
            pause_after_paste=True,
            pause_log=pauses,
            close_log=closes,
        )

        self.assertEqual(
            pauses,
            ["붙임 후 화면을 확인하세요. Enter를 누르면 다음 단계로 진행하거나 OK 없이 ESC로 닫습니다.", "input"],
        )
        self.assertEqual(closes, ["ESC"])

    def test_apply_geometry_actions_test_pause_before_button_clicks(self) -> None:
        pauses: list[str] = []
        moves: list[tuple[str, object]] = []

        self._apply_test_call(
            heating_point_count=16,
            pause_before_button_clicks=True,
            pause_log=pauses,
            move_log=moves,
        )

        self.assertEqual(
            pauses,
            [
                "마우스가 복사상세 버튼 위에 있는지 확인하세요. Enter를 누르면 클릭합니다.",
                "input",
                "마우스가 붙임 버튼 위에 있는지 확인하세요. Enter를 누르면 클릭합니다.",
                "input",
            ],
        )
        self.assertEqual(
            moves,
            [
                ("move", (1099, 749)),
                ("move", (1099, 749)),
                ("move", (1267, 749)),
                ("move", (1267, 749)),
            ],
        )

    def test_apply_geometry_actions_test_rejects_n10(self) -> None:
        open_calls: list[str] = []
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            with self.assertRaisesRegex(DisplayGroupInspectionError, "복사/붙임 작업이 필요하지 않아"):
                apply_display_group_geometry_actions_test(
                    root / "input" / "sample.DAE",
                    config,
                    self.logger,
                    heating_point_count=10,
                    open_raw_file_fn=lambda *_args, **_kwargs: open_calls.append("open") or self._opened(root),
                )

        self.assertEqual(open_calls, [])

    def test_apply_geometry_actions_test_rejects_n49(self) -> None:
        open_calls: list[str] = []
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            with self.assertRaisesRegex(DisplayGroupInspectionError, "48"):
                apply_display_group_geometry_actions_test(
                    root / "input" / "sample.DAE",
                    config,
                    self.logger,
                    heating_point_count=49,
                    open_raw_file_fn=lambda *_args, **_kwargs: open_calls.append("open") or self._opened(root),
                )

        self.assertEqual(open_calls, [])

    def test_apply_geometry_actions_test_rejects_n38_without_scroll_pause_or_continue(self) -> None:
        open_calls: list[str] = []
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            with self.assertRaisesRegex(DisplayGroupInspectionError, "--pause-after-display-group-scroll"):
                apply_display_group_geometry_actions_test(
                    root / "input" / "sample.DAE",
                    config,
                    self.logger,
                    heating_point_count=38,
                    open_raw_file_fn=lambda *_args, **_kwargs: open_calls.append("open") or self._opened(root),
                )

        self.assertEqual(open_calls, [])

    def test_apply_geometry_actions_test_rejects_n48_without_scroll_pause_or_continue(self) -> None:
        open_calls: list[str] = []
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            with self.assertRaisesRegex(DisplayGroupInspectionError, "--continue-without-display-group-pause"):
                apply_display_group_geometry_actions_test(
                    root / "input" / "sample.DAE",
                    config,
                    self.logger,
                    heating_point_count=48,
                    open_raw_file_fn=lambda *_args, **_kwargs: open_calls.append("open") or self._opened(root),
                )

        self.assertEqual(open_calls, [])

    def test_apply_geometry_actions_test_validates_coordinates_before_first_click(self) -> None:
        clicks: list[tuple[str, object]] = []
        closes: list[str] = []
        invalid_profile = replace(
            DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
            group_tab_x_ratios=(0.018, 2.0, 0.070, 0.096),
        )

        with self.assertRaisesRegex(DisplayGroupInspectionError, "대화상자 밖"):
            self._apply_test_call(
                heating_point_count=16,
                profile=invalid_profile,
                click_log=clicks,
                close_log=closes,
            )

        self.assertEqual(clicks, [])
        self.assertEqual(closes, ["ESC"])

    def test_apply_geometry_actions_test_missing_copy_detail_aborts_before_click(self) -> None:
        clicks: list[tuple[str, object]] = []

        def missing_copy_sequence(_geometry, _profile, _count):
            return (
                ActualClickTestStep(1, "tab_02_click", "group/page 02 tab 클릭", point=(470, 91)),
                ActualClickTestStep(2, "source_drag_select", "source", drag_start=(482, 195), drag_end=(1330, 275)),
                ActualClickTestStep(3, "tab_01_click", "group/page 01 tab 클릭", point=(447, 91)),
                ActualClickTestStep(4, "destination_drag_select", "destination", drag_start=(482, 355), drag_end=(1330, 435)),
                ActualClickTestStep(5, "paste_click", "붙임 버튼 클릭", point=(1267, 749)),
                ActualClickTestStep(6, "close_esc", "닫기"),
            )

        with self.assertRaisesRegex(DisplayGroupInspectionError, "허용되지 않은 actual-click test sequence"):
            self._apply_test_call(
                heating_point_count=16,
                click_log=clicks,
                sequence_builder_fn=missing_copy_sequence,
            )

        self.assertEqual(clicks, [])

    def test_apply_geometry_actions_test_missing_paste_aborts_before_click(self) -> None:
        clicks: list[tuple[str, object]] = []

        def missing_paste_sequence(_geometry, _profile, _count):
            return (
                ActualClickTestStep(1, "tab_02_click", "group/page 02 tab 클릭", point=(470, 91)),
                ActualClickTestStep(2, "source_drag_select", "source", drag_start=(482, 195), drag_end=(1330, 275)),
                ActualClickTestStep(3, "copy_detail_click", "복사상세 버튼 클릭", point=(1099, 749)),
                ActualClickTestStep(4, "tab_01_click", "group/page 01 tab 클릭", point=(447, 91)),
                ActualClickTestStep(5, "destination_drag_select", "destination", drag_start=(482, 355), drag_end=(1330, 435)),
                ActualClickTestStep(6, "close_esc", "닫기"),
            )

        with self.assertRaisesRegex(DisplayGroupInspectionError, "허용되지 않은 actual-click test sequence"):
            self._apply_test_call(
                heating_point_count=16,
                click_log=clicks,
                sequence_builder_fn=missing_paste_sequence,
            )

        self.assertEqual(clicks, [])

    def test_apply_geometry_actions_test_never_calls_pdf_printing(self) -> None:
        with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf", side_effect=AssertionError("PDF 출력 금지")):
            result = self._apply_test_call(heating_point_count=16)

        self.assertIn("PDF was not printed", result.safety_summary)

    def test_display_top_menu_text_does_not_match_display_group_item(self) -> None:
        self.assertTrue(is_display_top_menu_text("표시(V)"))
        self.assertTrue(is_display_top_menu_text("View(V)"))
        self.assertFalse(is_display_top_menu_text("표시 그룹 설정(D)..."))

    def test_dialog_candidate_filtering_prefers_matching_owner_and_title(self) -> None:
        windows = (
            Win32WindowSnapshot(1, "Universal Viewer", "Universal_Viewer R3.12.01", 1111, True, False),
            Win32WindowSnapshot(2, "표시 그룹 설정", "#32770", 1111, True, True),
            Win32WindowSnapshot(3, "표시 그룹 설정", "#32770", 9999, True, True),
            Win32WindowSnapshot(4, "표시 그룹 설정", "#32770", 1111, True, False),
            Win32WindowSnapshot(5, "무제", "#32770", 1111, True, True),
        )

        candidates = filter_display_group_dialog_candidates(windows, 1111, baseline_hwnds=(1,))

        self.assertEqual(tuple(candidate.hwnd for candidate in candidates), (2, 5))

    def test_commit_buttons_are_not_safe_close_buttons(self) -> None:
        for title in ("확인", "OK", "적용", "Apply", "저장", "Save"):
            self.assertTrue(is_forbidden_commit_button_title(title))
            self.assertFalse(is_safe_close_button_title(title))

        for title in ("취소", "Cancel", "닫기", "Close"):
            self.assertTrue(is_safe_close_button_title(title))
            self.assertFalse(is_forbidden_commit_button_title(title))

    def test_close_dialog_does_not_click_ok_apply_or_save(self) -> None:
        clicked: list[int] = []

        with patch("integrations.universal_viewer.display_group_settings.click_win32_button", side_effect=lambda hwnd: clicked.append(hwnd)):
            method = close_display_group_dialog_without_applying(self._dialog(), self.logger)

        self.assertEqual(clicked, [204])
        self.assertIn("취소", method)

    def test_close_dialog_uses_esc_when_only_commit_buttons_exist(self) -> None:
        dialog = DisplayGroupDialogSnapshot(
            top_level=Win32WindowSnapshot(200, "표시 그룹 설정", "#32770", 1111, True, True),
            win32_children=(
                Win32WindowSnapshot(201, "확인", "Button", 1111, True, True),
                Win32WindowSnapshot(202, "적용", "Button", 1111, True, True),
            ),
            uia_elements=(),
        )
        clicked: list[int] = []
        closed: list[str] = []

        with patch("integrations.universal_viewer.display_group_settings.click_win32_button", side_effect=lambda hwnd: clicked.append(hwnd)):
            with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely", side_effect=lambda: closed.append("ESC")):
                method = close_display_group_dialog_without_applying(dialog, self.logger)

        self.assertEqual(clicked, [])
        self.assertEqual(closed, ["ESC"])
        self.assertEqual(method, "ESC")

    def test_pause_mode_does_not_click_ok_apply_or_save(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = self._dialog()
            closed: list[str] = []
            messages: list[str] = []
            inputs: list[str] = []

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch(
                    "integrations.universal_viewer.display_group_settings.click_win32_button",
                    side_effect=AssertionError("pause 모드에서 버튼 클릭 금지"),
                ):
                    with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely", side_effect=lambda: closed.append("ESC")):
                        result = inspect_display_group_settings(
                            opened.source_path,
                            config,
                            self.logger,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog.top_level,
                            structure_collector_fn=lambda _top: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                            pause_before_close=True,
                            pause_input_fn=lambda prompt: inputs.append(prompt) or "",
                            message_printer=lambda message: messages.append(message),
                            now=datetime(2026, 7, 8, 12, 0, 0),
                        )

            self.assertEqual(closed, ["ESC"])
            self.assertEqual(result.close_method, "ESC")
            self.assertTrue(messages)
            self.assertEqual(inputs, [""])

    def test_pause_mode_does_not_call_print_or_pdf_functions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = self._dialog()

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely"):
                    with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                        inspect_display_group_settings(
                            opened.source_path,
                            config,
                            self.logger,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog.top_level,
                            structure_collector_fn=lambda _top: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                            pause_before_close=True,
                            pause_input_fn=lambda _prompt: "",
                            message_printer=lambda _message: None,
                        )

            print_to_pdf.assert_not_called()

    def test_recursive_win32_enumeration_includes_nested_children(self) -> None:
        tree = {
            1: (2, 3),
            2: (4,),
            3: (),
            4: (5,),
            5: (),
        }

        descendants = enum_descendant_hwnds_with_depth(1, direct_children_fn=lambda hwnd: tree[hwnd])

        self.assertEqual(descendants, ((2, 1), (4, 2), (5, 3), (3, 1)))

    def test_uia_descendant_collection_attempts_are_logged(self) -> None:
        class Rect:
            def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
                self.left = left
                self.top = top
                self.right = right
                self.bottom = bottom

        class Info:
            def __init__(self, name: str, class_name: str = "", automation_id: str = "") -> None:
                self.name = name
                self.class_name = class_name
                self.automation_id = automation_id

        class Wrapper:
            def __init__(
                self,
                name: str,
                control_type: str,
                rect: Rect,
                *,
                children: tuple["Wrapper", ...] = (),
            ) -> None:
                self.element_info = Info(name, "FakeClass", f"id_{name}")
                self._name = name
                self._control_type = control_type
                self._rect = rect
                self._children = children

            def window_text(self) -> str:
                return self._name

            def friendly_class_name(self) -> str:
                return self._control_type

            def is_enabled(self) -> bool:
                return True

            def rectangle(self) -> Rect:
                return self._rect

            def descendants(self) -> tuple["Wrapper", ...]:
                return self._children

        class Desktop:
            def __init__(self) -> None:
                self.root = Wrapper(
                    "Dialog",
                    "Window",
                    Rect(0, 0, 100, 100),
                    children=(Wrapper("Tab", "TabItem", Rect(10, 10, 40, 30)),),
                )
                self.inside = Wrapper("Inside", "Button", Rect(20, 20, 30, 30))
                self.outside = Wrapper("Outside", "Button", Rect(200, 200, 220, 220))

            def window(self, **_kwargs: object) -> Wrapper:
                return self.root

            def descendants(self) -> tuple[Wrapper, ...]:
                return (self.inside, self.outside)

        class FailingApplication:
            def connect(self, **_kwargs: object) -> object:
                raise RuntimeError("connect 실패")

        result = collect_uia_elements_with_attempt_logs(
            200,
            "(0, 0, 100, 100)",
            desktop_factory=lambda _backend: Desktop(),
            application_factory=lambda _backend: FailingApplication(),
        )

        joined_logs = "\n".join(result.attempt_logs)
        self.assertIn("Desktop(backend='uia').window(handle).descendants: success", joined_logs)
        self.assertIn("Application(backend='uia').connect(handle).descendants: failed", joined_logs)
        self.assertIn("Desktop(backend='uia').descendants filtered by dialog rectangle: success", joined_logs)
        names = tuple(element.name for element in result.elements)
        self.assertIn("Tab", names)
        self.assertIn("Inside", names)
        self.assertNotIn("Outside", names)

    def test_geometry_inspection_does_not_click_ok_apply_or_save(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            )
            closed: list[str] = []

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch(
                    "integrations.universal_viewer.display_group_settings.click_win32_button",
                    side_effect=AssertionError("geometry 모드에서 버튼 클릭 금지"),
                ):
                    with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely", side_effect=lambda: closed.append("ESC")):
                        result = inspect_display_group_geometry(
                            opened.source_path,
                            config,
                            self.logger,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                            now=datetime(2026, 7, 8, 12, 0, 0),
                        )

            self.assertEqual(closed, ["ESC"])
            self.assertEqual(result.close_method, "ESC")
            self.assertEqual(result.geometry.dialog_rect, (430, 50, 1368, 777))

    def test_geometry_inspection_does_not_call_print_or_pdf_functions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            )

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely"):
                    with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                        inspect_display_group_geometry(
                            opened.source_path,
                            config,
                            self.logger,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                        )

            print_to_pdf.assert_not_called()

    def test_geometry_inspection_requires_verified_work_copy_before_opening_dialog(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root, hint_verified=False)
            menu_calls: list[str] = []

            with self.assertRaisesRegex(DisplayGroupInspectionError, "작업본이 Universal Viewer에 열린 상태"):
                inspect_display_group_geometry(
                    opened.source_path,
                    config,
                    self.logger,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    menu_open_fn=lambda _opened, _logger: menu_calls.append("menu") or DISPLAY_GROUP_MENU_PATH,
                )

            self.assertEqual(menu_calls, [])

    def test_scrollbar_points_pause_records_absolute_and_relative_coordinates(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            )
            mouse_positions = iter(((1321, 450), (1340, 300), (1340, 620)))
            clicks: list[tuple[int, int]] = []
            messages: list[str] = []
            inputs: list[str] = []
            closes: list[str] = []

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                    result = inspect_display_group_scrollbar_points_pause(
                        opened.source_path,
                        config,
                        self.logger,
                        open_raw_file_fn=lambda *_args, **_kwargs: opened,
                        menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                        dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                        raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                        click_fn=lambda point: clicks.append(point),
                        mouse_position_fn=lambda: next(mouse_positions),
                        pause_input_fn=lambda prompt: inputs.append(prompt) or "",
                        message_printer=lambda message: messages.append(message),
                        close_dialog_fn=lambda _logger: closes.append("ESC") or "ESC",
                    )

            print_to_pdf.assert_not_called()
            self.assertEqual(clicks, [(447, 91)])
            self.assertEqual(inputs, ["", "", ""])
            self.assertEqual(closes, ["ESC"])
            self.assertEqual(result.close_method, "ESC")
            self.assertTrue(result.state_unchanged)
            self.assertEqual(
                result.output_lines,
                (
                    "grid_wheel_focus_abs=(1321,450), rel=(0.950,0.550)",
                    "scrollbar_thumb_start_abs=(1340,300), rel=(0.970,0.344)",
                    "scrollbar_thumb_end_abs=(1340,620), rel=(0.970,0.784)",
                ),
            )
            output_text = "\n".join(messages)
            self.assertIn("dialog rectangle: (430, 50, 1368, 777)", output_text)
            self.assertIn("grid_wheel_focus_abs=(1321,450), rel=(0.950,0.550)", output_text)
            self.assertIn("scrollbar_thumb_start_abs=(1340,300), rel=(0.970,0.344)", output_text)
            self.assertIn("scrollbar_thumb_end_abs=(1340,620), rel=(0.970,0.784)", output_text)

    def test_preview_mode_performs_no_clicks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            )
            closed: list[str] = []

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch(
                    "integrations.universal_viewer.display_group_settings.click_win32_button",
                    side_effect=AssertionError("preview 모드에서 버튼 클릭 금지"),
                ):
                    with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely", side_effect=lambda: closed.append("ESC")):
                        result = preview_display_group_geometry_actions(
                            opened.source_path,
                            config,
                            self.logger,
                            heating_point_count=11,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                            now=datetime(2026, 7, 8, 12, 0, 0),
                        )

            self.assertEqual(closed, ["ESC"])
            self.assertEqual(result.close_method, "ESC")
            self.assertTrue(any("copy_detail_candidate" in line for line in result.report_lines))
            report_text = "\n".join(result.report_lines)
            self.assertIn("[bottom button coordinate calibration]", report_text)
            self.assertIn("OK coordinate: (569, 749)", report_text)
            self.assertIn("Cancel coordinate: (755, 749)", report_text)
            self.assertIn("Copy detail coordinate: (1099, 749)", report_text)
            self.assertIn("Paste coordinate: (1267, 749)", report_text)
            self.assertIn("bottom button y ratio: 0.961", report_text)

    def test_preview_mode_does_not_call_stage4_print_or_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = Win32WindowSnapshot(
                200,
                "표시 그룹 설정",
                "#32770",
                1111,
                True,
                True,
                "(430, 50, 1368, 777)",
            )

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch("integrations.universal_viewer.display_group_settings.close_open_menu_safely"):
                    with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                        preview_display_group_geometry_actions(
                            opened.source_path,
                            config,
                            self.logger,
                            heating_point_count=11,
                            open_raw_file_fn=lambda *_args, **_kwargs: opened,
                            menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                            dialog_detector_fn=lambda _pid, _baseline, _logger: dialog,
                            raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                        )

            print_to_pdf.assert_not_called()

    def test_preview_requires_verified_work_copy_before_opening_dialog(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root, hint_verified=False)
            menu_calls: list[str] = []

            with self.assertRaisesRegex(DisplayGroupInspectionError, "작업본이 Universal Viewer에 열린 상태"):
                preview_display_group_geometry_actions(
                    opened.source_path,
                    config,
                    self.logger,
                    heating_point_count=1,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    menu_open_fn=lambda _opened, _logger: menu_calls.append("menu") or DISPLAY_GROUP_MENU_PATH,
                )

            self.assertEqual(menu_calls, [])

    def test_inspection_refuses_when_work_copy_hint_is_not_verified(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root, hint_verified=False)
            menu_calls: list[str] = []

            with self.assertRaisesRegex(DisplayGroupInspectionError, "작업본이 Universal Viewer에 열린 상태"):
                inspect_display_group_settings(
                    opened.source_path,
                    config,
                    self.logger,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    menu_open_fn=lambda _opened, _logger: menu_calls.append("menu") or DISPLAY_GROUP_MENU_PATH,
                )

            self.assertEqual(menu_calls, [])

    def test_inspection_does_not_call_print_or_pdf_functions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            config.ensure_directories()
            opened = self._opened(root)
            dialog = self._dialog()

            with patch("integrations.universal_viewer.display_group_settings.capture_top_level_windows", return_value=()):
                with patch("integrations.universal_viewer.pdf_printing.print_raw_file_to_pdf") as print_to_pdf:
                    result = inspect_display_group_settings(
                        opened.source_path,
                        config,
                        self.logger,
                        open_raw_file_fn=lambda *_args, **_kwargs: opened,
                        menu_open_fn=lambda _opened, _logger: DISPLAY_GROUP_MENU_PATH,
                        dialog_detector_fn=lambda _pid, _baseline, _logger: dialog.top_level,
                        structure_collector_fn=lambda _top: dialog,
                        close_dialog_fn=lambda _dialog, _logger: "ESC",
                        raw_hint_collector=lambda _hwnd: (opened.work_copy_path.name,),
                        now=datetime(2026, 7, 8, 12, 0, 0),
                    )

            print_to_pdf.assert_not_called()
            self.assertTrue(result.state_unchanged)
            self.assertTrue(result.report_path.is_file())

    def test_main_stage5_branch_does_not_call_stage4_print(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            opened = self._opened(root)
            dialog = self._dialog()
            fake_result = DisplayGroupInspectionResult(
                opened=opened,
                report_path=root / "logs" / "display_group_settings_inspection_20260708_120000.txt",
                menu_path=DISPLAY_GROUP_MENU_PATH,
                dialog=dialog,
                before_raw_file_hints=(opened.work_copy_path.name,),
                after_raw_file_hints=(opened.work_copy_path.name,),
                state_unchanged=True,
                close_method="ESC",
            )

            with patch("integrations.universal_viewer.main.resolve_input_files", return_value=[opened.source_path]):
                with patch("integrations.universal_viewer.main.inspect_display_group_settings", return_value=fake_result) as inspect_fn:
                    with patch("integrations.universal_viewer.main.print_raw_file_to_pdf") as print_fn:
                        exit_code = main(["--inspect-display-group-settings", ".\\input\\sample.DAE"])

            self.assertEqual(exit_code, 0)
            inspect_fn.assert_called_once()
            print_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
