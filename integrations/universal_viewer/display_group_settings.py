"""Universal Viewer 표시 그룹 설정창 안전 조사(Stage 5A)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .config import AppConfig
from .cursor_value import normalize_universal_viewer_main_window
from .viewer_launcher import (
    ViewerOpenResult,
    collect_opened_raw_file_hints,
    matching_work_copy_hints,
    open_prepared_raw_file,
)
from .viewer_discovery import WindowInfo


DISPLAY_GROUP_MENU_PATH = "표시(V) > 표시 그룹 설정(D)..."
DISPLAY_TOP_MENU_CANDIDATES = ("표시", "View")
DISPLAY_GROUP_MENU_CANDIDATES = (
    "표시 그룹 설정",
    "표시그룹 설정",
    "Display Group Settings",
    "Display Group",
)
DISPLAY_GROUP_DIALOG_TITLE_CANDIDATES = (
    "표시 그룹 설정",
    "표시그룹 설정",
    "Display Group Settings",
    "Display Group",
)
SAFE_CLOSE_BUTTON_TITLES = ("취소", "Cancel", "닫기", "Close")
FORBIDDEN_COMMIT_BUTTON_TITLES = ("확인", "OK", "적용", "Apply", "저장", "Save")
CHANNEL_LABEL_PATTERN = re.compile(r"\bCH\d{3}\b", re.IGNORECASE)
DISPLAY_GROUP_DIALOG_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.5


class DisplayGroupInspectionError(RuntimeError):
    """표시 그룹 설정창 안전 조사에 실패했을 때 발생한다."""


OpenRawFileFunction = Callable[..., ViewerOpenResult]
MenuOpenFunction = Callable[[ViewerOpenResult, logging.Logger], str]
DialogDetectorFunction = Callable[[int | None, tuple[int, ...], logging.Logger], "Win32WindowSnapshot"]
StructureCollectorFunction = Callable[["Win32WindowSnapshot"], "DisplayGroupDialogSnapshot"]
CloseDialogFunction = Callable[["DisplayGroupDialogSnapshot", logging.Logger], str]
RawHintCollector = Callable[[int | None], tuple[str, ...]]
PauseInputFunction = Callable[[str], str]
MessagePrinter = Callable[[str], None]
GeometryClickFunction = Callable[[tuple[int, int]], None]
GeometryDragFunction = Callable[[tuple[int, int], tuple[int, int]], None]
GeometryMoveFunction = Callable[[tuple[int, int]], None]
GeometryScrollFunction = Callable[[int], None]
GeometryWaitFunction = Callable[[float], None]
DialogReadyFunction = Callable[["Win32WindowSnapshot", logging.Logger], "Win32WindowSnapshot | None"]
MousePositionFunction = Callable[[], tuple[int, int]]
UnexpectedPopupDetectorFunction = Callable[[int | None], tuple["Win32WindowSnapshot", ...]]
TimeAxisFullDisplayFunction = Callable[..., "TimeAxisFullDisplayResult"]
UiaDesktopFactory = Callable[[str], object]

DISPLAY_GROUP_ACTION_WAIT_SECONDS = 0.5
DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS = 0.8
DISPLAY_GROUP_CONTINUOUS_SHORT_WAIT_SECONDS = 0.3
DISPLAY_GROUP_CALIBRATED_SCROLL_WAIT_SECONDS = 0.8
DISPLAY_GROUP_GRID_FOCUS_REL = (0.183, 0.230)
DISPLAY_GROUP_SCROLLBAR_THUMB_START_REL = (0.549, 0.558)
DISPLAY_GROUP_SCROLLBAR_THUMB_END_REL = (0.549, 0.831)
DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL = (0.975, 0.872)
DISPLAY_GROUP_SCROLLBAR_UP_CLICK_REL = (0.974, 0.183)
DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL = (0.046, 0.446)
DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL = (0.047, 0.664)
DISPLAY_GROUP_SCROLLED_DESTINATION_W40_REFERENCE_REL = (0.042, 0.642)
DISPLAY_GROUP_SCROLLED_DESTINATION_W50_REFERENCE_REL = (0.048, 0.864)
DISPLAY_GROUP_OK_BUTTON_REL = (0.148, 0.961)
UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL = (0.147, 0.075)
UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL = (0.164, 0.237)
UNIVERSAL_VIEWER_TIME_AXIS_MENU_WAIT_SECONDS = 0.3
UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_WAIT_SECONDS = 0.5
UNIVERSAL_VIEWER_TIME_AXIS_MENU_TEXT = "시간축"
UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_TEXTS = ("전부표시", "전부 표시")
UNIVERSAL_VIEWER_GROUP_SETTING_BUTTON_TEXT = "Group Setting"


@dataclass(frozen=True, slots=True)
class Win32WindowSnapshot:
    """win32gui로 읽은 창 또는 child control 정보."""

    hwnd: int
    title: str
    class_name: str
    pid: int | None
    visible: bool
    enabled: bool
    rectangle: str = ""
    control_id: int | None = None
    depth: int = 0


@dataclass(frozen=True, slots=True)
class UiaElementSnapshot:
    """UI Automation으로 읽은 요소 정보."""

    name: str
    control_type: str
    automation_id: str
    class_name: str
    enabled: bool | None
    rectangle: str
    source: str = ""


@dataclass(frozen=True, slots=True)
class UiaCollectionResult:
    """UIA 다중 수집 시도 결과."""

    elements: tuple[UiaElementSnapshot, ...]
    attempt_logs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeometryAreaCandidate:
    """대화상자 기준 상대 영역과 실제 화면 절대 영역."""

    name: str
    description: str
    relative_rect: tuple[float, float, float, float]
    absolute_rect: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class GeometryLineCandidate:
    """대화상자 기준 상대 x/y 또는 높이 후보."""

    name: str
    description: str
    relative_value: float
    absolute_value: int
    axis: str


@dataclass(frozen=True, slots=True)
class DisplayGroupGeometryProfile:
    """표시 그룹 설정창 custom-drawn UI의 상대 좌표 기반 초기 프로필."""

    name: str
    top_tab_row_area: tuple[float, float, float, float]
    group_name_field_area: tuple[float, float, float, float]
    grid_area: tuple[float, float, float, float]
    first_row_y_ratio: float
    row_height_ratio: float
    checkbox_column_x_ratio: float
    channel_column_x_ratio: float
    ok_button_area: tuple[float, float, float, float]
    cancel_button_area: tuple[float, float, float, float]
    apply_button_area: tuple[float, float, float, float]
    scale_calculation_button_area: tuple[float, float, float, float]
    copy_detail_button_area: tuple[float, float, float, float]
    paste_button_area: tuple[float, float, float, float]
    group_tab_x_ratios: tuple[float, ...]
    group_tab_y_ratio: float
    drag_select_start_x_ratio: float
    drag_select_end_x_ratio: float


@dataclass(frozen=True, slots=True)
class DisplayGroupGeometryReport:
    """표시 그룹 설정창 geometry 후보 계산 결과."""

    profile_name: str
    dialog_rect: tuple[int, int, int, int]
    width: int
    height: int
    areas: tuple[GeometryAreaCandidate, ...]
    lines: tuple[GeometryLineCandidate, ...]


@dataclass(frozen=True, slots=True)
class DisplayGroupGeometryInspectionResult:
    """Stage 5B geometry 기반 표시 그룹 설정창 조사 결과."""

    opened: ViewerOpenResult
    report_path: Path
    menu_path: str
    dialog: Win32WindowSnapshot
    geometry: DisplayGroupGeometryReport
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str


@dataclass(frozen=True, slots=True)
class HeatingPointGridPosition:
    """Heating Point index가 표시 그룹 설정 grid에서 차지할 group/page와 row."""

    heating_point_index: int
    group_no: int
    row_no: int


@dataclass(frozen=True, slots=True)
class PlannedGeometryAction:
    """실제 클릭 없이 기록하는 geometry 기반 예정 작업."""

    step: int
    action_type: str
    description: str
    group_no: int | None = None
    row_no: int | None = None
    point: tuple[int, int] | None = None
    drag_start: tuple[int, int] | None = None
    drag_end: tuple[int, int] | None = None
    heating_points: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DisplayGroupGeometryActionPreview:
    """표시 그룹 geometry 자동화 예정 작업 미리보기."""

    heating_point_count: int
    positions: tuple[HeatingPointGridPosition, ...]
    tab_coordinates: tuple[tuple[int, tuple[int, int]], ...]
    actions: tuple[PlannedGeometryAction, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisplayGroupActionPreviewInspectionResult:
    """표시 그룹 geometry action preview 결과."""

    opened: ViewerOpenResult
    report_path: Path
    menu_path: str
    dialog: Win32WindowSnapshot
    geometry: DisplayGroupGeometryReport
    preview: DisplayGroupGeometryActionPreview
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str
    report_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TimeAxisFullDisplayResult:
    """Universal Viewer 시간축 > 전부 표시 좌표 실행/미리보기 결과."""

    main_window_rect: tuple[int, int, int, int]
    time_axis_menu_point: tuple[int, int]
    time_axis_full_display_point: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ExecutedGeometryAction:
    """실제-click test mode에서 수행한 제한된 geometry action."""

    action_type: str
    description: str
    point: tuple[int, int] | None = None
    drag_start: tuple[int, int] | None = None
    drag_end: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class ActualClickTestStep:
    """개발 검증용 actual-click test의 명시적 실행 단계."""

    step: int
    action_type: str
    description: str
    point: tuple[int, int] | None = None
    drag_start: tuple[int, int] | None = None
    drag_end: tuple[int, int] | None = None
    scroll_amount: int | None = None
    wait_after_seconds: float = DISPLAY_GROUP_ACTION_WAIT_SECONDS
    move_before_click: bool = False


@dataclass(frozen=True, slots=True)
class DisplayGroupApplyTestResult:
    """Stage 5 개발 검증용 실제-click test mode 결과."""

    opened: ViewerOpenResult
    menu_path: str
    dialog: Win32WindowSnapshot
    geometry: DisplayGroupGeometryReport
    preview: DisplayGroupGeometryActionPreview
    executed_actions: tuple[ExecutedGeometryAction, ...]
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str
    safety_summary: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScrollbarCalibrationPoint:
    """표시 그룹 설정창 scrollbar 보정용으로 운영자가 찍은 한 지점."""

    name: str
    absolute: tuple[int, int]
    relative: tuple[float, float]


@dataclass(frozen=True, slots=True)
class DisplayGroupScrollbarCalibrationResult:
    """표시 그룹 설정창 vertical scrollbar 좌표 보정 pause mode 결과."""

    opened: ViewerOpenResult
    menu_path: str
    dialog: Win32WindowSnapshot
    geometry: DisplayGroupGeometryReport
    points: tuple[ScrollbarCalibrationPoint, ...]
    output_lines: tuple[str, ...]
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str


@dataclass(frozen=True, slots=True)
class DisplayGroupApplyConfirmedResult:
    """Stage 5 confirmed apply mode 결과. 이 모드에서만 OK 클릭이 허용된다."""

    opened: ViewerOpenResult
    menu_path: str
    dialog: Win32WindowSnapshot
    geometry: DisplayGroupGeometryReport
    preview: DisplayGroupGeometryActionPreview
    executed_actions: tuple[ExecutedGeometryAction, ...]
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str
    safety_summary: tuple[str, ...]


DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE = DisplayGroupGeometryProfile(
    name="universal_viewer_display_group_calibrated_relative_profile",
    # 실제 확인된 대화상자 예: (430, 50, 1368, 777). 모든 값은 대화상자 크기 대비 비율이다.
    top_tab_row_area=(0.01, 0.03, 0.99, 0.10),
    group_name_field_area=(0.02, 0.11, 0.98, 0.18),
    grid_area=(0.02, 0.20, 0.98, 0.86),
    first_row_y_ratio=0.199,
    row_height_ratio=0.022,
    checkbox_column_x_ratio=0.019,
    channel_column_x_ratio=0.150,
    ok_button_area=(0.128, 0.941, 0.168, 0.981),
    cancel_button_area=(0.327, 0.942, 0.367, 0.982),
    apply_button_area=(0.347, 0.942, 0.387, 0.982),
    scale_calculation_button_area=(0.512, 0.942, 0.552, 0.982),
    copy_detail_button_area=(0.693, 0.942, 0.733, 0.982),
    paste_button_area=(0.872, 0.942, 0.912, 0.982),
    group_tab_x_ratios=(0.018, 0.043, 0.070, 0.096, 0.123),
    group_tab_y_ratio=0.057,
    drag_select_start_x_ratio=0.055,
    drag_select_end_x_ratio=0.960,
)


DISPLAY_GROUP_PROFILE_SIZE_TOLERANCE_PX = 25
DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736 = {
    "dialog_title": "표시 그룹 설정",
    "dialog_class": "#32770",
    "dialog_size": (942, 736),
    "tab_01": (0.023355, 0.067935),
    "tab_02": (0.046709, 0.070652),
    "tab_03": (0.073248, 0.072011),
    "tab_04": (0.096603, 0.072011),
    "tab_05": (0.124204, 0.070652),
    "source_w01_start": (0.048832, 0.207880),
    "source_w10_end": (0.049894, 0.400815),
    "source_w08_end": (0.050955, 0.361413),
    "copy_detail": (0.685775, 0.955163),
    "paste": (0.866242, 0.959239),
    "ok": (0.162420, 0.963315),
    "dest_w11_start": (0.052017, 0.422554),
    "dest_w20_end": (0.048832, 0.618207),
    "dest_w21_start": (0.052017, 0.641304),
    "dest_w30_end": (0.049894, 0.838315),
    "scroll_down": (0.973461, 0.861413),
    "scroll_up": (0.973461, 0.201087),
    "dest_w31_start": (0.055202, 0.448370),
    "dest_w40_end": (0.045648, 0.645380),
    "dest_w41_start": (0.046709, 0.668478),
    "dest_w48_end": (0.048832, 0.820652),
}
DISPLAY_GROUP_COORDINATE_PROFILES = (DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736,)


@dataclass(frozen=True, slots=True)
class DisplayGroupDialogSnapshot:
    """표시 그룹 설정창 조사 결과."""

    top_level: Win32WindowSnapshot
    win32_children: tuple[Win32WindowSnapshot, ...]
    uia_elements: tuple[UiaElementSnapshot, ...]
    uia_attempt_logs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisplayGroupInspectionResult:
    """Stage 5A 표시 그룹 설정창 안전 조사 결과."""

    opened: ViewerOpenResult
    report_path: Path
    menu_path: str
    dialog: DisplayGroupDialogSnapshot
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool
    close_method: str


def inspect_display_group_settings(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    structure_collector_fn: StructureCollectorFunction | None = None,
    close_dialog_fn: CloseDialogFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    now: datetime | None = None,
    pause_before_close: bool = False,
    pause_input_fn: PauseInputFunction | None = None,
    message_printer: MessagePrinter | None = None,
) -> DisplayGroupInspectionResult:
    """작업본을 열고 표시 그룹 설정창을 조사한 뒤 설정 변경 없이 닫는다."""
    logger.info("Stage 5A 표시 그룹 설정창 조사 시작 | 원본=%s", source_path)
    opened = open_raw_file_fn(
        source_path,
        config,
        logger,
        explicit_viewer_exe=explicit_viewer_exe,
    )
    logger.info("Stage 5A 작업본 열림 대상 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 표시 그룹 설정창 조사를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    collect_structure = structure_collector_fn or collect_display_group_dialog_structure
    close_dialog = close_dialog_fn or (
        close_display_group_dialog_with_escape if pause_before_close else close_display_group_dialog_without_applying
    )

    dialog_snapshot: DisplayGroupDialogSnapshot | None = None
    close_method = "not_started"
    try:
        menu_path = open_menu(opened, logger)
        logger.info("Stage 5A 메뉴 경로 사용 | %s", menu_path)
        dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
        logger.info(
            "표시 그룹 설정창 탐지 | title=%s | class=%s | HWND=%s | PID=%s",
            dialog_top.title,
            dialog_top.class_name,
            dialog_top.hwnd,
            dialog_top.pid if dialog_top.pid is not None else "확인 불가",
        )
        dialog_snapshot = collect_structure(dialog_top)
        for attempt_log in dialog_snapshot.uia_attempt_logs:
            logger.info("표시 그룹 설정창 UIA 조사: %s", attempt_log)
        if pause_before_close:
            message = "표시 그룹 설정창이 열린 상태입니다. 창을 확인한 뒤 Enter를 누르면 설정 변경 없이 ESC로 닫습니다."
            printer = message_printer or print
            wait_for_input = pause_input_fn or input
            printer(message)
            wait_for_input("")
        close_method = close_dialog(dialog_snapshot, logger)
        logger.info("설정 변경 없이 표시 그룹 설정창 닫기 완료 | method=%s", close_method)
    except Exception:
        if dialog_snapshot is not None:
            try:
                close_dialog(dialog_snapshot, logger)
                logger.info("오류 발생 후 표시 그룹 설정창 안전 닫기 완료")
            except Exception as close_exc:
                logger.warning("오류 발생 후 표시 그룹 설정창 닫기 실패: %s", close_exc)
        raise

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "표시 그룹 설정창 조사 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 조사 전 힌트={before_hints} | 조사 후 힌트={after_hints}"
        )

    report_time = now or datetime.now()
    report_path = config.logs_dir / f"display_group_settings_inspection_{report_time.strftime('%Y%m%d_%H%M%S')}.txt"
    result = DisplayGroupInspectionResult(
        opened=opened,
        report_path=report_path,
        menu_path=menu_path,
        dialog=dialog_snapshot,
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
    )
    write_display_group_inspection_report(result)
    return result


def inspect_display_group_geometry(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    now: datetime | None = None,
    pause_before_close: bool = False,
    pause_input_fn: PauseInputFunction | None = None,
    message_printer: MessagePrinter | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
) -> DisplayGroupGeometryInspectionResult:
    """표시 그룹 설정창을 열고 custom-drawn UI용 geometry 후보만 계산한다."""
    logger.info("Stage 5B 표시 그룹 설정창 geometry 조사 시작 | 원본=%s", source_path)
    opened = open_raw_file_fn(
        source_path,
        config,
        logger,
        explicit_viewer_exe=explicit_viewer_exe,
    )
    logger.info("Stage 5B 작업본 열림 대상 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 표시 그룹 geometry 조사를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape

    menu_path = open_menu(opened, logger)
    logger.info("Stage 5B 메뉴 경로 사용 | %s", menu_path)
    dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
    dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top
    logger.info(
        "표시 그룹 설정창 geometry 대상 탐지 | title=%s | class=%s | HWND=%s | PID=%s | rect=%s",
        dialog_top.title,
        dialog_top.class_name,
        dialog_top.hwnd,
        dialog_top.pid if dialog_top.pid is not None else "확인 불가",
        dialog_top.rectangle,
    )

    try:
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        report_time = now or datetime.now()
        report_path = config.logs_dir / f"display_group_geometry_inspection_{report_time.strftime('%Y%m%d_%H%M%S')}.txt"
        report_lines = build_display_group_geometry_report_lines(
            opened=opened,
            menu_path=menu_path,
            dialog=dialog_top,
            geometry=geometry,
            before_raw_file_hints=before_hints,
            after_raw_file_hints=(),
            state_unchanged=False,
            close_method="not_closed",
        )
        write_text_report_with_bom(report_path, report_lines)
        logger.info("Stage 5B geometry 후보 보고서 저장 | %s", report_path)

        if pause_before_close:
            printer = message_printer or print
            for line in report_lines:
                printer(line)
            printer("표시 그룹 설정창이 열린 상태입니다. 창을 확인한 뒤 Enter를 누르면 설정 변경 없이 ESC로 닫습니다.")
            wait_for_input = pause_input_fn or input
            wait_for_input("")
    except Exception:
        try:
            close_dialog(logger)
            logger.info("오류 발생 후 표시 그룹 geometry 창 ESC 닫기 완료")
        except Exception as close_exc:
            logger.warning("오류 발생 후 표시 그룹 geometry 창 닫기 실패: %s", close_exc)
        raise

    close_method = close_dialog(logger)
    logger.info("설정 변경 없이 표시 그룹 설정창 geometry 조사 닫기 완료 | method=%s", close_method)

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "표시 그룹 geometry 조사 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 조사 전 힌트={before_hints} | 조사 후 힌트={after_hints}"
        )

    result = DisplayGroupGeometryInspectionResult(
        opened=opened,
        report_path=report_path,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
    )
    write_display_group_geometry_report(result)
    return result


def preview_display_group_geometry_actions(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    heating_point_count: int,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    now: datetime | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
    move_fn: GeometryMoveFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    move_through_profile_points: bool = False,
) -> DisplayGroupActionPreviewInspectionResult:
    """표시 그룹 geometry 자동화 예정 좌표만 미리보기로 계산한다."""
    validate_heating_point_count(heating_point_count)
    logger.info("표시 그룹 geometry action preview 시작 | 원본=%s | heating_point_count=%s", source_path, heating_point_count)
    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("표시 그룹 geometry action preview 작업본 열림 대상 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 표시 그룹 geometry action preview를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    time_axis_preview = preview_time_axis_full_display_points(opened, logger)
    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape

    menu_path = open_menu(opened, logger)
    logger.info("geometry action preview 메뉴 경로 사용 | %s", menu_path)
    dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
    dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top

    try:
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        preview = calculate_display_group_geometry_action_preview(geometry, profile, heating_point_count)
        report_time = now or datetime.now()
        report_path = config.logs_dir / f"display_group_geometry_actions_preview_{report_time.strftime('%Y%m%d_%H%M%S')}.txt"
        initial_lines = build_display_group_action_preview_report_lines(
            opened=opened,
            menu_path=menu_path,
            dialog=dialog_top,
            geometry=geometry,
            preview=preview,
            before_raw_file_hints=before_hints,
            after_raw_file_hints=(),
            state_unchanged=False,
            close_method="not_closed",
            time_axis_preview=time_axis_preview,
        )
        write_text_report_with_bom(report_path, initial_lines)
        for action in preview.actions:
            logger.info("geometry action preview 예정 작업 | %s", format_planned_geometry_action(action))
    except Exception:
        try:
            close_dialog(logger)
            logger.info("오류 발생 후 geometry action preview 창 ESC 닫기 완료")
        except Exception as close_exc:
            logger.warning("오류 발생 후 geometry action preview 창 닫기 실패: %s", close_exc)
        raise

    close_method = close_dialog(logger)
    logger.info("geometry action preview 닫기 완료 | method=%s", close_method)

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "geometry action preview 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 조사 전 힌트={before_hints} | 조사 후 힌트={after_hints}"
        )

    report_lines = tuple(
        build_display_group_action_preview_report_lines(
            opened=opened,
            menu_path=menu_path,
            dialog=dialog_top,
            geometry=geometry,
            preview=preview,
            before_raw_file_hints=before_hints,
            after_raw_file_hints=after_hints,
            state_unchanged=state_unchanged,
            close_method=close_method,
            time_axis_preview=time_axis_preview,
        )
    )
    result = DisplayGroupActionPreviewInspectionResult(
        opened=opened,
        report_path=report_path,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        preview=preview,
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
        report_lines=report_lines,
    )
    write_text_report_with_bom(report_path, report_lines)
    return result


def preview_display_group_max_48_actions(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    now: datetime | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
    move_fn: GeometryMoveFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    move_through_profile_points: bool = False,
) -> DisplayGroupActionPreviewInspectionResult:
    """max-48 workflow의 geometry action을 실제 클릭 없이 미리보기로 계산한다."""
    logger.info("표시 그룹 max-48 geometry action preview 시작 | 원본=%s", source_path)
    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("표시 그룹 max-48 geometry action preview 작업본 열림 확인 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 표시 그룹 max-48 geometry action preview를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    time_axis_preview = preview_time_axis_full_display_points(opened, logger)
    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape

    menu_path = open_menu(opened, logger)
    logger.info("max-48 geometry action preview 메뉴 경로 사용 | %s", menu_path)
    dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
    dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top

    try:
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        coordinate_profile = require_display_group_coordinate_profile(dialog_top)
        logger.info(
            "Display Group coordinate profile selected for preview | title=%s | class=%s | size=%s",
            coordinate_profile["dialog_title"],
            coordinate_profile["dialog_class"],
            coordinate_profile["dialog_size"],
        )
        profile_sequence = build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            geometry.dialog_rect,
            coordinate_profile,
        )
        preview = build_display_group_coordinate_profile_preview(profile_sequence)
        report_time = now or datetime.now()
        report_path = config.logs_dir / f"display_group_max_48_actions_preview_{report_time.strftime('%Y%m%d_%H%M%S')}.txt"
        initial_lines = build_display_group_action_preview_report_lines(
            opened=opened,
            menu_path=menu_path,
            dialog=dialog_top,
            geometry=geometry,
            preview=preview,
            before_raw_file_hints=before_hints,
            after_raw_file_hints=(),
            state_unchanged=False,
            close_method="not_closed",
            time_axis_preview=time_axis_preview,
        )
        write_text_report_with_bom(report_path, initial_lines)
        for action in preview.actions:
            logger.info("max-48 geometry action preview 예정 작업 | %s", format_planned_geometry_action(action))
        if move_through_profile_points:
            move_action = move_fn or move_geometry_pointer
            logger.info("Display Group profile preview mouse move-through started; no click/drag will be performed")
            for action in preview.actions:
                for coordinate_name, point in (
                    ("point", action.point),
                    ("drag_start", action.drag_start),
                    ("drag_end", action.drag_end),
                ):
                    if point is None:
                        continue
                    logger.info(
                        "Display Group profile preview move | step=%s | type=%s | coordinate=%s | rel=%s | abs=%s",
                        action.step,
                        action.action_type,
                        coordinate_name,
                        relative_point(point, geometry.dialog_rect),
                        point,
                    )
                    move_action(point)
                    wait_fn(0.15)
    except Exception:
        try:
            close_dialog(logger)
            logger.info("오류 발생 후 max-48 geometry action preview 창 ESC 닫기 완료")
        except Exception as close_exc:
            logger.warning("오류 발생 후 max-48 geometry action preview 창 닫기 실패: %s", close_exc)
        raise

    close_method = close_dialog(logger)
    logger.info("max-48 geometry action preview 닫기 완료 | method=%s", close_method)

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "max-48 geometry action preview 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 조사 전 힌트={before_hints} | 조사 후 힌트={after_hints}"
        )

    report_lines = tuple(
        build_display_group_action_preview_report_lines(
            opened=opened,
            menu_path=menu_path,
            dialog=dialog_top,
            geometry=geometry,
            preview=preview,
            before_raw_file_hints=before_hints,
            after_raw_file_hints=after_hints,
            state_unchanged=state_unchanged,
            close_method=close_method,
            time_axis_preview=time_axis_preview,
        )
    )
    result = DisplayGroupActionPreviewInspectionResult(
        opened=opened,
        report_path=report_path,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        preview=preview,
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
        report_lines=report_lines,
    )
    write_text_report_with_bom(report_path, report_lines)
    return result


def apply_display_group_geometry_actions_test(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    heating_point_count: int,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    click_fn: GeometryClickFunction | None = None,
    drag_fn: GeometryDragFunction | None = None,
    move_fn: GeometryMoveFunction | None = None,
    scroll_fn: GeometryScrollFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    dialog_ready_fn: DialogReadyFunction | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
    sequence_builder_fn: Callable[[DisplayGroupGeometryReport, DisplayGroupGeometryProfile, int], tuple[ActualClickTestStep, ...]]
    | None = None,
    pause_after_paste: bool = False,
    pause_after_scroll: bool = False,
    continue_without_pause: bool = False,
    pause_before_button_clicks: bool = False,
    pause_input_fn: PauseInputFunction | None = None,
    message_printer: MessagePrinter | None = None,
) -> DisplayGroupApplyTestResult:
    """개발 검증용으로 group 02~05 복사/붙임 geometry action만 실제 수행한다.

    이 함수는 production apply가 아니다. N=11..48만 허용하고 OK/Apply/Print/PDF를
    수행하지 않는다. 좌표 검증이 끝나기 전에는 click/drag 함수를 호출하지 않는다.
    """
    validate_actual_click_test_heating_point_count(heating_point_count)
    if heating_point_count > 30 and not (pause_after_scroll or continue_without_pause):
        raise DisplayGroupInspectionError(
            "N > 30 requires --pause-after-display-group-scroll or --continue-without-display-group-pause "
            "because scrolled destination rows must be explicitly acknowledged in development test mode."
        )
    logger.warning(
        "표시 그룹 geometry 실제-click test 시작 | 원본=%s | heating_point_count=%s | OK/Apply/PDF 금지",
        source_path,
        heating_point_count,
    )
    if continue_without_pause:
        logger.warning("continuous display group validation mode enabled")
        logger.warning("no Enter prompts will be used")
    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("표시 그룹 geometry 실제-click test 작업본 열림 대상 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 표시 그룹 geometry 실제-click test를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    click_action = click_fn or click_geometry_point
    drag_action = drag_fn or drag_geometry_between_points
    move_action = move_fn or move_geometry_pointer
    scroll_action = scroll_fn or scroll_geometry_grid

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape
    ensure_dialog_ready = dialog_ready_fn or ensure_display_group_dialog_ready
    build_sequence = sequence_builder_fn or build_actual_click_test_sequence
    wait_for_input = pause_input_fn or input
    printer = message_printer or print

    dialog_top: Win32WindowSnapshot | None = None
    executed_actions: list[ExecutedGeometryAction] = []
    close_method = "not_closed"
    try:
        menu_path = open_menu(opened, logger)
        logger.info("geometry 실제-click test 메뉴 경로 사용 | %s", menu_path)
        dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
        dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        preview = calculate_display_group_geometry_action_preview(geometry, profile, heating_point_count)
        sequence = build_sequence(geometry, profile, heating_point_count)
        validate_planned_geometry_actions_inside_dialog(list(preview.actions), geometry.dialog_rect)
        validate_actual_click_test_sequence(sequence, geometry.dialog_rect, geometry=geometry)
        print_and_log_actual_click_test_sequence(sequence, logger, printer)

        for step in sequence:
            if step.action_type == "close_esc":
                continue
            current_dialog = ensure_dialog_ready(dialog_top, logger)
            if current_dialog is not None:
                fresh_geometry = calculate_display_group_geometry(current_dialog.rectangle, profile)
                fresh_sequence = build_sequence(fresh_geometry, profile, heating_point_count)
                step = matching_fresh_actual_click_step(step, fresh_sequence)
                validate_actual_click_step_against_fresh_dialog(step, current_dialog, logger)
            logger.warning("BEFORE %s | %s", step.action_type, format_actual_click_test_step(step))
            if step.action_type == "copy_detail_click":
                logger.warning("BEFORE click 복사상세 | point=%s", step.point)
                maybe_pause_before_display_group_button_click(
                    step,
                    "마우스가 복사상세 버튼 위에 있는지 확인하세요. Enter를 누르면 클릭합니다.",
                    pause_before_button_clicks,
                    move_action,
                    printer,
                    wait_for_input,
                    logger,
                )
            elif step.action_type == "paste_click":
                logger.warning("BEFORE click 붙임 | point=%s", step.point)
                maybe_pause_before_display_group_button_click(
                    step,
                    "마우스가 붙임 버튼 위에 있는지 확인하세요. Enter를 누르면 클릭합니다.",
                    pause_before_button_clicks,
                    move_action,
                    printer,
                    wait_for_input,
                    logger,
                )
            elif step.action_type == "scrollbar_down_click":
                logger.warning(
                    "BEFORE scrollbar down click | scrollbar_down_click_abs=%s | scrollbar_down_click_rel=%s",
                    step.point,
                    DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL,
                )

            executed = execute_actual_click_test_step(
                step,
                click_fn=click_action,
                drag_fn=drag_action,
                move_fn=move_action,
                scroll_fn=scroll_action,
            )
            executed_actions.append(executed)
            if step.action_type == "copy_detail_click":
                logger.warning("AFTER click 복사상세 | point=%s | UI 상태는 검증하지 않습니다.", step.point)
            elif step.action_type == "paste_click":
                logger.warning("AFTER click 붙임 | point=%s | UI 상태는 검증하지 않습니다.", step.point)
                if pause_after_paste and not continue_without_pause:
                    pause_message = "붙임 후 화면을 확인하세요. Enter를 누르면 다음 단계로 진행하거나 OK 없이 ESC로 닫습니다."
                    logger.warning("표시 그룹 geometry 실제-click test 붙임 후 pause | %s", pause_message)
                    printer(pause_message)
                    wait_for_input("")
                elif continue_without_pause:
                    logger.warning(
                        "pasted %s | continuing without pause | visual_wait_seconds=%.1f",
                        paste_step_transfer_summary(step),
                        DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS,
                    )
            elif step.action_type == "scrollbar_down_click":
                logger.warning(
                    "AFTER scrollbar down click | scrollbar_down_click_abs=%s | assuming W20~W50 visible | group_01_scrolled_down=True",
                    step.point,
                )
                if pause_after_scroll and not continue_without_pause:
                    pause_message = "스크롤 후 W20~W50 표시 상태를 확인하세요. Enter를 누르면 다음 단계로 진행합니다."
                    logger.warning("표시 그룹 geometry 실제-click test calibrated scroll 후 pause | %s", pause_message)
                    printer(pause_message)
                    wait_for_input("")
            logger.warning("AFTER %s | %s", step.action_type, format_executed_geometry_action(executed))
            wait_after_seconds = (
                continuous_wait_after_step(step)
                if continue_without_pause
                else step.wait_after_seconds
            )
            wait_fn(wait_after_seconds)

        close_method = close_dialog(logger)
        executed_actions.append(
            ExecutedGeometryAction("close_esc", "OK 없이 ESC/Cancel 안전 닫기", point=None)
        )
        logger.info("표시 그룹 geometry 실제-click test 닫기 완료 | method=%s", close_method)
    except Exception:
        if dialog_top is not None:
            try:
                close_dialog(logger)
                logger.info("오류 발생 후 표시 그룹 geometry 실제-click test 창 ESC 닫기 완료")
            except Exception as close_exc:
                logger.warning("오류 발생 후 표시 그룹 geometry 실제-click test 창 닫기 실패: %s", close_exc)
        raise

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "geometry 실제-click test 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 조사 전 힌트={before_hints} | 조사 후 힌트={after_hints}"
        )

    safety_summary_items = ["actual tab/copy/paste/drag actions were performed"]
    if continue_without_pause:
        safety_summary_items.append("continuous no-pause mode was used")
    safety_summary_items.extend(
        [
            "OK was not clicked",
            "Apply was not clicked",
            "PDF was not printed",
            f"dialog was closed by {close_method}",
        ]
    )
    safety_summary = tuple(safety_summary_items)
    for line in safety_summary:
        logger.warning("표시 그룹 geometry 실제-click test 안전 요약 | %s", line)
    logger.warning("dialog closed by ESC")

    return DisplayGroupApplyTestResult(
        opened=opened,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        preview=preview,
        executed_actions=tuple(executed_actions),
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
        safety_summary=safety_summary,
    )


def inspect_display_group_scrollbar_points_pause(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    click_fn: GeometryClickFunction | None = None,
    mouse_position_fn: MousePositionFunction | None = None,
    pause_input_fn: PauseInputFunction | None = None,
    message_printer: MessagePrinter | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
) -> DisplayGroupScrollbarCalibrationResult:
    """개발 보정용으로 표시 그룹 설정창 scrollbar 관련 좌표 3개를 운영자 마우스 위치로 기록한다.

    이 함수는 group/page 01 탭 선택 외에는 UI를 변경하지 않는다. OK/Apply/Print/PDF는 호출하지 않고
    좌표 기록 후 ESC로 닫는다.
    """
    logger.info("표시 그룹 vertical scrollbar 좌표 보정 pause mode 시작 | 원본=%s", source_path)
    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("scrollbar 좌표 보정 작업본 열림 확인 | 작업본=%s", opened.work_copy_path)

    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 scrollbar 좌표 보정을 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape
    click_action = click_fn or click_geometry_point
    read_mouse_position = mouse_position_fn or get_mouse_position
    wait_for_input = pause_input_fn or input
    printer = message_printer or print

    dialog_top: Win32WindowSnapshot | None = None
    close_method = "not_closed"
    output_lines: list[str] = []
    points: list[ScrollbarCalibrationPoint] = []
    try:
        menu_path = open_menu(opened, logger)
        logger.info("scrollbar 좌표 보정 메뉴 경로 사용 | %s", menu_path)
        dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
        dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)

        tab_01_point = dict(group_tab_coordinates(geometry.dialog_rect, profile))[1]
        validate_point_inside_dialog(tab_01_point, geometry.dialog_rect, "group/page 01 tab")
        logger.warning("scrollbar 좌표 보정: group/page 01 tab 클릭 | point=%s", tab_01_point)
        click_action(tab_01_point)

        dialog_line = f"dialog rectangle: {geometry.dialog_rect}"
        printer(dialog_line)
        logger.info(dialog_line)

        prompts = (
            (
                "grid_wheel_focus",
                "A. grid wheel focus point에 마우스를 올린 뒤 Enter를 누르세요.",
            ),
            (
                "scrollbar_thumb_start",
                "B. vertical scrollbar thumb center before scrolling 위치에 마우스를 올린 뒤 Enter를 누르세요.",
            ),
            (
                "scrollbar_thumb_end",
                "C. W20~W50이 보이도록 스크롤한 뒤 vertical scrollbar thumb target position에 마우스를 올리고 Enter를 누르세요.",
            ),
        )
        for point_name, prompt in prompts:
            printer(prompt)
            wait_for_input("")
            absolute = read_mouse_position()
            relative = relative_point(absolute, geometry.dialog_rect)
            calibration_point = ScrollbarCalibrationPoint(point_name, absolute, relative)
            points.append(calibration_point)
            line = format_scrollbar_calibration_point(calibration_point)
            output_lines.append(line)
            printer(line)
            logger.info("scrollbar 좌표 보정 point | %s", line)

        close_method = close_dialog(logger)
        logger.info("scrollbar 좌표 보정 창 ESC 닫기 완료 | method=%s", close_method)
    except Exception:
        if dialog_top is not None:
            try:
                close_dialog(logger)
                logger.info("오류 발생 후 scrollbar 좌표 보정 창 ESC 닫기 완료")
            except Exception as close_exc:
                logger.warning("오류 발생 후 scrollbar 좌표 보정 창 닫기 실패: %s", close_exc)
        raise

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    if not state_unchanged:
        raise DisplayGroupInspectionError(
            "scrollbar 좌표 보정 후 동일 작업본이 열린 상태인지 확인하지 못했습니다. "
            f"작업본={opened.work_copy_path} | 보정 전 힌트={before_hints} | 보정 후 힌트={after_hints}"
        )

    return DisplayGroupScrollbarCalibrationResult(
        opened=opened,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        points=tuple(points),
        output_lines=tuple(output_lines),
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
    )


def apply_display_group_geometry_actions_confirmed(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    heating_point_count: int,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    click_fn: GeometryClickFunction | None = None,
    drag_fn: GeometryDragFunction | None = None,
    move_fn: GeometryMoveFunction | None = None,
    scroll_fn: GeometryScrollFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    dialog_ready_fn: DialogReadyFunction | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
    popup_detector_fn: UnexpectedPopupDetectorFunction | None = None,
    time_axis_full_display_fn: TimeAxisFullDisplayFunction | None = None,
    sequence_builder_fn: Callable[[DisplayGroupGeometryReport, DisplayGroupGeometryProfile, int], tuple[ActualClickTestStep, ...]]
    | None = None,
    message_printer: MessagePrinter | None = None,
) -> DisplayGroupApplyConfirmedResult:
    """표시 그룹 geometry 작업을 확정 적용하고 OK를 눌러 저장하는 confirmed apply mode.

    PDF 출력은 하지 않는다. 이 함수는 Enter prompt를 사용하지 않으며, OK는 모든 copy/paste block이
    성공적으로 끝난 뒤 마지막에만 클릭한다.
    """
    validate_actual_click_test_heating_point_count(heating_point_count)
    logger.warning("confirmed apply mode started | source=%s | heating_point_count=%s", source_path, heating_point_count)
    logger.warning("no Enter prompts will be used")
    logger.warning("PDF will not be printed")

    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("confirmed apply 작업본 열림 확인 | 작업본=%s", opened.work_copy_path)
    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 confirmed apply mode를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape
    click_action = click_fn or click_geometry_point
    drag_action = drag_fn or drag_geometry_between_points
    move_action = move_fn or move_geometry_pointer
    scroll_action = scroll_fn or scroll_geometry_grid
    apply_time_axis = time_axis_full_display_fn or apply_time_axis_full_display_by_coordinates
    apply_time_axis(opened, logger, click_fn=click_action, move_fn=move_action, wait_fn=wait_fn)
    logger.warning("BEFORE opening Display Group Settings")

    ensure_dialog_ready = dialog_ready_fn or ensure_display_group_dialog_ready
    build_sequence = sequence_builder_fn or build_confirmed_apply_sequence
    detect_popups = popup_detector_fn or detect_unexpected_channel_popups
    printer = message_printer or print

    dialog_top: Win32WindowSnapshot | None = None
    executed_actions: list[ExecutedGeometryAction] = []
    close_method = "not_closed"
    ok_clicked = False
    try:
        menu_path = open_menu(opened, logger)
        logger.info("confirmed apply 메뉴 경로 사용 | %s", menu_path)
        logger.warning("AFTER opening Display Group Settings | menu_path=%s", menu_path)
        dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
        dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        preview = calculate_display_group_geometry_action_preview(geometry, profile, heating_point_count)
        sequence = build_sequence(geometry, profile, heating_point_count)
        validate_planned_geometry_actions_inside_dialog(list(preview.actions), geometry.dialog_rect)
        validate_confirmed_apply_sequence(sequence, geometry.dialog_rect, geometry=geometry)
        print_and_log_actual_click_test_sequence(sequence, logger, printer)

        for step in sequence:
            current_dialog = ensure_dialog_ready(dialog_top, logger)
            if current_dialog is not None:
                fresh_geometry = calculate_display_group_geometry(current_dialog.rectangle, profile)
                fresh_sequence = build_sequence(fresh_geometry, profile, heating_point_count)
                step = matching_fresh_actual_click_step(step, fresh_sequence)
                validate_actual_click_step_against_fresh_dialog(step, current_dialog, logger)
            if step.action_type == "ok_click":
                ensure_no_unexpected_channel_popup(detect_popups, opened.main_window.pid, logger)
                logger.warning("BEFORE OK click | point=%s", step.point)
                wait_fn(DISPLAY_GROUP_ACTION_WAIT_SECONDS)
            elif step.action_type == "scrollbar_down_click":
                logger.warning("BEFORE scrollbar down click | scrollbar_down_click_abs=%s", step.point)
            elif step.action_type == "destination_drag_select":
                logger.warning("BEFORE destination drag | %s | drag_start=%s | drag_end=%s", step.description, step.drag_start, step.drag_end)
            elif step.action_type == "paste_click":
                logger.warning("BEFORE paste | %s | point=%s", paste_step_transfer_summary(step), step.point)
            else:
                logger.warning("BEFORE %s | %s", step.action_type, format_actual_click_test_step(step))

            executed = execute_actual_click_test_step(
                step,
                click_fn=click_action,
                drag_fn=drag_action,
                move_fn=move_action,
                scroll_fn=scroll_action,
            )
            executed_actions.append(executed)

            if step.action_type == "ok_click":
                ok_clicked = True
                close_method = "OK"
                logger.warning("AFTER OK click | point=%s", step.point)
                logger.warning("OK was clicked intentionally in confirmed apply mode")
            elif step.action_type == "scrollbar_down_click":
                logger.warning(
                    "AFTER scrollbar down click; assuming W20~W50 visible | group_01_scrolled_down=True | scrollbar_down_click_abs=%s",
                    step.point,
                )
            elif step.action_type == "destination_drag_select":
                logger.warning("AFTER destination drag | %s", format_executed_geometry_action(executed))
            elif step.action_type == "paste_click":
                logger.warning("AFTER paste | %s", paste_step_transfer_summary(step))
            else:
                logger.warning("AFTER %s | %s", step.action_type, format_executed_geometry_action(executed))

            if step.action_type != "ok_click":
                ensure_no_unexpected_channel_popup(detect_popups, opened.main_window.pid, logger)
            wait_fn(confirmed_apply_wait_after_step(step))

        logger.warning("confirmed apply mode completed")
    except Exception:
        if dialog_top is not None and not ok_clicked:
            try:
                close_dialog(logger)
                logger.info("오류 발생 후 confirmed apply 창 ESC 닫기 완료")
            except Exception as close_exc:
                logger.warning("오류 발생 후 confirmed apply 창 닫기 실패: %s", close_exc)
        raise

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    safety_summary = (
        "confirmed apply mode completed",
        "OK was clicked intentionally in confirmed apply mode",
        "Apply was not clicked",
        "PDF was not printed",
        "Save dialog was not opened",
        "Microsoft Print to PDF was not used",
        "dialog closed by OK",
    )
    for line in safety_summary:
        logger.warning("confirmed apply safety summary | %s", line)

    return DisplayGroupApplyConfirmedResult(
        opened=opened,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        preview=preview,
        executed_actions=tuple(executed_actions),
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
        safety_summary=safety_summary,
    )


def apply_display_group_max_48_confirmed(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    menu_open_fn: MenuOpenFunction | None = None,
    dialog_detector_fn: DialogDetectorFunction | None = None,
    raw_hint_collector: RawHintCollector = collect_opened_raw_file_hints,
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
    click_fn: GeometryClickFunction | None = None,
    drag_fn: GeometryDragFunction | None = None,
    move_fn: GeometryMoveFunction | None = None,
    scroll_fn: GeometryScrollFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    dialog_ready_fn: DialogReadyFunction | None = None,
    close_dialog_fn: Callable[[logging.Logger], str] | None = None,
    popup_detector_fn: UnexpectedPopupDetectorFunction | None = None,
    time_axis_full_display_fn: TimeAxisFullDisplayFunction | None = None,
    message_printer: MessagePrinter | None = None,
) -> DisplayGroupApplyConfirmedResult:
    """Heating Point 개수를 묻지 않고 group/page 02~05 전체를 W11~W48로 확정 적용한다."""
    logger.warning("max-48 confirmed mode started | source=%s", source_path)
    logger.warning("no heating_point_count is required")
    logger.warning("all group/page 02~05 blocks will be processed")
    logger.warning("no Enter prompts will be used")
    logger.warning("PDF will not be printed")

    opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    logger.info("max-48 confirmed apply 작업본 열림 확인 | 작업본=%s", opened.work_copy_path)
    if not opened.hint_verified:
        raise DisplayGroupInspectionError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 max-48 confirmed mode를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    click_action = click_fn or click_geometry_point
    drag_action = drag_fn or drag_geometry_between_points
    move_action = move_fn or move_geometry_pointer
    scroll_action = scroll_fn or scroll_geometry_grid
    apply_time_axis = time_axis_full_display_fn or apply_time_axis_full_display_by_coordinates
    apply_time_axis(opened, logger, click_fn=click_action, move_fn=move_action, wait_fn=wait_fn)
    logger.warning("BEFORE opening Display Group Settings")

    baseline_hwnds = tuple(window.hwnd for window in capture_top_level_windows(opened.main_window.pid))
    before_hints = opened.raw_file_hints
    open_menu = menu_open_fn or open_display_group_settings_dialog_via_menu
    detect_dialog = dialog_detector_fn or detect_display_group_dialog
    close_dialog = close_dialog_fn or close_display_group_dialog_geometry_with_escape
    ensure_dialog_ready = dialog_ready_fn or ensure_display_group_dialog_ready
    detect_popups = popup_detector_fn or detect_unexpected_channel_popups
    printer = message_printer or print

    dialog_top: Win32WindowSnapshot | None = None
    executed_actions: list[ExecutedGeometryAction] = []
    close_method = "not_closed"
    ok_clicked = False
    try:
        menu_path = open_menu(opened, logger)
        logger.info("max-48 confirmed apply 메뉴 경로 사용 | %s", menu_path)
        logger.warning("AFTER opening Display Group Settings | menu_path=%s", menu_path)
        dialog_top = detect_dialog(opened.main_window.pid, baseline_hwnds, logger)
        dialog_top = read_win32_window_snapshot(dialog_top.hwnd) or dialog_top
        geometry = calculate_display_group_geometry(dialog_top.rectangle, profile)
        coordinate_profile = require_display_group_coordinate_profile(dialog_top)
        logger.warning(
            "Display Group coordinate profile selected | title=%s | class=%s | size=%s",
            coordinate_profile["dialog_title"],
            coordinate_profile["dialog_class"],
            coordinate_profile["dialog_size"],
        )
        sequence = build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            geometry.dialog_rect,
            coordinate_profile,
        )
        preview = build_display_group_coordinate_profile_preview(sequence)
        validate_planned_geometry_actions_inside_dialog(list(preview.actions), geometry.dialog_rect)
        validate_confirmed_apply_sequence(sequence, geometry.dialog_rect, geometry=geometry)
        validate_display_group_max_48_sequence(sequence)
        print_and_log_actual_click_test_sequence(sequence, logger, printer)

        group_05_tab_clicked = False
        group_05_scrollbar_up_clicked = False
        for step in sequence:
            current_dialog = ensure_dialog_ready(dialog_top, logger)
            if current_dialog is not None:
                fresh_geometry = calculate_display_group_geometry(current_dialog.rectangle, profile)
                fresh_sequence = build_display_group_max_48_sequence_for_dialog(
                    current_dialog,
                    fresh_geometry,
                    profile,
                    required_coordinate_profile=coordinate_profile,
                )
                step = matching_fresh_actual_click_step(step, fresh_sequence)
                validate_actual_click_step_against_fresh_dialog(step, current_dialog, logger)
                log_actual_click_step_coordinate_context(step, current_dialog, logger)
            if step.action_type == "tab_05_click":
                group_05_tab_clicked = True
                group_05_scrollbar_up_clicked = False
            elif step.action_type == "source_drag_select" and "source group/page 05 W01~W08" in step.description:
                if not group_05_scrollbar_up_clicked:
                    raise DisplayGroupInspectionError(
                        "max-48 confirmed mode 안전 중단: group/page 05 source W01~W08 drag 전에 "
                        "scrollbar_up_click이 실제 실행되지 않았습니다."
                    )
            if step.action_type == "ok_click":
                ensure_no_unexpected_channel_popup(detect_popups, opened.main_window.pid, logger)
                logger.warning("BEFORE OK click | point=%s", step.point)
                wait_fn(DISPLAY_GROUP_ACTION_WAIT_SECONDS)
            elif step.action_type == "scrollbar_down_click":
                logger.warning("BEFORE scrollbar down click | scrollbar_down_click_abs=%s", step.point)
            elif step.action_type == "scrollbar_up_click":
                logger.warning("BEFORE scrollbar up click | scrollbar_up_click_abs=%s", step.point)
            elif step.action_type == "destination_drag_select":
                logger.warning("BEFORE destination drag | %s | drag_start=%s | drag_end=%s", step.description, step.drag_start, step.drag_end)
            elif step.action_type == "paste_click":
                logger.warning("BEFORE paste | %s | point=%s", paste_step_transfer_summary(step), step.point)
            else:
                logger.warning("BEFORE %s | %s", step.action_type, format_actual_click_test_step(step))

            executed = execute_actual_click_test_step(
                step,
                click_fn=click_action,
                drag_fn=drag_action,
                move_fn=move_action,
                scroll_fn=scroll_action,
            )
            executed_actions.append(executed)

            if step.action_type == "ok_click":
                ok_clicked = True
                close_method = "OK"
                logger.warning("AFTER OK click | point=%s", step.point)
                logger.warning("OK was clicked intentionally in max-48 confirmed mode")
            elif step.action_type == "scrollbar_down_click":
                logger.warning(
                    "AFTER scrollbar down click; assuming W20~W50 visible | scrollbar_down_click_abs=%s",
                    step.point,
                )
            elif step.action_type == "scrollbar_up_click":
                if group_05_tab_clicked:
                    group_05_scrollbar_up_clicked = True
                logger.warning(
                    "AFTER scrollbar up click; assuming source group top rows visible | scrollbar_up_click_abs=%s",
                    step.point,
                )
            elif step.action_type == "destination_drag_select":
                logger.warning("AFTER destination drag | %s", format_executed_geometry_action(executed))
            elif step.action_type == "paste_click":
                logger.warning("AFTER paste | %s", paste_step_transfer_summary(step))
            else:
                logger.warning("AFTER %s | %s", step.action_type, format_executed_geometry_action(executed))

            if step.action_type != "ok_click":
                ensure_no_unexpected_channel_popup(detect_popups, opened.main_window.pid, logger)
            wait_fn(confirmed_apply_wait_after_step(step))

        logger.warning("max-48 confirmed mode completed")
    except Exception:
        if dialog_top is not None and not ok_clicked:
            try:
                close_dialog(logger)
                logger.info("오류 발생 후 max-48 confirmed apply 창 ESC 닫기 완료")
            except Exception as close_exc:
                logger.warning("오류 발생 후 max-48 confirmed apply 창 닫기 실패: %s", close_exc)
        raise

    after_hints = raw_hint_collector(opened.main_window.handle)
    state_unchanged = bool(matching_work_copy_hints(after_hints, opened.work_copy_path))
    safety_summary = (
        "max-48 confirmed mode completed",
        "all group/page 02~05 blocks were processed",
        "OK was clicked intentionally in max-48 confirmed mode",
        "Apply was not clicked",
        "PDF was not printed",
        "Save dialog was not opened",
        "Microsoft Print to PDF was not used",
        "dialog closed by OK",
    )
    for line in safety_summary:
        logger.warning("max-48 confirmed safety summary | %s", line)

    return DisplayGroupApplyConfirmedResult(
        opened=opened,
        menu_path=menu_path,
        dialog=dialog_top,
        geometry=geometry,
        preview=preview,
        executed_actions=tuple(executed_actions),
        before_raw_file_hints=before_hints,
        after_raw_file_hints=after_hints,
        state_unchanged=state_unchanged,
        close_method=close_method,
        safety_summary=safety_summary,
    )


def validate_actual_click_test_heating_point_count(heating_point_count: int) -> None:
    """개발 검증용 실제-click test mode의 지원 범위를 검증한다."""
    if heating_point_count < 1:
        raise DisplayGroupInspectionError(
            f"--heating-point-count는 1 이상이어야 합니다: {heating_point_count}"
        )
    if heating_point_count <= 10:
        raise DisplayGroupInspectionError(
            "actual-click test mode에서는 Heating Point 1~10은 복사/붙임 작업이 필요하지 않아 실행하지 않습니다. "
            f"입력값={heating_point_count}"
        )
    if heating_point_count > 48:
        raise DisplayGroupInspectionError(
            "Heating Point 48 초과는 actual-click test mode에서 아직 지원하지 않습니다. "
            f"입력값={heating_point_count}"
        )


def build_actual_click_test_sequence(
    geometry: DisplayGroupGeometryReport,
    profile: DisplayGroupGeometryProfile,
    heating_point_count: int,
) -> tuple[ActualClickTestStep, ...]:
    """N=11..48 개발 검증용 실제 실행 sequence를 명시적으로 구성한다."""
    validate_actual_click_test_heating_point_count(heating_point_count)
    dialog_rect = geometry.dialog_rect
    tab_coordinates = dict(group_tab_coordinates(dialog_rect, profile))
    copy_detail_point = center_of_relative_area(dialog_rect, profile.copy_detail_button_area)
    paste_point = center_of_relative_area(dialog_rect, profile.paste_button_area)
    steps: list[ActualClickTestStep] = []
    step_no = 1
    group_01_scrolled_down = False
    for block in iter_display_group_copy_blocks(heating_point_count):
        steps.append(
            ActualClickTestStep(
                step_no,
                f"tab_{block['source_group']:02d}_click",
                f"group/page {block['source_group']:02d} tab 클릭",
                point=tab_coordinates[int(block["source_group"])],
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "source_drag_select",
                f"source group/page {block['source_group']:02d} W01~W{block['source_row_count']:02d} drag/select",
                drag_start=drag_select_coordinate_for_row(dialog_rect, profile, 1, "start"),
                drag_end=drag_select_coordinate_for_row(dialog_rect, profile, int(block["source_row_count"]), "end"),
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "copy_detail_click",
                "복사상세 버튼 클릭",
                point=copy_detail_point,
                move_before_click=True,
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "tab_01_click",
                "group/page 01 tab 클릭",
                point=tab_coordinates[1],
            )
        )
        step_no += 1
        destination_start = int(block["destination_start"])
        destination_end = int(block["destination_end"])
        if destination_start >= 31:
            if not group_01_scrolled_down:
                scrollbar_down_point = scrollbar_down_click_coordinate(dialog_rect)
                steps.append(
                    ActualClickTestStep(
                        step_no,
                        "scrollbar_down_click",
                        (
                            "group/page 01 scrollbar down area click; "
                            f"scrollbar_down_click_rel={DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL}; "
                            "assume W20~W50 visible"
                        ),
                        point=scrollbar_down_point,
                    )
                )
                step_no += 1
                group_01_scrolled_down = True
            drag_start = drag_select_coordinate_for_scrolled_destination_row(dialog_rect, profile, destination_start, "start")
            drag_end = drag_select_coordinate_for_scrolled_destination_row(dialog_rect, profile, destination_end, "end")
            view_label = "scrolled view W20~W50 visible"
        else:
            drag_start = drag_select_coordinate_for_row(dialog_rect, profile, destination_start, "start")
            drag_end = drag_select_coordinate_for_row(dialog_rect, profile, destination_end, "end")
            view_label = "normal view"
        steps.append(
            ActualClickTestStep(
                step_no,
                "destination_drag_select",
                f"destination group/page 01 W{destination_start:02d}~W{destination_end:02d} drag/select ({view_label})",
                drag_start=drag_start,
                drag_end=drag_end,
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "paste_click",
                (
                    "붙임 버튼 클릭 | "
                    f"source group/page {block['source_group']:02d} to destination W{destination_start:02d}~W{destination_end:02d}"
                ),
                point=paste_point,
                move_before_click=True,
            )
        )
        step_no += 1
    steps.append(
        ActualClickTestStep(
            step_no,
            "close_esc",
            "OK 없이 ESC/Cancel로 닫기",
            wait_after_seconds=0.0,
        )
    )
    return tuple(steps)


def build_confirmed_apply_sequence(
    geometry: DisplayGroupGeometryReport,
    profile: DisplayGroupGeometryProfile,
    heating_point_count: int,
) -> tuple[ActualClickTestStep, ...]:
    """confirmed apply mode에서 실행할 copy/paste sequence와 마지막 OK click을 구성한다."""
    base_steps = tuple(step for step in build_actual_click_test_sequence(geometry, profile, heating_point_count) if step.action_type != "close_esc")
    ok_point = center_of_relative_area(geometry.dialog_rect, profile.ok_button_area)
    return base_steps + (
        ActualClickTestStep(
            len(base_steps) + 1,
            "ok_click",
            "confirmed apply mode OK 버튼 클릭",
            point=ok_point,
            wait_after_seconds=DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS,
        ),
    )


def build_display_group_max_48_confirmed_sequence(
    geometry: DisplayGroupGeometryReport,
    profile: DisplayGroupGeometryProfile,
) -> tuple[ActualClickTestStep, ...]:
    """max-48 confirmed mode 전용 copy/paste sequence를 명시적으로 구성한다."""
    dialog_rect = geometry.dialog_rect
    tab_coordinates = dict(group_tab_coordinates(dialog_rect, profile))
    copy_detail_point = center_of_relative_area(dialog_rect, profile.copy_detail_button_area)
    paste_point = center_of_relative_area(dialog_rect, profile.paste_button_area)
    scrollbar_down_point = scrollbar_down_click_coordinate(dialog_rect)
    scrollbar_up_point = scrollbar_up_click_coordinate(dialog_rect)
    steps: list[ActualClickTestStep] = []
    step_no = 1
    for block in iter_display_group_max_48_copy_blocks():
        source_group = int(block["source_group"])
        source_row_count = int(block["source_row_count"])
        destination_start = int(block["destination_start"])
        destination_end = int(block["destination_end"])
        steps.append(
            ActualClickTestStep(
                step_no,
                f"tab_{source_group:02d}_click",
                f"group/page {source_group:02d} tab 클릭",
                point=tab_coordinates[source_group],
            )
        )
        step_no += 1
        if source_group == 5:
            steps.append(
                ActualClickTestStep(
                    step_no,
                    "scrollbar_up_click",
                    (
                        "group/page 05 scrollbar up area click before source W01~W08; "
                        f"scrollbar_up_click_rel={DISPLAY_GROUP_SCROLLBAR_UP_CLICK_REL}; assume source top rows visible"
                    ),
                    point=scrollbar_up_point,
                )
            )
            step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "source_drag_select",
                f"source group/page {source_group:02d} W01~W{source_row_count:02d} drag/select",
                drag_start=drag_select_coordinate_for_row(dialog_rect, profile, 1, "start"),
                drag_end=drag_select_coordinate_for_row(dialog_rect, profile, source_row_count, "end"),
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "copy_detail_click",
                "복사상세 버튼 클릭",
                point=copy_detail_point,
                move_before_click=True,
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "tab_01_click",
                "group/page 01 tab 클릭",
                point=tab_coordinates[1],
            )
        )
        step_no += 1
        if destination_start >= 31:
            steps.append(
                ActualClickTestStep(
                    step_no,
                    "scrollbar_down_click",
                    (
                        "group/page 01 scrollbar down area click; "
                        f"scrollbar_down_click_rel={DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL}; assume W20~W50 visible"
                    ),
                    point=scrollbar_down_point,
                )
            )
            step_no += 1
            drag_start = drag_select_coordinate_for_scrolled_destination_row(dialog_rect, profile, destination_start, "start")
            drag_end = drag_select_coordinate_for_scrolled_destination_row(dialog_rect, profile, destination_end, "end")
            view_label = "scrolled view W20~W50 visible"
        else:
            drag_start = drag_select_coordinate_for_row(dialog_rect, profile, destination_start, "start")
            drag_end = drag_select_coordinate_for_row(dialog_rect, profile, destination_end, "end")
            view_label = "normal view"
        steps.append(
            ActualClickTestStep(
                step_no,
                "destination_drag_select",
                f"destination group/page 01 W{destination_start:02d}~W{destination_end:02d} drag/select ({view_label})",
                drag_start=drag_start,
                drag_end=drag_end,
            )
        )
        step_no += 1
        steps.append(
            ActualClickTestStep(
                step_no,
                "paste_click",
                (
                    "붙임 버튼 클릭 | "
                    f"source group/page {source_group:02d} to destination W{destination_start:02d}~W{destination_end:02d}"
                ),
                point=paste_point,
                move_before_click=True,
            )
        )
        step_no += 1
    ok_point = center_of_relative_area(dialog_rect, profile.ok_button_area)
    steps.append(
        ActualClickTestStep(
            step_no,
            "ok_click",
            "max-48 confirmed mode OK 버튼 클릭",
            point=ok_point,
            wait_after_seconds=DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS,
        )
    )
    return tuple(steps)


def iter_display_group_copy_blocks(heating_point_count: int) -> tuple[dict[str, int], ...]:
    """HP11 이상을 group/page 02..05 source와 group/page 01 destination block으로 나눈다."""
    validate_heating_point_count(heating_point_count)
    blocks: list[dict[str, int]] = []
    for source_group in range(2, ((heating_point_count - 1) // 10) + 2):
        source_hp_start = ((source_group - 1) * 10) + 1
        if source_hp_start > heating_point_count:
            continue
        source_hp_end = min(source_group * 10, heating_point_count)
        source_row_count = source_hp_end - source_hp_start + 1
        destination_start = source_hp_start
        destination_end = destination_start + source_row_count - 1
        blocks.append(
            {
                "source_group": source_group,
                "source_row_count": source_row_count,
                "destination_start": destination_start,
                "destination_end": destination_end,
            }
        )
    return tuple(blocks)


def iter_display_group_max_48_copy_blocks() -> tuple[dict[str, int], ...]:
    """max-48 mode에서 항상 처리하는 group/page 02~05 source/destination block."""
    return (
        {"source_group": 2, "source_row_count": 10, "destination_start": 11, "destination_end": 20},
        {"source_group": 3, "source_row_count": 10, "destination_start": 21, "destination_end": 30},
        {"source_group": 4, "source_row_count": 10, "destination_start": 31, "destination_end": 40},
        {"source_group": 5, "source_row_count": 8, "destination_start": 41, "destination_end": 48},
    )



def group_tab_coordinates(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
) -> tuple[tuple[int, tuple[int, int]], ...]:
    """profile에 정의된 group/page tab 좌표를 반환한다."""
    return tuple(
        (group_no, point_from_relative(dialog_rect, x_ratio, profile.group_tab_y_ratio))
        for group_no, x_ratio in enumerate(profile.group_tab_x_ratios, start=1)
    )


def drag_select_coordinate_for_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    row_no: int,
    edge: str,
) -> tuple[int, int]:
    """row 범위 선택용 drag 시작/끝 좌표를 반환한다."""
    if edge == "start":
        x_ratio = profile.drag_select_start_x_ratio
    elif edge == "end":
        x_ratio = profile.drag_select_end_x_ratio
    else:
        raise ValueError(f"지원하지 않는 drag edge입니다: {edge}")
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        x_ratio,
        row_y_coordinate(dialog_rect, profile, row_no),
    )


SCROLLED_DESTINATION_VISIBLE_TOP_ROW = 20


def drag_select_coordinate_for_scrolled_destination_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    destination_row_no: int,
    edge: str,
) -> tuple[int, int]:
    """스크롤 후 group/page 01 destination row의 drag 좌표를 반환한다."""
    if edge == "start":
        if destination_row_no >= 41:
            x_ratio = DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL[0]
        else:
            x_ratio = DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL[0]
    elif edge == "end":
        x_ratio = profile.drag_select_end_x_ratio
    else:
        raise ValueError(f"지원하지 않는 drag edge입니다: {edge}")
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        x_ratio,
        scrolled_destination_row_y_coordinate(dialog_rect, profile, destination_row_no),
    )


def scrolled_destination_row_y_coordinate(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    destination_row_no: int,
) -> int:
    """visible_top_row=W20으로 가정한 스크롤 후 destination row y 좌표를 계산한다."""
    row_height = round((dialog_rect[3] - dialog_rect[1]) * profile.row_height_ratio)
    if destination_row_no >= 41:
        base_row = 41
        base_y = point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL)[1]
    else:
        base_row = 31
        base_y = point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL)[1]
    return base_y + ((destination_row_no - base_row) * row_height)


def grid_scroll_point(dialog_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """group/page 01 grid 내부 스크롤용 마우스 위치를 계산한다."""
    return point_from_relative(dialog_rect, 0.95, 0.55)


def calibrated_scrollbar_drag_coordinates(dialog_rect: tuple[int, int, int, int]) -> dict[str, tuple[int, int]]:
    """보정된 상대 좌표로 grid focus 및 vertical scrollbar thumb drag 좌표를 계산한다."""
    return {
        "grid_focus": point_from_relative(dialog_rect, *DISPLAY_GROUP_GRID_FOCUS_REL),
        "thumb_start": point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLBAR_THUMB_START_REL),
        "thumb_end": point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLBAR_THUMB_END_REL),
    }


def scrollbar_down_click_coordinate(dialog_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """W31+ 목적지 행 표시를 위해 보정된 vertical scrollbar down target 클릭 좌표를 계산한다."""
    return point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL)


def scrollbar_up_click_coordinate(dialog_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """group/page 05 source top rows 표시를 위해 보정된 vertical scrollbar up target 클릭 좌표를 계산한다."""
    return point_from_relative(dialog_rect, *DISPLAY_GROUP_SCROLLBAR_UP_CLICK_REL)


def find_planned_action(
    preview: DisplayGroupGeometryActionPreview,
    action_type: str,
    *,
    group_no: int | None = None,
    row_no: int | None = None,
) -> PlannedGeometryAction:
    """조건에 맞는 planned action을 하나 찾는다."""
    for action in preview.actions:
        if action.action_type != action_type:
            continue
        if group_no is not None and action.group_no != group_no:
            continue
        if row_no is not None and action.row_no != row_no:
            continue
        return action
    raise DisplayGroupInspectionError(
        f"actual-click test sequence에 필요한 action을 찾지 못했습니다: type={action_type}, group={group_no}, row={row_no}"
    )


def validate_actual_click_test_sequence(
    sequence: tuple[ActualClickTestStep, ...],
    dialog_rect: tuple[int, int, int, int],
    *,
    geometry: DisplayGroupGeometryReport | None = None,
) -> None:
    """실제-click test mode에서 허용된 action과 좌표만 포함하는지 검증한다."""
    validate_actual_click_test_step_coordinates_inside_dialog(sequence, dialog_rect)
    forbidden_types = {"ok_button_candidate", "apply_button_candidate", "print_candidate", "pdf_candidate", "ok_click"}
    forbidden = [step.action_type for step in sequence if step.action_type in forbidden_types]
    if forbidden:
        raise DisplayGroupInspectionError(f"actual-click test mode에서 금지된 action이 포함되었습니다: {forbidden}")
    if not sequence or sequence[-1].action_type != "close_esc":
        raise DisplayGroupInspectionError("actual-click test sequence 마지막은 close_esc여야 합니다.")

    index = 0
    group_01_scrolled_down = False
    while index < len(sequence) - 1:
        if not (sequence[index].action_type.startswith("tab_") and sequence[index].action_type.endswith("_click")):
            raise DisplayGroupInspectionError(f"source tab click이 필요한 위치입니다: {tuple(step.action_type for step in sequence)}")
        block_types = [sequence[index].action_type]
        index += 1
        if index < len(sequence) and sequence[index].action_type == "scrollbar_up_click":
            block_types.append(sequence[index].action_type)
            index += 1
        required_order = ("source_drag_select", "copy_detail_click", "tab_01_click")
        for expected in required_order:
            if index >= len(sequence) or sequence[index].action_type != expected:
                raise DisplayGroupInspectionError(f"허용되지 않은 actual-click test sequence입니다: {tuple(step.action_type for step in sequence)}")
            block_types.append(sequence[index].action_type)
            index += 1
        block_had_scroll_action = False
        if index < len(sequence) and sequence[index].action_type in (
            "scroll_for_destination_rows_w31_plus",
            "calibrated_scrollbar_drag",
            "scrollbar_down_click",
        ):
            block_types.append(sequence[index].action_type)
            block_had_scroll_action = True
            group_01_scrolled_down = True
            index += 1
        for expected in ("destination_drag_select", "paste_click"):
            if index >= len(sequence) or sequence[index].action_type != expected:
                raise DisplayGroupInspectionError(f"허용되지 않은 actual-click test sequence입니다: {tuple(step.action_type for step in sequence)}")
            if expected == "destination_drag_select" and geometry is not None and "scrolled view" in sequence[index].description:
                if not group_01_scrolled_down and not block_had_scroll_action:
                    raise DisplayGroupInspectionError(
                        "W31+ destination drag 전에 scrollbar_down_click이 수행되지 않았고 group/page 01 scrolled 상태도 아닙니다."
                    )
                validate_drag_step_inside_visible_grid(sequence[index], visible_grid_rect(geometry))
            block_types.append(sequence[index].action_type)
            index += 1


def validate_confirmed_apply_sequence(
    sequence: tuple[ActualClickTestStep, ...],
    dialog_rect: tuple[int, int, int, int],
    *,
    geometry: DisplayGroupGeometryReport,
) -> None:
    """confirmed apply mode sequence가 OK를 마지막에만 포함하고 copy/paste 규칙을 만족하는지 검증한다."""
    validate_actual_click_test_step_coordinates_inside_dialog(sequence, dialog_rect)
    if not sequence or sequence[-1].action_type != "ok_click":
        raise DisplayGroupInspectionError("confirmed apply sequence 마지막은 ok_click이어야 합니다.")
    ok_count = sum(1 for step in sequence if step.action_type == "ok_click")
    if ok_count != 1:
        raise DisplayGroupInspectionError(f"confirmed apply sequence에는 ok_click이 정확히 1개만 있어야 합니다: {ok_count}")
    forbidden_types = {"apply_button_candidate", "print_candidate", "pdf_candidate", "save_dialog_candidate"}
    forbidden = [step.action_type for step in sequence if step.action_type in forbidden_types]
    if forbidden:
        raise DisplayGroupInspectionError(f"confirmed apply mode에서 금지된 action이 포함되었습니다: {forbidden}")

    prefix = sequence[:-1] + (
        ActualClickTestStep(
            sequence[-1].step,
            "close_esc",
            "validation placeholder",
            wait_after_seconds=0.0,
        ),
    )
    validate_actual_click_test_sequence(prefix, dialog_rect, geometry=geometry)


def validate_display_group_max_48_sequence(sequence: tuple[ActualClickTestStep, ...]) -> None:
    """max-48 confirmed sequence의 고정 scroll/copy/paste 구조를 검증한다."""
    action_types = tuple(step.action_type for step in sequence)
    descriptions = "\n".join(step.description for step in sequence)
    required_transfers = (
        "source group/page 02 to destination W11~W20",
        "source group/page 03 to destination W21~W30",
        "source group/page 04 to destination W31~W40",
        "source group/page 05 to destination W41~W48",
    )
    for transfer in required_transfers:
        if transfer not in descriptions:
            raise DisplayGroupInspectionError(f"max-48 sequence에 필수 transfer가 없습니다: {transfer}")
    if action_types.count("scrollbar_down_click") != 2:
        raise DisplayGroupInspectionError(
            f"max-48 sequence에는 scrollbar_down_click이 정확히 2개 필요합니다: {action_types.count('scrollbar_down_click')}"
        )
    if action_types.count("scrollbar_up_click") != 1:
        raise DisplayGroupInspectionError(
            f"max-48 sequence에는 scrollbar_up_click이 정확히 1개 필요합니다: {action_types.count('scrollbar_up_click')}"
        )
    if not action_types or action_types[-1] != "ok_click":
        raise DisplayGroupInspectionError("max-48 sequence 마지막 action은 ok_click이어야 합니다.")

    tab_05_index = action_types.index("tab_05_click")
    source_after_05 = action_types.index("source_drag_select", tab_05_index)
    up_index = action_types.index("scrollbar_up_click")
    if not (tab_05_index < up_index < source_after_05):
        raise DisplayGroupInspectionError("max-48 sequence에서 scrollbar_up_click은 group/page 05 tab 클릭 후 source drag 전에 있어야 합니다.")

    destination_w41_index = next(
        index
        for index, step in enumerate(sequence)
        if step.action_type == "destination_drag_select" and "W41~W48" in step.description
    )
    second_down_index = [index for index, action_type in enumerate(action_types) if action_type == "scrollbar_down_click"][1]
    if not second_down_index < destination_w41_index:
        raise DisplayGroupInspectionError("max-48 sequence에서 두 번째 scrollbar_down_click은 W41~W48 destination drag 전에 있어야 합니다.")
    paste_indices = [index for index, action_type in enumerate(action_types) if action_type == "paste_click"]
    if len(paste_indices) != 4 or not paste_indices[-1] < len(sequence) - 1:
        raise DisplayGroupInspectionError("max-48 sequence는 네 번의 paste 후 마지막에 OK를 눌러야 합니다.")


def validate_actual_click_test_step_coordinates_inside_dialog(
    sequence: tuple[ActualClickTestStep, ...],
    dialog_rect: tuple[int, int, int, int],
) -> None:
    """actual-click test step의 모든 좌표가 dialog 안에 있는지 검증한다."""
    for step in sequence:
        for coordinate_name, point in (
            ("point", step.point),
            ("drag_start", step.drag_start),
            ("drag_end", step.drag_end),
        ):
            if point is None:
                continue
            if not is_point_inside_rect(point, dialog_rect):
                raise DisplayGroupInspectionError(
                    "actual-click test 좌표가 대화상자 밖입니다: "
                    f"step={step.step}, type={step.action_type}, coordinate={coordinate_name}, "
                    f"point={point}, dialog_rect={dialog_rect}"
                )


def print_and_log_actual_click_test_sequence(
    sequence: tuple[ActualClickTestStep, ...],
    logger: logging.Logger,
    printer: MessagePrinter,
) -> None:
    """실제 실행 전 전체 actual-click test sequence를 출력하고 로그에 남긴다."""
    header = "actual-click test execution sequence:"
    logger.warning(header)
    printer(header)
    for step in sequence:
        line = format_actual_click_test_step(step)
        logger.warning(line)
        printer(line)
        if step.action_type == "source_drag_select":
            logger.warning(
                "source drag range | %s | drag_start=%s | drag_end=%s",
                step.description,
                step.drag_start,
                step.drag_end,
            )
        elif step.action_type == "destination_drag_select":
            logger.warning(
                "destination group/page 01 drag range | %s | drag_start=%s | drag_end=%s",
                step.description,
                step.drag_start,
                step.drag_end,
            )
        elif step.action_type in ("scroll_for_destination_rows_w31_plus", "calibrated_scrollbar_drag", "scrollbar_down_click", "scrollbar_up_click"):
            logger.warning(
                "scroll action | %s | point=%s | drag_start=%s | drag_end=%s | scroll_amount=%s | assumed_visible_top_row=%s",
                step.description,
                step.point,
                step.drag_start,
                step.drag_end,
                step.scroll_amount,
                SCROLLED_DESTINATION_VISIBLE_TOP_ROW,
            )


def maybe_pause_before_display_group_button_click(
    step: ActualClickTestStep,
    message: str,
    enabled: bool,
    move_fn: GeometryMoveFunction,
    printer: MessagePrinter,
    wait_for_input: PauseInputFunction,
    logger: logging.Logger,
) -> None:
    """개발 검증용으로 복사상세/붙임 클릭 직전 마우스 위치를 확인한다."""
    if not enabled:
        return
    if step.point is None:
        raise DisplayGroupInspectionError(f"button click pause 대상 좌표가 없습니다: {format_actual_click_test_step(step)}")
    move_fn(step.point)
    logger.warning("button click 직전 pause | %s | point=%s", message, step.point)
    printer(message)
    wait_for_input("")


def execute_actual_click_test_step(
    step: ActualClickTestStep,
    *,
    click_fn: GeometryClickFunction,
    drag_fn: GeometryDragFunction,
    move_fn: GeometryMoveFunction,
    scroll_fn: GeometryScrollFunction,
) -> ExecutedGeometryAction:
    """검증된 actual-click test step 하나를 실제 click 또는 drag로 수행한다."""
    if step.action_type in ("scrollbar_down_click", "scrollbar_up_click"):
        if step.point is None:
            raise DisplayGroupInspectionError(f"scrollbar down click 좌표가 없습니다: {format_actual_click_test_step(step)}")
        move_fn(step.point)
        click_fn(step.point)
        return ExecutedGeometryAction(
            action_type=step.action_type,
            description=step.description,
            point=step.point,
        )

    if step.action_type == "calibrated_scrollbar_drag":
        if step.point is None or step.drag_start is None or step.drag_end is None:
            raise DisplayGroupInspectionError(
                f"calibrated scrollbar drag 좌표가 불완전합니다: {format_actual_click_test_step(step)}"
            )
        click_fn(step.point)
        drag_fn(step.drag_start, step.drag_end)
        return ExecutedGeometryAction(
            action_type=step.action_type,
            description=step.description,
            point=step.point,
            drag_start=step.drag_start,
            drag_end=step.drag_end,
        )

    if step.scroll_amount is not None:
        if step.point is None:
            raise DisplayGroupInspectionError(f"scroll action 좌표가 없습니다: {format_actual_click_test_step(step)}")
        move_fn(step.point)
        scroll_fn(step.scroll_amount)
        return ExecutedGeometryAction(
            action_type=step.action_type,
            description=step.description,
            point=step.point,
        )

    if step.drag_start is not None or step.drag_end is not None:
        if step.drag_start is None or step.drag_end is None:
            raise DisplayGroupInspectionError(f"drag action 좌표가 불완전합니다: {format_actual_click_test_step(step)}")
        drag_fn(step.drag_start, step.drag_end)
        return ExecutedGeometryAction(
            action_type=step.action_type,
            description=step.description,
            drag_start=step.drag_start,
            drag_end=step.drag_end,
        )

    if step.point is None:
        raise DisplayGroupInspectionError(f"click action 좌표가 없습니다: {format_actual_click_test_step(step)}")
    if step.move_before_click:
        move_fn(step.point)
    click_fn(step.point)
    return ExecutedGeometryAction(
        action_type=step.action_type,
        description=step.description,
        point=step.point,
    )


def continuous_wait_after_step(step: ActualClickTestStep) -> float:
    """continue-without-pause mode에서 action별 짧은 시각 확인 대기 시간을 반환한다."""
    if step.action_type.startswith("tab_"):
        return DISPLAY_GROUP_CONTINUOUS_SHORT_WAIT_SECONDS
    if step.action_type in ("source_drag_select", "destination_drag_select"):
        return DISPLAY_GROUP_CONTINUOUS_SHORT_WAIT_SECONDS
    if step.action_type == "copy_detail_click":
        return DISPLAY_GROUP_ACTION_WAIT_SECONDS
    if step.action_type in ("calibrated_scrollbar_drag", "scrollbar_down_click", "scrollbar_up_click"):
        return DISPLAY_GROUP_ACTION_WAIT_SECONDS
    if step.action_type == "paste_click":
        return DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS
    return step.wait_after_seconds


def confirmed_apply_wait_after_step(step: ActualClickTestStep) -> float:
    """confirmed apply mode에서 action별 시각 확인 대기 시간을 반환한다."""
    if step.action_type.startswith("tab_"):
        return DISPLAY_GROUP_CONTINUOUS_SHORT_WAIT_SECONDS
    if step.action_type in ("source_drag_select", "destination_drag_select"):
        return DISPLAY_GROUP_CONTINUOUS_SHORT_WAIT_SECONDS
    if step.action_type == "copy_detail_click":
        return DISPLAY_GROUP_ACTION_WAIT_SECONDS
    if step.action_type in ("scrollbar_down_click", "scrollbar_up_click"):
        return DISPLAY_GROUP_ACTION_WAIT_SECONDS
    if step.action_type == "paste_click":
        return DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS
    if step.action_type == "ok_click":
        return DISPLAY_GROUP_CONTINUOUS_PASTE_WAIT_SECONDS
    return step.wait_after_seconds


def detect_unexpected_channel_popups(owner_pid: int | None) -> tuple[Win32WindowSnapshot, ...]:
    """confirmed apply 중 예기치 않게 열린 채널 관련 popup/dialog를 찾는다."""
    candidates: list[Win32WindowSnapshot] = []
    for window in capture_top_level_windows(owner_pid):
        title = (window.title or "").strip()
        if not window.visible:
            continue
        if "채널" in title or "Channel" in title or "channel" in title:
            candidates.append(window)
    return tuple(candidates)


def ensure_no_unexpected_channel_popup(
    detector: UnexpectedPopupDetectorFunction,
    owner_pid: int | None,
    logger: logging.Logger,
) -> None:
    """채널 popup이 보이면 ESC로 닫고 confirmed apply를 중단한다."""
    popups = detector(owner_pid)
    if not popups:
        return
    for popup in popups:
        logger.error(
            "unexpected channel popup detected | title=%s | class=%s | hwnd=%s | pid=%s",
            popup.title,
            popup.class_name,
            popup.hwnd,
            popup.pid,
        )
    close_open_menu_safely()
    raise DisplayGroupInspectionError("예기치 않은 채널 popup/dialog가 감지되어 confirmed apply mode를 중단했습니다. OK는 클릭하지 않았습니다.")


def paste_step_transfer_summary(step: ActualClickTestStep) -> str:
    """paste_click step 설명에서 source/destination 요약을 추출한다."""
    marker = "| "
    if marker in step.description:
        return step.description.split(marker, 1)[1]
    return step.description


def get_mouse_position() -> tuple[int, int]:
    """현재 마우스 위치를 pyautogui로 읽는다."""
    try:
        import pyautogui

        position = pyautogui.position()
        if hasattr(position, "x") and hasattr(position, "y"):
            return (int(position.x), int(position.y))
        return (int(position[0]), int(position[1]))
    except Exception as exc:
        raise DisplayGroupInspectionError(f"마우스 위치 읽기 실패: {exc}") from exc


def relative_point(point: tuple[int, int], dialog_rect: tuple[int, int, int, int]) -> tuple[float, float]:
    """절대 좌표를 dialog rectangle 기준 상대 좌표로 변환한다."""
    left, top, right, bottom = dialog_rect
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise DisplayGroupInspectionError(f"유효하지 않은 dialog rectangle입니다: {dialog_rect}")
    return (round((point[0] - left) / width, 3), round((point[1] - top) / height, 3))


def format_scrollbar_calibration_point(point: ScrollbarCalibrationPoint) -> str:
    """scrollbar calibration point를 요청된 출력 형식으로 만든다."""
    return (
        f"{point.name}_abs=({point.absolute[0]},{point.absolute[1]}), "
        f"rel=({point.relative[0]:.3f},{point.relative[1]:.3f})"
    )


def validate_point_inside_dialog(
    point: tuple[int, int],
    dialog_rect: tuple[int, int, int, int],
    label: str,
) -> None:
    """한 점이 dialog rectangle 안에 있는지 검증한다."""
    if not is_point_inside_rect(point, dialog_rect):
        raise DisplayGroupInspectionError(f"{label} 좌표가 대화상자 밖입니다: point={point}, dialog_rect={dialog_rect}")


def ensure_display_group_dialog_ready(dialog: Win32WindowSnapshot, logger: logging.Logger) -> Win32WindowSnapshot:
    """실제-click 직전에 표시 그룹 설정창이 여전히 조작 가능한 상태인지 확인한다."""
    current = read_win32_window_snapshot(dialog.hwnd)
    if current is None:
        raise DisplayGroupInspectionError(f"표시 그룹 설정창을 찾지 못해 actual-click test를 중단합니다: HWND={dialog.hwnd}")
    if "표시 그룹 설정" not in current.title:
        raise DisplayGroupInspectionError(
            "표시 그룹 설정창 title이 예상과 다릅니다. "
            f"title={current.title!r}, class={current.class_name!r}, HWND={current.hwnd}"
        )
    if current.class_name != "#32770":
        raise DisplayGroupInspectionError(
            "표시 그룹 설정창 class가 예상과 다릅니다. "
            f"title={current.title!r}, class={current.class_name!r}, HWND={current.hwnd}"
        )
    if not current.visible or not current.enabled:
        raise DisplayGroupInspectionError(
            "표시 그룹 설정창이 visible/enabled 상태가 아니어서 actual-click test를 중단합니다. "
            f"title={current.title} | class={current.class_name} | HWND={current.hwnd} | "
            f"visible={current.visible} | enabled={current.enabled}"
        )

    focus_win32_window_if_possible(current.hwnd, logger)
    current = read_win32_window_snapshot(dialog.hwnd) or current
    rect = parse_rectangle_text(current.rectangle)
    if rect is None:
        raise DisplayGroupInspectionError(f"표시 그룹 설정창 현재 rectangle을 확인할 수 없습니다: HWND={current.hwnd}, rectangle={current.rectangle!r}")
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    size = (width, height)
    has_known_profile = select_display_group_coordinate_profile(current) is not None
    if not (has_known_profile or is_legacy_display_group_dialog_size(size)):
        raise DisplayGroupInspectionError(
            "표시 그룹 설정창 rectangle이 예상 범위가 아닙니다. "
            f"expected≈938x727 또는 942x736, actual={width}x{height}, rectangle={rect}"
        )

    try:
        import win32con
        import win32gui

        foreground = win32gui.GetForegroundWindow()
        foreground_root = win32gui.GetAncestor(foreground, win32con.GA_ROOT) if foreground else 0
        if foreground not in (0, dialog.hwnd) and foreground_root != dialog.hwnd:
            raise DisplayGroupInspectionError(
                "표시 그룹 설정창이 foreground를 잃어 actual-click test를 중단합니다. "
                f"dialog_hwnd={dialog.hwnd} | foreground_hwnd={foreground} | foreground_root={foreground_root}"
            )
    except DisplayGroupInspectionError:
        raise
    except Exception as exc:
        logger.debug("표시 그룹 설정창 foreground 확인을 건너뜁니다: %s", exc)
    return current


def log_actual_click_step_coordinate_context(
    step: "ActualClickTestStep",
    dialog: Win32WindowSnapshot,
    logger: logging.Logger,
) -> None:
    """실제 action 직전 fresh dialog rect와 rel/abs 좌표를 남긴다."""
    rect = parse_rectangle_text(dialog.rectangle)
    if rect is None:
        return
    width, height = display_group_dialog_size(rect)
    for coordinate_name, point in (
        ("point", step.point),
        ("drag_start", step.drag_start),
        ("drag_end", step.drag_end),
    ):
        if point is None:
            continue
        logger.info(
            "Display Group action coordinate | step=%s | type=%s | coordinate=%s | rel=%s | abs=%s | dialog_rect=%s | dialog_size=%sx%s",
            step.step,
            step.action_type,
            coordinate_name,
            relative_point(point, rect),
            point,
            rect,
            width,
            height,
        )


def validate_actual_click_step_against_fresh_dialog(
    step: "ActualClickTestStep",
    dialog: Win32WindowSnapshot,
    logger: logging.Logger,
) -> None:
    """좌표 실행 직전 fresh dialog rectangle 기준으로 step 좌표를 다시 검증한다."""
    rect = parse_rectangle_text(dialog.rectangle)
    if rect is None:
        raise DisplayGroupInspectionError(f"fresh 표시 그룹 설정창 rectangle을 확인할 수 없습니다: {dialog.rectangle!r}")
    for coordinate_name, point in (
        ("point", step.point),
        ("drag_start", step.drag_start),
        ("drag_end", step.drag_end),
    ):
        if point is None:
            continue
        if not is_point_inside_rect(point, rect):
            raise DisplayGroupInspectionError(
                "actual-click step 좌표가 fresh 표시 그룹 설정창 밖입니다: "
                f"type={step.action_type}, coordinate={coordinate_name}, point={point}, fresh_dialog_rect={rect}"
            )
    logger.debug("fresh 표시 그룹 설정창 기준 좌표 검증 완료 | type=%s | rect=%s", step.action_type, rect)


def matching_fresh_actual_click_step(
    original_step: "ActualClickTestStep",
    fresh_sequence: tuple["ActualClickTestStep", ...],
) -> "ActualClickTestStep":
    """같은 sequence step/action_type을 fresh rect로 재계산된 step에서 찾는다."""
    index = original_step.step - 1
    if 0 <= index < len(fresh_sequence):
        candidate = fresh_sequence[index]
        if candidate.action_type == original_step.action_type:
            return candidate
    for candidate in fresh_sequence:
        if candidate.step == original_step.step and candidate.action_type == original_step.action_type:
            return candidate
    raise DisplayGroupInspectionError(
        "fresh 표시 그룹 설정창 기준 sequence에서 동일 step을 찾지 못했습니다: "
        f"step={original_step.step}, action_type={original_step.action_type}"
    )


def click_geometry_point(point: tuple[int, int]) -> None:
    """geometry 좌표 한 점을 pyautogui로 클릭한다."""
    try:
        import pyautogui

        pyautogui.click(x=point[0], y=point[1])
    except Exception as exc:
        raise DisplayGroupInspectionError(f"geometry 좌표 클릭 실패: point={point} ({exc})") from exc


def move_geometry_pointer(point: tuple[int, int]) -> None:
    """geometry 좌표로 마우스를 짧게 이동한다."""
    try:
        import pyautogui

        pyautogui.moveTo(point[0], point[1], duration=0.05)
    except Exception as exc:
        raise DisplayGroupInspectionError(f"geometry 좌표 마우스 이동 실패: point={point} ({exc})") from exc


def scroll_geometry_grid(amount: int) -> None:
    """현재 마우스 위치에서 geometry grid를 스크롤한다."""
    try:
        import pyautogui

        pyautogui.scroll(amount)
    except Exception as exc:
        raise DisplayGroupInspectionError(f"geometry grid 스크롤 실패: amount={amount} ({exc})") from exc


def drag_geometry_between_points(start: tuple[int, int], end: tuple[int, int]) -> None:
    """geometry 좌표 사이를 pyautogui로 drag/select한다."""
    try:
        import pyautogui

        pyautogui.moveTo(start[0], start[1])
        pyautogui.dragTo(end[0], end[1], duration=0.2, button="left")
    except Exception as exc:
        raise DisplayGroupInspectionError(f"geometry 좌표 drag 실패: start={start}, end={end} ({exc})") from exc


def close_display_group_dialog_geometry_with_escape(logger: logging.Logger) -> str:
    """Stage 5B geometry 조사에서는 버튼 대신 ESC만 사용해 닫는다."""
    logger.info("geometry 조사 모드: 표시 그룹 설정창을 ESC로 닫습니다.")
    close_open_menu_safely()
    return "ESC"


def detect_display_group_dialog(
    owner_pid: int | None,
    baseline_hwnds: tuple[int, ...],
    logger: logging.Logger,
    *,
    timeout_seconds: float = DISPLAY_GROUP_DIALOG_TIMEOUT_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> Win32WindowSnapshot:
    """메뉴 실행 후 생성된 표시 그룹 설정 대화상자를 찾는다."""
    deadline = time.monotonic() + timeout_seconds
    last_candidates: tuple[Win32WindowSnapshot, ...] = ()
    while True:
        windows = capture_top_level_windows(owner_pid)
        candidates = filter_display_group_dialog_candidates(windows, owner_pid, baseline_hwnds)
        if candidates:
            if len(candidates) > 1:
                logger.warning("표시 그룹 설정창 후보가 여러 개입니다: %s", format_dialog_candidates(candidates))
            return candidates[0]
        last_candidates = tuple(window for window in windows if owner_pid is None or window.pid == owner_pid)
        if time.monotonic() >= deadline:
            raise DisplayGroupInspectionError(
                "표시 그룹 설정창을 찾지 못했습니다. "
                f"Universal Viewer PID={owner_pid if owner_pid is not None else '확인 불가'} | "
                f"후보={format_dialog_candidates(last_candidates)}"
            )
        time.sleep(poll_interval_seconds)


def filter_display_group_dialog_candidates(
    windows: Iterable[Win32WindowSnapshot],
    owner_pid: int | None,
    baseline_hwnds: Iterable[int] = (),
) -> tuple[Win32WindowSnapshot, ...]:
    """표시 그룹 설정창 후보를 안전 조건과 제목/클래스 힌트로 필터링한다."""
    baseline = set(baseline_hwnds)
    matches: list[tuple[int, Win32WindowSnapshot]] = []
    for window in windows:
        if owner_pid is not None and window.pid != owner_pid:
            continue
        if not window.visible or not window.enabled:
            continue
        is_new_window = window.hwnd not in baseline
        title_match = is_display_group_dialog_title(window.title)
        dialog_like = is_dialog_like_class(window.class_name)
        if not title_match and not (is_new_window and dialog_like):
            continue
        score = 0
        if title_match:
            score += 100
        if is_new_window:
            score += 20
        if window.class_name == "#32770":
            score += 10
        matches.append((score, window))
    return tuple(window for _score, window in sorted(matches, key=lambda item: (-item[0], item[1].hwnd)))


def is_display_group_dialog_title(title: str) -> bool:
    """표시 그룹 설정창으로 볼 수 있는 제목인지 확인한다."""
    normalized = normalize_menu_text(title)
    return any(normalize_menu_text(candidate) in normalized for candidate in DISPLAY_GROUP_DIALOG_TITLE_CANDIDATES)


def is_dialog_like_class(class_name: str) -> bool:
    """대화상자 또는 MFC/Afx 계열 popup으로 볼 수 있는 클래스인지 확인한다."""
    normalized = class_name.casefold()
    return "#32770" in normalized or "dialog" in normalized or "afx" in normalized


def open_display_group_settings_dialog_via_menu(opened: ViewerOpenResult, logger: logging.Logger) -> str:
    """검증된 UIA 메뉴 경로 표시(V) > 표시 그룹 설정(D)...를 기본으로 사용한다."""
    return open_display_group_settings_dialog_via_uia_menu(opened, logger)


def open_display_group_settings_dialog_via_toolbar_button(
    opened: ViewerOpenResult,
    logger: logging.Logger,
    *,
    desktop_factory: UiaDesktopFactory | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    timeout_seconds: float = 5.0,
) -> str:
    """Universal Viewer toolbar Button 'Group Setting'을 UIA로 실행한다."""
    if opened.main_window.handle is None:
        raise DisplayGroupInspectionError("Universal Viewer 메인 창 HWND가 없어 Group Setting toolbar button을 사용할 수 없습니다.")
    desktop = make_uia_desktop(desktop_factory)
    try:
        main_window = desktop.window(handle=opened.main_window.handle)  # type: ignore[attr-defined]
        focus_uia_wrapper_if_possible(main_window, logger)
        wrappers = (main_window, *safe_descendants(main_window))
    except Exception as exc:
        raise DisplayGroupInspectionError(f"Universal Viewer UIA toolbar tree를 읽지 못했습니다: {exc}") from exc

    button = find_first_visible_enabled_wrapper_by(wrappers, is_group_setting_toolbar_button)
    if button is None:
        names = tuple(filter(None, (read_wrapper_name(wrapper) for wrapper in wrappers)))
        raise DisplayGroupInspectionError(f"Group Setting toolbar button을 찾지 못했습니다. UIA 이름 후보={names[:30]}")

    logger.info("Group Setting toolbar button semantic action | name=%s", read_wrapper_name(button))
    invoke_or_click_uia_wrapper(button, logger, "Group Setting toolbar button")
    wait_fn(0.5)
    wait_for_display_group_dialog_title(opened.main_window.pid, logger, timeout_seconds=timeout_seconds)
    return DISPLAY_GROUP_MENU_PATH


def open_display_group_settings_dialog_via_uia_menu(
    opened: ViewerOpenResult,
    logger: logging.Logger,
    *,
    desktop_factory: UiaDesktopFactory | None = None,
    normalize_window_fn: Callable[..., object] = normalize_universal_viewer_main_window,
    wait_fn: GeometryWaitFunction = time.sleep,
) -> str:
    """UIA 메뉴에서 표시(V) > 표시 그룹 설정(D)...를 click_input으로 선택한다."""
    if opened.main_window.handle is None:
        raise DisplayGroupInspectionError("Universal Viewer 메인 창 HWND가 없어 표시 그룹 설정 메뉴를 열 수 없습니다.")

    normalize_window_fn(logger, main_window=opened.main_window, wait_fn=wait_fn)
    focus_win32_window_if_possible(opened.main_window.handle, logger)
    close_open_menu_safely()
    wait_fn(0.2)

    main_rect = get_universal_viewer_main_window_rect(opened.main_window)
    desktop = make_uia_desktop(desktop_factory)
    try:
        main_window = desktop.window(handle=opened.main_window.handle)
        focus_uia_wrapper_if_possible(main_window, logger)
        descendants = tuple(main_window.descendants())
    except Exception as exc:
        raise DisplayGroupInspectionError(f"Universal Viewer UIA 트리를 읽지 못했습니다: {exc}") from exc

    top_menu = find_first_visible_enabled_wrapper(descendants, is_display_top_menu_text)
    if top_menu is None:
        names = tuple(filter(None, (read_wrapper_name(wrapper) for wrapper in descendants)))
        raise DisplayGroupInspectionError(f"표시(V) 상위 메뉴를 찾지 못했습니다. UIA 이름 후보={names[:30]}")

    top_menu_name = read_wrapper_name(top_menu)
    logger.info("표시 상위 메뉴 열기 시도 | name=%s | method=click_input", top_menu_name)
    try:
        top_menu.click_input()  # type: ignore[attr-defined]
    except Exception as exc:
        raise DisplayGroupInspectionError(f"표시(V) 상위 메뉴 클릭 실패: {exc}") from exc
    wait_fn(0.5)

    try:
        menu_item = wait_for_display_group_menu_item(desktop, opened.main_window.pid, main_rect, logger)
        if menu_item is None:
            menu_names = collect_visible_menu_related_names(desktop, owner_pid=opened.main_window.pid, owner_rect=main_rect)
            raise DisplayGroupInspectionError(
                "표시 그룹 설정(D)... 메뉴 항목을 찾지 못했습니다. "
                f"열린 메뉴/UIA 후보={menu_names[:50]}"
            )
        menu_item_name = read_wrapper_name(menu_item)
        logger.info("표시 그룹 설정 메뉴 항목 실행 | name=%s | method=click_input", menu_item_name)
        menu_item.click_input()  # type: ignore[attr-defined]
        wait_for_display_group_dialog_title(opened.main_window.pid, logger, timeout_seconds=DISPLAY_GROUP_DIALOG_TIMEOUT_SECONDS)
    except Exception:
        close_open_menu_safely()
        raise
    return DISPLAY_GROUP_MENU_PATH


def find_display_group_menu_item(
    desktop: object,
    owner_pid: int | None,
    owner_rect: tuple[int, int, int, int] | None = None,
) -> object | None:
    """Desktop/UIA에서 표시 그룹 설정 메뉴 항목을 찾는다."""
    wrappers: list[object] = []
    try:
        top_windows = tuple(desktop.windows())  # type: ignore[attr-defined]
    except Exception:
        top_windows = ()
    for window in top_windows:
        if not is_wrapper_in_viewer_menu_scope(window, owner_pid, owner_rect):
            continue
        wrappers.append(window)
        wrappers.extend(safe_descendants(window))
    return find_first_visible_enabled_wrapper(wrappers, is_display_group_menu_text)


def wait_for_display_group_menu_item(
    desktop: object,
    owner_pid: int | None,
    owner_rect: tuple[int, int, int, int] | None,
    logger: logging.Logger,
    *,
    timeout_seconds: float = 3.0,
    poll_interval: float = 0.2,
) -> object | None:
    """표시 메뉴를 연 뒤 생성되는 표시 그룹 설정 submenu 항목을 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        item = find_display_group_menu_item(desktop, owner_pid, owner_rect)
        if item is not None:
            logger.info("표시 그룹 설정 submenu 후보 탐지 | name=%s", read_wrapper_name(item))
            return item
        time.sleep(poll_interval)
    return None


