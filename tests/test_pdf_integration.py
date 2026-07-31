from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pdf_converter import accept_universal_viewer_save_prompt, convert_raw_to_pdf
from integrations.universal_viewer.viewer_discovery import WindowInfo
from test_models import ElectricalMode, TestCondition, TestPlan
from test_runner import format_ampere_filename_suffix, TestRunner


class FakeStopEvent:
    def is_set(self):
        return False

    def wait(self, _seconds):
        return False


class FakeRecorder:
    def __init__(self, raw_path, *, use_local_filename_stem=False):
        self.raw_path = raw_path
        self.use_local_filename_stem = use_local_filename_stem
        self.downloaded_stems = []

    def snapshot_recording_files(self):
        return {"previous.DAE"}

    def recording_start(self):
        pass

    def recording_stop(self):
        pass

    def get_temperature_values(self, _first, _last):
        return {"0001": 25.0}

    def download_recording_file(self, _folder, previous_files, local_filename_stem):
        assert previous_files == {"previous.DAE"}
        self.downloaded_stems.append(local_filename_stem)
        local_path = self.raw_path
        if self.use_local_filename_stem and local_filename_stem:
            local_path = self.raw_path.with_name(
                f"{local_filename_stem}{self.raw_path.suffix}"
            )
        return "result.DAE", local_path, 123


class FakePowerMeter:
    def __init__(self, current):
        self.current = current
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def read_voltage(self):
        return "9.005E+01"

    def read_current(self):
        return self.current

    def read_power(self):
        return "1.627E+01"

    def read_frequency(self):
        return "6.000E+01"


class FakeDialogWrapper:
    def __init__(
        self,
        text,
        class_name,
        pid,
        *,
        children=(),
        clicks=None,
    ):
        self.text = text
        self.class_name_value = class_name
        self.pid = pid
        self.children = tuple(children)
        self.clicks = clicks if clicks is not None else []

    def window_text(self):
        return self.text

    def class_name(self):
        return self.class_name_value

    def process_id(self):
        return self.pid

    def descendants(self):
        return self.children

    def click_input(self):
        self.clicks.append(self.text)


class FakeDesktop:
    def __init__(self, windows):
        self._windows = tuple(windows)

    def windows(self):
        return self._windows


