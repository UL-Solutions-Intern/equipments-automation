import time

from .base import BaseCVCF


class PcrLe(BaseCVCF):
    """Driver for Kikusui PCR-LE series CVCF power supplies."""

    name = "PCR_LE"

    def configure(self, voltage, frequency, current_limit=None, output_mode="AC"):
        """입력된 항목만 설정한다.

        UI에서 선택한 출력 모드를 사용한다. PCR-LE 공식 명령에서 AC 전압은
        VOLT, DC 전압은 VOLT:OFFS를 사용한다.
        """
        is_dc_condition = output_mode.upper() == "DC"
        range_threshold = 215.5 if is_dc_condition else 152.5
        voltage_range = 150 if voltage is None or abs(voltage) <= range_threshold else 300
        resource_name = self.resource_name.upper()

        # PCR-LE RS232C/USB/LAN require remote mode. GPIB handles REN externally.
        if not resource_name.startswith("GPIB"):
            self.write("SYST:REM")
            time.sleep(0.2)

        self.write("*CLS")
        time.sleep(0.2)
        self.write("OUTP OFF")
        time.sleep(0.2)

        # 전체 AC 조건 또는 DC 전압 조건은 이전 설정의 영향을 받지 않도록
        # 초기화한다. 주파수만 바꿀 때는 기존 AC 전압을 유지해야 하므로
        # 초기화하지 않는다.
        if voltage is not None:
            self.write("*RST")
            time.sleep(0.5)

        self.write("OUTP:COUP DC" if is_dc_condition else "OUTP:COUP AC")
        time.sleep(0.2)
        if voltage is not None:
            self.write(f"VOLT:RANG {voltage_range}")
            time.sleep(0.2)

        if current_limit is not None:
            current_command = "CURR:OFFS" if is_dc_condition else "CURR"
            self.write(f"{current_command} {current_limit}")
            time.sleep(0.2)

        if voltage is not None:
            voltage_command = "VOLT:OFFS" if is_dc_condition else "VOLT"
            self.write(f"{voltage_command} {voltage}")
            time.sleep(0.2)
        if frequency is not None:
            self.write(f"FREQ {frequency}")
            time.sleep(0.2)
        self.log_error("PCR-LE 설정 후")

    def output_on(self):
        self.write("OUTP ON")
        time.sleep(0.5)
        self.log_error("PCR-LE 출력 ON 후")

    def output_off(self):
        self.write("OUTP OFF")
        time.sleep(0.5)

    def check_error(self):
        return self.query("SYST:ERR?")

    def log_error(self, context):
        err = self.check_error()
        if err and not err.startswith("+0"):
            self.log(f"{context} 에러 확인: {err}")

