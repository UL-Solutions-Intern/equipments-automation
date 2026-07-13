import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import pyvisa
import serial
import socket
import threading
import time
import os
from dataclasses import dataclass
from typing import Any

from devices.cvcf.factory import create_cvcf
from devices.recorder.factory import create_recorder
from devices.power_meter.factory import create_power_meter
from test_models import (
    DeviceStatus,
    ElectricalMode,
    TestPlan,
    build_temperature_channels,
    build_test_conditions,
)
from test_runner import TestRunner

# 장비명 상수로 선언 (나중에 변경 쉽게)
POWER_SUPPLY = "Power Supply"
RECORDER = "온도 센서"
POWER_METER = "Power Meter"
DEVICE_LABELS = (POWER_SUPPLY, RECORDER, POWER_METER)


# 흩어져 있던 변수 하나로 모음 ( 장비 => 상태, 주소, 드라이버 )
@dataclass
class DeviceContext:
    status: DeviceStatus = DeviceStatus.UNUSED
    connected_address: str | None = None
    connection_type: str | None = None
    driver: Any = None


class PowerAnalyzerGUI:
    def __init__(self, root):
        # Tkinter 메인 윈도우 설정
        self.root = root
        self.root.title("통합 테스트 시스템")

        # 상태, 실제 연결 주소, 모델별 드라이버를 장비 단위로 묶는다.
        self.devices = {label: DeviceContext() for label in DEVICE_LABELS}

        # 테스트 상태 관리
        self.is_testing = False
        self.test_thread = None
        self.stop_event = threading.Event()
        self.test_runner = None

        # VISA Resource Manager 생성
        self.rm = pyvisa.ResourceManager()

        # 기본 저장 폴더 = 현재 경로
        self.save_folder = os.getcwd()

        # UI 빌드
        self.build_gui()

    def build_gui(self):
        """Tkinter UI 구성"""
        # 프레임 구성
        top_frame = tk.Frame(self.root)  # 장비 주소 입력
        top_frame.pack(pady=10)

        setting_frame = tk.Frame(self.root)  # 테스트 설정 입력
        setting_frame.pack(pady=5)

        control_frame = tk.Frame(self.root)  # 제어 버튼
        control_frame.pack(pady=10)

        output_frame = tk.Frame(self.root)  # 측정값 표시
        output_frame.pack(pady=6)

        log_frame = tk.Frame(self.root)  # 로그 출력
        log_frame.pack(pady=10)

        # 장비 주소 입력 필드
        self.device_entries = {}

        for i, label in enumerate(DEVICE_LABELS):
            row = i + 1

            tk.Label(top_frame, text=label).grid(
                row=row, column=0, sticky="e", pady=(2, 2)
            )
            entry = tk.Entry(top_frame, width=40)
            entry.grid(row=row, column=1, columnspan=3, padx=5, pady=(2, 2))
            self.device_entries[label] = entry

        # 장비 연결 버튼
        self.connect_btn = tk.Button(
            top_frame, text="장비 연결", width=10, height=1, command=self.connect_all
        )
        self.connect_btn.grid(row=1, column=4, sticky="w", padx=(6, 2), pady=2)

        # 연결 해제 버튼
        self.disconnect_btn = tk.Button(
            top_frame, text="연결 해제", width=10, height=1, command=self.disconnect_all
        )
        self.disconnect_btn.grid(row=2, column=4, sticky="w", padx=(6, 2), pady=2)

        # 시험명 입력 필드
        tk.Label(setting_frame, text="시험명:").grid(row=0, column=0, sticky="e")
        self.test_name_combo = ttk.Combobox(
            setting_frame,
            values=["Normal", "Abnormal", "Fault"],
            state="normal",
            width=18,
        )
        self.test_name_combo.grid(row=0, column=1)
        self.test_name_combo.set("Normal")

        # AC/DC 선택 콤보박스
        tk.Label(setting_frame, text="출력 모드:").grid(row=2, column=2, sticky="e")
        self.electrical_mode_combo = ttk.Combobox(
            setting_frame,
            values=[ElectricalMode.AC.value, ElectricalMode.DC.value],
            state="readonly",
            width=8,
        )
        self.electrical_mode_combo.grid(row=2, column=3)
        self.electrical_mode_combo.set(ElectricalMode.AC.value)
        self.electrical_mode_combo.bind(
            "<<ComboboxSelected>>",
            self._on_electrical_mode_changed,
        )

        # 전압 시퀀스 입력. 비워두면 전압 설정을 변경하지 않는다.
        tk.Label(setting_frame, text="전압 시퀀스 (V):").grid(
            row=1, column=0, sticky="e"
        )
        self.voltage_entry = tk.Entry(setting_frame, width=15)
        self.voltage_entry.grid(row=1, column=1)
        self.voltage_entry.insert(0, "90,264")

        # 시험 시간 입력
        tk.Label(setting_frame, text="시험 시간 (s):").grid(row=0, column=2, sticky="e")
        self.wait_entry = tk.Entry(setting_frame, width=10)
        self.wait_entry.grid(row=0, column=3)
        self.wait_entry.insert(0, "5400")

        # 샘플링 간격 입력
        tk.Label(setting_frame, text="샘플링 간격 (s):").grid(
            row=0, column=4, sticky="e"
        )
        self.sampling_entry = tk.Entry(setting_frame, width=10)
        self.sampling_entry.grid(row=0, column=5)
        self.sampling_entry.insert(0, "1")

        # 주파수 시퀀스 입력. 비워두면 주파수를 변경하지 않는다.
        tk.Label(setting_frame, text="주파수 시퀀스 (Hz):").grid(
            row=2, column=0, sticky="e"
        )
        self.frequency_entry = tk.Entry(setting_frame, width=10)
        self.frequency_entry.grid(row=2, column=1)
        self.frequency_entry.insert(0, "50,60")

        # 부하 전류 입력
        tk.Label(setting_frame, text="부하 전류 (A):").grid(row=1, column=2, sticky="e")
        self.current_entry = tk.Entry(setting_frame, width=10)
        self.current_entry.grid(row=1, column=3)
        self.current_entry.insert(0, "11.0")

        # HR 채널 범위 입력 (온도 센서)
        tk.Label(setting_frame, text="HR 채널 (시작,끝):").grid(
            row=1, column=4, sticky="e"
        )
        self.HR_entry = tk.Entry(setting_frame, width=15)
        self.HR_entry.grid(row=1, column=5)
        self.HR_entry.insert(0, "0001,0008")

        # 제어 버튼
        self.start_test_btn = tk.Button(
            control_frame, text="테스트 시작", width=15, command=self.start_test
        )
        self.start_test_btn.grid(row=0, column=0, padx=10)

        self.stop_test_btn = tk.Button(
            control_frame, text="테스트 중지", width=15, command=self.stop_test
        )
        self.stop_test_btn.grid(row=0, column=1, padx=10)

        self.folder_btn = tk.Button(
            control_frame, text="폴더 지정", width=15, command=self.select_folder
        )
        self.folder_btn.grid(row=0, column=2, padx=10)

        # 폴더 경로 표시
        self.folder_label = tk.Label(
            control_frame, text=f"저장 폴더: {self.save_folder}", anchor="w", fg="blue"
        )
        self.folder_label.grid(
            row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 0)
        )

        # 실시간 측정값 표시
        self.dl_values_label = tk.Label(
            output_frame, text="DL 측정값: V=N/A, A=N/A", font=("Arial", 10)
        )
        self.dl_values_label.pack(anchor="w")

        self.pm_values_label = tk.Label(
            output_frame, text="PM 측정값: V=N/A, A=N/A, Hz=N/A", font=("Arial", 10)
        )
        self.pm_values_label.pack(anchor="w")

        # 로그 출력 박스
        self.log_box = tk.Text(log_frame, height=15, width=100)
        self.log_box.pack()

    def update_measurement_display(
        self, voltage_meas, current_meas, pm_v, pm_a, pm_p, pm_hz
    ):
        """UI에 실시간 측정값 표시"""
        self.dl_values_label.config(
            text=f"DL 측정값: V={voltage_meas}, A={current_meas}"
        )
        self.pm_values_label.config(
            text=f"PM 측정값: V={pm_v}, A={pm_a},P={pm_p}, Hz={pm_hz}"
        )

    def _on_electrical_mode_changed(self, _event=None):
        """DC에서는 사용하지 않는 주파수 입력을 비활성화한다."""
        state = (
            tk.DISABLED
            if self.electrical_mode_combo.get() == ElectricalMode.DC.value
            else tk.NORMAL
        )
        self.frequency_entry.config(state=state)

    def log(self, text):
        """로그 창에 메시지 출력"""

        def append_log():
            timestamp = time.strftime("%H:%M:%S")
            self.log_box.insert(tk.END, f"[{timestamp}] {text}\n")
            self.log_box.see(tk.END)

        self.root.after(0, append_log)

    def select_folder(self):
        """결과 저장 폴더 지정"""
        folder_selected = filedialog.askdirectory(
            initialdir=self.save_folder, title="저장 폴더 선택"
        )
        if folder_selected:
            self.save_folder = folder_selected
            self.folder_label.config(text=f"저장 폴더: {self.save_folder}")
            self.log(f"저장 폴더가 '{self.save_folder}'(으)로 설정되었습니다.")
        else:
            self.log("폴더 지정이 취소되었습니다.")

    def connect_all(self):
        """입력된 장비만 연결하고 미사용·성공·실패 상태를 기록한다."""
        if self.is_testing:
            self.log("시험 중에는 장비를 다시 연결할 수 없습니다.")
            return
        for label, entry in self.device_entries.items():
            self._cleanup_device_connection(label)
            address = entry.get().strip()
            if not address:
                if label == RECORDER:
                    self.devices[label].status = DeviceStatus.FAILED
                    self.log("온도 센서 주소가 없습니다. Recorder는 필수 장비입니다.")
                else:
                    self.log(f"{label} 미사용 (주소 미입력)")
                continue

            try:
                self._connect_device(label, address)
            except Exception as exc:
                self._cleanup_device_connection(label)
                self.devices[label].status = DeviceStatus.FAILED
                self.log(f"{label} 연결 실패: {exc}")

    def _connect_device(self, label, address):
        if address.upper().startswith("USB") or "::" in address:
            self._connect_visa(label, address)
        elif address.upper().startswith("COM"):
            self._connect_serial(label, address)
        elif ":" in address:
            self._connect_lan(label, address)
        else:
            raise ValueError(f"지원하지 않는 장비 주소 형식: {address}")

    def _connect_visa(self, label, address):
        if label == RECORDER:
            raise ValueError("Recorder는 현재 IP:PORT 형식의 LAN 연결만 지원합니다.")

        resource = self.rm.open_resource(address)
        resource.read_termination = "\n"
        resource.write_termination = "\n"
        resource.encoding = "ascii"
        resource.timeout = 5000
        device_io = DeviceIO(resource, "VISA")
        try:
            idn = device_io.query_line("*IDN?")
            driver = self._create_driver(label, device_io, idn)
        except Exception:
            device_io.close()
            raise

        self.devices[label] = DeviceContext(
            status=DeviceStatus.CONNECTED,
            connected_address=address,
            connection_type="VISA",
            driver=driver,
        )

        self.log(f"{label} 연결 성공 (VISA) - {idn}")

    def _connect_serial(self, label, address):
        if label == RECORDER:
            raise ValueError("Recorder는 현재 IP:PORT 형식의 LAN 연결만 지원합니다.")

        last_error = None
        for baudrate in (9600, 19200, 38400):
            device_io = None
            try:
                resource = serial.Serial(address, baudrate=baudrate, timeout=3)
                device_io = DeviceIO(resource, "SERIAL")
                idn = device_io.query_line("*IDN?", timeout=2.0)
                if not idn:
                    raise ConnectionError("IDN 응답 없음")

                driver = self._create_driver(label, device_io, idn)
                self.devices[label] = DeviceContext(
                    status=DeviceStatus.CONNECTED,
                    connected_address=address,
                    connection_type="SERIAL",
                    driver=driver,
                )
                self.log(f"{label} 연결 성공 (SERIAL, {baudrate}bps) - {idn!r}")
                return
            except Exception as exc:
                last_error = exc
                if device_io is not None:
                    device_io.close()

        raise ConnectionError(f"모든 baudrate에서 연결 실패: {last_error}")

    def _connect_lan(self, label, address):
        ip, port_text = address.rsplit(":", 1)
        port = int(port_text)
        resource = socket.create_connection((ip, port), timeout=5)
        resource.settimeout(3.0)
        device_io = DeviceIO(resource, "LAN")
        try:
            if label == RECORDER:
                driver = self._create_driver(label, device_io, port=port)
                driver.connect()
                idn = driver.get_info()
            else:
                idn = device_io.query_line("*IDN?")
                driver = self._create_driver(label, device_io, idn=idn)
        except Exception:
            device_io.close()
            raise

        self.devices[label] = DeviceContext(
            status=DeviceStatus.CONNECTED,
            connected_address=address,
            connection_type="LAN",
            driver=driver,
        )

        self.log(f"{label} 연결 성공 (LAN) - {idn or 'IDN 응답 없음'}")

    def _create_driver(self, label, device_io, idn=None, port=None):
        """레코더는 port, 나머지는 idn으로 장비 구분해 드라이버 생성"""
        if label == RECORDER:
            if port is None:
                raise ValueError("Recorder 드라이버 생성에는 port가 필요합니다.")
            return create_recorder(device_io, self.log, port)
        elif label == POWER_SUPPLY:
            return create_cvcf(device_io, self.log, idn)
        elif label == POWER_METER:
            return create_power_meter(device_io, self.log, idn)
        else:
            raise ValueError(f"지원하지 않는 장비 종류: {label}")

    def disconnect_all(self):
        if self.is_testing:
            self.log("시험을 중지한 뒤 장비 연결을 해제하세요.")
            return
        for label in list(self.device_entries):
            self._cleanup_device_connection(label, log_errors=True)
        self.log("모든 장비 연결 해제 완료")

    def _cleanup_device_connection(self, label, log_errors=False):
        driver = self.devices[label].driver
        if driver is not None:
            try:
                driver.close()
            except Exception as exc:
                if log_errors:
                    self.log(f"{label} 해제 오류: {exc}")

        self.devices[label] = DeviceContext()

    def start_test(self):
        """GUI 입력을 TestPlan으로 만들고 공통 TestRunner를 시작한다."""
        if self.is_testing:
            self.log("이미 시험이 실행 중입니다.")
            return

        try:
            self._validate_devices_before_test()
            plan = self._build_test_plan()
        except (ValueError, RuntimeError) as exc:
            self.log(f"시험 시작 오류: {exc}")
            messagebox.showerror("시험 시작 오류", str(exc))
            return

        self.stop_event.clear()
        self.is_testing = True
        self.test_runner = TestRunner(
            recorder=self.devices[RECORDER].driver,
            cvcf=self.devices[POWER_SUPPLY].driver,
            power_meter=self.devices[POWER_METER].driver,
            output_folder=self.save_folder,
            log_callback=self.log,
        )

        def execute_test():
            try:
                self.test_runner.run(plan, self.stop_event)
            finally:
                self.is_testing = False
                self.test_runner = None

        self.test_thread = threading.Thread(target=execute_test, daemon=True)
        self.test_thread.start()

    def stop_test(self):
        """테스트 중지 요청"""
        if not self.is_testing:
            self.log("실행 중인 테스트가 없습니다.")
            return
        self.stop_event.set()
        self.log("테스트 중지 요청됨.")

    def _validate_devices_before_test(self):
        recorder = self.devices[RECORDER]
        recorder_address = self.device_entries[RECORDER].get().strip()
        if (
            not recorder_address
            or recorder.status != DeviceStatus.CONNECTED
            or recorder.connected_address != recorder_address
            or recorder.driver is None
        ):
            raise RuntimeError("Recorder를 먼저 연결해야 합니다.")

        for label in (POWER_SUPPLY, POWER_METER):
            device = self.devices[label]
            address = self.device_entries[label].get().strip()

            if address and (
                device.status != DeviceStatus.CONNECTED
                or device.connected_address != address
                or device.driver is None
            ):
                raise RuntimeError(f"{label} 주소가 입력됐지만 연결되지 않았습니다.")
            if not address and device.status == DeviceStatus.CONNECTED:
                raise RuntimeError(
                    f"{label} 주소 변경 후 장비 연결 버튼을 다시 누르세요."
                )

    def _build_test_plan(self):
        test_name = self.test_name_combo.get().strip() or "Test"
        electrical_mode = ElectricalMode(self.electrical_mode_combo.get())
        duration = float(self.wait_entry.get())
        sample_interval = float(self.sampling_entry.get())
        if duration <= 0 or sample_interval <= 0:
            raise ValueError("시험 시간과 샘플링 간격은 0보다 커야 합니다.")

        try:
            first_channel, last_channel = [
                value.strip() for value in self.HR_entry.get().split(",")
            ]
        except ValueError as exc:
            raise ValueError("HR 채널은 시작,끝 형식으로 입력하세요.") from exc
        temperature_channels = build_temperature_channels(first_channel, last_channel)

        cvcf = self.devices[POWER_SUPPLY].driver
        if cvcf is None:
            voltages = []
            frequencies = []
            current_limit = None
        else:
            voltages = self._parse_float_list(self.voltage_entry.get(), "전압")
            frequencies = (
                self._parse_float_list(self.frequency_entry.get(), "주파수")
                if electrical_mode == ElectricalMode.AC
                else []
            )
            current_limit = self._parse_optional_float(
                self.current_entry.get(), "전류 제한"
            )

        conditions = build_test_conditions(
            has_cvcf=cvcf is not None,
            electrical_mode=electrical_mode,
            voltages=voltages,
            frequencies=frequencies,
        )
        return TestPlan(
            test_name=test_name,
            electrical_mode=electrical_mode,
            conditions=conditions,
            duration_seconds=duration,
            sample_interval_seconds=sample_interval,
            cooldown_seconds=1800,
            first_channel=first_channel,
            last_channel=last_channel,
            temperature_channels=temperature_channels,
            current_limit=current_limit,
            saturation_check_seconds=5400,
            saturation_recheck_seconds=600,
        )

    @staticmethod
    def _parse_float_list(text, field_name):
        try:
            return [float(value.strip()) for value in text.split(",") if value.strip()]
        except ValueError as exc:
            raise ValueError(f"{field_name} 목록에 숫자가 아닌 값이 있습니다.") from exc

    @staticmethod
    def _parse_optional_float(text, field_name):
        value = text.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"{field_name}은 숫자로 입력하세요.") from exc


