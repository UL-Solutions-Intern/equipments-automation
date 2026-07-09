"""
gp20_recorder.py
Yokogawa GP20 Hybrid Recorder 전용 드라이버.
"""

from .base import BaseRecorder


class GP20Recorder(BaseRecorder):

    PORT = 34434
    FTP_EXTENSION = ".GEV"

    @property
    def name(self) -> str:
        return "GP20"

    # ── 장비 접속 ────────────────────────────────────────────────
    def connect(self):
        # 로그인 기능이 꺼진 GP20 GENE 서버는 TCP 접속 직후 E0를 보낸다.
        result = self.transport.read_line(timeout=3.0)

        self.log(f"GP20 접속 응답: {result!r}")

        if not result.startswith("E0"):
            raise ConnectionError(f"GP20 접속 실패: {result!r}")

    # ── 장비 정보 조회 ────────────────────────────────────────────────
    def get_info(self) -> str:
        # _INF 응답은 여러 줄이며 마지막 EN 행까지 모두 읽어야 한다.
        idn = self.transport.query_until(
            "_INF",
            terminators=(b"EN\r\n", b"EN\n"),
            eol="\r\n",
        )

        if "GP20" not in idn.upper():
            raise ConnectionError(f"GP20이 아닙니다. 응답={idn}")

        return idn

    # ── 녹화 제어 ────────────────────────────────────────────────
    def recording_start(self):
        """GP20: ORec,0 + OSaveConf"""
        self.write("ORec,0")
        self.write("OSaveConf")
        self.log("GP20 녹화 시작 (ORec,0)")

    def recording_stop(self):
        """GP20: ORec,1"""
        self.write("ORec,1")
        self.log("GP20 녹화 정지 (ORec,1)")

    # ── 데이터 읽기 ──────────────────────────────────────────────
    def get_temperature_values(self, first_ch: str, last_ch: str) -> dict:
        """
        GP20 FData 명령으로 채널별 온도값 읽기.
        응답 예시:
            N 0001    °C       +00000236E-01
            N 0002    °C       +00000250E-01
            EN
        """
        cmd_in = f"{first_ch},{last_ch}"
        try:
            text = self.query_data(f"FData,0,{cmd_in}")
            if not text:
                return {}

            temp_dict = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("EA", "DATE", "TIME", "EN")):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                ch = parts[1]  # 예: "0001"
                unit = parts[2]  # 예: "°C"
                val_str = parts[-1]

                if unit in ("°C", "C"):
                    temp_dict[ch] = self._parse_value(val_str)
            return temp_dict

        except Exception as e:
            self.log(f"GP20 온도 측정 오류: {e}")
            return {}

    def get_temperature_channels(self, first_ch: str, last_ch: str) -> list[str]:
        first = int(first_ch)
        last = int(last_ch)

        if first > last:
            raise ValueError("Recorder 시작 채널은 마지막 채널보다 클 수 없습니다.")

        channels = []
        for block in range(first // 100, last // 100 + 1):
            low = max(first, block * 100 + 1)
            high = min(last, block * 100 + 10)
            if low <= high:
                channels.extend(f"{channel:04d}" for channel in range(low, high + 1))

        if not channels:
            raise ValueError("유효한 GP20 Recorder 채널이 없습니다.")

        return channels

    # ── 내부 헬퍼 ────────────────────────────────────────────────
    def _parse_value(self, s: str):
        """
        GP20 특유의 과학표기 문자열을 float로 변환.
        결측값(-99999999E-01)은 원문 그대로 반환.
        """
        if not s:
            return ""
        s = s.strip()
        if s == "-99999999E-01":
            return s
        try:
            return float(s)  # "+00000236E-01" → 23.6
        except Exception:
            return s