class PdfIntegrationTests(TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

    def test_converter_runs_complete_manual_pdf_workflow(self):
        raw_path = Path(self.temp_directory.name) / "result.DAE"
        raw_path.write_bytes(b"raw")
        events = []
        pdf_result = SimpleNamespace(
            output_pdf_path=raw_path.with_suffix(".pdf"),
            pdf_size_bytes=456,
        )
        workflow_result = SimpleNamespace(pdf_result=pdf_result)

        with patch(
            "pdf_converter.run_manual_pdf_workflow",
            side_effect=lambda *_args, **_kwargs: events.append("workflow") or workflow_result,
        ) as run_workflow:
            with patch(
                "pdf_converter.close_universal_viewer_instances",
                side_effect=lambda *_args, **kwargs: events.append(f"close:{kwargs['reason']}"),
            ) as close_viewer:
                result = convert_raw_to_pdf(raw_path, lambda _message: None)

        self.assertIs(result, pdf_result)
        self.assertEqual(
            events,
            [
                "close:before opening next raw data",
                "workflow",
                "close:after PDF workflow",
            ],
        )
        self.assertEqual(close_viewer.call_count, 2)
        run_workflow.assert_called_once()
        args, kwargs = run_workflow.call_args
        self.assertEqual(args[0], raw_path.resolve())
        self.assertEqual(kwargs["explicit_output_pdf"], raw_path.with_suffix(".pdf").resolve())

    def test_converter_appends_current_suffix_to_pdf_filename(self):
        raw_path = Path(self.temp_directory.name) / "result.DAE"
        raw_path.write_bytes(b"raw")
        pdf_result = SimpleNamespace(
            output_pdf_path=raw_path.with_name("result_0.346A.pdf"),
            pdf_size_bytes=456,
        )
        workflow_result = SimpleNamespace(pdf_result=pdf_result)

        with patch(
            "pdf_converter.run_manual_pdf_workflow",
            return_value=workflow_result,
        ) as run_workflow:
            result = convert_raw_to_pdf(
                raw_path,
                lambda _message: None,
                pdf_filename_suffix="_0.346A",
            )

        self.assertIs(result, pdf_result)
        workflow_kwargs = run_workflow.call_args.kwargs
        self.assertEqual(
            workflow_kwargs["explicit_output_pdf"],
            raw_path.with_name("result_0.346A.pdf").resolve(),
        )

    def test_ampere_filename_suffix_formats_pm_a_value(self):
        self.assertEqual(format_ampere_filename_suffix("3.4614E-01"), "_0.346A")
        self.assertEqual(format_ampere_filename_suffix("1.2000E+00"), "_1.2A")
        self.assertEqual(format_ampere_filename_suffix("2.000"), "_2A")
        self.assertEqual(format_ampere_filename_suffix("-4.000E-04"), "_0A")
        self.assertEqual(format_ampere_filename_suffix(""), "")
        self.assertEqual(format_ampere_filename_suffix("N/A"), "")

    def test_save_changes_prompt_is_accepted_when_universal_viewer_closes(self):
        clicks = []
        yes_button = FakeDialogWrapper("예(&Y)", "Button", 1111, clicks=clicks)
        prompt = FakeDialogWrapper(
            "Universal Viewer",
            "#32770",
            1111,
            children=(
                FakeDialogWrapper("변경사항을 저장하시겠습니까?", "Static", 1111),
                yes_button,
                FakeDialogWrapper("아니오(&N)", "Button", 1111),
            ),
        )
        viewer_window = WindowInfo(
            title="Universal Viewer",
            pid=1111,
            window_class="Universal_Viewer R3.12.01",
            backend="win32",
            handle=100,
            main_window=True,
        )

        accepted = accept_universal_viewer_save_prompt(
            viewer_window,
            SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
            desktop_factory=lambda _backend: FakeDesktop((prompt,)),
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(accepted)
        self.assertEqual(clicks, ["예(&Y)"])

    def test_downloaded_recorder_file_is_converted_to_pdf(self):
        raw_path = Path("result.DAE")
        calls = []
        logs = []

        def convert(path, log_callback, *, pdf_filename_suffix=""):
            calls.append((path, log_callback, pdf_filename_suffix))
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

        self.assertEqual(calls, [(raw_path, logs.append, "")])
        self.assertTrue(any("PDF saved: result.pdf (456 bytes)" in line for line in logs))

    def test_downloaded_raw_and_pdf_filenames_use_pm_a_value(self):
        raw_path = Path("result.DAE")
        calls = []
        logs = []
        power_meter = FakePowerMeter("3.4614E-01")
        recorder = FakeRecorder(raw_path, use_local_filename_stem=True)

        def convert(path, log_callback, *, pdf_filename_suffix=""):
            calls.append((path, log_callback, pdf_filename_suffix))
            return SimpleNamespace(
                output_pdf_path=path.with_suffix(".pdf"),
                pdf_size_bytes=456,
            )

        runner = TestRunner(
            recorder=recorder,
            power_meter=power_meter,
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

        self.assertTrue(power_meter.initialized)
        self.assertEqual(len(recorder.downloaded_stems), 1)
        self.assertTrue(recorder.downloaded_stems[0].endswith("_0.346A"))
        self.assertEqual(calls, [(raw_path.with_name(f"{recorder.downloaded_stems[0]}.DAE"), logs.append, "")])
        self.assertTrue(any("_0.346A.pdf (456 bytes)" in line for line in logs))

    def test_pdf_failure_does_not_fail_recorder_download(self):
        raw_path = Path("result.GEV")
        logs = []

        def fail_conversion(_path, _log_callback, *, pdf_filename_suffix=""):
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
