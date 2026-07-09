"""
base_recorder.py
온도 센서(Hybrid Recorder) 추상 기반 클래스.
GP20, MV2000 등 모든 레코더 드라이버가 이 클래스를 상속한다.
"""

from abc import ABC, abstractmethod
from .ftp_transfer import RecorderFTPClient, RecorderFTPConfig


class BaseRecorder(ABC):

    FTP_PORT = 21
    FTP_REMOTE_DIR = "/MEM0/DATA"
    FTP_EXTENSION = ""
    FTP_USER = "anonymous"
    FTP_PASSWORD = ""

    def __init__(self, transport, log_callback):
        """
        transport    : 열린 LAN socket을 감싼 송수신 어댑터
        log_callback : PowerAnalyzerGUI.log. 드라이버는 Tkinter를 직접 모른다.
        """
        self.transport = transport
        self.log = log_callback

    def close(self):
        self.transport.close()

    # ── 드라이버 이름 (로그 표시용) ──────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str:
        """드라이버 이름 문자열 반환 (예: 'GP20', 'MV2000')"""

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def get_info(self) -> str:
        """장비 정보 응답을 반환하고 예상 모델인지 검증한다."""

    # ── 녹화 제어 ────────────────────────────────────────────────
    @abstractmethod
    def recording_start(self):
        pass

    @abstractmethod
    def recording_stop(self):
        pass

    # ── 데이터 읽기 ──────────────────────────────────────────────
    @abstractmethod
    def get_temperature_values(self, first_ch: str, last_ch: str) -> dict:
        """
        채널별 최신 온도값을 읽어 dict로 반환.
        반환 형식: {채널번호문자열: float 또는 원문문자열(결측)}
        예: {"001": 23.6, "002": 25.0, "003": "-99999999E-01"}
        """

    # ── 공통 헬퍼 ────────────────────────────────────────────────
    def snapshot_recording_files(self) -> set[str]:
        """Return the current recorder data files before a new recording starts."""
        if not self.FTP_EXTENSION:
            return set()
        return self._ftp_client().list_file_names()

    def download_recording_file(
        self, output_folder, previous_files: set[str] | None = None
    ):
        """Download the newly created recorder data file to the output folder."""
        if not self.FTP_EXTENSION:
            return None
        return self._ftp_client().download_latest(output_folder, previous_files)

    def _ftp_client(self) -> RecorderFTPClient:
        host = self.transport.peer_host
        if not host:
            raise RuntimeError(f"{self.name} FTP host를 확인할 수 없습니다.")
        config = RecorderFTPConfig(
            device_key=self.name,
            host=host,
            port=self.FTP_PORT,
            remote_dir=self.FTP_REMOTE_DIR,
            extension=self.FTP_EXTENSION,
            user=self.FTP_USER,
            password=self.FTP_PASSWORD,
        )
        return RecorderFTPClient(config, self.log)

    def write(self, command: str):
        # Yokogawa Recorder 명령은 LAN에서 CRLF로 끝난다.
        self.transport.write(command, eol="\r\n")

    def query_data(self, command: str):
        """FData/FD처럼 EN 행으로 끝나는 여러 줄 응답을 읽는다."""
        return self.transport.query_until(
            command,
            terminators=(b"EN\r\n", b"EN\n"),
            eol="\r\n",
        )
