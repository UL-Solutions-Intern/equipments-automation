"""
Yokogawa MV1000/MV2000 Hybrid Recorder 전용 드라이버.

통신 매뉴얼 (IM MV1000-17E) 기준:
  - 녹화 시작/정지 : PS0 / PS1
  - 최신 측정값    : FD0,first,last  (ASCII 포맷)
  - 응답 구조      : EA ... DATE ... TIME ... N ccc unit value ... EN
"""

from .base import BaseRecorder


class MV2000Recorder(BaseRecorder):

    PORT = 34260
    FTP_EXTENSION = ".DAE"

    @property
    def name(self) -> str:
        return "MV2000"

    # ── 장비 접속 ────────────────────────────────────────────────
    def connect(self):
        # Setting/Measurement 서버는 접속 직후 사용자명 요청(E1 402)을 보낸다.
        login_request = self.transport.read_line(timeout=3.0)

        self.log(f"MV2000 접속 응답: {login_request!r}")

        if not login_request.startswith("E1 402"):
            raise ConnectionError(f"MV2000 로그인 요청이 아닙니다: {login_request!r}")

        self.transport.write("admin", eol="\r\n")
        login_result = self.transport.read_line(timeout=3.0)

        self.log(f"MV2000 로그인 응답: {login_result!r}")

        if login_result != "E0":
            raise ConnectionError(f"MV2000 로그인 실패: {login_result!r}")

    # ── 장비 정보 조회 ────────────────────────────────────────────────
    def get_info(self) -> str:
        idn = self.transport.query_line("*I", eol="\r\n", timeout=3.0)

        if "MV" not in idn.upper():
            raise ConnectionError(f"MV2000이 아닙니다. 응답={idn}")

        return idn

    # ── 녹화 제어 ────────────────────────────────────────────────
    def recording_start(self):
        self.write("PS0")
        self.log("MV2000 녹화 시작 (PS0)")

    def recording_stop(self):
        self.write("PS1")
        self.log("MV2000 녹화 정지 (PS1)")

    # ── 데이터 읽기 ──────────────────────────────────────────────
    def get_temperature_values(self, first_ch: str, last_ch: str) -> dict:
        """
        MV2000 FD 명령으로 최신 측정값 읽기.

        명령: FD0,<first>,<last>
          - p1=0 : ASCII 포맷 출력
          - first/last : 3자리 채널번호 (예: 001, 048)

        응답 예시:
            EA
            DATE 99/02/23
            TIME 19:56:32.500
            N 001h  ^C    +12345E-03
            N 002   ^C    -67890E-01
            S 003
            EN

        채널번호 형식: GP20는 4자리(0001), MV2000는 3자리(001)
        → 반환 dict 키는 4자리로 통일 (기존 temp_channels와 호환)
        """
        # MV2000 채널번호는 3자리
        first_3 = str(int(first_ch)).zfill(3)
        last_3 = str(int(last_ch)).zfill(3)

        try:
            text = self.query_data(f"FD0,{first_3},{last_3}")
            if not text:
                return {}

            temp_dict = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("EA", "DATE", "TIME", "EN")):
                    continue

                parts = line.split()
                # 최소 토큰: 상태(N/D/S/O/E/B) + 채널번호 + 단위 + 값
                if len(parts) < 4:
                    continue

                status = parts[0]  # N, D, S, O, E, B
                ch_raw = parts[1]  # 예: "001" or "001h" (알람 있으면 h 등 붙음)
                unit = parts[2]  # 예: "^C" (°C), "mV", "V"
                val_str = parts[-1]  # 마지막 토큰이 값

                # Skip(S), Error(E), Burnout(B) 채널은 값 없음 → 건너뜀
                if status in ("S", "E", "B"):
                    continue

                # 채널번호에서 알람 접미사(h, H, l, L 등) 제거
                ch_num = "".join(filter(str.isdigit, ch_raw))
                if not ch_num:
                    continue

                # 4자리로 패딩하여 기존 temp_channels 키와 통일
                ch_key = ch_num.zfill(4)

                # 온도 단위 필터 (°C 또는 ^C)
                if unit in ("^C", "°C", "C"):
                    temp_dict[ch_key] = self._parse_value(val_str)

            return temp_dict

        except Exception as e:
            self.log(f"MV2000 온도 측정 오류: {e}")
            return {}

    def get_temperature_channels(self, first_ch: str, last_ch: str) -> list[str]:
        first = int(first_ch)
        last = int(last_ch)

        if first > last:
            raise ValueError("Recorder 시작 채널은 마지막 채널보다 클 수 없습니다.")

        if first < 1 or last > 48:
            raise ValueError("MV2000 Recorder 채널은 001~048 범위로 입력하세요.")

        return [f"{channel:04d}" for channel in range(first, last + 1)]

    # ── 내부 헬퍼 ────────────────────────────────────────────────
    def _parse_value(self, s: str) -> float | str:
        """
        MV2000 과학표기 값 파싱.
        예: "+12345E-03" → 12.345
        이상값(99999 mantissa)은 원문 반환.
        """
        if not s:
            return ""
        s = s.strip()
        # 이상값: mantissa가 99999인 경우 (Overflow)
        if "99999" in s and "E" in s.upper():
            return s
        try:
            return float(s)
        except Exception:
            return s
