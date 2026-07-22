"""장비 조합과 무관하게 한 가지 흐름으로 시험을 실행한다."""

from collections import deque
import csv
from datetime import datetime
from pathlib import Path
import time

from test_models import (
    ElectricalMode,
    PowerMeasurement,
    TestPlan,
    sanitize_filename,
)


class StabilizationTracker:
    """모든 온도 채널이 30분간 1.5도 미만으로 변했는지 판단한다."""

    def __init__(
        self,
        channels,
        window_seconds=1800,
        max_delta=1.5,
        min_elapsed_seconds=0,
    ):
        self.channels = list(channels)
        self.window_seconds = window_seconds
        self.max_delta = max_delta
        self.min_elapsed_seconds = min_elapsed_seconds
        self.history = {channel: deque() for channel in self.channels}

    def add_sample(self, timestamp: float, temperatures: dict):
        cutoff = timestamp - self.window_seconds
        for channel in self.channels:
            value = temperatures.get(channel)
            if not isinstance(value, (int, float)):
                continue

            history = self.history[channel]
            history.append((timestamp, value))
            # cutoff 직전 값 하나는 비교 기준으로 남긴다.
            while len(history) >= 2 and history[1][0] <= cutoff:
                history.popleft()

    def is_stable(self, now: float, started_at: float) -> bool:
        if not self.channels:
            return False
        if now - started_at < self.min_elapsed_seconds:
            return False

        cutoff = now - self.window_seconds
        for channel in self.channels:
            history = self.history[channel]
            # 현재 샘플에 채널 값이 없으면 과거 값만으로 안정 상태를
            # 판정하지 않는다.
            if not history or history[-1][0] != now or history[0][0] > cutoff:
                return False
            if abs(history[-1][1] - history[0][1]) >= self.max_delta:
                return False
        return True


