"""Universal Viewer UI 읽기 전용 조사 테스트."""

import unittest

from integrations.universal_viewer.ui_inspection import (
    NativeMenuItemInfo,
    MenuPathItemInfo,
    MenuUiSnapshot,
    PopupWindowInfo,
    DesktopUiaElementInfo,
    ToolbarMenuItemInfo,
    UiElementInfo,
    _accelerator_key_for_root,
    _deduplicate_menu_path_items,
    _is_allowed_menu_root,
    _menu_path_signature,
    _probe_menu_opening,
    collect_ui_elements,
    find_raw_file_hints,
    format_menu_path_item,
    format_popup_window_delta,
    format_native_menu_item,
    format_toolbar_menu_item,
    format_ui_element,
    inspect_native_menu,
    inspect_menu_bar_toolbars,
    is_menu_bar_toolbar_candidate,
    is_priority_menu_text,
)


class FakeControl:
    def __init__(
        self,
        title: str,
        class_name: str,
        control_id: int | None,
        control_type: str,
        visible: bool,
        enabled: bool,
    ) -> None:
        self._title = title
        self._class_name = class_name
        self._control_id = control_id
        self._control_type = control_type
        self._visible = visible
        self._enabled = enabled

    def window_text(self) -> str:
        return self._title

    def class_name(self) -> str:
        return self._class_name

    def control_id(self) -> int | None:
        return self._control_id

    def friendly_class_name(self) -> str:
        return self._control_type

    def is_visible(self) -> bool:
        return self._visible

    def is_enabled(self) -> bool:
        return self._enabled


class FakeRoot:
    def __init__(self, controls: tuple[FakeControl, ...]) -> None:
        self._controls = controls

    def descendants(self) -> tuple[FakeControl, ...]:
        return self._controls


class FakeRectangle:
    left = 1
    top = 2
    right = 30
    bottom = 40


class FakeToolbarButton:
    def __init__(self, text: str, command_id: int) -> None:
        self._text = text
        self._command_id = command_id

    def window_text(self) -> str:
        return self._text

    def command_id(self) -> int:
        return self._command_id

    def class_name(self) -> str:
        return "ToolbarButton"

    def rectangle(self) -> FakeRectangle:
        return FakeRectangle()

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def is_separator(self) -> bool:
        return False

    def legacy_properties(self) -> dict[str, str]:
        return {"Name": self._text}


class FakeToolbar(FakeControl):
    def __init__(self) -> None:
        super().__init__("메뉴 모음", "Afx:ToolBar:test", 59398, "Toolbar", True, True)
        self._buttons = (
            FakeToolbarButton("파일(F)", 100),
            FakeToolbarButton("표시(V)", 200),
        )

    def buttons(self) -> tuple[FakeToolbarButton, ...]:
        return self._buttons

    def button_count(self) -> int:
        return len(self._buttons)

    def rectangle(self) -> FakeRectangle:
        return FakeRectangle()


