"""Power Meter 드라이버가 제공해야 하는 공통 인터페이스."""

from abc import ABC, abstractmethod


class BasePowerMeter(ABC):
    """GUI가 모델별 SCPI 명령을 몰라도 측정할 수 있게 하는 계약."""

    def __init__(self, transport, log_callback):
        self.transport = transport
        # log_callback은 현재 PowerAnalyzerGUI.log 메서드다. 장비 파일은
        # Tkinter를 몰라도 이 함수를 통해 기존 GUI 로그 창에 기록할 수 있다.
        self.log = log_callback

    def close(self):
        self.transport.close()

    @property
    @abstractmethod
    def name(self) -> str:
        """로그에 표시할 장비 모델명."""

    @abstractmethod
    def initialize(self):
        """측정 전에 출력 항목과 데이터 포맷을 설정한다."""

    @abstractmethod
    def read_voltage(self) -> str:
        """전압 측정값을 장비 응답 문자열로 반환한다."""

    @abstractmethod
    def read_current(self) -> str:
        """전류 측정값을 장비 응답 문자열로 반환한다."""

    @abstractmethod
    def read_power(self) -> str:
        """유효전력 측정값을 장비 응답 문자열로 반환한다."""

    @abstractmethod
    def read_frequency(self) -> str:
        """주파수 측정값을 장비 응답 문자열로 반환한다."""
