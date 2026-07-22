"""최종 수동 PDF workflow 연결 테스트."""

from __future__ import annotations

import logging
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.cursor_value import ABCursorAdjustmentAttempt, ABCursorAdjustmentResult, CursorValueError, CursorValueWindow
from integrations.universal_viewer.file_manager import RawDataValidationError
from integrations.universal_viewer.manual_pdf_workflow import ManualPdfWorkflowError, run_manual_pdf_workflow
from integrations.universal_viewer.pdf_printing import PrintToPdfResult
from integrations.universal_viewer.viewer_discovery import WindowInfo
from integrations.universal_viewer.viewer_launcher import ViewerOpenResult
from integrations.universal_viewer.main import build_parser, main


class ManualPdfWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"manual-pdf-workflow-test-{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def _config(self) -> AppConfig:
        root = Path(tempfile.mkdtemp())
        return AppConfig(project_root=root)

    def _opened(self, config: AppConfig) -> ViewerOpenResult:
        source = config.input_dir / "sample.DAE"
        work_copy = config.work_dir / "sample_DAE.DAE"
        planned_pdf = config.output_dir / "sample_DAE.pdf"
        return ViewerOpenResult(
            source_path=source,
            work_copy_path=work_copy,
            viewer_exe_path=Path("UnivViewer.exe"),
            planned_pdf_path=planned_pdf,
            process_id=1111,
            main_window=WindowInfo(
                title="Universal Viewer",
                pid=1111,
                window_class="Universal_Viewer R3.12.01",
                backend="win32",
                handle=200,
                main_window=True,
            ),
            raw_file_hints=("sample_DAE.DAE",),
            hint_verified=True,
            matched_raw_file_hints=("sample_DAE.DAE",),
            warning_message="",
        )

    def _ab_success(self) -> ABCursorAdjustmentResult:
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
        return ABCursorAdjustmentResult(True, (attempt,), attempt, "success")

    def _ab_failure(self) -> ABCursorAdjustmentResult:
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
        return ABCursorAdjustmentResult(False, (attempt,), attempt, "not adjusted")

    def test_cli_option_is_registered(self) -> None:
        args = build_parser().parse_args(["sample.DAE", "--run-manual-pdf-workflow"])
        help_text = build_parser().format_help()

        self.assertTrue(args.run_manual_pdf_workflow)
        self.assertIn("--run-manual-pdf-workflow", help_text)

    def test_cli_requires_one_raw_file(self) -> None:
        stderr = StringIO()

        with patch("integrations.universal_viewer.main.run_manual_pdf_workflow") as runner:
            with redirect_stderr(stderr):
                exit_code = main(["--run-manual-pdf-workflow"])

        self.assertEqual(exit_code, 1)
        runner.assert_not_called()
        self.assertIn("1", stderr.getvalue())

    def test_cli_rejects_unsupported_extension(self) -> None:
        stderr = StringIO()

        with patch("integrations.universal_viewer.main.resolve_input_files", side_effect=RawDataValidationError("unsupported")):
            with patch("integrations.universal_viewer.main.run_manual_pdf_workflow") as runner:
                with redirect_stderr(stderr):
                    exit_code = main(["sample.txt", "--run-manual-pdf-workflow"])

        self.assertEqual(exit_code, 1)
        runner.assert_not_called()
        self.assertIn("unsupported", stderr.getvalue())

    def test_workflow_runs_steps_in_required_order_and_reuses_stage4_print(self) -> None:
        config = self._config()
        opened = self._opened(config)
        events: list[str] = []
        pdf_result = PrintToPdfResult(
            opened=opened,
            output_pdf_path=config.output_dir / "final.pdf",
            pdf_size_bytes=1234,
            pdf_page_count=1,
            validation_warning="",
        )

        def open_raw(*_args: object, **_kwargs: object) -> ViewerOpenResult:
            events.append("open raw work copy")
            return opened

        def time_axis(*_args: object, **_kwargs: object) -> None:
            events.append("time axis full display")

        def normalize_viewer(*_args: object, **_kwargs: object) -> None:
            events.append("normalize viewer")

        def display_group(*_args: object, **_kwargs: object) -> object:
            events.append("display group setup")
            return SimpleNamespace(opened=opened)

        def cursor_window(_logger: logging.Logger) -> CursorValueWindow:
            events.append("cursor value window")
            return CursorValueWindow(100, "커서값", "#32770", 1111, (400, 200, 700, 500), True, True)

        def adjust(_logger: logging.Logger) -> ABCursorAdjustmentResult:
            events.append("ab adjust")
            return self._ab_success()

        def move_cursor(_logger: logging.Logger) -> None:
            events.append("move cursor window")

        def focus(_logger: logging.Logger) -> None:
            events.append("focus viewer")

        def print_pdf(*_args: object, **kwargs: object) -> PrintToPdfResult:
            events.append("print pdf")
            reopened = kwargs["open_raw_file_fn"]()
            self.assertIs(reopened, opened)
            return pdf_result

        result = run_manual_pdf_workflow(
            config.input_dir / "sample.DAE",
            config,
            self.logger,
            open_raw_file_fn=open_raw,
            time_axis_fn=time_axis,
            display_group_fn=display_group,
            cursor_window_fn=cursor_window,
            ab_adjustment_fn=adjust,
            move_cursor_window_fn=move_cursor,
            focus_viewer_fn=focus,
            print_pdf_fn=print_pdf,
            normalize_viewer_window_fn=normalize_viewer,
        )

        self.assertEqual(
            events,
            [
                "open raw work copy",
                "normalize viewer",
                "time axis full display",
                "display group setup",
                "cursor value window",
                "ab adjust",
                "move cursor window",
                "focus viewer",
                "print pdf",
            ],
        )
        self.assertEqual(result.pdf_result.pdf_size_bytes, 1234)
        self.assertEqual(result.absolute_time_difference, "00:29:55.000")

    def test_workflow_opens_cursor_value_window_after_display_group_before_ab_adjustment(self) -> None:
        config = self._config()
        opened = self._opened(config)
        events: list[str] = []
        pdf_result = PrintToPdfResult(opened, config.output_dir / "final.pdf", 1234, 1, "")

        run_manual_pdf_workflow(
            config.input_dir / "sample.GEV",
            config,
            self.logger,
            open_raw_file_fn=lambda *_args, **_kwargs: events.append("open raw") or opened,
            time_axis_fn=lambda *_args, **_kwargs: events.append("time axis"),
            display_group_fn=lambda *_args, **_kwargs: events.append("display group max 48") or SimpleNamespace(opened=opened),
            cursor_window_fn=lambda _logger: events.append("open cursor value window") or CursorValueWindow(100, "커서값", "#32770", 1111, (0, 0, 1, 1), True, True),
            ab_adjustment_fn=lambda _logger: events.append("ab adjust") or self._ab_success(),
            move_cursor_window_fn=lambda _logger: events.append("move cursor"),
            focus_viewer_fn=lambda _logger: events.append("focus viewer"),
            print_pdf_fn=lambda *_args, **_kwargs: events.append("print pdf") or pdf_result,
            normalize_viewer_window_fn=lambda *_args, **_kwargs: events.append("normalize viewer"),
        )

        self.assertLess(events.index("normalize viewer"), events.index("time axis"))
        self.assertLess(events.index("time axis"), events.index("display group max 48"))
        self.assertLess(events.index("display group max 48"), events.index("open cursor value window"))
        self.assertLess(events.index("open cursor value window"), events.index("ab adjust"))
        self.assertLess(events.index("ab adjust"), events.index("print pdf"))

    def test_workflow_stops_before_ab_and_pdf_if_cursor_value_window_open_fails(self) -> None:
        config = self._config()
        opened = self._opened(config)
        events: list[str] = []

        def fail_cursor_window(_logger: logging.Logger) -> CursorValueWindow:
            events.append("open cursor value window")
            raise CursorValueError("cursor value window open failed")

        with self.assertRaisesRegex(ManualPdfWorkflowError, "Cursor value window"):
            run_manual_pdf_workflow(
                config.input_dir / "sample.DAE",
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: events.append("open raw") or opened,
                time_axis_fn=lambda *_args, **_kwargs: events.append("time axis"),
                display_group_fn=lambda *_args, **_kwargs: events.append("display group max 48") or SimpleNamespace(opened=opened),
                cursor_window_fn=fail_cursor_window,
                ab_adjustment_fn=lambda _logger: events.append("ab adjust") or self._ab_success(),
                print_pdf_fn=lambda *_args, **_kwargs: events.append("print pdf"),
                normalize_viewer_window_fn=lambda *_args, **_kwargs: events.append("normalize viewer"),
            )

        self.assertEqual(events, ["open raw", "normalize viewer", "time axis", "display group max 48", "open cursor value window"])
        self.assertNotIn("ab adjust", events)
        self.assertNotIn("print pdf", events)

    def test_display_group_is_not_called_if_time_axis_fails(self) -> None:
        config = self._config()
        opened = self._opened(config)
        events: list[str] = []

        def fail_time_axis(*_args: object, **_kwargs: object) -> None:
            events.append("time axis")
            raise RuntimeError("time axis failed")

        with self.assertRaisesRegex(ManualPdfWorkflowError, "Time axis"):
            run_manual_pdf_workflow(
                config.input_dir / "sample.DAE",
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: events.append("open") or opened,
                normalize_viewer_window_fn=lambda *_args, **_kwargs: events.append("normalize viewer"),
                time_axis_fn=fail_time_axis,
                display_group_fn=lambda *_args, **_kwargs: events.append("display group"),
            )

        self.assertEqual(events, ["open", "normalize viewer", "time axis"])

    def test_pdf_is_not_printed_if_ab_adjustment_fails(self) -> None:
        config = self._config()
        opened = self._opened(config)
        events: list[str] = []

        with self.assertRaisesRegex(ManualPdfWorkflowError, "A/B"):
            run_manual_pdf_workflow(
                config.input_dir / "sample.DAE",
                config,
                self.logger,
                open_raw_file_fn=lambda *_args, **_kwargs: opened,
                time_axis_fn=lambda *_args, **_kwargs: events.append("time axis"),
                display_group_fn=lambda *_args, **_kwargs: SimpleNamespace(opened=opened),
                cursor_window_fn=lambda _logger: CursorValueWindow(100, "커서값", "#32770", 1111, (0, 0, 1, 1), True, True),
                ab_adjustment_fn=lambda _logger: self._ab_failure(),
                print_pdf_fn=lambda *_args, **_kwargs: events.append("print"),
                normalize_viewer_window_fn=lambda *_args, **_kwargs: events.append("normalize viewer"),
            )

        self.assertNotIn("print", events)

    def test_cli_success_prints_final_summary(self) -> None:
        config = self._config()
        opened = self._opened(config)
        pdf_result = PrintToPdfResult(opened, config.output_dir / "final.pdf", 1234, 1, "")
        workflow_result = SimpleNamespace(
            opened=opened,
            pdf_result=pdf_result,
            absolute_time_difference="00:29:55.000",
            difference_seconds=1795.0,
        )
        stdout = StringIO()

        with patch("integrations.universal_viewer.main.resolve_input_files", return_value=[config.input_dir / "sample.DAE"]):
            with patch("integrations.universal_viewer.main.run_manual_pdf_workflow", return_value=workflow_result):
                with redirect_stdout(stdout):
                    exit_code = main(["sample.DAE", "--run-manual-pdf-workflow", "--output-pdf", ".\\output\\final.pdf"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Manual PDF workflow completed", output)
        self.assertIn("absolute time difference: 00:29:55.000", output)
        self.assertIn("difference seconds: 1795", output)
        self.assertIn("pdf size: 1234", output)


if __name__ == "__main__":
    unittest.main()
