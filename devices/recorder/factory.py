"""
recorder_factory.py
IDN 응답 문자열을 기반으로 적절한 Recorder 드라이버를 반환하는 팩토리.

사용 예:
    recorder = create_recorder(app, label="온도 센서", idn=idn_string)
"""

from .gp20  import GP20Recorder
from .mv2000 import MV2000Recorder


def create_recorder(transport, log_callback, port: int):
    """
    port를 보고 알맞은 Recorder 드라이버 인스턴스를 반환.

    Parameters
    ----------
    transport    : LAN socket을 감싼 DeviceIO
    log_callback : PowerAnalyzerGUI.log 메서드
    port  : 우리가 입력창에 적은 port 번호

    Returns
    -------
    BaseRecorder 를 상속한 드라이버 인스턴스
    """

    if port == MV2000Recorder.PORT:
        return MV2000Recorder(transport, log_callback)

    if port == GP20Recorder.PORT:
        return GP20Recorder(transport, log_callback)

    raise ValueError(
        f"지원하지 않는 Recorder Port : {port}"
    )