class UiInspectionTests(unittest.TestCase):
    def test_priority_menu_keywords_include_file_view_and_print(self) -> None:
        self.assertTrue(is_priority_menu_text("파일(&F)"))
        self.assertTrue(is_priority_menu_text("View"))
        self.assertTrue(is_priority_menu_text("인쇄"))
        self.assertFalse(is_priority_menu_text("도움말"))

    def test_collect_ui_elements_reads_control_metadata(self) -> None:
        root = FakeRoot(
            (
                FakeControl("파일", "#32768", 100, "MenuItem", True, True),
                FakeControl("그래프", "AfxWnd", None, "Pane", True, False),
            )
        )
        elements = collect_ui_elements(root)
        self.assertEqual(len(elements), 2)
        self.assertEqual(elements[0].title, "파일")
        self.assertEqual(elements[0].control_id, 100)
        self.assertEqual(elements[1].control_id, None)
        self.assertFalse(elements[1].enabled)

    def test_format_ui_element_contains_required_fields(self) -> None:
        line = format_ui_element(
            UiElementInfo(
                depth=1,
                title="Print",
                class_name="Button",
                control_id=7,
                control_type="Button",
                visible=True,
                enabled=False,
            )
        )
        self.assertIn("title=Print", line)
        self.assertIn("class=Button", line)
        self.assertIn("control_id=7", line)
        self.assertIn("control_type=Button", line)
        self.assertIn("visible=true", line)
        self.assertIn("enabled=false", line)

    def test_find_raw_file_hints_detects_dae_and_gev(self) -> None:
        hints = find_raw_file_hints(
            (
                "Universal Viewer - C:\\data\\sample.DAE",
                "현재 파일: bench test.GEV",
                "이벤트파일-파형[12 Vdc_Normal On the bench.DAE]",
                "sample.DAE",
            )
        )
        self.assertIn("sample.DAE", hints)
        self.assertIn("bench test.GEV", hints)
        self.assertIn("12 Vdc_Normal On the bench.DAE", hints)

    def test_inspect_native_menu_reports_missing_hwnd(self) -> None:
        message, items = inspect_native_menu(None)
        self.assertIn("native menu not found", message)
        self.assertEqual(items, ())

    def test_format_native_menu_item_contains_required_fields(self) -> None:
        line = format_native_menu_item(
            NativeMenuItemInfo(
                path="파일 > 인쇄",
                text="인쇄",
                command_id=57607,
                has_submenu=False,
                enabled=True,
                separator=False,
                depth=1,
            )
        )
        self.assertIn("path=파일 > 인쇄", line)
        self.assertIn("text=인쇄", line)
        self.assertIn("command_id=57607", line)
        self.assertIn("submenu=false", line)
        self.assertIn("enabled=true", line)
        self.assertIn("separator=false", line)

    def test_menu_bar_toolbar_candidate_uses_title_control_id_and_class(self) -> None:
        candidate = UiElementInfo(
            depth=1,
            title="메뉴 모음",
            class_name="Afx:ToolBar:test",
            control_id=59398,
            control_type="Toolbar",
            visible=True,
            enabled=True,
        )
        self.assertTrue(is_menu_bar_toolbar_candidate(candidate))

    def test_inspect_menu_bar_toolbars_reads_button_metadata(self) -> None:
        root = FakeRoot((FakeToolbar(),))
        items = inspect_menu_bar_toolbars(root)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].text, "파일(F)")
        self.assertEqual(items[0].command_id, 100)
        self.assertEqual(items[0].control_id, 59398)
        self.assertEqual(items[0].rectangle, "(1, 2, 30, 40)")
        self.assertTrue(items[0].visible)
        self.assertTrue(items[0].enabled)
        self.assertFalse(items[0].separator)
        self.assertEqual(items[0].accessibility_name, "파일(F)")

    def test_format_toolbar_menu_item_contains_required_fields(self) -> None:
        line = format_toolbar_menu_item(
            ToolbarMenuItemInfo(
                source="menu_bar_toolbar",
                text="파일(F)",
                index=0,
                command_id=100,
                class_name="ToolbarButton",
                control_id=59398,
                rectangle="(1, 2, 30, 40)",
                visible=True,
                enabled=True,
                separator=False,
                accessibility_name="파일(F)",
            )
        )
        self.assertIn("text=파일(F)", line)
        self.assertIn("index=0", line)
        self.assertIn("command_id=100", line)
        self.assertIn("control_id=59398", line)
        self.assertIn("rectangle=(1, 2, 30, 40)", line)

    def test_allowed_menu_root_is_limited_to_file_and_view(self) -> None:
        self.assertTrue(_is_allowed_menu_root("파일(F)"))
        self.assertTrue(_is_allowed_menu_root("표시(V)"))
        self.assertTrue(_is_allowed_menu_root("File"))
        self.assertTrue(_is_allowed_menu_root("View"))
        self.assertFalse(_is_allowed_menu_root("편집(E)"))
        self.assertFalse(_is_allowed_menu_root("인쇄"))

    def test_accelerator_key_is_limited_to_allowed_roots(self) -> None:
        self.assertEqual(_accelerator_key_for_root("파일(F)"), "F")
        self.assertEqual(_accelerator_key_for_root("표시(V)"), "V")
        self.assertEqual(_accelerator_key_for_root("File"), "F")
        self.assertEqual(_accelerator_key_for_root("View"), "V")
        self.assertIsNone(_accelerator_key_for_root("편집(E)"))

    def test_format_menu_path_item_contains_required_fields(self) -> None:
        line = format_menu_path_item(
            MenuPathItemInfo(
                root_menu="파일(F)",
                path="파일(F) > 인쇄",
                text="인쇄",
                index=3,
                command_id=None,
                source="uia_open_menu",
                visible=True,
                enabled=False,
                rectangle="(10, 20, 30, 40)",
                class_name="MenuItem",
            )
        )
        self.assertIn("path=파일(F) > 인쇄", line)
        self.assertIn("text=인쇄", line)
        self.assertIn("source=uia_open_menu", line)
        self.assertIn("visible=true", line)
        self.assertIn("enabled=false", line)

    def test_deduplicate_menu_path_items_keeps_unique_results(self) -> None:
        first = MenuPathItemInfo(
            root_menu="파일(F)",
            path="파일(F) > 열기",
            text="열기",
            index=1,
            command_id=None,
            source="uia_open_menu",
            visible=True,
            enabled=True,
            rectangle="(1, 2, 3, 4)",
            class_name="MenuItem",
        )
        duplicate = MenuPathItemInfo(
            root_menu="파일(F)",
            path="파일(F) > 열기",
            text="열기",
            index=2,
            command_id=None,
            source="uia_open_menu",
            visible=True,
            enabled=True,
            rectangle="(1, 2, 3, 4)",
            class_name="MenuItem",
        )
        unique = MenuPathItemInfo(
            root_menu="표시(V)",
            path="표시(V) > 상세설정",
            text="상세설정",
            index=1,
            command_id=None,
            source="uia_open_menu",
            visible=True,
            enabled=True,
            rectangle="(5, 6, 7, 8)",
            class_name="MenuItem",
        )
        self.assertEqual(_deduplicate_menu_path_items((first, duplicate, unique)), (first, unique))

    def test_menu_path_signature_ignores_root_menu_for_baseline_diff(self) -> None:
        before = MenuPathItemInfo(
            root_menu="__baseline__",
            path="__baseline__ > Open",
            text="Open",
            index=1,
            command_id=None,
            source="uia_open_menu",
            visible=True,
            enabled=True,
            rectangle="(1, 2, 3, 4)",
            class_name="MenuItem",
        )
        after = MenuPathItemInfo(
            root_menu="파일(F)",
            path="파일(F) > Open",
            text="Open",
            index=5,
            command_id=None,
            source="uia_open_menu",
            visible=True,
            enabled=True,
            rectangle="(1, 2, 3, 4)",
            class_name="MenuItem",
        )
        self.assertEqual(_menu_path_signature(before), _menu_path_signature(after))

    def test_menu_probe_uses_only_one_click_and_no_accelerator(self) -> None:
        calls: list[str] = []
        snapshots = iter((MenuUiSnapshot((), ()), MenuUiSnapshot((), ())))

        result = _probe_menu_opening(
            "파일(F)",
            object(),
            10,
            20,
            set(),
            snapshot_fn=lambda _pid: next(snapshots),
            click_fn=lambda _wrapper: calls.append("click") or True,
            close_fn=lambda: calls.append("esc"),
            sleep_fn=lambda _seconds: None,
        )

        self.assertEqual(calls, ["click", "esc"])
        self.assertFalse(result.opening_verified)

    def test_menu_probe_never_clicks_or_invokes_submenu(self) -> None:
        class GuardedSubmenu:
            def click_input(self) -> None:
                raise AssertionError("하위 메뉴 click 금지")

            def invoke(self) -> None:
                raise AssertionError("하위 메뉴 invoke 금지")

        popup = PopupWindowInfo(10, 99, "#32768", "", True, "win32")
        element = DesktopUiaElementInfo("열기...", 10, "MenuItem", "", 99, True, True, "(1, 2, 3, 4)")
        snapshots = iter((MenuUiSnapshot((), ()), MenuUiSnapshot((popup,), (element,))))
        submenu = GuardedSubmenu()

        result = _probe_menu_opening(
            "파일(F)",
            object(),
            10,
            20,
            set(),
            snapshot_fn=lambda _pid: next(snapshots),
            click_fn=lambda _wrapper: True,
            close_fn=lambda: None,
            sleep_fn=lambda _seconds: None,
            inspect_items_fn=lambda _root, _hwnd, _signatures: (),
        )

        self.assertTrue(result.opening_verified)
        self.assertEqual(submenu.__class__.__name__, "GuardedSubmenu")
        self.assertIn("열기...", tuple(item.text for item in result.items))

    def test_popup_window_delta_format_contains_required_fields(self) -> None:
        line = format_popup_window_delta(
            PopupWindowInfo(123, 456, "#32768", "파일", True, "win32")
        )
        self.assertIn("PID=123", line)
        self.assertIn("HWND=456", line)
        self.assertIn("class=#32768", line)
        self.assertIn("visible=true", line)
        self.assertIn("title/text=파일", line)

    def test_menu_opening_verification_failure_still_closes_with_escape(self) -> None:
        closed: list[str] = []
        snapshots = iter((MenuUiSnapshot((), ()), MenuUiSnapshot((), ())))
        result = _probe_menu_opening(
            "표시(V)",
            object(),
            10,
            20,
            set(),
            snapshot_fn=lambda _pid: next(snapshots),
            click_fn=lambda _wrapper: True,
            close_fn=lambda: closed.append("esc"),
            sleep_fn=lambda _seconds: None,
        )
        self.assertFalse(result.opening_verified)
        self.assertEqual(closed, ["esc"])

    def test_unrelated_desktop_uia_delta_does_not_verify_viewer_menu(self) -> None:
        unrelated = DesktopUiaElementInfo(
            "More", 999, "MenuItem", "menubar-menu-button", None, True, True, "(1, 2, 3, 4)"
        )
        snapshots = iter((MenuUiSnapshot((), ()), MenuUiSnapshot((), (unrelated,))))
        result = _probe_menu_opening(
            "파일(F)",
            object(),
            10,
            20,
            set(),
            snapshot_fn=lambda _pid: next(snapshots),
            click_fn=lambda _wrapper: True,
            close_fn=lambda: None,
            sleep_fn=lambda _seconds: None,
            inspect_items_fn=lambda _root, _hwnd, _signatures: (),
        )
        self.assertFalse(result.opening_verified)
        self.assertEqual(result.new_uia_elements, ())


if __name__ == "__main__":
    unittest.main()
