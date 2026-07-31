"""Microsoft Print to PDF Stage 4 테스트."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.pdf_printing import (
    PdfPrintingError,
    FilenameEntryResult,
    SAVE_DIALOG_TITLES,
    Win32ChildControlInfo,
    Win32DialogInfo,
    collect_pdf_wait_diagnostics,
    copy_pdf_to_desktop_archive,
    enter_and_verify_filename,
    enter_save_path_and_confirm,
    find_filename_edit_child_info,
    handle_overwrite_confirmation,
    find_save_button_child_info,
    find_win32_dialog_info,
    print_raw_file_to_pdf,
    resolve_output_pdf_path,
    select_or_verify_microsoft_print_to_pdf,
    set_win32_edit_text,
    wait_for_dialog,
)
from integrations.universal_viewer.viewer_discovery import WindowInfo
from integrations.universal_viewer.viewer_launcher import ViewerOpenResult
from result_folders import RESULTS_FOLDER_NAME


class FakeDialog:
    def __init__(self, children: tuple[object, ...] = (), handle: int | None = None) -> None:
        self._children = children
        self.handle = handle

    def descendants(self, **_kwargs: object) -> tuple[object, ...]:
        return self._children


class FakeDesktop:
    def windows(self) -> tuple[object, ...]:
        return ()

    def window(self, **_kwargs: object) -> object:
        return FakeDialog()


class PdfPrintingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"pdf-printing-test-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def _opened(self, root: Path, *, hint_verified: bool = True, planned_pdf_path: Path | None = None) -> ViewerOpenResult:
        work_copy = root / "output" / "work" / "sample_DAE.DAE"
        viewer_exe = root / "UnivViewer.exe"
        work_copy.parent.mkdir(parents=True, exist_ok=True)
        work_copy.write_bytes(b"raw-data")
        viewer_exe.write_bytes(b"exe")
        planned = planned_pdf_path or (root / "output" / "sample_DAE_20260708_120000.pdf")
        return ViewerOpenResult(
            source_path=root / "input" / "sample.DAE",
            work_copy_path=work_copy,
            viewer_exe_path=viewer_exe,
            planned_pdf_path=planned,
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

    def test_default_output_pdf_path_is_used_when_omitted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root)

            result = print_raw_file_to_pdf(
                opened.source_path,
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                print_automation_fn=lambda _opened, path, _logger: path.write_bytes(b"%PDF-1.4\n"),
                pdf_validation_fn=lambda path, _logger: 1 if path.stat().st_size > 0 else None,
                archive_copy_fn=lambda _path: None,
            )

            self.assertEqual(result.output_pdf_path, opened.planned_pdf_path.resolve())
            self.assertGreater(result.pdf_size_bytes, 0)

    def test_explicit_output_pdf_path_is_respected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root)
            explicit = root / "output" / "custom_name.pdf"

            result = print_raw_file_to_pdf(
                opened.source_path,
                config,
                self.logger,
                explicit_output_pdf=explicit,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                print_automation_fn=lambda _opened, path, _logger: path.write_bytes(b"%PDF-1.4\n"),
                pdf_validation_fn=lambda path, _logger: 1 if path.stat().st_size > 0 else None,
                archive_copy_fn=lambda _path: None,
            )

            self.assertEqual(result.output_pdf_path, explicit.resolve())

    def test_default_pdf_path_avoids_overwriting_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            planned = root / "output" / "sample.pdf"
            planned.parent.mkdir()
            planned.write_bytes(b"existing")

            resolved = resolve_output_pdf_path(config, planned)

            self.assertEqual(resolved, (root / "output" / "sample_1.pdf").resolve())

    def test_pdf_path_is_not_allowed_inside_input(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            bad_path = root / "input" / "bad.pdf"

            with self.assertRaisesRegex(PdfPrintingError, "input 폴더"):
                resolve_output_pdf_path(config, root / "output" / "planned.pdf", explicit_output_pdf=bad_path)

    def test_missing_microsoft_print_to_pdf_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(PdfPrintingError, "Microsoft Print to PDF"):
            select_or_verify_microsoft_print_to_pdf(FakeDialog(), self.logger)

    def test_print_flow_refuses_when_work_copy_is_not_confirmed_open(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root, hint_verified=False)
            called: list[Path] = []

            with self.assertRaisesRegex(PdfPrintingError, "작업본이 Universal Viewer에 열린 상태"):
                print_raw_file_to_pdf(
                    opened.source_path,
                    config,
                    self.logger,
                    open_raw_file_fn=lambda *_args, **_kwargs: opened,
                    print_automation_fn=lambda _opened, path, _logger: called.append(path),
                    pdf_validation_fn=lambda _path, _logger: 1,
                    archive_copy_fn=lambda _path: None,
                )
            self.assertEqual(called, [])

    def test_successful_print_flow_waits_for_and_validates_created_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root)
            validated: list[Path] = []

            def fake_validate(path: Path, _logger: logging.Logger) -> int:
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
                validated.append(path)
                return 1

            result = print_raw_file_to_pdf(
                opened.source_path,
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                print_automation_fn=lambda _opened, path, _logger: path.write_bytes(b"%PDF-1.4\n"),
                pdf_validation_fn=fake_validate,
                archive_copy_fn=lambda _path: None,
            )

            self.assertEqual(validated, [result.output_pdf_path])
            self.assertEqual(result.pdf_page_count, 1)
            self.assertGreater(result.pdf_size_bytes, 0)

    def test_desktop_archive_copy_creates_root_and_date_folder(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            source = root / "output" / "final.pdf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"%PDF-1.4\narchive")

            copied = copy_pdf_to_desktop_archive(
                source,
                now=datetime(2026, 7, 22, 13, 42, 35),
                desktop_dir=desktop,
            )

            self.assertEqual(
                copied,
                (desktop / RESULTS_FOLDER_NAME / "2026-07-22" / "final.pdf").resolve(),
            )
            self.assertEqual(copied.read_bytes(), source.read_bytes())

    def test_desktop_archive_copy_reuses_existing_folders_for_multiple_pdfs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            archive_day = desktop / RESULTS_FOLDER_NAME / "2026-07-22"
            archive_day.mkdir(parents=True)
            source_one = root / "output" / "one.pdf"
            source_two = root / "output" / "two.pdf"
            source_one.parent.mkdir(parents=True)
            source_one.write_bytes(b"one")
            source_two.write_bytes(b"two")

            copied_one = copy_pdf_to_desktop_archive(source_one, now=datetime(2026, 7, 22), desktop_dir=desktop)
            copied_two = copy_pdf_to_desktop_archive(source_two, now=datetime(2026, 7, 22), desktop_dir=desktop)

            self.assertEqual(copied_one.parent, archive_day.resolve())
            self.assertEqual(copied_two.parent, archive_day.resolve())
            self.assertTrue(copied_one.is_file())
            self.assertTrue(copied_two.is_file())

    def test_desktop_archive_copy_keeps_existing_same_size_destination(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            source = root / "output" / "same.pdf"
            destination = desktop / RESULTS_FOLDER_NAME / "2026-07-22" / "same.pdf"
            source.parent.mkdir(parents=True)
            destination.parent.mkdir(parents=True)
            source.write_bytes(b"same-size")
            destination.write_bytes(b"different")

            with patch("integrations.universal_viewer.pdf_printing.shutil.copy2", side_effect=AssertionError("same-size destination should not be copied")):
                copied = copy_pdf_to_desktop_archive(source, now=datetime(2026, 7, 22), desktop_dir=desktop)

            self.assertEqual(copied, destination.resolve())
            self.assertEqual(destination.read_bytes(), b"different")

    def test_desktop_archive_copy_uses_copy_suffix_for_different_size_collision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            source = root / "output" / "collision.pdf"
            archive_day = desktop / RESULTS_FOLDER_NAME / "2026-07-22"
            destination = archive_day / "collision.pdf"
            copy2_destination = archive_day / "collision_copy2.pdf"
            source.parent.mkdir(parents=True)
            archive_day.mkdir(parents=True)
            source.write_bytes(b"new-content")
            destination.write_bytes(b"old")
            copy2_destination.write_bytes(b"occupied")

            copied = copy_pdf_to_desktop_archive(source, now=datetime(2026, 7, 22), desktop_dir=desktop)

            self.assertEqual(copied, (archive_day / "collision_copy3.pdf").resolve())
            self.assertEqual(copied.read_bytes(), source.read_bytes())
            self.assertEqual(destination.read_bytes(), b"old")

    def test_desktop_archive_copy_is_not_attempted_before_pdf_exists(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "Desktop"
            missing = root / "output" / "missing.pdf"

            with patch("integrations.universal_viewer.pdf_printing.shutil.copy2") as copy2:
                with self.assertRaisesRegex(PdfPrintingError, "source PDF does not exist"):
                    copy_pdf_to_desktop_archive(missing, now=datetime(2026, 7, 22), desktop_dir=desktop)

            copy2.assert_not_called()
            self.assertFalse((desktop / RESULTS_FOLDER_NAME).exists())

    def test_successful_print_flow_copies_verified_pdf_to_archive_after_validation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            opened = self._opened(root)
            events: list[str] = []
            copied_paths: list[Path] = []

            def fake_validate(path: Path, _logger: logging.Logger) -> int:
                events.append("validate")
                self.assertTrue(path.is_file())
                return 1

            def fake_archive_copy(path: Path) -> Path:
                events.append("archive")
                self.assertTrue(path.is_file())
                copied_paths.append(path)
                return root / "Desktop" / RESULTS_FOLDER_NAME / "2026-07-22" / path.name

            result = print_raw_file_to_pdf(
                opened.source_path,
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                print_automation_fn=lambda _opened, path, _logger: path.write_bytes(b"%PDF-1.4\n"),
                pdf_validation_fn=fake_validate,
                archive_copy_fn=fake_archive_copy,
            )

            self.assertEqual(events, ["validate", "archive"])
            self.assertEqual(copied_paths, [result.output_pdf_path])
            self.assertEqual(
                result.desktop_archive_pdf_path,
                root / "Desktop" / RESULTS_FOLDER_NAME / "2026-07-22" / result.output_pdf_path.name,
            )
            self.assertEqual(result.desktop_archive_warning, "")

    def test_win32_fallback_finds_korean_print_dialog_with_matching_pid(self) -> None:
        windows = {
            6688118: Win32DialogInfo(6688118, "인쇄", "#32770", 22628, True, True),
            855552: Win32DialogInfo(855552, "Universal Viewer", "Universal_Viewer R3.18.02", 22628, True, False),
        }

        found = find_win32_dialog_info(
            ("Print", "인쇄"),
            22628,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertEqual(found, windows[6688118])

    def test_win32_fallback_ignores_invisible_or_disabled_dialogs(self) -> None:
        windows = {
            1: Win32DialogInfo(1, "인쇄", "#32770", 22628, False, True),
            2: Win32DialogInfo(2, "인쇄", "#32770", 22628, True, False),
        }

        found = find_win32_dialog_info(
            ("Print", "인쇄"),
            22628,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertIsNone(found)

    def test_win32_fallback_ignores_dialogs_from_unrelated_pids(self) -> None:
        windows = {
            1: Win32DialogInfo(1, "인쇄", "#32770", 99999, True, True),
        }

        found = find_win32_dialog_info(
            ("Print", "인쇄"),
            22628,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertIsNone(found)

    def test_wait_for_dialog_raises_clear_error_when_win32_fallback_has_no_match(self) -> None:
        with self.assertRaisesRegex(PdfPrintingError, "인쇄 대화상자.*찾지 못했습니다"):
            wait_for_dialog(
                FakeDesktop(),
                ("Print", "인쇄"),
                timeout_seconds=0,
                diagnostic_label="인쇄 대화상자",
                owner_pid=22628,
                logger=self.logger,
                win32_dialog_finder=lambda _titles, _pid: None,
            )

    def test_win32_fallback_detects_korean_save_dialog_title(self) -> None:
        windows = {
            25758768: Win32DialogInfo(
                25758768,
                "다음 이름으로 프린터 출력 저장",
                "#32770",
                23600,
                True,
                True,
            ),
        }

        found = find_win32_dialog_info(
            SAVE_DIALOG_TITLES,
            23600,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertEqual(found, windows[25758768])

    def test_win32_fallback_detects_partial_printer_output_save_title(self) -> None:
        windows = {
            1: Win32DialogInfo(1, "테스트 프린터 출력 저장 창", "#32770", 23600, True, True),
        }

        found = find_win32_dialog_info(
            SAVE_DIALOG_TITLES,
            23600,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertEqual(found, windows[1])

    def test_win32_save_dialog_ignores_disabled_progress_dialog(self) -> None:
        windows = {
            1: Win32DialogInfo(1, "Universal Viewer", "#32770", 23600, True, False),
            2: Win32DialogInfo(2, "다음 이름으로 프린터 출력 저장", "#32770", 23600, True, True),
        }

        found = find_win32_dialog_info(
            SAVE_DIALOG_TITLES,
            23600,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertEqual(found, windows[2])

    def test_win32_save_dialog_ignores_unrelated_pid(self) -> None:
        windows = {
            1: Win32DialogInfo(1, "다음 이름으로 프린터 출력 저장", "#32770", 99999, True, True),
        }

        found = find_win32_dialog_info(
            SAVE_DIALOG_TITLES,
            23600,
            enum_windows_fn=lambda: windows.keys(),
            read_window_info_fn=lambda hwnd: windows[hwnd],
        )

        self.assertIsNone(found)

    def test_find_filename_edit_child_uses_visible_enabled_edit(self) -> None:
        children = {
            1: Win32ChildControlInfo(1, "", "Edit", 23600, False, True),
            920082: Win32ChildControlInfo(920082, "", "Edit", 23600, True, True),
            3: Win32ChildControlInfo(3, "저장(&S)", "Button", 23600, True, True),
        }

        found = find_filename_edit_child_info(
            25758768,
            enum_children_fn=lambda _parent: children.keys(),
            read_child_info_fn=lambda hwnd: children[hwnd],
        )

        self.assertEqual(found, children[920082])

    def test_find_save_button_child_accepts_korean_save_button_with_accelerator(self) -> None:
        children = {
            1: Win32ChildControlInfo(1, "취소", "Button", 23600, True, True),
            23923034: Win32ChildControlInfo(23923034, "저장(&S)", "Button", 23600, True, True),
        }

        found = find_save_button_child_info(
            25758768,
            enum_children_fn=lambda _parent: children.keys(),
            read_child_info_fn=lambda hwnd: children[hwnd],
        )

        self.assertEqual(found, children[23923034])

    def test_filename_edit_receives_full_absolute_target_pdf_path(self) -> None:
        with TemporaryDirectory() as directory:
            target = (Path(directory) / "output" / "stage4 test.pdf").resolve()
            entered: list[str] = []

            def fake_set(_hwnd: int, text: str) -> None:
                entered.append(text)

            with patch("integrations.universal_viewer.pdf_printing.set_win32_edit_text", fake_set), patch(
                "integrations.universal_viewer.pdf_printing.get_win32_text", lambda _hwnd: entered[-1]
            ):
                result = enter_and_verify_filename(1234, target, self.logger)

            self.assertEqual(entered, [str(target)])
            self.assertEqual(result.text, str(target))
            self.assertTrue(result.verified)

    def test_wm_settext_is_attempted_without_setfocus(self) -> None:
        calls: list[tuple[str, int, object]] = []
        texts: dict[int, str] = {}

        class FakeWin32Gui:
            @staticmethod
            def SetFocus(_hwnd: int) -> None:
                raise AssertionError("SetFocus should not be called")

            @staticmethod
            def SendMessage(hwnd: int, message: int, _wparam: int, lparam: object) -> None:
                calls.append(("SendMessage", message, lparam))
                if message == 0x000C:
                    texts[hwnd] = str(lparam)

            @staticmethod
            def GetWindowText(hwnd: int) -> str:
                return texts.get(hwnd, "")

        fake_win32con = types.SimpleNamespace(WM_SETTEXT=0x000C)
        with patch.dict(sys.modules, {"win32gui": FakeWin32Gui, "win32con": fake_win32con}):
            set_win32_edit_text(1234, "C:\\out\\file.pdf")

        self.assertEqual(texts[1234], "C:\\out\\file.pdf")
        self.assertEqual(calls, [("SendMessage", 0x000C, "C:\\out\\file.pdf")])

    def test_setfocus_access_denied_does_not_fail_if_wm_settext_verifies(self) -> None:
        texts: dict[int, str] = {}

        class FakeWin32Gui:
            @staticmethod
            def SetFocus(_hwnd: int) -> None:
                raise OSError("access denied")

            @staticmethod
            def SendMessage(hwnd: int, message: int, _wparam: int, lparam: object) -> None:
                if message == 0x000C:
                    texts[hwnd] = str(lparam)

            @staticmethod
            def GetWindowText(hwnd: int) -> str:
                return texts.get(hwnd, "")

        fake_win32con = types.SimpleNamespace(WM_SETTEXT=0x000C)
        with TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"win32gui": FakeWin32Gui, "win32con": fake_win32con}
        ):
            target = (Path(directory) / "output" / "stage4 test.pdf").resolve()
            result = enter_and_verify_filename(1234, target, self.logger)

        self.assertEqual(result.text, str(target))
        self.assertTrue(result.verified)

    def test_filename_entry_verification_failure_raises_clear_error(self) -> None:
        with TemporaryDirectory() as directory:
            target = (Path(directory) / "output" / "stage4 test.pdf").resolve()

            with patch("integrations.universal_viewer.pdf_printing.set_win32_edit_text", lambda _hwnd, _text: None), patch(
                "integrations.universal_viewer.pdf_printing.paste_text_with_clipboard", lambda _hwnd, _text, **_kwargs: None
            ), patch("integrations.universal_viewer.pdf_printing.get_win32_text", lambda _hwnd: "wrong.pdf"):
                with self.assertRaisesRegex(PdfPrintingError, "expected=.*stage4 test.pdf.*current=wrong.pdf"):
                    enter_and_verify_filename(1234, target, self.logger, strict_verification=True)

    def test_save_button_click_is_called_after_filename_verification(self) -> None:
        clicked: list[int] = []
        dialog = FakeDialog(handle=25758768)
        edit = Win32ChildControlInfo(920082, "", "Edit", 23600, True, True)
        button = Win32ChildControlInfo(23923034, "저장(&S)", "Button", 23600, True, True)

        with TemporaryDirectory() as directory, patch(
            "integrations.universal_viewer.pdf_printing.find_filename_edit_child_info", lambda _hwnd: edit
        ), patch(
            "integrations.universal_viewer.pdf_printing.enter_and_verify_filename",
            lambda _hwnd, path, _logger, **_kwargs: FilenameEntryResult(str(path), True, False),
        ), patch(
            "integrations.universal_viewer.pdf_printing.find_save_button_child_info", lambda _hwnd: button
        ), patch(
            "integrations.universal_viewer.pdf_printing.click_win32_button", lambda hwnd: clicked.append(hwnd)
        ), patch(
            "integrations.universal_viewer.pdf_printing.handle_overwrite_confirmation", lambda *_args, **_kwargs: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.wait_for_save_dialog_to_close_or_pdf", lambda *_args, **_kwargs: None
        ):
            enter_save_path_and_confirm(dialog, Path(directory) / "output.pdf", self.logger)

        self.assertEqual(clicked, [23923034])

    def test_unreadable_text_after_clipboard_paste_proceeds_to_save_click(self) -> None:
        clicked: list[int] = []
        dialog = FakeDialog(handle=25758768)
        edit = Win32ChildControlInfo(920082, "", "Edit", 23600, True, True)
        button = Win32ChildControlInfo(23923034, "저장(&S)", "Button", 23600, True, True)

        with TemporaryDirectory() as directory, patch(
            "integrations.universal_viewer.pdf_printing.find_filename_edit_child_info", lambda _hwnd: edit
        ), patch(
            "integrations.universal_viewer.pdf_printing.set_win32_edit_text", lambda _hwnd, _text: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.find_parent_combobox", lambda _hwnd: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.try_pywinauto_set_edit_text", lambda _hwnd, _text: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.paste_text_with_clipboard", lambda _hwnd, _text, **_kwargs: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.get_win32_text", lambda _hwnd: ""
        ), patch(
            "integrations.universal_viewer.pdf_printing.find_save_button_child_info", lambda _hwnd: button
        ), patch(
            "integrations.universal_viewer.pdf_printing.can_proceed_after_unreadable_filename", lambda _entry, _dialog_hwnd, _button: True
        ), patch(
            "integrations.universal_viewer.pdf_printing.click_save_button", lambda button, _dialog, _logger: clicked.append(button.hwnd) or "BM_CLICK"
        ), patch(
            "integrations.universal_viewer.pdf_printing.handle_overwrite_confirmation", lambda *_args, **_kwargs: None
        ), patch(
            "integrations.universal_viewer.pdf_printing.wait_for_save_dialog_to_close_or_pdf", lambda *_args, **_kwargs: None
        ):
            result = enter_save_path_and_confirm(dialog, Path(directory) / "output.pdf", self.logger)

        self.assertEqual(clicked, [23923034])
        self.assertFalse(result.entered_text)
        self.assertEqual(result.click_method, "BM_CLICK")

    def test_if_pdf_not_created_after_save_error_includes_diagnostics(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "missing.pdf"
            with patch(
                "integrations.universal_viewer.pdf_printing.collect_pdf_wait_diagnostics",
                lambda path, **_kwargs: f"expected_pdf_path={path}; save_dialog_visible=true; visible_windows=('dialog',)",
            ):
                with self.assertRaisesRegex(PdfPrintingError, "expected_pdf_path=.*missing.pdf.*visible_windows"):
                    from integrations.universal_viewer.pdf_printing import wait_for_pdf_created

                    wait_for_pdf_created(target, timeout_seconds=0, poll_interval_seconds=0)

    def test_save_button_click_is_not_called_when_filename_verification_fails(self) -> None:
        clicked: list[int] = []
        dialog = FakeDialog(handle=25758768)
        edit = Win32ChildControlInfo(920082, "", "Edit", 23600, True, True)
        button = Win32ChildControlInfo(23923034, "저장(&S)", "Button", 23600, True, True)

        with TemporaryDirectory() as directory, patch(
            "integrations.universal_viewer.pdf_printing.find_filename_edit_child_info", lambda _hwnd: edit
        ), patch(
            "integrations.universal_viewer.pdf_printing.enter_and_verify_filename",
            side_effect=PdfPrintingError("PDF 저장 경로 입력 검증 실패: expected=x, current=y"),
        ), patch(
            "integrations.universal_viewer.pdf_printing.find_save_button_child_info", lambda _hwnd: button
        ), patch(
            "integrations.universal_viewer.pdf_printing.click_win32_button", lambda hwnd: clicked.append(hwnd)
        ):
            with self.assertRaisesRegex(PdfPrintingError, "입력 검증 실패"):
                enter_save_path_and_confirm(dialog, Path(directory) / "output.pdf", self.logger)

        self.assertEqual(clicked, [])

    def test_timeout_diagnostics_include_visible_windows_and_save_dialog_visibility(self) -> None:
        confirm = Win32DialogInfo(1, "저장 확인", "#32770", 23600, True, True)

        with patch("integrations.universal_viewer.pdf_printing._is_save_dialog_visible", lambda _pid, _hwnd: True), patch(
            "integrations.universal_viewer.pdf_printing.find_win32_dialog_info", lambda _titles, _pid: confirm
        ), patch(
            "integrations.universal_viewer.pdf_printing.describe_visible_top_level_windows",
            lambda owner_pid=None: ("HWND=1|title=저장 확인|class=#32770|pid=23600|enabled=1",),
        ), patch(
            "integrations.universal_viewer.pdf_printing.get_win32_text_or_none", lambda _hwnd: "C:\\out\\stage4.pdf"
        ):
            diagnostics = collect_pdf_wait_diagnostics(
                Path("missing.pdf"), owner_pid=23600, save_dialog_hwnd=2, filename_edit_hwnd=3
            )

        self.assertIn("save_dialog_visible=true", diagnostics)
        self.assertIn("current_edit_text=C:\\out\\stage4.pdf", diagnostics)
        self.assertIn("confirm_or_error_dialog=HWND=1|title=저장 확인", diagnostics)
        self.assertIn("visible_windows=('HWND=1|title=저장 확인", diagnostics)

    def test_overwrite_confirmation_is_only_accepted_for_explicit_output(self) -> None:
        dialog = Win32DialogInfo(10, "저장 확인", "#32770", 23600, True, True)
        button = Win32ChildControlInfo(11, "예", "Button", 23600, True, True)
        clicked: list[int] = []

        with patch("integrations.universal_viewer.pdf_printing.find_win32_dialog_info", lambda _titles, _pid: dialog), patch(
            "integrations.universal_viewer.pdf_printing.find_confirmation_button_child_info", lambda _hwnd: button
        ), patch("integrations.universal_viewer.pdf_printing.click_win32_button", lambda hwnd: clicked.append(hwnd)):
            with self.assertRaisesRegex(PdfPrintingError, "덮어쓰기 확인"):
                handle_overwrite_confirmation(23600, False, self.logger)
            self.assertEqual(clicked, [])
            handle_overwrite_confirmation(23600, True, self.logger)

        self.assertEqual(clicked, [11])


if __name__ == "__main__":
    unittest.main()
