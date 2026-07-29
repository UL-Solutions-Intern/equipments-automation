from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest

from test_models import ElectricalMode, TestCondition, TestPlan
from test_runner import TestRunner


class StopAfterOneOverloadSample:
    def is_set(self):
        return False

    def wait(self, _seconds):
        return True


class FakeRecorder:
    def __init__(self, temperature_samples):
        self.temperature_samples = list(temperature_samples)
        self.downloaded_stems = []
        self.recording_starts = 0
        self.recording_stops = 0

    def snapshot_recording_files(self):
        return set()

    def recording_start(self):
        self.recording_starts += 1

    def recording_stop(self):
        self.recording_stops += 1

    def get_temperature_values(self, _first, _last):
        return self.temperature_samples.pop(0)

    def download_recording_file(self, folder, _previous_files, local_filename_stem):
        self.downloaded_stems.append(local_filename_stem)
        return (
            f"{local_filename_stem}.DAE",
            Path(folder) / f"{local_filename_stem}.DAE",
            100,
        )


class FakeCVCF:
    def __init__(self):
        self.configurations = []
        self.output_on_count = 0
        self.output_off_count = 0

    def configure(self, voltage, frequency, current_limit, output_mode):
        self.configurations.append((voltage, frequency, current_limit, output_mode))

    def output_on(self):
        self.output_on_count += 1

    def output_off(self):
        self.output_off_count += 1


class OverloadWorkflowTests(unittest.TestCase):
    def test_hottest_coil_condition_is_rerun_as_overload_until_stop(self):
        with TemporaryDirectory() as temp_dir:
            recorder = FakeRecorder(
                [
                    {"0004": 30.0},
                    {"0004": 45.0},
                    {"0004": 40.0},
                    {"0004": 46.0},
                ]
            )
            cvcf = FakeCVCF()
            target_labels = []
            logs = []
            runner = TestRunner(
                recorder=recorder,
                cvcf=cvcf,
                output_folder=temp_dir,
                log_callback=logs.append,
                overload_target_callback=target_labels.append,
            )
            plan = TestPlan(
                test_name="Normal",
                electrical_mode=ElectricalMode.AC,
                conditions=[
                    TestCondition(90, 50),
                    TestCondition(120, 60),
                    TestCondition(264, 50),
                ],
                duration_seconds=0,
                sample_interval_seconds=1,
                cooldown_seconds=0,
                first_channel="0004",
                last_channel="0004",
                temperature_channels=["0004"],
                current_limit=11.0,
                saturation_enabled=False,
                overload_enabled=True,
                overload_rest_seconds=0,
                overload_coil_channel="0004",
                overload_coil_display_channel="0004",
            )

            runner.run(plan, StopAfterOneOverloadSample())

            self.assertEqual(target_labels, ["Normal_120V_60Hz"])
            self.assertEqual(
                cvcf.configurations,
                [
                    (90, 50, 11.0, "AC"),
                    (120, 60, 11.0, "AC"),
                    (264, 50, 11.0, "AC"),
                    (120, 60, 11.0, "AC"),
                ],
            )
            self.assertEqual(recorder.recording_starts, 4)
            self.assertEqual(recorder.recording_stops, 4)
            self.assertTrue(any("_OverLoad_" in stem for stem in recorder.downloaded_stems))
            self.assertTrue(
                any("OverLoad는 시간 설정으로 종료하지 않습니다" in line for line in logs)
            )

            overload_csv_paths = list(Path(temp_dir).glob("Normal_OverLoad_*.csv"))
            self.assertEqual(len(overload_csv_paths), 1)
            with overload_csv_paths[0].open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["Test_Name"], "Normal_OverLoad")
            self.assertEqual(rows[0]["Condition"], "OverLoad_Normal_120V_60Hz")


if __name__ == "__main__":
    unittest.main()
