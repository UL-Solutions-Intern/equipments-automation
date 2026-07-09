"""Yokogawa WT310 전용 Power Meter 드라이버."""

from .base import BasePowerMeter


class WT310PowerMeter(BasePowerMeter):
    """WT310의 NUMERIC NORMAL 모드로 네 개 항목을 개별 조회한다."""

    @property
    def name(self) -> str:
        return "WT310"

    def initialize(self):
        # 응답을 CSV에 바로 기록할 수 있는 ASCII 형식으로 고정한다.
        self.transport.write(":NUMERIC:FORMAT ASCII")
        self.transport.write(":NUMERIC:NORMAL:CLEAR ALL")
        self.transport.write(":NUMERIC:NORMAL:NUMBER 4")

        # WT310의 U/I/P/FU는 각각 전압, 전류, 유효전력, 전압 주파수다.
        # 항목 순서를 고정했기 때문에 아래 read 메서드도 같은 번호를 조회한다.
        self.transport.write(":NUMERIC:NORMAL:ITEM1 U,1")
        self.transport.write(":NUMERIC:NORMAL:ITEM2 I,1")
        self.transport.write(":NUMERIC:NORMAL:ITEM3 P,1")
        self.transport.write(":NUMERIC:NORMAL:ITEM4 FU,1")
        self.log("PM 명령 매핑: WT310 NUMERIC 모드 사용 (U, I, P, FU)")

    def _read_item(self, item_number: int) -> str:
        try:
            response = self.transport.query_line(
                f":NUMERIC:NORMAL:VALUE? {item_number}"
            )
            # 기존 코드는 쉼표 응답에서도 첫 값만 사용했다. CSV 형식과 기존
            # 동작을 유지하기 위해 같은 규칙을 WT310 드라이버 내부에 둔다.
            return response.split(",")[0].strip()
        except Exception as exc:
            # 일시적인 계측 실패가 전체 장시간 시험을 즉시 종료시키지 않도록
            # 기존 pm_read와 동일하게 빈 값을 반환하고 원인은 GUI에 기록한다.
            self.log(f"WT310 ITEM{item_number} 쿼리 오류: {exc}")
            return ""

    def read_voltage(self) -> str:
        return self._read_item(1)

    def read_current(self) -> str:
        return self._read_item(2)

    def read_power(self) -> str:
        return self._read_item(3)

    def read_frequency(self) -> str:
        return self._read_item(4)