def find_visible_desktop_menu_item(
    desktop: object,
    owner_pid: int | None,
    text_predicate: Callable[[str], bool],
    owner_rect: tuple[int, int, int, int] | None = None,
) -> object | None:
    """Desktop/UIA 전체에서 현재 열린 popup/MenuItem 후보를 찾는다."""
    wrappers: list[object] = []
    try:
        top_windows = tuple(desktop.windows())  # type: ignore[attr-defined]
    except Exception:
        top_windows = ()
    for window in top_windows:
        if not is_wrapper_in_viewer_menu_scope(window, owner_pid, owner_rect):
            continue
        wrappers.append(window)
        wrappers.extend(safe_descendants(window))

    menu_item = find_first_visible_enabled_wrapper_by(
        wrappers,
        lambda wrapper: text_predicate(read_wrapper_name(wrapper)) and "menu" in safe_control_type(wrapper).casefold(),
    )
    return menu_item or find_first_visible_enabled_wrapper(wrappers, text_predicate)


def is_wrapper_in_viewer_menu_scope(
    wrapper: object,
    owner_pid: int | None,
    owner_rect: tuple[int, int, int, int] | None,
) -> bool:
    """Universal Viewer 또는 그 근처의 popup menu만 후보로 허용한다."""
    pid = safe_process_id(wrapper)
    class_name = safe_class_name(wrapper)
    control_type = safe_control_type(wrapper)
    class_or_type = f"{class_name} {control_type}".casefold()
    popup_like = "#32768" in class_or_type or "popup" in class_or_type or "menu" in control_type.casefold()
    if owner_pid is not None and pid == owner_pid:
        return True
    if not popup_like:
        return False
    if owner_rect is None:
        return True
    wrapper_rect = parse_rectangle_text(safe_rectangle_text(wrapper))
    if wrapper_rect is None:
        return True
    return rectangles_intersect_or_are_near(wrapper_rect, owner_rect, margin=120)


