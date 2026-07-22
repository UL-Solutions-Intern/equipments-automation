from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pdf_converter import convert_raw_to_pdf
from test_models import ElectricalMode, TestCondition, TestPlan
from test_runner import TestRunner


class FakeStopEvent:
    def is_set(self):
        return False

    def wait(self, _seconds):
        return False


class FakeRecorder:
    def __init__(self, raw_path):
        self.raw_path = raw_path

    def snapshot_recording_files(self):
        return {"previous.DAE"}

    def recording_start(self):
        pass

    def recording_stop(self):
        pass

    def get_temperature_values(self, _first, _last):
        return {"0001": 25.0}

    def download_recording_file(self, _folder, previous_files):
        assert previous_files == {"previous.DAE"}
        return "result.DAE", self.raw_path, 123


class PdfIntegrationTests(TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

    def test_converter_runs_complete_manual_pdf_workflow(self):
        raw_path = Path(self.temp_directory.name) / "result.DAE"
        raw_path.write_bytes(b"raw")
        pdf_result = SimpleNamespace(
            output_pdf_path=raw_path.with_suffix(".pdf"),
            pdf_size_bytes=456,
        )
        workflow_result = SimpleNamespace(pdf_result=pdf_result)

        with patch(
            "pdf_converter.run_manual_pdf_workflow",
            return_value=workflow_result,
        ) as run_workflow:
            result = convert_raw_to_pdf(raw_path, lambda _message: None)

        self.assertIs(result, pdf_result)
        run_workflow.assert_called_once()
        args, kwargs = run_workflow.call_args
        self.assertEqual(args[0], raw_path.resolve())
        self.assertEqual(kwargs["explicit_output_pdf"], raw_path.with_suffix(".pdf").resolve())

    def test_downloaded_recorder_file_is_converted_to_pdf(self):
        raw_path = Path("result.DAE")
        calls = []
        logs = []

        def convert(path, log_callback):
            calls.append((path, log_callback))
            return SimpleNamespace(
                output_pdf_path=Path("result.pdf"),
                pdf_size_bytes=456,
            )

        runner = TestRunner(
            recorder=FakeRecorder(raw_path),
            output_folder=self.temp_directory.name,
            log_callback=logs.append,
            pdf_converter=convert,
        )
        plan = TestPlan(
            test_name="integration",
            electrical_mode=ElectricalMode.AC,
            conditions=[TestCondition()],
            duration_seconds=0,
            sample_interval_seconds=1,
            cooldown_seconds=0,
            first_channel="0001",
            last_channel="0001",
            temperature_channels=["0001"],
            saturation_enabled=False,
        )

        runner.run(plan, FakeStopEvent())

        self.assertEqual(calls, [(raw_path, logs.append)])
        self.assertTrue(any("PDF saved: result.pdf (456 bytes)" in line for line in logs))

    def test_pdf_failure_does_not_fail_recorder_download(self):
        raw_path = Path("result.GEV")
        logs = []

        def fail_conversion(_path, _log_callback):
            raise RuntimeError("viewer unavailable")

        runner = TestRunner(
            recorder=FakeRecorder(raw_path),
            output_folder=self.temp_directory.name,
            log_callback=logs.append,
            pdf_converter=fail_conversion,
        )
        plan = TestPlan(
            test_name="integration",
            electrical_mode=ElectricalMode.AC,
            conditions=[TestCondition()],
            duration_seconds=0,
            sample_interval_seconds=1,
            cooldown_seconds=0,
            first_channel="0001",
            last_channel="0001",
            temperature_channels=["0001"],
            saturation_enabled=False,
        )

        runner.run(plan, FakeStopEvent())

        self.assertTrue(any("Recorder file saved" in line for line in logs))
        self.assertTrue(any("PDF conversion error: viewer unavailable" in line for line in logs))