class TestRunner:
    """Recorder는 필수, CVCF와 Power Meter는 선택적으로 사용하는 실행기."""

    def __init__(
        self,
        recorder,
        cvcf=None,
        power_meter=None,
        output_folder=".",
        log_callback=print,
        pdf_converter=None,
    ):
        self.recorder = recorder
        self.cvcf = cvcf
        self.power_meter = power_meter
        self.output_folder = Path(output_folder)
        self.log = log_callback
        self.pdf_converter = pdf_converter

    def run(self, plan: TestPlan, stop_event):
        csv_file = None
        try:
            if self.power_meter is not None:
                self.power_meter.initialize()

            csv_file, writer, file_path = self._open_result_file(plan)
            self.log(f"CSV 파일 생성 완료: {file_path}")

            total_steps = len(plan.conditions)
            for index, condition in enumerate(plan.conditions, start=1):
                if stop_event.is_set():
                    break

                self.log(f"[{index}/{total_steps}] 조건 {condition.label} 테스트 시작")
                stable = False
                recorder_started = False
                cvcf_output_enabled = False
                recorder_files_before = None

                try:
                    if self.cvcf is not None:
                        if (
                            condition.voltage is not None
                            or condition.frequency is not None
                        ):
                            self.cvcf.configure(
                                condition.voltage,
                                condition.frequency,
                                plan.current_limit,
                                plan.electrical_mode.value,
                            )
                        cvcf_output_enabled = True
                        self.cvcf.output_on()

                    try:
                        recorder_files_before = self.recorder.snapshot_recording_files()
                    except Exception as exc:
                        self.log(f"Recorder FTP 파일 목록 확인 오류: {exc}")

                    recorder_started = True
                    self.recorder.recording_start()

                    saturation_check_seconds = (
                        plan.saturation_check_seconds
                        if plan.saturation_check_seconds is not None
                        else 0
                    )
                    saturation_recheck_seconds = (
                        plan.saturation_recheck_seconds
                        if plan.saturation_recheck_seconds is not None
                        else plan.sample_interval_seconds
                    )

                    tracker = StabilizationTracker(
                        plan.temperature_channels,
                        min_elapsed_seconds=saturation_check_seconds,
                    )
                    started_at = time.monotonic()
                    deadline = started_at + plan.duration_seconds
                    extend_until_saturation = (
                        plan.saturation_enabled
                        and plan.saturation_check_seconds is not None
                    )
                    next_saturation_check_at = (
                        started_at + saturation_check_seconds
                        if extend_until_saturation
                        else started_at
                    )

                    while True:
                        if stop_event.is_set():
                            break
                        sample_started_at = time.monotonic()
                        is_final_sample = sample_started_at >= deadline

                        timestamp = datetime.now()
                        temperatures = self.recorder.get_temperature_values(
                            plan.first_channel,
                            plan.last_channel,
                        )
                        power = self._read_power(plan.electrical_mode)
                        self._write_result(
                            writer,
                            plan,
                            condition,
                            timestamp,
                            temperatures,
                            power,
                        )
                        csv_file.flush()

                        now = time.monotonic()
                        tracker.add_sample(now, temperatures)
                        should_check_saturation = (
                            plan.saturation_enabled
                            and now >= next_saturation_check_at
                        )
                        if should_check_saturation:
                            if tracker.is_stable(now, started_at):
                                self.log(
                                    "[포화] 판정 시점 기준 모든 채널의 30분 전 대비 변화량 < 1.5"
                                )
                                stable = True
                                break
                            next_saturation_check_at = (
                                now + saturation_recheck_seconds
                            )
                            if now - started_at >= saturation_check_seconds:
                                self.log(
                                    f"[포화 미도달] CSV 기록은 계속 유지, {saturation_recheck_seconds:g}초 후 재판정"
                                )

                        self.log(
                            f"[{timestamp:%Y-%m-%d %H:%M:%S}] Temps={temperatures}"
                        )

                        if not extend_until_saturation:
                            if is_final_sample:
                                break

                            wait_seconds = min(
                                plan.sample_interval_seconds,
                                max(0, deadline - time.monotonic()),
                            )
                        else:
                            wait_seconds = plan.sample_interval_seconds
                        if wait_seconds <= 0:
                            continue
                        if stop_event.wait(wait_seconds):
                            break
                finally:
                    if recorder_started:
                        try:
                            self.recorder.recording_stop()
                        except Exception as exc:
                            self.log(f"Recorder 정지 오류: {exc}")
                    if cvcf_output_enabled:
                        try:
                            self.cvcf.output_off()
                        except Exception as exc:
                            self.log(f"CVCF 출력 OFF 오류: {exc}")

                    if recorder_started:
                        try:
                            result = self.recorder.download_recording_file(
                                self.output_folder,
                                recorder_files_before,
                            )
                            if result is not None:
                                remote_name, local_path, size = result
                                self.log(
                                    f"Recorder file saved: {remote_name} -> {local_path} ({size} bytes)"
                                )
                                if self.pdf_converter is not None:
                                    try:
                                        pdf_result = self.pdf_converter(
                                            local_path, self.log
                                        )
                                        self.log(
                                            f"PDF saved: {pdf_result.output_pdf_path} "
                                            f"({pdf_result.pdf_size_bytes} bytes)"
                                        )
                                    except Exception as exc:
                                        self.log(f"PDF conversion error: {exc}")
                        except Exception as exc:
                            self.log(f"Recorder FTP download error: {exc}")

                if stop_event.is_set():
                    break

                if index < total_steps and plan.cooldown_seconds > 0:
                    self.log(f"다음 조건 시작 전 {plan.cooldown_seconds:g}초 대기")
                    if stop_event.wait(plan.cooldown_seconds):
                        break

            self.log("시험 실행 종료")
        except Exception as exc:
            self.log(f"시험 실행 오류: {exc}")
        finally:
            if csv_file is not None:
                csv_file.close()
                self.log("CSV 저장 완료")

    def _read_power(self, electrical_mode):
        if self.power_meter is None:
            return PowerMeasurement()
        return PowerMeasurement(
            voltage=self.power_meter.read_voltage(),
            current=self.power_meter.read_current(),
            power=self.power_meter.read_power(),
            frequency=(
                self.power_meter.read_frequency()
                if electrical_mode == ElectricalMode.AC
                else None
            ),
        )

    def _open_result_file(self, plan):
        self.output_folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = (
            self.output_folder / f"{sanitize_filename(plan.test_name)}_{timestamp}.csv"
        )
        csv_file = file_path.open("w", newline="", encoding="utf-8-sig")
        writer = csv.writer(csv_file)
        writer.writerow(
            ["Time", "Test_Name", "Electrical_Mode", "Condition"]
            + [f"Temp_{channel}" for channel in plan.temperature_channels]
            + ["Supply_V", "Supply_Hz", "PM_V", "PM_A", "PM_P", "PM_Hz"]
        )
        return csv_file, writer, file_path

    @staticmethod
    def _write_result(writer, plan, condition, timestamp, temperatures, power):
        temperature_values = [
            temperatures.get(channel, "") for channel in plan.temperature_channels
        ]
        writer.writerow(
            [
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                plan.test_name,
                plan.electrical_mode.value,
                condition.label,
            ]
            + temperature_values
            + [
                condition.voltage,
                condition.frequency,
                power.voltage,
                power.current,
                power.power,
                power.frequency,
            ]
        )