def rectangles_intersect_or_are_near(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
    *,
    margin: int = 0,
) -> bool:
    """두 rectangle이 겹치거나 지정 margin 안에 있는지 확인한다."""
    first_left, first_top, first_right, first_bottom = first
    second_left, second_top, second_right, second_bottom = second
    return not (
        first_right < second_left - margin
        or first_left > second_right + margin
        or first_bottom < second_top - margin
        or first_top > second_bottom + margin
    )


def wait_for_display_group_dialog_title(
    owner_pid: int | None,
    logger: logging.Logger,
    *,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.2,
) -> Win32WindowSnapshot:
    """표시 그룹 설정 dialog가 나타날 때까지 title 기반으로 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    candidates: tuple[Win32WindowSnapshot, ...] = ()
    while time.monotonic() < deadline:
        candidates = tuple(
            window
            for window in capture_top_level_windows(owner_pid)
            if window.visible
            and window.enabled
            and window.class_name == "#32770"
            and is_display_group_dialog_title(window.title)
        )
        if candidates:
            selected = sorted(candidates, key=lambda item: item.hwnd)[0]
            logger.info(
                "Display Group Settings dialog detected | title=%s | class=%s | hwnd=%s | pid=%s | rectangle=%s",
                selected.title,
                selected.class_name,
                selected.hwnd,
                selected.pid,
                selected.rectangle,
            )
            return selected
        time.sleep(poll_interval)
    raise DisplayGroupInspectionError(
        f"표시 그룹 설정 dialog를 찾지 못했습니다: timeout={timeout_seconds}s, last_candidates={format_dialog_candidates(candidates)}"
    )


def collect_visible_menu_related_names(
    desktop: object,
    *,
    owner_pid: int | None = None,
    owner_rect: tuple[int, int, int, int] | None = None,
) -> tuple[str, ...]:
    """진단용으로 현재 보이는 메뉴 관련 UIA 이름을 수집한다."""
    names: list[str] = []
    try:
        windows = tuple(desktop.windows())  # type: ignore[attr-defined]
    except Exception:
        return ()
    for window in windows:
        if not is_wrapper_in_viewer_menu_scope(window, owner_pid, owner_rect):
            continue
        for wrapper in (window, *safe_descendants(window)):
            name = read_wrapper_name(wrapper)
            if not name:
                continue
            class_name = safe_class_name(wrapper)
            control_type = safe_control_type(wrapper)
            combined = f"{name} {class_name} {control_type}".casefold()
            if "menu" in combined or "메뉴" in combined or "#32768" in combined:
                names.append(name)
    return tuple(dict.fromkeys(names))


def collect_display_group_dialog_structure(dialog: Win32WindowSnapshot) -> DisplayGroupDialogSnapshot:
    """표시 그룹 설정창의 win32 child와 UIA 요소를 읽는다."""
    top_level = read_win32_window_snapshot(dialog.hwnd) or dialog
    children = tuple(
        None if snapshot is None else replace(snapshot, depth=depth)
        for hwnd, depth in enum_descendant_hwnds_with_depth(dialog.hwnd)
        for snapshot in (read_win32_window_snapshot(hwnd),)
    )
    win32_children = tuple(child for child in children if child is not None)
    uia_result = collect_uia_elements_with_attempt_logs(dialog.hwnd, top_level.rectangle)
    return DisplayGroupDialogSnapshot(
        top_level=replace(top_level, control_id=None),
        win32_children=win32_children,
        uia_elements=uia_result.elements,
        uia_attempt_logs=uia_result.attempt_logs,
    )


def close_display_group_dialog_without_applying(
    dialog: DisplayGroupDialogSnapshot,
    logger: logging.Logger,
) -> str:
    """확인/적용/저장을 누르지 않고 취소/닫기 또는 Esc로 대화상자를 닫는다."""
    for child in dialog.win32_children:
        if child.class_name.casefold() != "button":
            continue
        if is_forbidden_commit_button_title(child.title):
            logger.info("설정 변경 버튼은 클릭하지 않습니다 | title=%s | HWND=%s", child.title, child.hwnd)
            continue
        if not child.visible or not child.enabled:
            continue
        if is_safe_close_button_title(child.title):
            click_win32_button(child.hwnd)
            return f"BM_CLICK:{child.title or child.hwnd}"
    close_open_menu_safely()
    return "ESC"


def close_display_group_dialog_with_escape(
    _dialog: DisplayGroupDialogSnapshot,
    logger: logging.Logger,
) -> str:
    """pause 모드에서 버튼을 누르지 않고 ESC만 전송한다."""
    logger.info("pause 모드: 표시 그룹 설정창을 ESC로 닫습니다.")
    close_open_menu_safely()
    return "ESC"


def is_safe_close_button_title(title: str) -> bool:
    """설정 변경 없이 닫는 버튼인지 확인한다."""
    return any(button_text_matches(title, candidate) for candidate in SAFE_CLOSE_BUTTON_TITLES)


def is_forbidden_commit_button_title(title: str) -> bool:
    """검사 모드에서 누르면 안 되는 버튼인지 확인한다."""
    return any(button_text_matches(title, candidate) for candidate in FORBIDDEN_COMMIT_BUTTON_TITLES)


def write_display_group_inspection_report(result: DisplayGroupInspectionResult) -> None:
    """표시 그룹 설정창 조사 결과를 로그 파일로 저장한다."""
    lines = build_display_group_inspection_report(result)
    write_text_report_with_bom(result.report_path, lines)


def write_display_group_geometry_report(result: DisplayGroupGeometryInspectionResult) -> None:
    """표시 그룹 설정창 geometry 후보 보고서를 저장한다."""
    lines = build_display_group_geometry_report_lines(
        opened=result.opened,
        menu_path=result.menu_path,
        dialog=result.dialog,
        geometry=result.geometry,
        before_raw_file_hints=result.before_raw_file_hints,
        after_raw_file_hints=result.after_raw_file_hints,
        state_unchanged=result.state_unchanged,
        close_method=result.close_method,
    )
    write_text_report_with_bom(result.report_path, lines)


def write_text_report_with_bom(report_path: Path, lines: Iterable[str]) -> None:
    """Windows PowerShell 한글 표시를 위해 UTF-8 BOM 형식으로 저장한다."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def calculate_display_group_geometry(
    dialog_rectangle: str | tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile = DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE,
) -> DisplayGroupGeometryReport:
    """dialog rectangle과 상대 좌표 프로필로 geometry 후보를 계산한다."""
    rect = dialog_rectangle if isinstance(dialog_rectangle, tuple) else parse_rectangle_text(dialog_rectangle)
    if rect is None:
        raise DisplayGroupInspectionError(f"표시 그룹 설정창 rectangle을 해석하지 못했습니다: {dialog_rectangle}")
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise DisplayGroupInspectionError(f"표시 그룹 설정창 rectangle 크기가 유효하지 않습니다: {rect}")

    areas = (
        geometry_area("estimated_top_tab_row_area", "상단 탭 행 후보", profile.top_tab_row_area, rect),
        geometry_area("estimated_group_name_field_area", "그룹 이름 입력/표시 영역 후보", profile.group_name_field_area, rect),
        geometry_area("estimated_grid_area", "W01/W02 및 CH0001 계열 grid 후보", profile.grid_area, rect),
        geometry_area("estimated_OK_button_area", "OK/확인 버튼 후보. Stage 5B에서는 클릭하지 않음", profile.ok_button_area, rect),
        geometry_area("estimated_Cancel_button_area", "취소/Cancel 버튼 후보. Stage 5B에서는 클릭하지 않음", profile.cancel_button_area, rect),
        geometry_area(
            "estimated_Apply_button_area_if_visible",
            "적용/Apply 버튼 후보. 보일 때만 참고하며 Stage 5B에서는 클릭하지 않음",
            profile.apply_button_area,
            rect,
        ),
        geometry_area("estimated_scale_calculation_button_area", "스케일계산 버튼 후보. 클릭 금지", profile.scale_calculation_button_area, rect),
        geometry_area("estimated_copy_detail_button_area", "복사상세 버튼 후보. 클릭 금지", profile.copy_detail_button_area, rect),
        geometry_area("estimated_paste_button_area", "붙임 버튼 후보. 클릭 금지", profile.paste_button_area, rect),
    )
    lines = (
        geometry_line("estimated_first_row_y", "첫 visible row y 후보(W01/CH0001 근처)", profile.first_row_y_ratio, rect, "y"),
        geometry_line("estimated_row_height", "grid row height 후보", profile.row_height_ratio, rect, "height"),
        geometry_line("estimated_checkbox_column_x", "checkbox column x 후보", profile.checkbox_column_x_ratio, rect, "x"),
        geometry_line("estimated_channel_column_x", "CH0001/CH0002 channel column x 후보", profile.channel_column_x_ratio, rect, "x"),
    )
    return DisplayGroupGeometryReport(profile.name, rect, width, height, areas, lines)


