"""VS Code Run 버튼용 input 선택 런처 테스트."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from run_from_input import (
    RunFromInputError,
    build_output_pdf_path,
    build_subprocess_command,
    list_supported_raw_files,
    run_launcher,
    select_raw_file,
    verify_file_is_stable,
)


class RunFromInputTests(unittest.TestCase):
    def _write_file(self, path: Path, modified_time: float, text: str = "dummy") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        import os

        os.utime(path, (modified_time, modified_time))

    def test_raw_file_listing_includes_dae_and_gev_and_ignores_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            self._write_file(input_dir / "mv2000.DAE", 100)
            self._write_file(input_dir / "gp20.GEV", 200)
            self._write_file(input_dir / "lowercase.dae", 300)
            self._write_file(input_dir / "ignore.tmp", 400)
            self._write_file(input_dir / "ignore.partial", 500)
            self._write_file(input_dir / "ignore.crdownload", 600)
            self._write_file(input_dir / "almost.DAE~", 700)
            self._write_file(input_dir / "raw.DAE.tmp", 800)
            self._write_file(input_dir / "raw.GEV.partial", 900)
            self._write_file(input_dir / "notes.txt", 1000)

            entries = list_supported_raw_files(input_dir)

        self.assertEqual([entry.path.name for entry in entries], ["lowercase.dae", "gp20.GEV", "mv2000.DAE"])

    def test_raw_file_listing_sorts_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            self._write_file(input_dir / "old.DAE", 100)
            self._write_file(input_dir / "new.GEV", 300)
            self._write_file(input_dir / "middle.DAE", 200)

            entries = list_supported_raw_files(input_dir)

        self.assertEqual([entry.path.name for entry in entries], ["new.GEV", "middle.DAE", "old.DAE"])

    def test_missing_input_folder_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RunFromInputError, "input"):
                list_supported_raw_files(Path(temp_dir) / "input")

    def test_pressing_enter_selects_newest_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            self._write_file(input_dir / "old.DAE", 100)
            self._write_file(input_dir / "new.GEV", 300)
            entries = list_supported_raw_files(input_dir)

            selected = select_raw_file(entries, input_fn=lambda _prompt: "")

        self.assertEqual(selected.name, "new.GEV")

    def test_build_output_pdf_path_under_output_with_manual_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            raw_path = Path(temp_dir) / "input" / "12 Vdc_Normal On the bench.DAE"

            result = build_output_pdf_path(raw_path, output_dir, datetime(2026, 7, 16, 3, 25, 0))

        self.assertEqual(
            result,
            output_dir / "12 Vdc_Normal On the bench_manual_20260716_032500.pdf",
        )

    def test_build_output_pdf_path_avoids_overwriting_existing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()
            raw_path = Path(temp_dir) / "input" / "sample.GEV"
            existing = output_dir / "sample_manual_20260716_032500.pdf"
            existing_1 = output_dir / "sample_manual_20260716_032500_1.pdf"
            existing.write_text("old", encoding="utf-8")
            existing_1.write_text("old", encoding="utf-8")

            result = build_output_pdf_path(raw_path, output_dir, datetime(2026, 7, 16, 3, 25, 0))

        self.assertEqual(result, output_dir / "sample_manual_20260716_032500_2.pdf")

    def test_build_subprocess_command_uses_sys_executable_module_call(self) -> None:
        raw_path = Path("C:/project/input/sample.GEV")
        pdf_path = Path("C:/project/output/sample_manual_20260716_032500.pdf")

        command = build_subprocess_command(raw_path, pdf_path, python_executable="python.exe")

        self.assertEqual(
            command,
            [
                "python.exe",
                "-m",
                "integrations.universal_viewer.main",
                str(raw_path),
                "--run-manual-pdf-workflow",
                "--output-pdf",
                str(pdf_path),
            ],
        )

    def test_verify_file_is_stable_opens_file_for_read_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "input" / "sample.DAE"
            self._write_file(raw_path, 100)
            waits: list[float] = []

            verify_file_is_stable(raw_path, stable_seconds=1.0, poll_seconds=0.5, wait_fn=waits.append)

        self.assertEqual(waits, [0.5, 0.5])

    def test_launcher_calls_existing_workflow_subprocess_with_selected_file_and_generated_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            selected_file = project_root / "input" / "selected.DAE"
            older_file = project_root / "input" / "older.GEV"
            self._write_file(selected_file, 300)
            self._write_file(older_file, 100)
            calls: list[tuple[list[str], Path]] = []
            prompts = iter(("", ""))
            output: list[str] = []

            exit_code = run_launcher(
                project_root=project_root,
                input_fn=lambda _prompt: next(prompts),
                print_fn=output.append,
                workflow_runner=lambda command, cwd: calls.append((list(command), cwd)) or 0,
                now=datetime(2026, 7, 16, 3, 25, 0),
                stable_seconds=0,
                wait_fn=lambda _seconds: None,
            )

        expected_pdf = project_root / "output" / "selected_manual_20260716_032500.pdf"
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        command, cwd = calls[0]
        self.assertEqual(cwd, project_root)
        self.assertEqual(command[1:], ["-m", "integrations.universal_viewer.main", str(selected_file), "--run-manual-pdf-workflow", "--output-pdf", str(expected_pdf)])
        self.assertIn("PDF automation completed.", output)
        self.assertIn(f"PDF path: {expected_pdf}", output)

    def test_launcher_aborts_when_confirmation_is_no(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            self._write_file(project_root / "input" / "sample.DAE", 100)
            calls: list[tuple[list[str], Path]] = []
            prompts = iter(("", "n"))

            exit_code = run_launcher(
                project_root=project_root,
                input_fn=lambda _prompt: next(prompts),
                print_fn=lambda _message: None,
                workflow_runner=lambda command, cwd: calls.append((list(command), cwd)) or 0,
                now=datetime(2026, 7, 16, 3, 25, 0),
                stable_seconds=0,
                wait_fn=lambda _seconds: None,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
