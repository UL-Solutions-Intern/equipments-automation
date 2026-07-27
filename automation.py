import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import pyvisa
import serial
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

from devices.cvcf.factory import create_cvcf
from devices.recorder.factory import create_recorder
from devices.power_meter.factory import create_power_meter
from test_models import (
    DeviceStatus,
    ElectricalMode,
    TestPlan,
    build_test_conditions,
)
from test_runner import TestRunner
from pdf_converter import convert_raw_to_pdf
from result_folders import create_unique_test_folder, default_results_root

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
        self.log_popup = None
        self.popup_log_box = None

        # VISA Resource Manager 생성
        self.rm = pyvisa.ResourceManager()

        # 기본 저장 루트 = 바탕화면/하이브리드레코더 pdf
        self.save_root_folder = str(default_results_root())
        self.save_folder = self.save_root_folder

        # UI 빌드
        self.build_gui()

    def build_gui(self):
        """Tkinter UI 구성"""
        scroll_container = tk.Frame(self.root)
        scroll_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            scroll_container,
            width=650,
            height=650,
            highlightthickness=0,
        )
        vertical_scrollbar = ttk.Scrollbar(
            scroll_container,
            orient="vertical",
            command=canvas.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            scroll_container,
            orient="horizontal",
            command=canvas.xview,
        )
        canvas.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

        vertical_scrollbar.pack(side="right", fill="y")
        horizontal_scrollbar.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        main_frame = tk.Frame(canvas, padx=24, pady=14)
        main_window = canvas.create_window(
            (0, 0),
            window=main_frame,
            anchor="n",
        )

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_content_width(event=None):
            viewport_width = event.width if event is not None else canvas.winfo_width()
            if hasattr(self, "_setting_groups"):
                settings_gap = max(
                    2,
                    min(18, int((viewport_width - 620) / 15)),
                )
                if getattr(self, "_settings_gap", None) != settings_gap:
                    self._settings_gap = settings_gap
                    for index, group in enumerate(self._setting_groups):
                        group.grid(
                            row=0,
                            column=index,
                            padx=settings_gap,
                            pady=0,
                            sticky="n",
                        )
                    main_frame.update_idletasks()
            content_width = max(main_frame.winfo_reqwidth(), viewport_width)
            if hasattr(self, "log_frame"):
                self.log_frame.configure(width=max(120, viewport_width - 48))
            canvas.coords(main_window, content_width / 2, 0)
            canvas.itemconfigure(main_window, width=content_width)
            update_scroll_region()
            if content_width > viewport_width:
                centered_left = (content_width - viewport_width) / 2
                canvas.xview_moveto(centered_left / content_width)
            else:
                canvas.xview_moveto(0)

        def scroll_with_mouse_wheel(event):
            canvas.yview_scroll(-1 * int(event.delta / 120), "units")

        def scroll_horizontally_with_mouse_wheel(event):
            canvas.xview_scroll(-1 * int(event.delta / 120), "units")

        def attach_tooltip(widget, message):
            def show_tooltip(_event=None):
                if getattr(widget, "_tooltip_window", None) is not None:
                    return
                tooltip = tk.Toplevel(widget)
                tooltip.wm_overrideredirect(True)
                x = widget.winfo_rootx() + widget.winfo_width() + 6
                y = widget.winfo_rooty()
                tooltip.wm_geometry(f"+{x}+{y}")
                tk.Label(
                    tooltip,
                    text=message or " ",
                    anchor="nw",
                    justify="left",
                    wraplength=360,
                    font=("맑은 고딕", 8),
                    background="#fffde7",
                    relief="solid",
                    borderwidth=1,
                    padx=8,
                    pady=6,
                ).pack()
                widget._tooltip_window = tooltip

            def hide_tooltip(_event=None):
                tooltip = getattr(widget, "_tooltip_window", None)
                if tooltip is not None:
                    tooltip.destroy()
                    widget._tooltip_window = None

            widget.bind("<Enter>", show_tooltip)
            widget.bind("<Leave>", hide_tooltip)

        def create_help_button(parent, message):
            button = tk.Button(
                parent,
                text="?",
                width=1,
                font=("맑은 고딕", 8, "bold"),
                padx=1,
                pady=0,
            )
            attach_tooltip(button, message)
            return button

        main_frame.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_content_width)
        self.root.bind_all("<MouseWheel>", scroll_with_mouse_wheel)
        self.root.bind_all("<Shift-MouseWheel>", scroll_horizontally_with_mouse_wheel)

        top_frame = tk.Frame(main_frame)  # 장비 주소 입력
        top_frame.pack(anchor="center", pady=(0, 14))

        setting_frame = tk.Frame(main_frame)  # 테스트 설정 입력
        setting_frame.pack(fill="x", pady=(0, 12))
        left_settings = tk.Frame(setting_frame)
        center_settings = tk.Frame(setting_frame)
        right_settings = tk.Frame(setting_frame)
        left_settings.grid(row=0, column=0, padx=18, sticky="n")
        center_settings.grid(row=0, column=1, padx=18, sticky="n")
        right_settings.grid(row=0, column=2, padx=18, sticky="n")
        for column in range(3):
            setting_frame.grid_columnconfigure(column, weight=1)
        self._setting_groups = (left_settings, center_settings, right_settings)

        self.overload_enabled_var = tk.BooleanVar(value=True)
        overload_header = tk.Frame(main_frame)
        tk.Label(
            overload_header,
            text="OverLoad 설정",
            fg="black",
            font=("맑은 고딕", 9, "bold"),
        ).pack(side="left")
        self.overload_check = tk.Checkbutton(
            overload_header,
            text="OverLoad 테스트 수행",
            variable=self.overload_enabled_var,
            fg="black",
            command=self._toggle_overload_controls,
        )
        self.overload_check.pack(side="left", padx=(14, 0))
        tk.Label(
            overload_header,
            text="오버로드 쉬는 시간 (s):",
            fg="black",
        ).pack(side="left", padx=(22, 8))
        self.overload_rest_entry = tk.Entry(overload_header, width=10)
        self.overload_rest_entry.pack(side="left")
        self.overload_rest_entry.insert(0, "1800")

        overload_frame = tk.LabelFrame(
            main_frame,
            labelwidget=overload_header,
            padx=16,
            pady=10,
        )
        overload_frame.pack(anchor="center", pady=(0, 12))

        control_frame = tk.Frame(main_frame)  # 제어 버튼
        control_frame.pack(fill="x", pady=(2, 12))
        button_frame = tk.Frame(control_frame)
        button_frame.pack(anchor="center")

        progress_frame = tk.Frame(main_frame)
        progress_frame.pack(anchor="center", pady=(0, 10))

        output_frame = tk.Frame(main_frame)
        output_frame.pack(anchor="center", pady=(0, 10))

        log_header = tk.Frame(main_frame)
        tk.Label(log_header, text="로그").pack(side="left")
        tk.Button(
            log_header,
            text="크게 보기",
            command=self.open_log_popup,
            padx=6,
            pady=0,
        ).pack(side="left", padx=(8, 0))

        self.log_frame = tk.LabelFrame(
            main_frame,
            labelwidget=log_header,
            width=850,
            height=220,
            padx=8,
            pady=8,
        )
        self.log_frame.pack(anchor="center", pady=(0, 4))
        self.log_frame.pack_propagate(False)

        # 장비 주소 입력 필드
        self.device_entries = {}

        for i, label in enumerate(DEVICE_LABELS):
            row = i + 1

            tk.Label(top_frame, text=label).grid(
                row=row, column=0, sticky="e", pady=(2, 2)
            )
            entry = tk.Entry(top_frame, width=48)
            entry.grid(
                row=row,
                column=1,
                columnspan=3,
                sticky="w",
                padx=8,
                pady=(3, 3),
            )
            self.device_entries[label] = entry

        top_frame.grid_columnconfigure(1, weight=0)

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
        tk.Label(left_settings, text="시험명:").grid(row=0, column=0, sticky="e")
        self.test_name_combo = ttk.Combobox(
            left_settings,
            values=["Normal", "Abnormal", "Fault"],
            state="normal",
            width=10,
        )
        self.test_name_combo.grid(row=0, column=1, padx=(8, 0), pady=3)
        self.test_name_combo.set("Normal")

        # AC/DC 선택 콤보박스
        tk.Label(center_settings, text="출력 모드:").grid(
            row=2, column=0, sticky="e"
        )
        self.electrical_mode_combo = ttk.Combobox(
            center_settings,
            values=[ElectricalMode.AC.value, ElectricalMode.DC.value],
            state="readonly",
            width=5,
        )
        self.electrical_mode_combo.grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3
        )
        self.electrical_mode_combo.set(ElectricalMode.AC.value)
        self.electrical_mode_combo.bind(
            "<<ComboboxSelected>>",
            self._on_electrical_mode_changed,
        )

        tk.Label(left_settings, text="전압 시퀀스 (V):").grid(
            row=1, column=0, sticky="e"
        )
        self.voltage_entry = tk.Entry(left_settings, width=12)
        self.voltage_entry.grid(row=1, column=1, padx=(8, 0), pady=3)
        self.voltage_entry.insert(0, "90,264")

        # 시험 시간 입력
        tk.Label(center_settings, text="시험 시간 (s):").grid(
            row=0, column=0, sticky="e"
        )
        self.wait_entry = tk.Entry(center_settings, width=10)
        self.wait_entry.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        self.wait_entry.insert(0, "5400")

        self.sampling_entry = tk.Entry(setting_frame)
        self.sampling_entry.insert(0, "1")

        tk.Label(right_settings, text="쉬는 시간 (s):").grid(
            row=0, column=0, sticky="e"
        )
        self.condition_rest_entry = tk.Entry(right_settings, width=10)
        self.condition_rest_entry.grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=3
        )
        self.condition_rest_entry.insert(0, "600")

        tk.Label(left_settings, text="주파수 시퀀스 (Hz):").grid(
            row=2, column=0, sticky="e"
        )
        self.frequency_entry = tk.Entry(left_settings, width=10)
        self.frequency_entry.grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3
        )
        self.frequency_entry.insert(0, "50,60")

        # 부하 전류 입력
        tk.Label(center_settings, text="부하 전류 (A):").grid(
            row=1, column=0, sticky="e"
        )
        self.current_entry = tk.Entry(center_settings, width=10)
        self.current_entry.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)
        self.current_entry.insert(0, "11.0")

        # HR 채널 범위 입력 (온도 센서)
        tk.Label(right_settings, text="HR 채널 (시작,끝):").grid(
            row=1, column=0, sticky="e"
        )
        self.HR_entry = tk.Entry(right_settings, width=10)
        self.HR_entry.grid(row=1, column=1, padx=(8, 0), pady=3)
        self.HR_entry.insert(0, "0001,0008")

        hr_channel_tooltip_message = "MV2000: 0001~0010,0011~0020\n" \
        "GP20: 0001~0010, 0101~0110, 0201~0210"
        self.hr_channel_help_btn = create_help_button(
            right_settings,
            hr_channel_tooltip_message,
        )
        self.hr_channel_help_btn.grid(row=1, column=2, padx=(8, 0))

        tk.Label(right_settings, text="비교할 시간:").grid(
            row=2, column=0, sticky="e"
        )
        self.compare_time_entry = tk.Entry(right_settings, width=10)
        self.compare_time_entry.grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3
        )
        self.compare_time_entry.insert(0, "1800")
        compare_time_tooltip_message = "포화상태 체크를 위해\n비교할 시간을 입력해주세요."
        self.compare_time_help_btn = create_help_button(
            right_settings,
            compare_time_tooltip_message,
        )
        self.compare_time_help_btn.grid(row=2, column=2, padx=(8, 0), pady=3)

        tk.Label(overload_frame, text="T1 Coil 채널:", fg="black").grid(
            row=0, column=0, sticky="e", padx=(0, 8)
        )
        self.t1_coil_channel_combo = ttk.Combobox(
            overload_frame,
            values=[f"{channel:04d}" for channel in range(1, 49)],
            state="readonly",
            width=10,
        )
        self.t1_coil_channel_combo.grid(row=0, column=1, sticky="w")
        self.t1_coil_channel_combo.set("0001")

        tk.Label(overload_frame, text="오버로드 대상 시험:", fg="black").grid(
            row=0, column=2, sticky="e", padx=(28, 8)
        )
        self.overload_target_entry = tk.Entry(
            overload_frame,
            width=15,
            disabledforeground="#666666",
        )
        self.overload_target_entry.grid(row=0, column=3, sticky="w")
        self.overload_target_entry.insert(0, "Normal_90V_50Hz")
        self._toggle_overload_controls()

        # 제어 버튼
        self.start_test_btn = tk.Button(
            button_frame, text="테스트 시작", width=15, command=self.start_test
        )
        self.start_test_btn.grid(row=0, column=0, padx=10)

        self.stop_test_btn = tk.Button(
            button_frame, text="테스트 중지", width=15, command=self.stop_test
        )
        self.stop_test_btn.grid(row=0, column=1, padx=10)

        self.folder_btn = tk.Button(
            button_frame, text="폴더 지정", width=15, command=self.select_folder
        )
        self.folder_btn.grid(row=0, column=2, padx=10)

        # 폴더 경로 표시
        self.folder_label = tk.Label(
            control_frame, text=f"저장 폴더: {self.save_folder}", anchor="w", fg="blue"
        )
        self.folder_label.pack(anchor="center", padx=10, pady=(5, 0))

        tk.Label(progress_frame, text="[현재 진행중인 테스트]").grid(
            row=0, column=0, sticky="w", padx=(0, 16), pady=3
        )
        tk.Label(progress_frame, text="테스트 이름:").grid(
            row=0, column=1, sticky="w", padx=(0, 8), pady=3
        )
        self.current_test_label = tk.Label(
            progress_frame,
            text="대기 중",
            anchor="w",
        )
        self.current_test_label.grid(
            row=0, column=2, sticky="w", padx=(0, 36), pady=3
        )

        tk.Label(progress_frame, text="진행 시간:").grid(
            row=0, column=3, sticky="w", padx=(0, 8), pady=3
        )
        self.elapsed_time_label = tk.Label(
            progress_frame,
            text="0초",
            anchor="w",
        )
        self.elapsed_time_label.grid(row=0, column=4, sticky="w", pady=3)

        # 실시간 측정값 표시
        tk.Label(output_frame, text="[실시간 측정값]").pack(
            side="left", anchor="w", padx=(0, 16)
        )
        self.dl_values_label = tk.Label(
            output_frame, text="DL 측정값: V=N/A, A=N/A"
        )
        self.dl_values_label.pack(side="left", anchor="w")

        self.pm_values_label = tk.Label(
            output_frame, text="PM 측정값: V=N/A, A=N/A, Hz=N/A"
        )
        self.pm_values_label.pack(side="left", anchor="w", padx=(16, 0))

        # 로그 출력 박스
        log_content = tk.Frame(self.log_frame)
        log_content.pack(fill="both", expand=True)
        log_scrollbar = ttk.Scrollbar(log_content, orient="vertical")
        self.log_box = tk.Text(
            log_content,
            height=10,
            yscrollcommand=log_scrollbar.set,
        )
        log_scrollbar.configure(command=self.log_box.yview)
        log_scrollbar.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)
        self.root.after_idle(fit_content_width)

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

    def _toggle_overload_controls(self):
        """OverLoad 수행 여부에 따라 관련 설정 입력을 활성화한다."""
        enabled = self.overload_enabled_var.get()
        self.t1_coil_channel_combo.config(
            state="readonly" if enabled else "disabled"
        )
        entry_state = tk.NORMAL if enabled else tk.DISABLED
        self.overload_rest_entry.config(state=entry_state)
        self.overload_target_entry.config(state=entry_state)

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
            line = f"[{timestamp}] {text}\n"
            self.log_box.insert(tk.END, line)
            self.log_box.see(tk.END)
            if (
                self.popup_log_box is not None
                and self.popup_log_box.winfo_exists()
            ):
                self.popup_log_box.insert(tk.END, line)
                self.popup_log_box.see(tk.END)

        self.root.after(0, append_log)

    def open_log_popup(self):
        """현재 로그를 크기 조절 가능한 별도 창에서 표시한다."""
        if self.log_popup is not None and self.log_popup.winfo_exists():
            self.log_popup.deiconify()
            self.log_popup.lift()
            self.log_popup.focus_force()
            return

        self.log_popup = tk.Toplevel(self.root)
        self.log_popup.title("통합 테스트 시스템 - 로그")
        self.log_popup.geometry("900x600")
        self.log_popup.minsize(450, 300)

        popup_frame = tk.Frame(self.log_popup, padx=8, pady=8)
        popup_frame.pack(fill="both", expand=True)
        popup_scrollbar = ttk.Scrollbar(popup_frame, orient="vertical")
        self.popup_log_box = tk.Text(
            popup_frame,
            yscrollcommand=popup_scrollbar.set,
        )
        popup_scrollbar.configure(command=self.popup_log_box.yview)
        popup_scrollbar.pack(side="right", fill="y")
        self.popup_log_box.pack(side="left", fill="both", expand=True)
        self.popup_log_box.insert("1.0", self.log_box.get("1.0", tk.END))
        self.popup_log_box.see(tk.END)

        def close_popup():
            self.log_popup.destroy()
            self.log_popup = None
            self.popup_log_box = None

        self.log_popup.protocol("WM_DELETE_WINDOW", close_popup)

    def select_folder(self):
        """결과 저장 폴더 지정"""
        folder_selected = filedialog.askdirectory(
            initialdir=self.save_root_folder, title="저장 폴더 선택"
        )
        if folder_selected:
            self.save_root_folder = folder_selected
            self.save_folder = folder_selected
            self.folder_label.config(text=f"저장 폴더: {self.save_folder}")
            self.log(f"저장 기본 폴더가 '{self.save_folder}'(으)로 설정되었습니다.")
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

        try:
            test_output_folder = create_unique_test_folder(self.save_root_folder)
        except OSError as exc:
            self.log(f"시험 결과 폴더 생성 오류: {exc}")
            messagebox.showerror(
                "시험 시작 오류",
                f"시험 결과 폴더를 만들 수 없습니다.\n{exc}",
            )
            return

        self.save_folder = str(test_output_folder)
        self.folder_label.config(text=f"저장 폴더: {self.save_folder}")
        self.log(f"시험 결과 폴더 생성 완료: {self.save_folder}")

        self.stop_event.clear()
        self.is_testing = True
        self.test_runner = TestRunner(
            recorder=self.devices[RECORDER].driver,
            cvcf=self.devices[POWER_SUPPLY].driver,
            power_meter=self.devices[POWER_METER].driver,
            output_folder=self.save_folder,
            log_callback=self.log,
            pdf_converter=convert_raw_to_pdf,
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
        comparison_window = float(self.compare_time_entry.get())
        condition_rest_seconds = float(self.condition_rest_entry.get())
        if duration <= 0 or sample_interval <= 0 or comparison_window <= 0:
            raise ValueError(
                "시험 시간, 샘플링 간격, 비교할 시간은 0보다 커야 합니다."
            )
        if condition_rest_seconds < 0:
            raise ValueError("쉬는 시간은 0 이상이어야 합니다.")

        try:
            first_channel, last_channel = [
                value.strip() for value in self.HR_entry.get().split(",")
            ]
        except ValueError as exc:
            raise ValueError("HR 채널은 시작,끝 형식으로 입력하세요.") from exc
        recorder = self.devices[RECORDER].driver
        temperature_channels = recorder.get_temperature_channels(
            first_channel, last_channel
        )

        cvcf = self.devices[POWER_SUPPLY].driver
        voltages = self._parse_float_list(self.voltage_entry.get(), "전압")
        frequencies = (
            self._parse_float_list(self.frequency_entry.get(), "주파수")
            if electrical_mode == ElectricalMode.AC
            else []
        )
        if cvcf is None:
            current_limit = None
        else:
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
            cooldown_seconds=condition_rest_seconds,
            first_channel=first_channel,
            last_channel=last_channel,
            temperature_channels=temperature_channels,
            current_limit=current_limit,
            saturation_check_seconds=duration,
            saturation_recheck_seconds=600,
            stabilization_window_seconds=comparison_window,
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