def geometry_area(
    name: str,
    description: str,
    relative_rect: tuple[float, float, float, float],
    dialog_rect: tuple[int, int, int, int],
) -> GeometryAreaCandidate:
    """상대 rectangle을 절대 rectangle으로 변환한다."""
    return GeometryAreaCandidate(name, description, relative_rect, absolute_rect_from_relative(dialog_rect, relative_rect))


def geometry_line(
    name: str,
    description: str,
    relative_value: float,
    dialog_rect: tuple[int, int, int, int],
    axis: str,
) -> GeometryLineCandidate:
    """상대 x/y/height 값을 절대 좌표 또는 픽셀 크기로 변환한다."""
    left, top, right, bottom = dialog_rect
    width = right - left
    height = bottom - top
    if axis == "x":
        absolute = round(left + width * relative_value)
    elif axis == "y":
        absolute = round(top + height * relative_value)
    elif axis == "height":
        absolute = round(height * relative_value)
    else:
        raise ValueError(f"지원하지 않는 geometry axis입니다: {axis}")
    return GeometryLineCandidate(name, description, relative_value, absolute, axis)


def absolute_rect_from_relative(
    dialog_rect: tuple[int, int, int, int],
    relative_rect: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    """대화상자 기준 상대 rectangle을 화면 절대 rectangle으로 변환한다."""
    left, top, right, bottom = dialog_rect
    width = right - left
    height = bottom - top
    rel_left, rel_top, rel_right, rel_bottom = relative_rect
    return (
        round(left + width * rel_left),
        round(top + height * rel_top),
        round(left + width * rel_right),
        round(top + height * rel_bottom),
    )


def build_display_group_geometry_report_lines(
    *,
    opened: ViewerOpenResult,
    menu_path: str,
    dialog: Win32WindowSnapshot,
    geometry: DisplayGroupGeometryReport,
    before_raw_file_hints: tuple[str, ...],
    after_raw_file_hints: tuple[str, ...],
    state_unchanged: bool,
    close_method: str,
) -> list[str]:
    """Stage 5B geometry 후보 보고서 문자열을 구성한다."""
    lines = [
        "[Stage 5B 표시 그룹 설정창 geometry 조사]",
        f"작업본: {opened.work_copy_path}",
        f"메뉴 경로: {menu_path}",
        f"조사 전 Raw Data 힌트: {', '.join(before_raw_file_hints) or '(없음)'}",
        "",
        "[감지된 표시 그룹 설정창]",
        format_win32_snapshot(dialog),
        "",
        "[geometry profile]",
        f"profile_name: {geometry.profile_name}",
        f"dialog absolute rectangle: {geometry.dialog_rect}",
        f"dialog width/height: {geometry.width} x {geometry.height}",
        "",
        "[geometry area candidates]",
    ]
    lines.extend(format_geometry_area_candidate(area) for area in geometry.areas)
    lines.extend(["", "[geometry line candidates]"])
    lines.extend(format_geometry_line_candidate(line) for line in geometry.lines)
    lines.extend(
        [
            "",
            "[주의]",
            "Stage 5B는 custom-drawn grid를 읽기 위한 좌표 후보만 계산합니다.",
            "checkbox/cell/button 클릭, OK/Apply/Save, 인쇄, PDF 생성은 수행하지 않습니다.",
            "",
            "[닫기 및 상태 확인]",
            f"닫기 방식: {close_method}",
            f"조사 후 Raw Data 힌트: {', '.join(after_raw_file_hints) or '(닫기 전 또는 미확인)'}",
            f"열린 파일 힌트 변경 없음: {str(state_unchanged).lower()}",
        ]
    )
    return lines


def format_geometry_area_candidate(area: GeometryAreaCandidate) -> str:
    """geometry area 후보를 한 줄로 만든다."""
    return (
        f"- {area.name}: {area.description} | "
        f"absolute={area.absolute_rect} | relative_to_dialog_top_left={area.relative_rect}"
    )


def format_geometry_line_candidate(line: GeometryLineCandidate) -> str:
    """geometry x/y/height 후보를 한 줄로 만든다."""
    return (
        f"- {line.name}: {line.description} | axis={line.axis} | "
        f"absolute={line.absolute_value} | relative_to_dialog_top_left={line.relative_value:.3f}"
    )


def validate_heating_point_count(count: int) -> None:
    """현재 preview에서 지원하는 Heating Point 개수 범위를 검증한다."""
    if count < 1 or count > 48:
        raise DisplayGroupInspectionError(f"--heating-point-count는 1부터 48까지 지원합니다: {count}")


def heating_point_to_group_position(index: int) -> HeatingPointGridPosition:
    """Heating Point index를 group/page와 row 번호로 변환한다."""
    if index < 1 or index > 48:
        raise DisplayGroupInspectionError(f"Heating Point index는 1부터 48까지 지원합니다: {index}")
    return HeatingPointGridPosition(
        heating_point_index=index,
        group_no=((index - 1) // 10) + 1,
        row_no=((index - 1) % 10) + 1,
    )


def calculate_display_group_geometry_action_preview(
    geometry: DisplayGroupGeometryReport,
    profile: DisplayGroupGeometryProfile,
    heating_point_count: int,
) -> DisplayGroupGeometryActionPreview:
    """Heating Point 개수에 따라 실제 클릭 없는 geometry action 후보를 계산한다."""
    validate_heating_point_count(heating_point_count)
    positions = tuple(heating_point_to_group_position(index) for index in range(1, heating_point_count + 1))
    tab_coordinates = tuple(
        (group_no, point_from_relative(geometry.dialog_rect, x_ratio, profile.group_tab_y_ratio))
        for group_no, x_ratio in enumerate(profile.group_tab_x_ratios, start=1)
    )
    tab_map = dict(tab_coordinates)
    actions: list[PlannedGeometryAction] = []
    warnings: list[str] = []
    step = 1
    actions.append(
        PlannedGeometryAction(
            step,
            "tab_candidate",
            "group/page 01 탭 좌표 후보. preview에서는 클릭하지 않음",
            group_no=1,
            point=tab_map[1],
        )
    )
    step += 1
    for position in positions:
        actions.append(
            PlannedGeometryAction(
                step,
                "row_candidate",
                (
                    f"Heating Point {position.heating_point_index:02d} -> "
                    f"group/page {position.group_no:02d}, row {position.row_no:02d} "
                    "checkbox/channel 좌표 후보. preview에서는 클릭하지 않음"
                ),
                group_no=position.group_no,
                row_no=position.row_no,
                point=checkbox_coordinate_for_row(geometry.dialog_rect, profile, position.row_no),
                drag_start=channel_coordinate_for_row(geometry.dialog_rect, profile, position.row_no),
                heating_points=(position.heating_point_index,),
            )
        )
        step += 1

    if heating_point_count > 10:
        group_01_scrolled_down = False
        for block in iter_display_group_copy_blocks(heating_point_count):
            group_no = int(block["source_group"])
            source_row_count = int(block["source_row_count"])
            destination_start = int(block["destination_start"])
            destination_end = int(block["destination_end"])
            source_points = tuple(range(((group_no - 1) * 10) + 1, ((group_no - 1) * 10) + source_row_count + 1))
            actions.append(
                PlannedGeometryAction(
                    step,
                    "move_to_source_group_candidate",
                    f"group/page {group_no:02d}로 이동 예정. preview에서는 탭 클릭하지 않음",
                    group_no=group_no,
                    point=tab_map[group_no],
                    heating_points=source_points,
                )
            )
            step += 1
            actions.append(
                PlannedGeometryAction(
                    step,
                    "source_drag_select_candidate",
                    f"source group/page {group_no:02d} W01~W{source_row_count:02d} drag/select 후보. preview에서는 드래그하지 않음",
                    group_no=group_no,
                    row_no=1,
                    drag_start=drag_select_coordinate_for_row(geometry.dialog_rect, profile, 1, "start"),
                    drag_end=drag_select_coordinate_for_row(geometry.dialog_rect, profile, source_row_count, "end"),
                    heating_points=source_points,
                )
            )
            step += 1
            actions.append(
                PlannedGeometryAction(
                    step,
                    "copy_detail_candidate",
                    "복사상세 버튼 좌표 후보. preview에서는 클릭하지 않음",
                    group_no=group_no,
                    point=center_of_relative_area(geometry.dialog_rect, profile.copy_detail_button_area),
                    heating_points=source_points,
                )
            )
            step += 1
            actions.append(
                PlannedGeometryAction(
                    step,
                    "return_to_group_01_candidate",
                    "group/page 01로 복귀 예정. preview에서는 탭 클릭하지 않음",
                    group_no=1,
                    point=tab_map[1],
                    heating_points=source_points,
                )
            )
            step += 1
            if destination_start >= 31:
                if not group_01_scrolled_down:
                    scrollbar_down_point = scrollbar_down_click_coordinate(geometry.dialog_rect)
                    actions.append(
                        PlannedGeometryAction(
                            step,
                            "scrollbar_down_click_candidate",
                            (
                                "group/page 01 scrollbar_down_click_abs 후보. "
                                f"scrollbar_down_click_rel={DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL}. "
                                "preview에서는 클릭하지 않음 | W20~W50 visible state로 전환"
                            ),
                            group_no=1,
                            point=scrollbar_down_point,
                            heating_points=source_points,
                        )
                    )
                    step += 1
                    group_01_scrolled_down = True
                destination_drag_start = drag_select_coordinate_for_scrolled_destination_row(
                    geometry.dialog_rect, profile, destination_start, "start"
                )
                destination_drag_end = drag_select_coordinate_for_scrolled_destination_row(
                    geometry.dialog_rect, profile, destination_end, "end"
                )
                if destination_start >= 41:
                    start_rel = DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL
                else:
                    start_rel = DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL
                view_label = f"scrolled view W20~W50 visible, destination_start_rel={start_rel}"
            else:
                destination_drag_start = drag_select_coordinate_for_row(geometry.dialog_rect, profile, destination_start, "start")
                destination_drag_end = drag_select_coordinate_for_row(geometry.dialog_rect, profile, destination_end, "end")
                view_label = "normal view"
            actions.append(
                PlannedGeometryAction(
                    step,
                    "drag_select_insertion_area_candidate",
                    (
                        f"destination group/page 01 W{destination_start:02d}~W{destination_end:02d} "
                        f"drag/select 후보 ({view_label}). preview에서는 드래그하지 않음"
                    ),
                    group_no=1,
                    row_no=destination_start,
                    drag_start=destination_drag_start,
                    drag_end=destination_drag_end,
                    heating_points=source_points,
                )
            )
            step += 1
            actions.append(
                PlannedGeometryAction(
                    step,
                    "paste_candidate",
                    "붙임 버튼 좌표 후보. preview에서는 클릭하지 않음",
                    group_no=1,
                    point=center_of_relative_area(geometry.dialog_rect, profile.paste_button_area),
                    heating_points=source_points,
                )
            )
            step += 1

    actions.extend(
        (
            PlannedGeometryAction(
                step,
                "ok_button_candidate",
                f"OK/확인 버튼 좌표 후보. ok_button_rel={DISPLAY_GROUP_OK_BUTTON_REL}. preview에서는 클릭하지 않음",
                point=center_of_relative_area(geometry.dialog_rect, profile.ok_button_area),
            ),
            PlannedGeometryAction(
                step + 1,
                "cancel_button_candidate",
                "취소/Cancel 버튼 좌표 후보. 실제 닫기는 ESC를 사용함",
                point=center_of_relative_area(geometry.dialog_rect, profile.cancel_button_area),
            ),
        )
    )
    validate_planned_geometry_actions_inside_dialog(actions, geometry.dialog_rect)
    return DisplayGroupGeometryActionPreview(heating_point_count, positions, tab_coordinates, tuple(actions), tuple(warnings))


def calculate_display_group_max_48_action_preview(
    geometry: DisplayGroupGeometryReport,
    profile: DisplayGroupGeometryProfile,
) -> DisplayGroupGeometryActionPreview:
    """Heating Point count 입력 없이 max-48 workflow의 no-click preview를 계산한다."""
    heating_point_count = 48
    positions = tuple(heating_point_to_group_position(index) for index in range(1, heating_point_count + 1))
    tab_coordinates = tuple(
        (group_no, point_from_relative(geometry.dialog_rect, x_ratio, profile.group_tab_y_ratio))
        for group_no, x_ratio in enumerate(profile.group_tab_x_ratios, start=1)
    )
    tab_map = dict(tab_coordinates)
    actions: list[PlannedGeometryAction] = []
    warnings: list[str] = ["max-48 preview: actual Heating Point count와 무관하게 group/page 02~05 전체를 처리하는 계획입니다."]
    step = 1
    actions.append(
        PlannedGeometryAction(
            step,
            "tab_candidate",
            "group/page 01 탭 좌표 후보. preview에서는 클릭하지 않음",
            group_no=1,
            point=tab_map[1],
        )
    )
    step += 1
    for position in positions:
        actions.append(
            PlannedGeometryAction(
                step,
                "row_candidate",
                (
                    f"Heating Point {position.heating_point_index:02d} -> "
                    f"group/page {position.group_no:02d}, row {position.row_no:02d} "
                    "checkbox/channel 좌표 후보. preview에서는 클릭하지 않음"
                ),
                group_no=position.group_no,
                row_no=position.row_no,
                point=checkbox_coordinate_for_row(geometry.dialog_rect, profile, position.row_no),
                drag_start=channel_coordinate_for_row(geometry.dialog_rect, profile, position.row_no),
                heating_points=(position.heating_point_index,),
            )
        )
        step += 1

    for block in iter_display_group_max_48_copy_blocks():
        group_no = int(block["source_group"])
        source_row_count = int(block["source_row_count"])
        destination_start = int(block["destination_start"])
        destination_end = int(block["destination_end"])
        source_points = tuple(range(((group_no - 1) * 10) + 1, ((group_no - 1) * 10) + source_row_count + 1))
        actions.append(
            PlannedGeometryAction(
                step,
                "move_to_source_group_candidate",
                f"group/page {group_no:02d}로 이동 예정. preview에서는 탭 클릭하지 않음",
                group_no=group_no,
                point=tab_map[group_no],
                heating_points=source_points,
            )
        )
        step += 1
        if group_no == 5:
            actions.append(
                PlannedGeometryAction(
                    step,
                    "scrollbar_up_click_candidate",
                    (
                        "group/page 05 source W01~W08 선택 전 scrollbar_up_click_abs 후보. "
                        f"scrollbar_up_click_rel={DISPLAY_GROUP_SCROLLBAR_UP_CLICK_REL}. preview에서는 클릭하지 않음"
                    ),
                    group_no=group_no,
                    point=scrollbar_up_click_coordinate(geometry.dialog_rect),
                    heating_points=source_points,
                )
            )
            step += 1
        actions.append(
            PlannedGeometryAction(
                step,
                "source_drag_select_candidate",
                f"source group/page {group_no:02d} W01~W{source_row_count:02d} drag/select 후보. preview에서는 드래그하지 않음",
                group_no=group_no,
                row_no=1,
                drag_start=drag_select_coordinate_for_row(geometry.dialog_rect, profile, 1, "start"),
                drag_end=drag_select_coordinate_for_row(geometry.dialog_rect, profile, source_row_count, "end"),
                heating_points=source_points,
            )
        )
        step += 1
        actions.append(
            PlannedGeometryAction(
                step,
                "copy_detail_candidate",
                "복사상세 버튼 좌표 후보. preview에서는 클릭하지 않음",
                group_no=group_no,
                point=center_of_relative_area(geometry.dialog_rect, profile.copy_detail_button_area),
                heating_points=source_points,
            )
        )
        step += 1
        actions.append(
            PlannedGeometryAction(
                step,
                "return_to_group_01_candidate",
                "group/page 01로 복귀 예정. preview에서는 탭 클릭하지 않음",
                group_no=1,
                point=tab_map[1],
                heating_points=source_points,
            )
        )
        step += 1
        if destination_start >= 31:
            actions.append(
                PlannedGeometryAction(
                    step,
                    "scrollbar_down_click_candidate",
                    (
                        "group/page 01 scrollbar_down_click_abs 후보. "
                        f"scrollbar_down_click_rel={DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL}. "
                        "preview에서는 클릭하지 않음 | W20~W50 visible state로 전환"
                    ),
                    group_no=1,
                    point=scrollbar_down_click_coordinate(geometry.dialog_rect),
                    heating_points=source_points,
                )
            )
            step += 1
            destination_drag_start = drag_select_coordinate_for_scrolled_destination_row(
                geometry.dialog_rect, profile, destination_start, "start"
            )
            destination_drag_end = drag_select_coordinate_for_scrolled_destination_row(
                geometry.dialog_rect, profile, destination_end, "end"
            )
            start_rel = (
                DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL
                if destination_start >= 41
                else DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL
            )
            view_label = f"scrolled view W20~W50 visible, destination_start_rel={start_rel}"
        else:
            destination_drag_start = drag_select_coordinate_for_row(geometry.dialog_rect, profile, destination_start, "start")
            destination_drag_end = drag_select_coordinate_for_row(geometry.dialog_rect, profile, destination_end, "end")
            view_label = "normal view"
        actions.append(
            PlannedGeometryAction(
                step,
                "drag_select_insertion_area_candidate",
                (
                    f"destination group/page 01 W{destination_start:02d}~W{destination_end:02d} "
                    f"drag/select 후보 ({view_label}). preview에서는 드래그하지 않음"
                ),
                group_no=1,
                row_no=destination_start,
                drag_start=destination_drag_start,
                drag_end=destination_drag_end,
                heating_points=source_points,
            )
        )
        step += 1
        actions.append(
            PlannedGeometryAction(
                step,
                "paste_candidate",
                "붙임 버튼 좌표 후보. preview에서는 클릭하지 않음",
                group_no=1,
                point=center_of_relative_area(geometry.dialog_rect, profile.paste_button_area),
                heating_points=source_points,
            )
        )
        step += 1

    actions.extend(
        (
            PlannedGeometryAction(
                step,
                "ok_button_candidate",
                f"OK/확인 버튼 좌표 후보. ok_button_rel={DISPLAY_GROUP_OK_BUTTON_REL}. preview에서는 클릭하지 않음",
                point=center_of_relative_area(geometry.dialog_rect, profile.ok_button_area),
            ),
            PlannedGeometryAction(
                step + 1,
                "cancel_button_candidate",
                "취소/Cancel 버튼 좌표 후보. 실제 닫기는 ESC를 사용함",
                point=center_of_relative_area(geometry.dialog_rect, profile.cancel_button_area),
            ),
        )
    )
    validate_planned_geometry_actions_inside_dialog(actions, geometry.dialog_rect)
    return DisplayGroupGeometryActionPreview(heating_point_count, positions, tab_coordinates, tuple(actions), tuple(warnings))


def build_drag_select_description(target_start_row: int, target_end_row: int) -> str:
    """drag/select 후보 설명을 구성한다."""
    if target_start_row == target_end_row:
        return f"W{target_start_row:02d} 시작 삽입 영역 drag/select 후보. preview에서는 드래그하지 않음"
    return (
        f"W{target_start_row:02d}~W{target_end_row:02d} 삽입 영역 drag/select 후보. "
        "preview에서는 드래그하지 않음"
    )


def clip_drag_end_to_visible_grid(
    geometry: DisplayGroupGeometryReport,
    drag_end: tuple[int, int],
    warnings: list[str],
) -> tuple[int, int]:
    """drag 끝 좌표가 visible grid 아래로 내려가면 grid bottom으로 clip한다."""
    grid_bottom = visible_grid_bottom(geometry)
    if drag_end[1] <= grid_bottom:
        return drag_end

    warning = "target range extends beyond visible grid; scrolling or additional handling may be required"
    if warning not in warnings:
        warnings.append(warning)
    return (drag_end[0], grid_bottom)


def visible_grid_bottom(geometry: DisplayGroupGeometryReport) -> int:
    """현재 geometry profile이 추정한 visible grid의 하단 y 좌표를 반환한다."""
    grid_areas = tuple(area for area in geometry.areas if area.name == "estimated_grid_area")
    if not grid_areas:
        return geometry.dialog_rect[3]
    return min(grid_areas[0].absolute_rect[3], geometry.dialog_rect[3])


def visible_grid_rect(geometry: DisplayGroupGeometryReport) -> tuple[int, int, int, int]:
    """현재 geometry profile이 추정한 visible grid rectangle을 반환한다."""
    grid_areas = tuple(area for area in geometry.areas if area.name == "estimated_grid_area")
    if not grid_areas:
        return geometry.dialog_rect
    left, top, right, bottom = grid_areas[0].absolute_rect
    dialog_left, dialog_top, dialog_right, dialog_bottom = geometry.dialog_rect
    return (
        max(left, dialog_left),
        max(top, dialog_top),
        min(right, dialog_right),
        min(bottom, dialog_bottom),
    )


def validate_drag_step_inside_visible_grid(step: ActualClickTestStep, grid_rect: tuple[int, int, int, int]) -> None:
    """스크롤 목적지 drag/select 좌표가 추정 visible grid 안에 있는지 검증한다."""
    for coordinate_name, point in (("drag_start", step.drag_start), ("drag_end", step.drag_end)):
        if point is None:
            raise DisplayGroupInspectionError(
                f"scrolled destination drag 좌표가 불완전합니다: {format_actual_click_test_step(step)}"
            )
        if not is_point_inside_rect(point, grid_rect):
            raise DisplayGroupInspectionError(
                "scrolled destination drag 좌표가 visible grid 밖입니다: "
                f"step={step.step}, type={step.action_type}, coordinate={coordinate_name}, "
                f"point={point}, visible_grid_rect={grid_rect}"
            )


def validate_planned_geometry_actions_inside_dialog(
    actions: list[PlannedGeometryAction],
    dialog_rect: tuple[int, int, int, int],
) -> None:
    """preview action의 모든 좌표가 dialog rectangle 안에 있는지 검증한다."""
    for action in actions:
        for coordinate_name, point in (
            ("point", action.point),
            ("drag_start", action.drag_start),
            ("drag_end", action.drag_end),
        ):
            if point is None:
                continue
            if not is_point_inside_rect(point, dialog_rect):
                raise DisplayGroupInspectionError(
                    "표시 그룹 geometry preview 좌표가 대화상자 밖입니다: "
                    f"step={action.step}, type={action.action_type}, coordinate={coordinate_name}, "
                    f"point={point}, dialog_rect={dialog_rect}"
                )


def is_point_inside_rect(point: tuple[int, int], rect: tuple[int, int, int, int]) -> bool:
    """점이 rectangle 내부 또는 경계 위에 있는지 확인한다."""
    x, y = point
    left, top, right, bottom = rect
    return left <= x <= right and top <= y <= bottom


def point_from_relative(
    dialog_rect: tuple[int, int, int, int],
    x_ratio: float,
    y_ratio: float,
) -> tuple[int, int]:
    """대화상자 기준 상대 좌표를 절대 좌표로 변환한다."""
    left, top, right, bottom = dialog_rect
    return (round(left + (right - left) * x_ratio), round(top + (bottom - top) * y_ratio))


def display_group_dialog_size(dialog_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Display Group dialog rectangle에서 width/height를 계산한다."""
    left, top, right, bottom = dialog_rect
    return (right - left, bottom - top)


def is_size_close(
    actual_size: tuple[int, int],
    expected_size: tuple[int, int],
    *,
    tolerance: int,
) -> bool:
    """창 레이아웃 프로필 선택용 size tolerance 검사."""
    return (
        abs(actual_size[0] - expected_size[0]) <= tolerance
        and abs(actual_size[1] - expected_size[1]) <= tolerance
    )


def is_legacy_display_group_dialog_size(actual_size: tuple[int, int]) -> bool:
    """기존 ADMIN/original PC에서 검증된 Display Group dialog size 범위."""
    width, height = actual_size
    return 850 <= width <= 1050 and 650 <= height <= 850


def select_display_group_coordinate_profile(
    dialog: Win32WindowSnapshot,
    *,
    profiles: tuple[dict[str, object], ...] = DISPLAY_GROUP_COORDINATE_PROFILES,
    tolerance: int = DISPLAY_GROUP_PROFILE_SIZE_TOLERANCE_PX,
) -> dict[str, object] | None:
    """COMPUTERNAME이 아니라 dialog title/class/size/layout으로 좌표 프로필을 선택한다."""
    rect = parse_rectangle_text(dialog.rectangle)
    if rect is None:
        return None
    actual_size = display_group_dialog_size(rect)
    for profile in profiles:
        expected_title = str(profile["dialog_title"])
        expected_class = str(profile["dialog_class"])
        expected_size = tuple(int(value) for value in profile["dialog_size"])  # type: ignore[arg-type]
        if expected_title not in dialog.title:
            continue
        if dialog.class_name != expected_class:
            continue
        if not is_size_close(actual_size, expected_size, tolerance=tolerance):
            continue
        return profile
    return None


def require_display_group_coordinate_profile(dialog: Win32WindowSnapshot) -> dict[str, object]:
    """새 profile 기반 workflow에서 사용할 Display Group 좌표 프로필을 찾지 못하면 안전하게 중단한다."""
    profile = select_display_group_coordinate_profile(dialog)
    if profile is None:
        rect = parse_rectangle_text(dialog.rectangle)
        actual_size = display_group_dialog_size(rect) if rect is not None else "unknown"
        expected_size = DISPLAY_GROUP_PROFILE_C_WORKFLOW_942x736["dialog_size"]
        tolerance = DISPLAY_GROUP_PROFILE_SIZE_TOLERANCE_PX
        raise DisplayGroupInspectionError(
            "Display Group Settings size does not match verified C profile; "
            "aborting instead of using old coordinates. "
            f"expected={expected_size}±{tolerance}px, actual={actual_size}, "
            f"title={dialog.title!r}, class={dialog.class_name!r}, rectangle={dialog.rectangle!r}"
        )
    return profile


def relative_point_from_coordinate_profile(profile: dict[str, object], key: str) -> tuple[float, float]:
    """dict 기반 Display Group coordinate profile에서 rel point를 읽는다."""
    value = profile[key]
    if not isinstance(value, tuple) or len(value) != 2:
        raise DisplayGroupInspectionError(f"Display Group profile coordinate가 올바르지 않습니다: key={key}, value={value!r}")
    return (float(value[0]), float(value[1]))


def point_from_coordinate_profile(
    dialog_rect: tuple[int, int, int, int],
    profile: dict[str, object],
    key: str,
) -> tuple[int, int]:
    """Display Group coordinate profile rel point를 fresh dialog rect 기준 abs point로 변환한다."""
    return point_from_relative(dialog_rect, *relative_point_from_coordinate_profile(profile, key))


def profile_step_description(text: str, *keys: str, profile: dict[str, object]) -> str:
    """실제 실행 로그에 rel coordinate가 남도록 step description에 profile key/value를 포함한다."""
    rel_parts = ", ".join(f"{key}_rel={relative_point_from_coordinate_profile(profile, key)}" for key in keys)
    return f"{text} | {rel_parts}" if rel_parts else text


def build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
    dialog_rect: tuple[int, int, int, int],
    coordinate_profile: dict[str, object],
) -> tuple[ActualClickTestStep, ...]:
    """C workflow 942x736처럼 검증된 explicit relative-coordinate profile 기반 max-48 sequence."""
    step_no = 1
    steps: list[ActualClickTestStep] = []

    def click_step(action_type: str, description: str, key: str, *, move_before_click: bool = False) -> None:
        nonlocal step_no
        steps.append(
            ActualClickTestStep(
                step_no,
                action_type,
                profile_step_description(description, key, profile=coordinate_profile),
                point=point_from_coordinate_profile(dialog_rect, coordinate_profile, key),
                move_before_click=move_before_click,
            )
        )
        step_no += 1

    def drag_step(action_type: str, description: str, start_key: str, end_key: str) -> None:
        nonlocal step_no
        steps.append(
            ActualClickTestStep(
                step_no,
                action_type,
                profile_step_description(description, start_key, end_key, profile=coordinate_profile),
                drag_start=point_from_coordinate_profile(dialog_rect, coordinate_profile, start_key),
                drag_end=point_from_coordinate_profile(dialog_rect, coordinate_profile, end_key),
            )
        )
        step_no += 1

    click_step("tab_02_click", "group/page 02 tab 클릭", "tab_02")
    drag_step("source_drag_select", "source group/page 02 W01~W10 drag/select", "source_w01_start", "source_w10_end")
    click_step("copy_detail_click", "복사상세 버튼 클릭", "copy_detail", move_before_click=True)
    click_step("tab_01_click", "group/page 01 tab 클릭", "tab_01")
    drag_step("destination_drag_select", "destination group/page 01 W11~W20 drag/select (profile C normal view)", "dest_w11_start", "dest_w20_end")
    click_step("paste_click", "붙임 버튼 클릭 | source group/page 02 to destination W11~W20", "paste", move_before_click=True)

    click_step("tab_03_click", "group/page 03 tab 클릭", "tab_03")
    drag_step("source_drag_select", "source group/page 03 W01~W10 drag/select", "source_w01_start", "source_w10_end")
    click_step("copy_detail_click", "복사상세 버튼 클릭", "copy_detail", move_before_click=True)
    click_step("tab_01_click", "group/page 01 tab 클릭", "tab_01")
    drag_step("destination_drag_select", "destination group/page 01 W21~W30 drag/select (profile C normal view)", "dest_w21_start", "dest_w30_end")
    click_step("paste_click", "붙임 버튼 클릭 | source group/page 03 to destination W21~W30", "paste", move_before_click=True)

    click_step("tab_04_click", "group/page 04 tab 클릭", "tab_04")
    drag_step("source_drag_select", "source group/page 04 W01~W10 drag/select", "source_w01_start", "source_w10_end")
    click_step("copy_detail_click", "복사상세 버튼 클릭", "copy_detail", move_before_click=True)
    click_step("tab_01_click", "group/page 01 tab 클릭", "tab_01")
    click_step("scrollbar_down_click", "group/page 01 scrollbar down area click", "scroll_down")
    drag_step("destination_drag_select", "destination group/page 01 W31~W40 drag/select (profile C scrolled view)", "dest_w31_start", "dest_w40_end")
    click_step("paste_click", "붙임 버튼 클릭 | source group/page 04 to destination W31~W40", "paste", move_before_click=True)

    click_step("tab_05_click", "group/page 05 tab 클릭", "tab_05")
    click_step("scrollbar_up_click", "group/page 05 scrollbar up area click before source W01~W08", "scroll_up")
    drag_step("source_drag_select", "source group/page 05 W01~W08 drag/select", "source_w01_start", "source_w08_end")
    click_step("copy_detail_click", "복사상세 버튼 클릭", "copy_detail", move_before_click=True)
    click_step("tab_01_click", "group/page 01 tab 클릭", "tab_01")
    click_step("scrollbar_down_click", "group/page 01 scrollbar down area click", "scroll_down")
    drag_step("destination_drag_select", "destination group/page 01 W41~W48 drag/select (profile C scrolled view)", "dest_w41_start", "dest_w48_end")
    click_step("paste_click", "붙임 버튼 클릭 | source group/page 05 to destination W41~W48", "paste", move_before_click=True)

    click_step("ok_click", "max-48 confirmed mode OK 버튼 클릭", "ok")
    return tuple(steps)


def convert_actual_steps_to_planned_actions(
    steps: tuple[ActualClickTestStep, ...],
) -> tuple[PlannedGeometryAction, ...]:
    """profile 기반 actual step을 no-click preview action으로 변환한다."""
    return tuple(
        PlannedGeometryAction(
            step=step.step,
            action_type=step.action_type,
            description=step.description,
            point=step.point,
            drag_start=step.drag_start,
            drag_end=step.drag_end,
        )
        for step in steps
    )


def build_display_group_coordinate_profile_preview(
    sequence: tuple[ActualClickTestStep, ...],
    *,
    heating_point_count: int = 48,
) -> DisplayGroupGeometryActionPreview:
    """명시 좌표 profile sequence를 기존 preview result 형태로 감싼다."""
    return DisplayGroupGeometryActionPreview(
        heating_point_count=heating_point_count,
        positions=tuple(heating_point_to_group_position(index) for index in range(1, heating_point_count + 1)),
        tab_coordinates=tuple(
            (int(step.action_type[4:6]), step.point)
            for step in sequence
            if step.action_type.startswith("tab_") and step.point is not None
        ),
        actions=convert_actual_steps_to_planned_actions(sequence),
    )


def build_display_group_max_48_sequence_for_dialog(
    dialog: Win32WindowSnapshot,
    geometry: DisplayGroupGeometryReport,
    legacy_profile: DisplayGroupGeometryProfile,
    *,
    required_coordinate_profile: dict[str, object] | None = None,
) -> tuple[ActualClickTestStep, ...]:
    """현재 dialog layout에 맞는 max-48 sequence를 고른다."""
    coordinate_profile = select_display_group_coordinate_profile(dialog)
    if required_coordinate_profile is not None:
        if coordinate_profile is not required_coordinate_profile:
            rect = parse_rectangle_text(dialog.rectangle)
            actual_size = display_group_dialog_size(rect) if rect is not None else "unknown"
            raise DisplayGroupInspectionError(
                "Display Group coordinate profile changed or no longer matches the fresh dialog. "
                "Aborting before using fallback coordinates. "
                f"title={dialog.title!r}, class={dialog.class_name!r}, size={actual_size}, rectangle={dialog.rectangle!r}"
            )
        return build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            geometry.dialog_rect,
            required_coordinate_profile,
        )
    if coordinate_profile is not None:
        return build_display_group_max_48_confirmed_sequence_from_coordinate_profile(
            geometry.dialog_rect,
            coordinate_profile,
        )
    raise DisplayGroupInspectionError(
        "Display Group Settings size does not match verified C profile; "
        "aborting instead of using old coordinates."
    )


def calculate_time_axis_full_display_points(main_window_rect: tuple[int, int, int, int]) -> TimeAxisFullDisplayResult:
    """Universal Viewer 메인 창 기준 시간축 > 전부 표시 좌표를 계산하고 검증한다."""
    time_axis_menu_point = point_from_relative(main_window_rect, *UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL)
    time_axis_full_display_point = point_from_relative(main_window_rect, *UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL)
    for name, point in (
        ("time_axis_menu_abs", time_axis_menu_point),
        ("time_axis_full_display_abs", time_axis_full_display_point),
    ):
        if not is_point_inside_rect(point, main_window_rect):
            raise DisplayGroupInspectionError(
                "Universal Viewer 시간축 좌표가 메인 창 밖입니다: "
                f"{name}={point}, main_window_rect={main_window_rect}"
            )
    return TimeAxisFullDisplayResult(
        main_window_rect=main_window_rect,
        time_axis_menu_point=time_axis_menu_point,
        time_axis_full_display_point=time_axis_full_display_point,
    )


def get_universal_viewer_main_window_rect(
    main_window: WindowInfo,
    *,
    snapshot_fn: Callable[[int], Win32WindowSnapshot | None] | None = None,
) -> tuple[int, int, int, int]:
    """Universal Viewer 메인 창 HWND에서 현재 창 rectangle을 읽는다."""
    if main_window.handle is None:
        raise DisplayGroupInspectionError("Universal Viewer 메인 창 HWND가 없어 시간축 좌표를 계산할 수 없습니다.")
    read_snapshot = snapshot_fn or read_win32_window_snapshot
    snapshot = read_snapshot(int(main_window.handle))
    if snapshot is None:
        raise DisplayGroupInspectionError(f"Universal Viewer 메인 창 정보를 읽을 수 없습니다: HWND={main_window.handle}")
    rect = parse_rectangle_text(snapshot.rectangle)
    if rect is None:
        raise DisplayGroupInspectionError(
            "Universal Viewer 메인 창 rectangle을 확인할 수 없습니다: "
            f"HWND={main_window.handle}, rectangle={snapshot.rectangle!r}"
        )
    return rect


def apply_time_axis_full_display_by_uia(
    opened: ViewerOpenResult,
    logger: logging.Logger,
    *,
    main_window_rect: tuple[int, int, int, int],
    desktop_factory: UiaDesktopFactory | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
) -> TimeAxisFullDisplayResult:
    """UIA semantic action으로 시간축 > 전부 표시를 실행한다."""
    if opened.main_window.handle is None:
        raise DisplayGroupInspectionError("Universal Viewer 메인 창 HWND가 없어 시간축 UIA action을 사용할 수 없습니다.")
    desktop = make_uia_desktop(desktop_factory)
    try:
        main_window = desktop.window(handle=opened.main_window.handle)  # type: ignore[attr-defined]
        focus_uia_wrapper_if_possible(main_window, logger)
        descendants = tuple(main_window.descendants())  # type: ignore[attr-defined]
    except Exception as exc:
        raise DisplayGroupInspectionError(f"Universal Viewer UIA tree를 읽지 못했습니다: {exc}") from exc

    time_axis_menu = find_first_visible_enabled_wrapper(descendants, is_time_axis_menu_text)
    if time_axis_menu is None:
        names = tuple(filter(None, (read_wrapper_name(wrapper) for wrapper in descendants)))
        raise DisplayGroupInspectionError(f"시간축 UIA control을 찾지 못했습니다. UIA 이름 후보={names[:30]}")

    logger.info("Time Axis semantic open | name=%s", read_wrapper_name(time_axis_menu))
    invoke_or_click_uia_wrapper(time_axis_menu, logger, "시간축")
    wait_fn(UNIVERSAL_VIEWER_TIME_AXIS_MENU_WAIT_SECONDS)

    full_display = find_visible_desktop_menu_item(
        desktop,
        opened.main_window.pid,
        is_time_axis_full_display_text,
        main_window_rect,
    )
    if full_display is None:
        menu_names = collect_visible_menu_related_names(desktop, owner_pid=opened.main_window.pid, owner_rect=main_window_rect)
        raise DisplayGroupInspectionError(f"전부 표시 UIA MenuItem을 찾지 못했습니다. UIA 메뉴 후보={menu_names[:50]}")

    logger.info("Time Axis Full Display semantic action | name=%s", read_wrapper_name(full_display))
    invoke_or_click_uia_wrapper(full_display, logger, "전부 표시")
    wait_fn(UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_WAIT_SECONDS)
    return calculate_time_axis_full_display_points(main_window_rect)


def preview_time_axis_full_display_points(
    opened: ViewerOpenResult,
    logger: logging.Logger,
    *,
    snapshot_fn: Callable[[int], Win32WindowSnapshot | None] | None = None,
) -> TimeAxisFullDisplayResult | None:
    """preview 모드에서 시간축 > 전부 표시 후보 좌표를 읽기 전용으로 계산한다."""
    try:
        main_rect = get_universal_viewer_main_window_rect(opened.main_window, snapshot_fn=snapshot_fn)
        result = calculate_time_axis_full_display_points(main_rect)
        logger.info(
            "time-axis full display preview | main_window_rect=%s | time_axis_menu_abs=%s rel=%s | "
            "time_axis_full_display_abs=%s rel=%s",
            result.main_window_rect,
            result.time_axis_menu_point,
            UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL,
            result.time_axis_full_display_point,
            UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL,
        )
        return result
    except Exception as exc:
        logger.warning("time-axis full display preview 좌표 계산 실패: %s", exc)
        return None


def apply_time_axis_full_display_by_coordinates(
    opened: ViewerOpenResult,
    logger: logging.Logger,
    *,
    click_fn: GeometryClickFunction | None = None,
    move_fn: GeometryMoveFunction | None = None,
    wait_fn: GeometryWaitFunction = time.sleep,
    snapshot_fn: Callable[[int], Win32WindowSnapshot | None] | None = None,
    desktop_factory: UiaDesktopFactory | None = None,
) -> TimeAxisFullDisplayResult:
    """UIA 의미 기반으로 시간축 > 전부 표시를 적용하고, 실패할 때만 fresh rect 좌표 fallback을 사용한다."""
    click_action = click_fn or click_geometry_point
    move_action = move_fn or move_geometry_pointer
    logger.warning("BEFORE time-axis full display")
    main_rect = get_universal_viewer_main_window_rect(opened.main_window, snapshot_fn=snapshot_fn)

    try:
        result = apply_time_axis_full_display_by_uia(
            opened,
            logger,
            main_window_rect=main_rect,
            desktop_factory=desktop_factory,
            wait_fn=wait_fn,
        )
        logger.warning("AFTER time-axis full display semantic action")
        return result
    except DisplayGroupInspectionError as exc:
        logger.warning(
            "Time Axis semantic action failed; falling back to coordinate click with fresh current rect: %s",
            exc,
        )

    focus_win32_window_if_possible(opened.main_window.handle, logger)
    main_rect = get_universal_viewer_main_window_rect(opened.main_window, snapshot_fn=snapshot_fn)
    result = calculate_time_axis_full_display_points(main_rect)
    logger.warning("Universal Viewer main window rectangle: %s", result.main_window_rect)
    logger.warning(
        "time_axis_menu_abs=%s | rel=%s",
        result.time_axis_menu_point,
        UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL,
    )
    move_action(result.time_axis_menu_point)
    click_action(result.time_axis_menu_point)
    wait_fn(UNIVERSAL_VIEWER_TIME_AXIS_MENU_WAIT_SECONDS)
    logger.warning("AFTER time_axis_menu click")
    logger.warning(
        "time_axis_full_display_abs=%s | rel=%s",
        result.time_axis_full_display_point,
        UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL,
    )
    move_action(result.time_axis_full_display_point)
    click_action(result.time_axis_full_display_point)
    wait_fn(UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_WAIT_SECONDS)
    logger.warning("AFTER time_axis_full_display click")
    return result


def center_of_relative_area(
    dialog_rect: tuple[int, int, int, int],
    relative_area: tuple[float, float, float, float],
) -> tuple[int, int]:
    """상대 영역의 중심점을 절대 좌표로 변환한다."""
    left, top, right, bottom = relative_area
    return point_from_relative(dialog_rect, (left + right) / 2, (top + bottom) / 2)


def checkbox_coordinate_for_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    row_no: int,
) -> tuple[int, int]:
    """row 번호의 checkbox column 좌표 후보를 반환한다."""
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        profile.checkbox_column_x_ratio,
        row_y_coordinate(dialog_rect, profile, row_no),
    )


def channel_coordinate_for_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    row_no: int,
) -> tuple[int, int]:
    """row 번호의 channel label/cell 좌표 후보를 반환한다."""
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        profile.channel_column_x_ratio,
        row_y_coordinate(dialog_rect, profile, row_no),
    )


def drag_start_coordinate_for_absolute_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    absolute_row_no: int,
) -> tuple[int, int]:
    """W11/W21/W31 같은 삽입 대상 row의 drag 시작 좌표 후보를 반환한다."""
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        profile.drag_select_start_x_ratio,
        row_y_coordinate(dialog_rect, profile, absolute_row_no),
    )


def drag_end_coordinate_for_absolute_row(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    absolute_row_no: int,
) -> tuple[int, int]:
    """삽입 대상 row 범위의 drag 끝 좌표 후보를 반환한다."""
    return point_from_relative_x_and_absolute_y(
        dialog_rect,
        profile.drag_select_end_x_ratio,
        row_y_coordinate(dialog_rect, profile, absolute_row_no),
    )


def row_y_ratio(profile: DisplayGroupGeometryProfile, row_no: int) -> float:
    """row 번호를 대화상자 상대 y 좌표로 변환한다."""
    return profile.first_row_y_ratio + ((row_no - 1) * profile.row_height_ratio)


def row_y_coordinate(
    dialog_rect: tuple[int, int, int, int],
    profile: DisplayGroupGeometryProfile,
    row_no: int,
) -> int:
    """row 번호를 절대 y 좌표로 변환한다.

    Stage 5B preview에서는 W11/W21/W31처럼 아래쪽 행 후보도 계산해야 한다.
    상대 ratio를 row마다 누적하면 24.7px 같은 소수 pitch가 누적되어 실제 관찰된
    약 25px 행 간격과 아래쪽에서 몇 픽셀씩 어긋날 수 있다. 따라서 dialog 크기에서
    첫 행 y와 row pitch를 각각 한 번 반올림한 뒤, 픽셀 pitch를 누적한다.
    """
    left, top, right, bottom = dialog_rect
    height = bottom - top
    first_row_y = round(top + height * profile.first_row_y_ratio)
    row_height = round(height * profile.row_height_ratio)
    return first_row_y + ((row_no - 1) * row_height)


def point_from_relative_x_and_absolute_y(
    dialog_rect: tuple[int, int, int, int],
    x_ratio: float,
    absolute_y: int,
) -> tuple[int, int]:
    """x는 대화상자 상대 ratio, y는 절대 row 좌표로 조합한다."""
    left, top, right, bottom = dialog_rect
    return (round(left + (right - left) * x_ratio), absolute_y)


def build_display_group_action_preview_report_lines(
    *,
    opened: ViewerOpenResult,
    menu_path: str,
    dialog: Win32WindowSnapshot,
    geometry: DisplayGroupGeometryReport,
    preview: DisplayGroupGeometryActionPreview,
    before_raw_file_hints: tuple[str, ...],
    after_raw_file_hints: tuple[str, ...],
    state_unchanged: bool,
    close_method: str,
    time_axis_preview: TimeAxisFullDisplayResult | None = None,
) -> list[str]:
    """geometry action preview 보고서 문자열을 구성한다."""
    lines = [
        "[표시 그룹 geometry action preview]",
        f"작업본: {opened.work_copy_path}",
        f"Heating Point count: {preview.heating_point_count}",
        f"메뉴 경로: {menu_path}",
        f"조사 전 Raw Data 힌트: {', '.join(before_raw_file_hints) or '(없음)'}",
        "",
        "[dialog]",
        f"dialog rectangle: {geometry.dialog_rect}",
        f"dialog width/height: {geometry.width} x {geometry.height}",
        format_win32_snapshot(dialog),
        "",
        "[row coordinate calibration]",
        *format_row_coordinate_calibration(geometry),
        "",
        "[group/page tab coordinates]",
    ]
    time_axis_lines = ["[time-axis full display preview]"]
    if time_axis_preview is None:
        time_axis_lines.append("- time-axis coordinates could not be calculated in preview; no click was performed")
    else:
        time_axis_lines.extend(
            [
                f"- main_window_rect: {time_axis_preview.main_window_rect}",
                (
                    f"- time_axis_menu_candidate: {time_axis_preview.time_axis_menu_point} "
                    f"rel={UNIVERSAL_VIEWER_TIME_AXIS_MENU_REL}"
                ),
                (
                    f"- time_axis_full_display_candidate: {time_axis_preview.time_axis_full_display_point} "
                    f"rel={UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_REL}"
                ),
                "- opening Display Group Settings after time-axis full display",
            ]
        )
    if "[dialog]" in lines:
        dialog_index = lines.index("[dialog]")
        lines[dialog_index:dialog_index] = time_axis_lines + [""]

    for group_no, point in preview.tab_coordinates:
        lines.append(f"- group/page {group_no:02d}: tab coordinate={point}")
    lines.extend(["", "[bottom button coordinate calibration]"])
    lines.extend(format_bottom_button_coordinate_calibration(geometry))
    lines.extend(["", "[scrolled destination coordinate calibration]"])
    lines.extend(format_scrolled_destination_coordinate_calibration(geometry))
    lines.extend(["", "[heating point row mapping]"])
    row_actions = {
        action.heating_points[0]: action
        for action in preview.actions
        if action.action_type == "row_candidate" and action.heating_points
    }
    for position in preview.positions:
        row_action = row_actions[position.heating_point_index]
        lines.append(
            f"- HP{position.heating_point_index:02d}: group/page={position.group_no:02d}, row={position.row_no:02d}, "
            f"target checkbox coordinate={row_action.point}, target channel row coordinate={row_action.drag_start}"
        )
    if preview.warnings:
        lines.extend(["", "[warnings]"])
        lines.extend(f"- {warning}" for warning in preview.warnings)
    lines.extend(["", "[planned actions - no click will be performed]"])
    lines.extend(format_planned_geometry_action(action) for action in preview.actions)
    lines.extend(
        [
            "",
            "[안전 확인]",
            "이 preview는 tab/row/checkbox/copy/paste/OK/Apply/Save를 클릭하지 않습니다.",
            "인쇄 및 PDF 생성도 수행하지 않습니다.",
            f"닫기 방식: {close_method}",
            f"조사 후 Raw Data 힌트: {', '.join(after_raw_file_hints) or '(닫기 전 또는 미확인)'}",
            f"열린 파일 힌트 변경 없음: {str(state_unchanged).lower()}",
        ]
    )
    return lines


def format_row_coordinate_calibration(geometry: DisplayGroupGeometryReport) -> list[str]:
    """preview row 좌표 계산 기준을 사람이 확인하기 쉽게 표시한다."""
    geometry_lines = {line.name: line for line in geometry.lines}
    first_row = geometry_lines["estimated_first_row_y"].absolute_value
    row_height = geometry_lines["estimated_row_height"].absolute_value
    return [
        f"row y formula: Wnn y = W01 y + ((nn - 1) * row height)",
        f"W01 y={first_row}",
        f"W10 y={first_row + (row_height * 9)}",
        f"W20 y={first_row + (row_height * 19)}",
        f"W30 y={first_row + (row_height * 29)}",
        f"row height={row_height}px",
    ]


def format_bottom_button_coordinate_calibration(geometry: DisplayGroupGeometryReport) -> list[str]:
    """preview bottom button 좌표 계산 기준을 사람이 확인하기 쉽게 표시한다."""
    areas = {area.name: area for area in geometry.areas}
    button_specs = (
        ("OK coordinate", "estimated_OK_button_area"),
        ("Cancel coordinate", "estimated_Cancel_button_area"),
        ("Scale calculation coordinate", "estimated_scale_calculation_button_area"),
        ("Copy detail coordinate", "estimated_copy_detail_button_area"),
        ("Paste coordinate", "estimated_paste_button_area"),
    )
    lines = [
        f"- {label}: {center_of_relative_area(geometry.dialog_rect, areas[area_name].relative_rect)}"
        for label, area_name in button_specs
    ]
    ok_area = areas["estimated_OK_button_area"].relative_rect
    bottom_button_y_ratio = (ok_area[1] + ok_area[3]) / 2
    lines.append(f"- bottom button y ratio: {bottom_button_y_ratio:.3f}")
    return lines


def format_scrolled_destination_coordinate_calibration(geometry: DisplayGroupGeometryReport) -> list[str]:
    """스크롤 후 destination 좌표 보정 기준점을 preview/report에 표시한다."""
    rect = geometry.dialog_rect
    return [
        f"- scrollbar_down_click_rel: {DISPLAY_GROUP_SCROLLBAR_DOWN_CLICK_REL}",
        f"- scrollbar_down_click_abs: {scrollbar_down_click_coordinate(rect)}",
        f"- scrollbar_up_click_rel: {DISPLAY_GROUP_SCROLLBAR_UP_CLICK_REL}",
        f"- scrollbar_up_click_abs: {scrollbar_up_click_coordinate(rect)}",
        f"- dest_w31_drag_start_rel: {DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL}",
        f"- dest_w31_drag_start_abs: {point_from_relative(rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W31_START_REL)}",
        f"- dest_w40_reference_rel: {DISPLAY_GROUP_SCROLLED_DESTINATION_W40_REFERENCE_REL}",
        f"- dest_w40_reference_abs: {point_from_relative(rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W40_REFERENCE_REL)}",
        f"- dest_w41_drag_start_rel: {DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL}",
        f"- dest_w41_drag_start_abs: {point_from_relative(rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W41_START_REL)}",
        f"- dest_w50_reference_rel: {DISPLAY_GROUP_SCROLLED_DESTINATION_W50_REFERENCE_REL}",
        f"- dest_w50_reference_abs: {point_from_relative(rect, *DISPLAY_GROUP_SCROLLED_DESTINATION_W50_REFERENCE_REL)}",
        f"- ok_button_rel: {DISPLAY_GROUP_OK_BUTTON_REL}",
        f"- ok_button_abs: {center_of_relative_area(rect, DEFAULT_DISPLAY_GROUP_GEOMETRY_PROFILE.ok_button_area)}",
    ]


def format_planned_geometry_action(action: PlannedGeometryAction) -> str:
    """예정 geometry action을 사람이 읽기 쉬운 한 줄로 만든다."""
    parts = [f"- step={action.step}", f"type={action.action_type}", f"description={action.description}"]
    if action.group_no is not None:
        parts.append(f"group/page={action.group_no:02d}")
    if action.row_no is not None:
        parts.append(f"row={action.row_no:02d}")
    if action.point is not None:
        parts.append(f"point={action.point}")
    if action.drag_start is not None or action.drag_end is not None:
        parts.append(f"drag_start={action.drag_start}")
        parts.append(f"drag_end={action.drag_end}")
    if action.heating_points:
        parts.append(f"heating_points={','.join(str(item) for item in action.heating_points)}")
    return " | ".join(parts)


def format_actual_click_test_step(step: ActualClickTestStep) -> str:
    """actual-click test step을 사람이 읽기 쉬운 한 줄로 만든다."""
    parts = [f"- step={step.step}", f"type={step.action_type}", f"description={step.description}"]
    if step.point is not None:
        parts.append(f"point={step.point}")
    if step.drag_start is not None or step.drag_end is not None:
        parts.append(f"drag_start={step.drag_start}")
        parts.append(f"drag_end={step.drag_end}")
    if step.scroll_amount is not None:
        parts.append(f"scroll_amount={step.scroll_amount}")
    if step.move_before_click:
        parts.append("move_before_click=true")
    if step.wait_after_seconds:
        parts.append(f"wait_after={step.wait_after_seconds:.1f}s")
    return " | ".join(parts)


def format_executed_geometry_action(action: ExecutedGeometryAction) -> str:
    """실제 수행된 geometry action을 사람이 읽기 쉬운 한 줄로 만든다."""
    parts = [f"type={action.action_type}", f"description={action.description}"]
    if action.point is not None:
        parts.append(f"point={action.point}")
    if action.drag_start is not None or action.drag_end is not None:
        parts.append(f"drag_start={action.drag_start}")
        parts.append(f"drag_end={action.drag_end}")
    return " | ".join(parts)


def build_display_group_inspection_report(result: DisplayGroupInspectionResult) -> list[str]:
    """표시 그룹 설정창 조사 보고서 문자열을 구성한다."""
    dialog = result.dialog.top_level
    lines = [
        "[Stage 5A 표시 그룹 설정창 조사]",
        f"작업본: {result.opened.work_copy_path}",
        f"메뉴 경로: {result.menu_path}",
        f"조사 전 Raw Data 힌트: {', '.join(result.before_raw_file_hints) or '(없음)'}",
        "",
        "[감지된 표시 그룹 설정창]",
        format_win32_snapshot(dialog),
        "",
        "[win32 child controls]",
    ]
    if result.dialog.win32_children:
        lines.extend(f"- {format_win32_snapshot(child)}" for child in result.dialog.win32_children)
    else:
        lines.append("- child control 없음 또는 읽기 실패")

    lines.extend(["", "[UIA collection attempts]"])
    if result.dialog.uia_attempt_logs:
        lines.extend(f"- {attempt}" for attempt in result.dialog.uia_attempt_logs)
    else:
        lines.append("- UIA 수집 시도 로그 없음")

    lines.extend(["", "[UIA elements]"])
    if result.dialog.uia_elements:
        lines.extend(f"- {format_uia_snapshot(element)}" for element in result.dialog.uia_elements)
    else:
        lines.append("- UIA 요소 없음 또는 읽기 실패")

    lines.extend(["", "[우선 식별 항목]"])
    lines.extend(format_priority_findings(result.dialog))
    lines.extend(["", "[geometry focused report]"])
    lines.extend(format_geometry_report(result.dialog))
    lines.extend(
        [
            "",
            "[닫기 및 상태 확인]",
            f"닫기 방식: {result.close_method}",
            f"조사 후 Raw Data 힌트: {', '.join(result.after_raw_file_hints) or '(없음)'}",
            f"열린 파일 힌트 변경 없음: {str(result.state_unchanged).lower()}",
            "설정 변경 없이 표시 그룹 설정창 닫기 완료",
        ]
    )
    return lines


def format_priority_findings(dialog: DisplayGroupDialogSnapshot) -> list[str]:
    """탭, 목록/표/트리, 체크박스, 채널 라벨, 버튼 후보를 요약한다."""
    lines: list[str] = []
    win32_texts = tuple(child.title for child in dialog.win32_children if child.title)
    uia_texts = tuple(element.name for element in dialog.uia_elements if element.name)
    all_texts = (*win32_texts, *uia_texts)
    tab_names = tuple(element.name for element in dialog.uia_elements if "tab" in element.control_type.casefold() and element.name)
    list_like = tuple(
        element
        for element in dialog.uia_elements
        if any(marker in element.control_type.casefold() for marker in ("list", "table", "tree", "data grid"))
    )
    checkbox_like = tuple(
        element
        for element in dialog.uia_elements
        if "check" in element.control_type.casefold() or "checkbox" in element.class_name.casefold()
    )
    channel_labels = tuple(dict.fromkeys(match.group(0) for text in all_texts for match in CHANNEL_LABEL_PATTERN.finditer(text)))
    button_titles = tuple(
        child.title
        for child in dialog.win32_children
        if child.class_name.casefold() == "button" and child.title
    )
    button_titles += tuple(
        element.name
        for element in dialog.uia_elements
        if "button" in element.control_type.casefold() and element.name
    )
    lines.append(f"탭 이름: {', '.join(tab_names) if tab_names else '(미확인)'}")
    lines.append(f"목록/표/트리 후보 수: {len(list_like)}")
    lines.append(f"체크박스 후보 수: {len(checkbox_like)}")
    lines.append(f"채널 라벨 후보: {', '.join(channel_labels) if channel_labels else '(미확인)'}")
    lines.append(f"버튼 후보: {', '.join(dict.fromkeys(button_titles)) if button_titles else '(미확인)'}")
    return lines


def capture_top_level_windows(owner_pid: int | None = None) -> tuple[Win32WindowSnapshot, ...]:
    """win32gui로 top-level 창을 읽는다."""
    snapshots: list[Win32WindowSnapshot] = []
    for hwnd in enum_top_level_hwnds():
        snapshot = read_win32_window_snapshot(hwnd)
        if snapshot is None:
            continue
        if owner_pid is not None and snapshot.pid != owner_pid:
            continue
        snapshots.append(snapshot)
    return tuple(snapshots)


def enum_top_level_hwnds() -> tuple[int, ...]:
    """top-level HWND 목록을 반환한다."""
    try:
        import win32gui
    except ImportError:
        return ()
    hwnds: list[int] = []

    def _callback(hwnd: int, _param: object) -> bool:
        hwnds.append(hwnd)
        return True

    win32gui.EnumWindows(_callback, None)
    return tuple(hwnds)


def enum_child_hwnds(parent_hwnd: int) -> tuple[int, ...]:
    """하위 호환용 descendant HWND 목록을 반환한다."""
    return tuple(hwnd for hwnd, _depth in enum_descendant_hwnds_with_depth(parent_hwnd))


def enum_descendant_hwnds_with_depth(
    parent_hwnd: int,
    *,
    direct_children_fn: Callable[[int], Iterable[int]] | None = None,
) -> tuple[tuple[int, int], ...]:
    """모든 descendant HWND를 재귀적으로 열거하고 depth를 함께 반환한다."""
    result: list[tuple[int, int]] = []
    get_children = direct_children_fn or enum_direct_child_hwnds

    def _visit(current_hwnd: int, depth: int) -> None:
        for child_hwnd in get_children(current_hwnd):
            result.append((child_hwnd, depth))
            _visit(child_hwnd, depth + 1)

    _visit(parent_hwnd, 1)
    return tuple(result)


def enum_direct_child_hwnds(parent_hwnd: int) -> tuple[int, ...]:
    """직계 child HWND만 반환한다."""
    try:
        import win32con
        import win32gui
    except ImportError:
        return ()
    hwnds: list[int] = []
    try:
        child = win32gui.GetWindow(parent_hwnd, win32con.GW_CHILD)
        while child:
            hwnds.append(int(child))
            child = win32gui.GetWindow(child, win32con.GW_HWNDNEXT)
    except Exception:
        return ()
    return tuple(hwnds)


def read_win32_window_snapshot(hwnd: int) -> Win32WindowSnapshot | None:
    """HWND에서 읽을 수 있는 win32 정보를 수집한다."""
    try:
        import win32gui
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            rectangle = f"({left}, {top}, {right}, {bottom})"
        except Exception:
            rectangle = ""
        try:
            control_id = int(win32gui.GetDlgCtrlID(hwnd))
        except Exception:
            control_id = None
        return Win32WindowSnapshot(
            hwnd=hwnd,
            title=str(win32gui.GetWindowText(hwnd)).strip(),
            class_name=str(win32gui.GetClassName(hwnd)).strip(),
            pid=int(pid) if pid is not None else None,
            visible=bool(win32gui.IsWindowVisible(hwnd)),
            enabled=bool(win32gui.IsWindowEnabled(hwnd)),
            rectangle=rectangle,
            control_id=control_id,
        )
    except Exception:
        return None


def collect_uia_elements(dialog_hwnd: int) -> tuple[UiaElementSnapshot, ...]:
    """대화상자 UIA 요소를 읽는다."""
    return collect_uia_elements_with_attempt_logs(dialog_hwnd).elements


def collect_uia_elements_with_attempt_logs(
    dialog_hwnd: int,
    dialog_rectangle: str = "",
    *,
    desktop_factory: Callable[[str], object] | None = None,
    application_factory: Callable[[str], object] | None = None,
) -> UiaCollectionResult:
    """여러 UIA 연결 방법을 시도하고 성공/실패 로그와 요소를 반환한다."""
    elements: list[UiaElementSnapshot] = []
    attempt_logs: list[str] = []
    desktop_maker, application_maker = resolve_uia_factories(desktop_factory, application_factory)

    try:
        desktop = desktop_maker("uia")
        root = desktop.window(handle=dialog_hwnd)  # type: ignore[attr-defined]
        wrappers = (root, *safe_descendants(root))
        collected = tuple(to_uia_snapshot(wrapper, "Desktop.window(handle).descendants") for wrapper in wrappers)
        elements.extend(collected)
        attempt_logs.append(f"Desktop(backend='uia').window(handle).descendants: success count={len(collected)}")
    except Exception as exc:
        attempt_logs.append(f"Desktop(backend='uia').window(handle).descendants: failed error={exc}")

    try:
        application = application_maker("uia")
        connected = application.connect(handle=dialog_hwnd)  # type: ignore[attr-defined]
        root = connected.window(handle=dialog_hwnd)  # type: ignore[attr-defined]
        wrappers = (root, *safe_descendants(root))
        collected = tuple(to_uia_snapshot(wrapper, "Application.connect(handle).descendants") for wrapper in wrappers)
        elements.extend(collected)
        attempt_logs.append(f"Application(backend='uia').connect(handle).descendants: success count={len(collected)}")
    except Exception as exc:
        attempt_logs.append(f"Application(backend='uia').connect(handle).descendants: failed error={exc}")

    try:
        desktop = desktop_maker("uia")
        dialog_rect = parse_rectangle_text(dialog_rectangle)
        wrappers = tuple(
            wrapper
            for wrapper in safe_descendants(desktop)
            if dialog_rect is None or wrapper_center_is_inside(wrapper, dialog_rect)
        )
        collected = tuple(to_uia_snapshot(wrapper, "Desktop.descendants filtered by dialog rectangle") for wrapper in wrappers)
        elements.extend(collected)
        attempt_logs.append(
            "Desktop(backend='uia').descendants filtered by dialog rectangle: "
            f"success count={len(collected)}"
        )
    except Exception as exc:
        attempt_logs.append(f"Desktop(backend='uia').descendants filtered by dialog rectangle: failed error={exc}")

    return UiaCollectionResult(deduplicate_uia_elements(elements), tuple(attempt_logs))


def resolve_uia_factories(
    desktop_factory: Callable[[str], object] | None,
    application_factory: Callable[[str], object] | None,
) -> tuple[Callable[[str], object], Callable[[str], object]]:
    """UIA factory를 실제 pywinauto 또는 테스트용 주입 객체로 확정한다."""
    if desktop_factory is not None and application_factory is not None:
        return desktop_factory, application_factory
    try:
        from pywinauto import Application, Desktop
    except ImportError as exc:
        raise DisplayGroupInspectionError(f"pywinauto UIA backend를 사용할 수 없습니다: {exc}") from exc
    return desktop_factory or (lambda backend: Desktop(backend=backend)), application_factory or (
        lambda backend: Application(backend=backend)
    )


def to_uia_snapshot(wrapper: object, source: str) -> UiaElementSnapshot:
    """wrapper를 보고서용 UIA 정보로 변환한다."""
    info = getattr(wrapper, "element_info", None)
    return UiaElementSnapshot(
        name=read_wrapper_name(wrapper),
        control_type=safe_control_type(wrapper),
        automation_id=str(getattr(info, "automation_id", "") or ""),
        class_name=str(getattr(info, "class_name", "") or safe_class_name(wrapper)),
        enabled=safe_bool_call(wrapper, "is_enabled", None),
        rectangle=safe_rectangle_text(wrapper),
        source=source,
    )


def deduplicate_uia_elements(elements: Iterable[UiaElementSnapshot]) -> tuple[UiaElementSnapshot, ...]:
    """동일 UIA 요소를 중복 기록하지 않는다."""
    deduped: list[UiaElementSnapshot] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for element in elements:
        key = (element.name, element.control_type, element.automation_id, element.class_name, element.rectangle)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(element)
    return tuple(deduped)


def wrapper_center_is_inside(wrapper: object, rect: tuple[int, int, int, int]) -> bool:
    """wrapper rectangle 중심이 dialog rectangle 내부인지 확인한다."""
    wrapper_rect = parse_rectangle_text(safe_rectangle_text(wrapper))
    if wrapper_rect is None:
        return False
    center_x = (wrapper_rect[0] + wrapper_rect[2]) // 2
    center_y = (wrapper_rect[1] + wrapper_rect[3]) // 2
    return rect[0] <= center_x <= rect[2] and rect[1] <= center_y <= rect[3]


def format_geometry_report(dialog: DisplayGroupDialogSnapshot) -> list[str]:
    """대화상자와 descendant 위치 중심 보고서를 만든다."""
    lines: list[str] = [f"dialog rectangle: {dialog.top_level.rectangle or '확인 불가'}"]
    visible_children = tuple(child for child in dialog.win32_children if child.visible and child.rectangle)
    lines.append("all visible descendant rectangles:")
    if visible_children:
        lines.extend(f"- depth={child.depth} | HWND={child.hwnd} | class={child.class_name} | rectangle={child.rectangle} | title={child.title!r}" for child in visible_children)
    else:
        lines.append("- visible descendant rectangle 없음")

    lines.append("controls grouped by screen area:")
    grouped: dict[str, list[Win32WindowSnapshot]] = {}
    dialog_rect = parse_rectangle_text(dialog.top_level.rectangle)
    for child in visible_children:
        area = screen_area_label(dialog_rect, parse_rectangle_text(child.rectangle))
        grouped.setdefault(area, []).append(child)
    if grouped:
        for area in sorted(grouped):
            lines.append(f"- {area}")
            for child in grouped[area]:
                lines.append(f"  - HWND={child.hwnd} | class={child.class_name} | title={child.title!r} | rectangle={child.rectangle}")
    else:
        lines.append("- screen area grouping 대상 없음")

    lines.append("possible clickable candidates:")
    candidates = possible_clickable_candidates(dialog)
    if candidates:
        lines.extend(f"- {candidate}" for candidate in candidates)
    else:
        lines.append("- possible clickable candidate 없음")
    return lines


def possible_clickable_candidates(dialog: DisplayGroupDialogSnapshot) -> tuple[str, ...]:
    """이름이 비어 있어도 클릭 가능성이 있는 후보를 위치 정보 중심으로 기록한다."""
    lines: list[str] = []
    for child in dialog.win32_children:
        if not child.visible or not child.enabled or not child.rectangle:
            continue
        class_name = child.class_name.casefold()
        if any(marker in class_name for marker in ("button", "afx", "directui", "custom", "systabcontrol32", "syslistview32", "systreeview32")):
            lines.append(
                f"win32 depth={child.depth} | HWND={child.hwnd} | class={child.class_name} | "
                f"title={child.title!r} | rectangle={child.rectangle}"
            )
    for element in dialog.uia_elements:
        if element.enabled is False or not element.rectangle:
            continue
        combined = f"{element.control_type} {element.class_name}".casefold()
        if any(marker in combined for marker in ("button", "check", "list", "tree", "tab", "custom", "pane")):
            lines.append(
                f"uia source={element.source or '확인 불가'} | ControlType={element.control_type} | "
                f"Name={element.name!r} | ClassName={element.class_name} | BoundingRectangle={element.rectangle}"
            )
    return tuple(lines)


def screen_area_label(
    dialog_rect: tuple[int, int, int, int] | None,
    child_rect: tuple[int, int, int, int] | None,
) -> str:
    """child rectangle을 대화상자 기준 3x3 영역명으로 분류한다."""
    if dialog_rect is None or child_rect is None:
        return "unknown"
    left, top, right, bottom = dialog_rect
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    center_x = (child_rect[0] + child_rect[2]) / 2
    center_y = (child_rect[1] + child_rect[3]) / 2
    x_ratio = (center_x - left) / width
    y_ratio = (center_y - top) / height
    horizontal = "left" if x_ratio < 1 / 3 else "center" if x_ratio < 2 / 3 else "right"
    vertical = "top" if y_ratio < 1 / 3 else "middle" if y_ratio < 2 / 3 else "bottom"
    return f"{vertical}-{horizontal}"


def parse_rectangle_text(rectangle: str) -> tuple[int, int, int, int] | None:
    """'(left, top, right, bottom)' 문자열을 정수 튜플로 변환한다."""
    numbers = re.findall(r"-?\d+", rectangle)
    if len(numbers) < 4:
        return None
    left, top, right, bottom = (int(value) for value in numbers[:4])
    return (left, top, right, bottom)


def click_win32_button(hwnd: int) -> None:
    """win32 Button을 BM_CLICK으로 누른다."""
    try:
        import win32con
        import win32gui

        win32gui.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
    except Exception as exc:
        raise DisplayGroupInspectionError(f"표시 그룹 설정창 닫기 버튼 클릭 실패: HWND={hwnd} ({exc})") from exc


def close_open_menu_safely() -> None:
    """열린 메뉴 또는 대화상자를 Esc로 닫는다."""
    try:
        from pywinauto.keyboard import send_keys

        send_keys("{ESC}")
    except Exception:
        pass


def focus_win32_window_if_possible(hwnd: int | None, logger: logging.Logger) -> None:
    """좌표 fallback 또는 grid 조작 직전에 대상 win32 창을 foreground로 올린다."""
    if hwnd is None:
        return
    try:
        import win32gui

        win32gui.SetForegroundWindow(int(hwnd))
    except Exception as exc:
        logger.debug("win32 foreground 설정을 건너뜁니다: hwnd=%s (%s)", hwnd, exc)


def make_uia_desktop(desktop_factory: UiaDesktopFactory | None = None) -> object:
    """테스트 주입 또는 pywinauto Desktop(backend='uia') 객체를 만든다."""
    if desktop_factory is not None:
        return desktop_factory("uia")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise DisplayGroupInspectionError("pywinauto가 설치되어 있지 않아 UIA semantic action을 사용할 수 없습니다.") from exc
    return Desktop(backend="uia")


def focus_uia_wrapper_if_possible(wrapper: object, logger: logging.Logger) -> None:
    """UIA wrapper를 foreground로 올리되, 실패해도 semantic 탐색 자체는 계속한다."""
    try:
        wrapper.set_focus()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("UIA wrapper focus를 건너뜁니다: %s", exc)


def invoke_or_click_uia_wrapper(wrapper: object, logger: logging.Logger, label: str) -> None:
    """UIA invoke를 우선 사용하고, 지원되지 않으면 click_input으로 실행한다."""
    invoke_error: Exception | None = None
    try:
        wrapper.invoke()  # type: ignore[attr-defined]
        logger.info("%s UIA invoke completed", label)
        return
    except Exception as exc:
        invoke_error = exc
        logger.debug("%s UIA invoke 실패, click_input fallback 시도: %s", label, exc)

    try:
        wrapper.click_input()  # type: ignore[attr-defined]
        logger.info("%s UIA click_input completed", label)
        return
    except Exception as exc:
        raise DisplayGroupInspectionError(f"{label} UIA action 실패: invoke={invoke_error}, click_input={exc}") from exc


def find_first_visible_enabled_wrapper_by(
    wrappers: Iterable[object],
    predicate: Callable[[object], bool],
) -> object | None:
    """wrapper 전체 정보를 기준으로 visible/enabled 후보 하나를 찾는다."""
    for wrapper in wrappers:
        if safe_bool_call(wrapper, "is_visible", True) is False:
            continue
        if safe_bool_call(wrapper, "is_enabled", True) is False:
            continue
        if predicate(wrapper):
            return wrapper
    return None


def find_first_visible_enabled_wrapper(wrappers: Iterable[object], text_predicate: Callable[[str], bool]) -> object | None:
    """조건에 맞는 visible/enabled wrapper 하나를 반환한다."""
    for wrapper in wrappers:
        text = read_wrapper_name(wrapper)
        if not text or not text_predicate(text):
            continue
        if safe_bool_call(wrapper, "is_visible", True) is False:
            continue
        if safe_bool_call(wrapper, "is_enabled", True) is False:
            continue
        return wrapper
    return None


def is_time_axis_menu_text(text: str) -> bool:
    """시간축 상위 메뉴 텍스트인지 확인한다."""
    normalized = normalize_menu_text(text)
    return normalize_menu_text(UNIVERSAL_VIEWER_TIME_AXIS_MENU_TEXT) in normalized or "timeaxis" in normalized


def is_time_axis_full_display_text(text: str) -> bool:
    """시간축 > 전부 표시 메뉴 텍스트인지 확인한다."""
    normalized = normalize_menu_text(text)
    return any(normalize_menu_text(candidate) in normalized for candidate in UNIVERSAL_VIEWER_TIME_AXIS_FULL_DISPLAY_TEXTS) or (
        "full" in normalized and "display" in normalized
    )


def is_group_setting_toolbar_button(wrapper: object) -> bool:
    """Universal Viewer toolbar의 Group Setting 버튼인지 확인한다."""
    name = normalize_button_text(read_wrapper_name(wrapper))
    expected = normalize_button_text(UNIVERSAL_VIEWER_GROUP_SETTING_BUTTON_TEXT)
    if name != expected:
        return False
    control_type = safe_control_type(wrapper).casefold()
    return not control_type or "button" in control_type


def is_display_top_menu_text(text: str) -> bool:
    """표시/View 상위 메뉴 텍스트인지 확인한다."""
    normalized = normalize_menu_text(text)
    if is_display_group_menu_text(text):
        return False
    return normalized in {"표시", "표시v", "view", "viewv"}


def is_display_group_menu_text(text: str) -> bool:
    """표시 그룹 설정 메뉴 텍스트인지 확인한다."""
    normalized = normalize_menu_text(text)
    return any(normalize_menu_text(candidate) in normalized for candidate in DISPLAY_GROUP_MENU_CANDIDATES)


def normalize_menu_text(text: str) -> str:
    """메뉴 비교용 텍스트를 정규화한다."""
    return (
        text.replace("&", "")
        .replace("...", "")
        .replace("…", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
        .strip()
        .casefold()
    )


def button_text_matches(text: str, candidate: str) -> bool:
    """버튼 텍스트가 후보와 일치하는지 확인한다."""
    normalized = normalize_button_text(text)
    expected = normalize_button_text(candidate)
    return normalized == expected or normalized.startswith(expected)


def normalize_button_text(text: str) -> str:
    """버튼 비교용 텍스트를 정규화한다."""
    return text.replace("&", "").replace("(", "").replace(")", "").strip().casefold()


def safe_descendants(wrapper: object) -> tuple[object, ...]:
    try:
        return tuple(wrapper.descendants())  # type: ignore[attr-defined]
    except Exception:
        return ()


def read_wrapper_name(wrapper: object) -> str:
    """pywinauto wrapper에서 표시 이름을 안전하게 읽는다."""
    for value in (
        safe_call(wrapper, "window_text", ""),
        getattr(getattr(wrapper, "element_info", None), "name", ""),
    ):
        if value:
            return str(value).strip()
    return ""


def safe_class_name(wrapper: object) -> str:
    return str(safe_call(wrapper, "class_name", "") or getattr(getattr(wrapper, "element_info", None), "class_name", "") or "")


def safe_control_type(wrapper: object) -> str:
    return str(
        safe_call(wrapper, "friendly_class_name", "")
        or getattr(getattr(wrapper, "element_info", None), "control_type", "")
        or ""
    )


def safe_process_id(wrapper: object) -> int | None:
    for value in (
        safe_call(wrapper, "process_id", None),
        getattr(getattr(wrapper, "element_info", None), "process_id", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def safe_bool_call(wrapper: object, method_name: str, default: bool | None) -> bool | None:
    value = safe_call(wrapper, method_name, default)
    if value is None:
        return None
    return bool(value)


def safe_call(wrapper: object, method_name: str, default: object) -> object:
    try:
        method = getattr(wrapper, method_name)
        return method()
    except Exception:
        return default


def safe_rectangle_text(wrapper: object) -> str:
    rectangle = safe_call(wrapper, "rectangle", None)
    if rectangle is None:
        rectangle = getattr(getattr(wrapper, "element_info", None), "rectangle", None)
    if rectangle is None:
        return ""
    try:
        left = getattr(rectangle, "left")
        top = getattr(rectangle, "top")
        right = getattr(rectangle, "right")
        bottom = getattr(rectangle, "bottom")
        return f"({left}, {top}, {right}, {bottom})"
    except Exception:
        return str(rectangle)


def format_win32_snapshot(snapshot: Win32WindowSnapshot) -> str:
    """win32 창 정보를 한 줄로 만든다."""
    return (
        f"depth={snapshot.depth} | HWND={snapshot.hwnd} | title={snapshot.title!r} | "
        f"class={snapshot.class_name!r} | highlight={highlight_win32_class(snapshot.class_name)} | "
        f"PID={snapshot.pid if snapshot.pid is not None else '확인 불가'} | "
        f"control_id={snapshot.control_id if snapshot.control_id is not None else '확인 불가'} | "
        f"visible={str(snapshot.visible).lower()} | enabled={str(snapshot.enabled).lower()} | "
        f"rectangle={snapshot.rectangle or '확인 불가'}"
    )


def format_uia_snapshot(snapshot: UiaElementSnapshot) -> str:
    """UIA 요소 정보를 한 줄로 만든다."""
    return (
        f"source={snapshot.source or '확인 불가'} | ControlType={snapshot.control_type or '확인 불가'} | "
        f"Name={snapshot.name!r} | "
        f"AutomationId={snapshot.automation_id or '확인 불가'} | ClassName={snapshot.class_name or '확인 불가'} | "
        f"IsEnabled={snapshot.enabled if snapshot.enabled is not None else '확인 불가'} | "
        f"BoundingRectangle={snapshot.rectangle or '확인 불가'}"
    )


def highlight_win32_class(class_name: str) -> str:
    """보고서에서 우선 확인할 win32 class를 표시한다."""
    normalized = class_name.casefold()
    exact_classes = {
        "button": "Button",
        "static": "Static",
        "systabcontrol32": "SysTabControl32",
        "syslistview32": "SysListView32",
        "systreeview32": "SysTreeView32",
        "combobox": "ComboBox",
        "edit": "Edit",
        "custom": "Custom",
    }
    if normalized in exact_classes:
        return exact_classes[normalized]
    if normalized.startswith("afx"):
        return "Afx*"
    if normalized.startswith("directui"):
        return "DirectUI*"
    return "-"


def format_dialog_candidates(candidates: Iterable[Win32WindowSnapshot]) -> str:
    """대화상자 후보 목록을 진단 문자열로 만든다."""
    items = tuple(candidates)
    if not items:
        return "(없음)"
    return "; ".join(format_win32_snapshot(candidate) for candidate in items)
