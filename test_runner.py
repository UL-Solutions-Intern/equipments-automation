"""장비 조합과 무관하게 한 가지 흐름으로 시험을 실행한다."""

from collections import deque
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time

from test_models import (
    build_overload_target_label,
    build_recording_filename_stem,
    ElectricalMode,
    format_elapsed_time,
    PowerMeasurement,
    TestCondition,
    TestPlan,
    sanitize_filename,
)


@dataclass(frozen=True)
class OverloadCandidate:
    """Normal run sample that produced the highest temperature on the coil channel."""

    condition: TestCondition
    target_label: str
    channel: str
    display_channel: str
    temperature: float
    timestamp: datetime


class StabilizationTracker:
    """모든 온도 채널이 설정된 비교 시간 동안 1.5도 미만으로 변했는지 판단한다."""

    def __init__(
        self,
        channels,
        window_seconds,
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
        overload_target_callback=None,
    ):
        self.recorder = recorder
        self.cvcf = cvcf
        self.power_meter = power_meter
        self.output_folder = Path(output_folder)
        self.log = log_callback
        self.pdf_converter = pdf_converter
        self.overload_target_callback = overload_target_callback

    def run(self, plan: TestPlan, stop_event):
        csv_file = None
        run_started_at = datetime.now()
        total_condition_elapsed_seconds = 0.0
        overload_candidate = None
        try:
            if self.power_meter is not None:
                self.power_meter.initialize()

            csv_file, writer, file_path = self._open_result_file(plan)
            self.log(f"CSV 파일 생성 완료: {file_path}")

            total_steps = len(plan.conditions)
            for index, condition in enumerate(plan.conditions, start=1):
                if stop_event.is_set():
                    break

                condition_elapsed, overload_candidate = self._run_condition(
                    plan,
                    condition,
                    writer,
                    csv_file,
                    stop_event,
                    condition_label=f"[{index}/{total_steps}] 조건 {condition.label}",
                    overload_candidate=overload_candidate,
                    track_overload=True,
                )
                total_condition_elapsed_seconds += condition_elapsed

                if stop_event.is_set():
                    break

                if index < total_steps and plan.cooldown_seconds > 0:
                    self.log(f"다음 조건 시작 전 {plan.cooldown_seconds:g}초 대기")
                    if stop_event.wait(plan.cooldown_seconds):
                        break

            if csv_file is not None:
                csv_file.close()
                csv_file = None
                self.log("CSV 저장 완료")

            if (
                plan.overload_enabled
                and not stop_event.is_set()
                and overload_candidate is not None
            ):
                if plan.overload_rest_seconds > 0:
                    self.log(
                        f"OverLoad 시작 전 {plan.overload_rest_seconds:g}초 대기"
                    )
                    if stop_event.wait(plan.overload_rest_seconds):
                        return

                self._publish_overload_target(overload_candidate.target_label)
                self.log(
                    "OverLoad 대상 시험: "
                    f"{overload_candidate.target_label} "
                    f"(Coil {overload_candidate.display_channel}"
                    f"={overload_candidate.temperature:g}°C)"
                )

                overload_csv_file, overload_writer, overload_file_path = (
                    self._open_result_file(
                        plan,
                        filename_test_name=f"{plan.test_name}_OverLoad",
                    )
                )
                self.log(f"OverLoad CSV 파일 생성 완료: {overload_file_path}")
                try:
                    condition_elapsed, _ = self._run_condition(
                        plan,
                        overload_candidate.condition,
                        overload_writer,
                        overload_csv_file,
                        stop_event,
                        condition_label=(
                            "[OverLoad] "
                            f"{overload_candidate.target_label}"
                        ),
                        is_overload=True,
                        csv_test_name=f"{plan.test_name}_OverLoad",
                        csv_condition_label=(
                            f"OverLoad_{overload_candidate.target_label}"
                        ),
                        recording_test_name=f"{plan.test_name}_OverLoad",
                    )
                    total_condition_elapsed_seconds += condition_elapsed
                finally:
                    overload_csv_file.close()
                    self.log("OverLoad CSV 저장 완료")
            elif plan.overload_enabled and not stop_event.is_set():
                self._publish_overload_target("")
                self.log(
                    "OverLoad 대상 시험을 찾지 못했습니다. "
                    f"Coil 채널 {plan.overload_coil_display_channel or plan.overload_coil_channel}의 "
                    "숫자 온도값이 일반 조건 시험 중 기록되지 않았습니다."
                )

        except Exception as exc:
            self.log(f"시험 실행 오류: {exc}")
        finally:
            if csv_file is not None:
                csv_file.close()
                self.log("CSV 저장 완료")
            run_ended_at = datetime.now()
            self.log(f"시험 시작 시간: {run_started_at:%Y-%m-%d %H:%M:%S}")
            self.log(f"시험 종료 시간: {run_ended_at:%Y-%m-%d %H:%M:%S}")
            self.log(
                f"전체 시험시간: {format_elapsed_time(total_condition_elapsed_seconds)}"
            )
            self.log("시험 실행 종료")

    def _run_condition(
        self,
        plan,
        condition,
        writer,
        csv_file,
        stop_event,
        *,
        condition_label,
        is_overload=False,
        overload_candidate=None,
        track_overload=False,
        csv_test_name=None,
        csv_condition_label=None,
        recording_test_name=None,
    ):
        self.log(f"{condition_label} 테스트 시작")
        recorder_started = False
        cvcf_output_enabled = False
        recorder_files_before = None
        condition_started_at = None

        try:
            if self.cvcf is not None:
                if condition.voltage is not None or condition.frequency is not None:
                    self.cvcf.configure(
                        condition.voltage,
                        condition.frequency,
                        plan.current_limit,
                        plan.electrical_mode.value,
                    )
                cvcf_output_enabled = True
                condition_started_at = time.monotonic()
                self.cvcf.output_on()

            try:
                recorder_files_before = self.recorder.snapshot_recording_files()
            except Exception as exc:
                self.log(f"Recorder FTP 파일 목록 확인 오류: {exc}")

            if condition_started_at is None:
                condition_started_at = time.monotonic()
            recorder_started = True
            self.recorder.recording_start()

            started_at = time.monotonic()
            deadline = started_at + plan.duration_seconds
            extend_until_saturation = (
                not is_overload
                and plan.saturation_enabled
                and plan.saturation_check_seconds is not None
            )
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
                window_seconds=plan.stabilization_window_seconds,
                min_elapsed_seconds=saturation_check_seconds,
            )
            next_saturation_check_at = (
                started_at + saturation_check_seconds
                if extend_until_saturation
                else started_at
            )

            if is_overload:
                self.log("OverLoad는 시간 설정으로 종료하지 않습니다. 테스트 중지를 누르면 종료됩니다.")

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
                    test_name=csv_test_name,
                    condition_label=csv_condition_label,
                )
                csv_file.flush()

                now = time.monotonic()
                if track_overload:
                    overload_candidate = self._update_overload_candidate(
                        plan,
                        condition,
                        timestamp,
                        temperatures,
                        overload_candidate,
                    )

                if not is_overload:
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
                            break
                        next_saturation_check_at = now + saturation_recheck_seconds
                        if now - started_at >= saturation_check_seconds:
                            self.log(
                                f"[포화 미도달] CSV 기록은 계속 유지, {saturation_recheck_seconds:g}초 후 재판정"
                            )

                self.log(f"[{timestamp:%Y-%m-%d %H:%M:%S}] Temps={temperatures}")

                if is_overload:
                    wait_seconds = plan.sample_interval_seconds
                elif not extend_until_saturation:
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

            condition_elapsed_seconds = (
                time.monotonic() - condition_started_at
                if condition_started_at is not None
                else 0.0
            )
            local_filename_stem = build_recording_filename_stem(
                recording_test_name or plan.test_name,
                plan.electrical_mode,
                condition,
                condition_elapsed_seconds,
            )

            if recorder_started:
                self._download_and_convert_recording(
                    recorder_files_before,
                    local_filename_stem,
                )

        return condition_elapsed_seconds, overload_candidate

    def _download_and_convert_recording(
        self,
        recorder_files_before,
        local_filename_stem,
    ):
        try:
            result = self.recorder.download_recording_file(
                self.output_folder,
                recorder_files_before,
                local_filename_stem,
            )
            if result is None:
                return
            remote_name, local_path, size = result
            self.log(f"Recorder file saved: {remote_name} -> {local_path} ({size} bytes)")
            if self.pdf_converter is None:
                return
            try:
                pdf_result = self.pdf_converter(local_path, self.log)
                self.log(
                    f"PDF saved: {pdf_result.output_pdf_path} "
                    f"({pdf_result.pdf_size_bytes} bytes)"
                )
            except Exception as exc:
                self.log(f"PDF conversion error: {exc}")
        except Exception as exc:
            self.log(f"Recorder FTP download error: {exc}")

    def _update_overload_candidate(
        self,
        plan,
        condition,
        timestamp,
        temperatures,
        current_candidate,
    ):
        channel = plan.overload_coil_channel
        if not plan.overload_enabled or not channel:
            return current_candidate

        value = temperatures.get(channel)
        if not isinstance(value, (int, float)):
            return current_candidate

        if current_candidate is not None and value <= current_candidate.temperature:
            return current_candidate

        return OverloadCandidate(
            condition=condition,
            target_label=build_overload_target_label(
                plan.test_name,
                plan.electrical_mode,
                condition,
            ),
            channel=channel,
            display_channel=plan.overload_coil_display_channel or channel,
            temperature=float(value),
            timestamp=timestamp,
        )

    def _publish_overload_target(self, target_label):
        if self.overload_target_callback is not None:
            self.overload_target_callback(target_label)

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

    def _open_result_file(self, plan, filename_test_name=None):
        self.output_folder.mkdir(parents=True, exist_ok=True)
        test_date = datetime.now().strftime("%Y%m%d")
        file_test_name = filename_test_name or plan.test_name
        file_path = (
            self.output_folder / f"{sanitize_filename(file_test_name)}_{test_date}.csv"
        )
        if file_path.exists():
            duplicate_no = 2
            while True:
                candidate = file_path.with_name(
                    f"{file_path.stem} ({duplicate_no}){file_path.suffix}"
                )
                if not candidate.exists():
                    file_path = candidate
                    break
                duplicate_no += 1
        csv_file = file_path.open("w", newline="", encoding="utf-8-sig")
        writer = csv.writer(csv_file)
        writer.writerow(
            ["Time", "Test_Name", "Electrical_Mode", "Condition"]
            + [f"Temp_{channel}" for channel in plan.temperature_channels]
            + ["Supply_V", "Supply_Hz", "PM_V", "PM_A", "PM_P", "PM_Hz"]
        )
        return csv_file, writer, file_path

    @staticmethod
    def _write_result(
        writer,
        plan,
        condition,
        timestamp,
        temperatures,
        power,
        *,
        test_name=None,
        condition_label=None,
    ):
        temperature_values = [
            temperatures.get(channel, "") for channel in plan.temperature_channels
        ]
        writer.writerow(
            [
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                test_name or plan.test_name,
                plan.electrical_mode.value,
                condition_label or condition.label,
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
