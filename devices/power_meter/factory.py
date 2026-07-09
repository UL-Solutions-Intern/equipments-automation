"""Power Meter IDN 응답으로 장비 드라이버를 선택한다."""

from .wt310 import WT310PowerMeter


def create_power_meter(transport, log_callback, idn: str):
    """현재 운영 장비인 WT310만 허용한다.

    알 수 없는 장비에 여러 SCPI 명령을 무작위로 보내지 않도록 명시적으로
    실패시킨다. 향후 모델 추가 시 이 팩토리에 IDN 조건과 드라이버만 추가하면
    되며 GUI의 시험 코드는 변경할 필요가 없다.
    """
    idn_upper = (idn or "").upper()
    if "WT310" in idn_upper:
        return WT310PowerMeter(transport, log_callback)
    raise ValueError(f"지원하지 않는 Power Meter입니다. IDN={idn!r}")


# ---------------------------------------------------------------------------
# 향후 Power Meter 추가 시 참고할 기존 범용 SCPI 탐지 코드
# ---------------------------------------------------------------------------
# 기존 automation.py는 WT310이 아닌 장비에 아래 후보 명령을 차례로 보내고,
# 숫자 응답이 오는 첫 명령을 VOLT/CURR/POW/FREQ 측정 명령으로 저장했다.
# 현재는 WT310만 사용하므로 실행 코드에서 제거했지만, 향후 Keysight/Chroma
# 등의 모델을 지원할 때 별도 드라이버를 작성하기 위한 참고 자료로 남긴다.
# 새 장비가 추가되면 이 목록을 GUI로 되돌리지 말고, 해당 모델 파일에
# 검증된 명령을 명시적으로 구현하는 것이 안전하다.
#
# volt_cmds = [
#     ":MEAS:VOLT?", "MEAS:VOLT?", "MEAS:VOLT:DC?", "MEAS:VOLT:AC?",
#     "MEAS:VOLTage?", "MEASure:VOLTage:DC?", "MEASure:VOLTage:AC?",
#     "NUM:VAL? VOLT", "READ? VOLT", "FETCh? VOLT",
# ]
# curr_cmds = [
#     ":MEAS:CURR?", "MEAS:CURR?", "MEAS:CURR:DC?", "MEAS:CURR:AC?",
#     "MEAS:CURRent?", "MEASure:CURRent:AC?",
#     "NUM:VAL? CURR", "READ? CURR", "FETCh? CURR",
# ]
# pow_cmds = [":POW?", "MEAS:POW?", "READ? POW", "FETCh? POW"]
# freq_cmds = [
#     ":FREQ?", "MEAS:FREQ?", "MEAS:FREQuency?",
#     "NUM:VAL? FREQ", "READ? FREQ", "FETCh? FREQ",
# ]
