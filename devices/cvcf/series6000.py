import time

from .base import BaseCVCF


class Series6000(BaseCVCF):
    """Driver for the existing small CVCF command set."""

    name = "SERIES6000"

    def configure(self, voltage, frequency, current_limit=None, output_mode="AC"):
        # Series6000은 기존 명령 체계를 유지하되 입력된 항목만 변경한다.
        # 두 값이 모두 주어진 기존 AC 시험에서는 이전과 동일하게 초기화한다.
        if voltage is not None and frequency is not None:
            self.write("*RST")
            time.sleep(0.5)
            self.write("AR 1")
            time.sleep(0.5)
        if voltage is not None:
            self.write(f"VOLT {voltage}")
            time.sleep(0.5)
        if frequency is not None:
            self.write(f"FREQ {frequency}")
            time.sleep(0.5)

    def output_on(self):
        self.write("TEST")
        time.sleep(0.5)

    def output_off(self):
        self.write("*RST")
        time.sleep(0.5)

