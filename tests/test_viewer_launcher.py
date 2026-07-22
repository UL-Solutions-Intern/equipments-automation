"""Universal Viewer 작업본 열기(Stage 3) 테스트."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.viewer_discovery import WindowInfo
from integrations.universal_viewer.viewer_launcher import (
    ViewerLaunchError,
    discover_viewer_executable,
    launch_viewer_with_file,
    matching_work_copy_hints,
    open_prepared_raw_file,
)


class FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid


class ViewerLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"viewer-launcher-test-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def test_explicit_viewer_exe_path_is_preferred(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit" / "UnivViewer.exe"
            env_exe = root / "env" / "UnivViewer.exe"
            explicit.parent.mkdir()
            env_exe.parent.mkdir()
            explicit.write_bytes(b"exe")
            env_exe.write_bytes(b"exe")

            found = discover_viewer_executable(
                explicit,
                environ={"UNIVERSAL_VIEWER_EXE": str(env_exe)},
                program_files_roots=(),
                which=lambda _name: None,
            )

            self.assertEqual(found, explicit.resolve())

    def test_environment_variable_is_used(self) -> None:
        with TemporaryDirectory() as directory:
            exe = Path(directory) / "UnivViewer.exe"
            exe.write_bytes(b"exe")

            found = discover_viewer_executable(
                environ={"UNIVERSAL_VIEWER_EXE": str(exe)},
                program_files_roots=(),
                which=lambda _name: None,
            )

            self.assertEqual(found, exe.resolve())

    def test_invalid_explicit_viewer_exe_path_raises_clear_error(self) -> None:
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "UnivViewer.exe"

            with self.assertRaisesRegex(ViewerLaunchError, "--viewer-exe"):
                discover_viewer_executable(
                    missing,
                    environ={},
                    program_files_roots=(),
                    which=lambda _name: None,
                )

    def test_program_files_search_can_find_univviewer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "Yokogawa" / "SMARTDAC" / "UnivViewer.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"exe")

            found = discover_viewer_executable(
                environ={},
                program_files_roots=(root,),
                which=lambda _name: None,
            )

            self.assertEqual(found, exe.resolve())

    def test_path_search_via_which_works(self) -> None:
        with TemporaryDirectory() as directory:
            exe = Path(directory) / "UnivViewer.exe"
            exe.write_bytes(b"exe")

            found = discover_viewer_executable(
                environ={},
                program_files_roots=(),
                which=lambda _name: str(exe),
            )

            self.assertEqual(found, exe.resolve())

    def test_missing_executable_raises_helpful_error(self) -> None:
        with self.assertRaisesRegex(ViewerLaunchError, "UNIVERSAL_VIEWER_EXE"):
            discover_viewer_executable(
                environ={},
                program_files_roots=(),
                which=lambda _name: None,
            )

    def test_launch_command_uses_work_copy_path_not_original_input_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            viewer_exe = root / "UnivViewer.exe"
            original = root / "input" / "sample.DAE"
            work_copy = root / "output" / "work" / "sample_DAE.DAE"
            viewer_exe.write_bytes(b"exe")
            original.parent.mkdir()
            work_copy.parent.mkdir(parents=True)
            original.write_bytes(b"original")
            work_copy.write_bytes(b"copy")
            commands: list[list[str]] = []

            launch_viewer_with_file(
                viewer_exe,
                work_copy,
                popen_factory=lambda command: commands.append(list(command)) or FakeProcess(),
            )

            self.assertEqual(commands, [[str(viewer_exe.resolve()), str(work_copy.resolve())]])
            self.assertNotIn(str(original.resolve()), commands[0])

    def test_open_prepared_raw_file_launches_prepared_work_copy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            source = root / "input" / "sample.GEV"
            source.parent.mkdir()
            source.write_bytes(b"raw-data")
            viewer_exe = root / "UnivViewer.exe"
            viewer_exe.write_bytes(b"exe")
            launched: list[tuple[Path, Path]] = []

            def fake_launch(exe_path: Path, raw_path: Path) -> FakeProcess:
                launched.append((exe_path, raw_path))
                return FakeProcess(pid=5555)

            def fake_wait(_logger, _profile, preferred_pid):
                return WindowInfo(
                    "Universal Viewer",
                    preferred_pid,
                    "Universal_Viewer R3.12.01",
                    "win32",
                    handle=100,
                    main_window=True,
                )

            result = open_prepared_raw_file(
                source,
                config,
                self.logger,
                explicit_viewer_exe=viewer_exe,
                discover_executable_fn=lambda explicit: explicit.resolve(),  # type: ignore[union-attr]
                launch_fn=fake_launch,
                wait_for_window_fn=fake_wait,
                hint_collector=lambda _hwnd: ("already_open.DAE", launched[0][1].name),
            )

            self.assertEqual(result.work_copy_path.name, "sample_GEV.GEV")
            self.assertEqual(launched[0][1], result.work_copy_path)
            self.assertNotEqual(launched[0][1], source.resolve())
            self.assertTrue(result.hint_verified)
            self.assertEqual(result.matched_raw_file_hints, ("sample_GEV.GEV",))

    def test_multiple_raw_file_hints_succeed_when_work_copy_hint_is_included(self) -> None:
        work_copy = Path("output/work/sample_DAE.DAE")
        hints = ("old_file.GEV", "이벤트파일-파형[sample_DAE.DAE]", "other.DAE")

        self.assertEqual(matching_work_copy_hints(hints, work_copy), ("이벤트파일-파형[sample_DAE.DAE]",))

    def test_open_prepared_raw_file_logs_stage3_specific_preparation_message(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = AppConfig(project_root=root)
            source = root / "input" / "sample.DAE"
            source.parent.mkdir()
            source.write_bytes(b"raw-data")
            viewer_exe = root / "UnivViewer.exe"
            viewer_exe.write_bytes(b"exe")
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            self.logger.addHandler(handler)

            launched: list[tuple[Path, Path]] = []

            def fake_launch(exe_path: Path, raw_path: Path) -> FakeProcess:
                launched.append((exe_path, raw_path))
                return FakeProcess(pid=1111)

            result = open_prepared_raw_file(
                source,
                config,
                self.logger,
                explicit_viewer_exe=viewer_exe,
                discover_executable_fn=lambda explicit: explicit.resolve(),  # type: ignore[union-attr]
                launch_fn=fake_launch,
                wait_for_window_fn=lambda _logger, _profile, _pid: WindowInfo(
                    "Universal Viewer",
                    2222,
                    "Universal_Viewer R3.12.01",
                    "win32",
                    handle=100,
                    main_window=True,
                ),
                hint_collector=lambda _hwnd: (launched[0][1].name,),
            )

            logs = stream.getvalue()
            self.assertTrue(result.hint_verified)
            self.assertIn("Universal Viewer로 작업본 열기를 진행합니다", logs)
            self.assertNotIn("Universal Viewer 실행, 마우스/키보드 입력, PDF 출력은 수행하지 않았습니다", logs)
            self.assertIn("실행 프로세스 PID와 탐지된 메인 창 PID가 다릅니다", logs)


if __name__ == "__main__":
    unittest.main()
