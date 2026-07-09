from abc import ABC, abstractmethod


class BaseCVCF(ABC):
    """Common interface for CVCF power supply drivers."""

    name = "BASE"

    def __init__(self, transport, log_callback):
        # CVCF는 GUI 전체가 아니라 통신과 로그 함수에만 의존한다.
        self.transport = transport
        self.log = log_callback

    @property
    def resource_name(self):
        return self.transport.resource_name

    def write(self, command):
        self.transport.write(command)

    def query(self, command):
        return self.transport.query_line(command)

    def close(self):
        self.transport.close()

    @abstractmethod
    def configure(self, voltage, frequency, current_limit=None, output_mode="AC"):
        """시험 전압, 주파수와 선택적인 전류 제한을 설정한다."""

    @abstractmethod
    def output_on(self):
        """CVCF 출력을 켠다."""

    @abstractmethod
    def output_off(self):
        """CVCF 출력을 끈다."""

    def check_error(self):
        return None