# IO 관련 코드: 열린 VISA/Serial/LAN 연결의 명령 송신과 응답 수신 차이를 처리한다.
class DeviceIO:
    def __init__(self, resource, connection_type: str, default_eol: str = "\n"):
        self.resource = resource
        self.connection_type = connection_type.upper()
        self.default_eol = default_eol

    @property
    def resource_name(self) -> str:
        return getattr(self.resource, "resource_name", "")

    @property
    def peer_host(self) -> str:
        """Return the remote host for LAN sockets, when available."""
        if self.connection_type != "LAN":
            return ""
        try:
            return self.resource.getpeername()[0]
        except OSError:
            return ""

    def close(self):
        self.resource.close()

    def write(self, command: str, eol: str | None = None):
        if self.connection_type == "VISA":
            self.resource.write(command)
            return

        line_end = self.default_eol if eol is None else eol
        payload = (command + line_end).encode("ascii")
        if self.connection_type == "SERIAL":
            self.resource.write(payload)
        elif self.connection_type == "LAN":
            self.resource.sendall(payload)
        else:
            raise ValueError(f"지원하지 않는 연결 방식: {self.connection_type}")

    def read_line(self, timeout: float = 3.0) -> str:
        if self.connection_type == "SERIAL":
            self.resource.timeout = timeout
            return self.resource.readline().decode("ascii", errors="ignore").strip()
        if self.connection_type != "LAN":
            raise TypeError("read_line은 Serial 또는 LAN 연결에서만 사용합니다.")

        self.resource.settimeout(timeout)
        data = bytearray()
        while True:
            chunk = self.resource.recv(1)
            if not chunk:
                raise ConnectionError("장비가 응답 중 연결을 종료했습니다.")
            data.extend(chunk)
            if chunk == b"\n":
                return data.decode("ascii", errors="ignore").strip()

    def read_until(
        self,
        terminators: tuple[bytes, ...] = (b"EN\r\n", b"EN\n"),
        timeout: float = 3.0,
        max_bytes: int = 65536,
    ) -> str:
        if self.connection_type != "LAN":
            raise TypeError("read_until은 LAN 연결에서만 사용합니다.")

        self.resource.settimeout(timeout)
        data = bytearray()
        while len(data) < max_bytes:
            chunk = self.resource.recv(4096)
            if not chunk:
                raise ConnectionError("장비가 응답 중 연결을 종료했습니다.")
            data.extend(chunk)
            if any(terminator in data for terminator in terminators):
                return data.decode("ascii", errors="ignore").strip()
        raise ValueError(f"장비 응답이 최대 크기({max_bytes} bytes)를 초과했습니다.")

    def query_line(
        self, command: str, eol: str | None = None, timeout: float = 3.0
    ) -> str:
        if self.connection_type == "VISA":
            return self.resource.query(command).strip()
        self.write(command, eol=eol)
        return self.read_line(timeout=timeout)

    def query_until(
        self,
        command: str,
        terminators: tuple[bytes, ...] = (b"EN\r\n", b"EN\n"),
        eol: str | None = None,
        timeout: float = 3.0,
    ) -> str:
        self.write(command, eol=eol)
        return self.read_until(terminators=terminators, timeout=timeout)


if __name__ == "__main__":
    root = tk.Tk()
    app = PowerAnalyzerGUI(root)
    root.mainloop()
