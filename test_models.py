"""시험 실행에 사용하는 작은 데이터 모델과 입력 변환 함수.

GUI나 장비 통신 코드는 포함하지 않는다. 사용자가 입력한 값들을 명확한
이름의 객체로 바꿔 TestRunner에 전달하는 역할만 담당한다.
"""

from dataclasses import dataclass
from enum import Enum
import re


class DeviceStatus(Enum):
    """장비 주소 입력 및 연결 결과."""

    UNUSED = "unused"
    CONNECTED = "connected"
    FAILED = "failed"


class ElectricalMode(Enum):
    """전압 명령과 주파수 사용 여부를 결정하는 출력 모드."""

    AC = "AC"
    DC = "DC"


@dataclass(frozen=True)
class TestCondition:
    """한 시험 단계에서 변경할 전압과 주파수.

    None은 해당 설정을 변경하지 않는다는 의미다. 둘 다 None이면 외부
    전원을 사용하거나 현재 CVCF 설정을 유지한 채 한 번만 측정한다.
    """

    voltage: float | None = None
    frequency: float | None = None

    @property
    def label(self) -> str:
        parts = []
        if self.voltage is not None:
            parts.append(f"{self.voltage:g}V")
        if self.frequency is not None:
            parts.append(f"{self.frequency:g}Hz")
        return " / ".join(parts) if parts else "현재 상태 측정"


@dataclass
class TestPlan:
    """GUI 입력을 검증한 뒤 만들어지는 한 번의 시험 계획."""

    test_name: str
    electrical_mode: ElectricalMode
    conditions: list[TestCondition]
    duration_seconds: float
    sample_interval_seconds: float
    cooldown_seconds: float
    first_channel: str
    last_channel: str
    temperature_channels: list[str]
    current_limit: float | None = None
    saturation_enabled: bool = True
    saturation_check_seconds: float | None = None
    saturation_recheck_seconds: float | None = None
    stabilization_window_seconds: float = 1800


@dataclass
class PowerMeasurement:
    """Power Meter 미사용 시 모든 필드가 None인 동일한 결과를 사용한다."""

    voltage: str | None = None
    current: str | None = None
    power: str | None = None
    frequency: str | None = None


def build_test_conditions(
    has_cvcf: bool,
    electrical_mode: ElectricalMode,
    voltages: list[float],
    frequencies: list[float],
) -> list[TestCondition]:
    """입력된 전압·주파수 조합을 공통 시험 조건으로 변환한다."""
    if electrical_mode == ElectricalMode.DC:
        return [TestCondition(voltage=voltage) for voltage in (voltages or [None])]

    if not voltages and not frequencies:
        return [TestCondition()]

    voltage_values = voltages or [None]
    frequency_values = frequencies or [None]
    return [
        TestCondition(voltage=voltage, frequency=frequency)
        for voltage in voltage_values
        for frequency in frequency_values
    ]


def sanitize_filename(name: str) -> str:
    """시험명을 Windows에서 안전한 파일명 일부로 변환한다."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "Test"


def format_elapsed_time(elapsed_seconds: float) -> str:
    """Format a measured condition duration for use in a filename."""
    total_seconds = max(0, int(elapsed_seconds))
    if total_seconds < 60:
        return f"({total_seconds}s)"

    total_minutes = total_seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0:
        return f"({minutes}m)"
    return f"({hours}h {minutes}m)"


def build_recording_filename_stem(
    test_name: str,
    electrical_mode: ElectricalMode,
    condition: TestCondition,
    elapsed_seconds: float,
) -> str:
    """Build the local raw-data filename without the recorder extension."""
    parts = []
    if condition.voltage is not None:
        parts.append(f"{condition.voltage:g}V{electrical_mode.value.lower()}")
    else:
        parts.append(electrical_mode.value)

    if electrical_mode == ElectricalMode.AC and condition.frequency is not None:
        parts.append(f"{condition.frequency:g}Hz")

    parts.extend([sanitize_filename(test_name), format_elapsed_time(elapsed_seconds)])
    return "_".join(parts)
