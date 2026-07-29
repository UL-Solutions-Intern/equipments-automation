"""Universal Viewer 커서값 창에서 절대시간 차 값을 읽는 보조 기능."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable


CURSOR_VALUE_TITLE_KEYWORD = "커서값"
CURSOR_VALUE_WINDOW_CLICK_REL = (0.50, 0.50)
CURSOR_VALUE_COPY_WAIT_SECONDS = 0.5
UNIVERSAL_VIEWER_WINDOW_MENU_REL = (0.288, 0.079)
CURSOR_VALUE_WINDOW_MENU_REL = UNIVERSAL_VIEWER_WINDOW_MENU_REL
CURSOR_VALUE_DISPLAY_MENU_ITEM_REL = (0.387, 0.530)
CURSOR_VALUE_WINDOW_MENU_WAIT_SECONDS = 0.3
CURSOR_VALUE_DISPLAY_WAIT_SECONDS = 0.7
UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT = "Cursor Value ON/OFF"
UNIVERSAL_VIEWER_TITLE = "Universal Viewer"
UNIVERSAL_VIEWER_CLASS_PREFIX = "Universal_Viewer"
# Universal Viewer graph area does not scale linearly on all PCs, so the
# window is normalized to the calibrated size before coordinate-based automation.
UNIVERSAL_VIEWER_NORMALIZED_LEFT = -6
UNIVERSAL_VIEWER_NORMALIZED_TOP = 6
UNIVERSAL_VIEWER_NORMALIZED_WIDTH = 1152
UNIVERSAL_VIEWER_NORMALIZED_HEIGHT = 598
UNIVERSAL_VIEWER_NORMALIZED_RECT = (
    UNIVERSAL_VIEWER_NORMALIZED_LEFT,
    UNIVERSAL_VIEWER_NORMALIZED_TOP,
    UNIVERSAL_VIEWER_NORMALIZED_LEFT + UNIVERSAL_VIEWER_NORMALIZED_WIDTH,
    UNIVERSAL_VIEWER_NORMALIZED_TOP + UNIVERSAL_VIEWER_NORMALIZED_HEIGHT,
)
AB_CURSOR_A_START_REL = (0.265, 0.607)
AB_CURSOR_A_FIXED_Y_REL = 0.607
AB_CURSOR_A_MAX_X_REL = 0.573
AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL = AB_CURSOR_A_START_REL
AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL = (AB_CURSOR_A_MAX_X_REL, AB_CURSOR_A_FIXED_Y_REL)
AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL = (0.651, 0.607)
AB_CURSOR_A_CANDIDATE_REL = AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL
AB_CURSOR_B_RELEASE_REL = AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL
AB_CURSOR_MOVE_TO_A_DURATION_SECONDS = 0.2
AB_CURSOR_DRAG_DURATION_SECONDS = 0.5
AB_CURSOR_AFTER_DRAG_WAIT_SECONDS = 0.8
AB_CURSOR_ACCEPT_MIN_SECONDS = 1795
AB_CURSOR_ACCEPT_MAX_SECONDS = 1805
AB_CURSOR_TARGET_SECONDS = 1800
AB_CURSOR_MAX_ADJUST_ITERATIONS = 20
AB_CURSOR_MAX_ADJUST_ATTEMPTS = 30
AB_CURSOR_INITIAL_ADJUST_STEP = 0.050
AB_CURSOR_MIN_ADJUST_STEP = 0.001
AB_CURSOR_COARSE_PROGRESS_VALUES = (0.25, 0.50, 0.75, 1.00)
AB_CURSOR_PROFILE_SIZE_TOLERANCE_PX = 40
AB_CURSOR_PROFILE_C_768x399 = {
    "main_class": "Universal_Viewer R3.12.01",
    "main_size": (768, 399),
    "ab_a_start": (0.341146, 0.621554),
    "ab_a_max": (0.475260, 0.621554),
    "ab_b_release_target": (0.514323, 0.621554),
}
AB_CURSOR_COORDINATE_PROFILES = (AB_CURSOR_PROFILE_C_768x399,)
ABSOLUTE_DATETIME_RE = re.compile(
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?\b"
)
TIME_VALUE_RE = re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?\b")


class CursorValueError(RuntimeError):
    """커서값 창 탐지 또는 clipboard 파싱 실패 시 발생한다."""


@dataclass(frozen=True, slots=True)
class CursorValueWindow:
    """커서값 top-level window 정보."""

    hwnd: int
    title: str
    class_name: str
    pid: int | None
    rectangle: tuple[int, int, int, int]
    visible: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class CursorValueReadResult:
    """커서값 창 clipboard 읽기 결과."""

    window: CursorValueWindow
    click_point: tuple[int, int]
    clipboard_text: str
    absolute_time_difference: str

    @property
    def difference_seconds(self) -> float:
        """절대시간 차 값을 초 단위로 반환한다."""
        return duration_text_to_seconds(self.absolute_time_difference)


@dataclass(frozen=True, slots=True)
class ABCursorDragReadResult:
    """A/B cursor drag 후 커서값 창 clipboard 읽기 결과."""

    main_window: CursorValueWindow
    cursor_window: CursorValueWindow
    a_candidate_rel: tuple[float, float]
    a_candidate_abs: tuple[int, int]
    b_release_rel: tuple[float, float]
    b_release_abs: tuple[int, int]
    cursor_value_result: CursorValueReadResult
    a_search_right_limit_rel: tuple[float, float] = AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL
    a_search_right_limit_abs: tuple[int, int] = (0, 0)

    @property
    def a_search_left_limit_rel(self) -> tuple[float, float]:
        """A cursor search left limit 상대 좌표를 반환한다."""
        return self.a_candidate_rel

    @property
    def a_search_left_limit_abs(self) -> tuple[int, int]:
        """A cursor search left limit 절대 좌표를 반환한다."""
        return self.a_candidate_abs

    @property
    def b_release_overshoot_target_rel(self) -> tuple[float, float]:
        """B cursor release overshoot target 상대 좌표를 반환한다."""
        return self.b_release_rel

    @property
    def b_release_overshoot_target_abs(self) -> tuple[int, int]:
        """B cursor release overshoot target 절대 좌표를 반환한다."""
        return self.b_release_abs

    @property
    def absolute_time_difference(self) -> str:
        """커서값 창에서 읽은 절대시간 차 값을 반환한다."""
        return self.cursor_value_result.absolute_time_difference

    @property
    def difference_seconds(self) -> float:
        """커서값 창에서 읽은 절대시간 차 값을 초 단위로 반환한다."""
        return self.cursor_value_result.difference_seconds


@dataclass(frozen=True, slots=True)
class ABCursorAdjustmentAttempt:
    """A/B cursor 30분 조정 시도 1회의 기록."""

    attempt_number: int
    phase: str
    progress: float
    a_candidate_rel: tuple[float, float]
    a_candidate_abs: tuple[int, int]
    b_release_rel: tuple[float, float]
    b_release_abs: tuple[int, int]
    absolute_time_difference: str
    seconds: float
    decision: str


@dataclass(frozen=True, slots=True)
class ABCursorAdjustmentResult:
    """A/B cursor 30분 조정 결과."""

    success: bool
    attempts: tuple[ABCursorAdjustmentAttempt, ...]
    best_attempt: ABCursorAdjustmentAttempt | None
    reason: str
    accepted_min_seconds: int = AB_CURSOR_ACCEPT_MIN_SECONDS
    accepted_max_seconds: int = AB_CURSOR_ACCEPT_MAX_SECONDS

    @property
    def absolute_time_difference(self) -> str:
        """최종/최선 시도의 절대시간 차 값을 반환한다."""
        return self.best_attempt.absolute_time_difference if self.best_attempt else ""

    @property
    def difference_seconds(self) -> float:
        """최종/최선 시도의 초 값을 반환한다."""
        return self.best_attempt.seconds if self.best_attempt else 0

@dataclass(frozen=True, slots=True)
class ABCursorProfilePreviewResult:
    """A/B cursor profile preview 결과."""

    main_window: CursorValueWindow
    profile: dict[str, object]
    a_start_rel: tuple[float, float]
    a_start_abs: tuple[int, int]
    a_max_rel: tuple[float, float]
    a_max_abs: tuple[int, int]
    b_release_rel: tuple[float, float]
    b_release_abs: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CursorValueWindowMoveResult:
    """커서값 창을 안전 위치로 이동한 결과."""

    main_window: CursorValueWindow
    old_window: CursorValueWindow
    new_window: CursorValueWindow
    target_rectangle: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class UniversalViewerWindowNormalizeResult:
    """Universal Viewer main window normalization result."""

    hwnd: int
    before_rectangle: tuple[int, int, int, int]
    after_rectangle: tuple[int, int, int, int]
    target_rectangle: tuple[int, int, int, int]


ClickFunction = Callable[[tuple[int, int]], None]
MoveFunction = Callable[[tuple[int, int]], None]
MoveToFunction = Callable[[tuple[int, int], float], None]
MouseButtonFunction = Callable[[str], None]
HotkeyFunction = Callable[[str, str], None]
ClipboardReader = Callable[[], str]
WaitFunction = Callable[[float], None]
MousePositionFunction = Callable[[], tuple[int, int] | None]
MoveWindowFunction = Callable[[int, int, int, int, int], None]
ScreenRectFunction = Callable[[], tuple[int, int, int, int]]
FocusWindowFunction = Callable[[int], None]
RestoreWindowFunction = Callable[[int], None]
GetWindowRectangleFunction = Callable[[int], tuple[int, int, int, int]]
UiaDesktopFactory = Callable[[str], object]
AdjustmentReadFunction = Callable[
    [
        int,
        str,
        float,
        tuple[float, float],
        tuple[int, int],
        tuple[float, float],
        tuple[int, int],
    ],
    CursorValueReadResult,
]


def cursor_value_window_center(rectangle: tuple[int, int, int, int]) -> tuple[int, int]:
    """커서값 창의 현재 rectangle 기준 중앙 클릭 좌표를 계산한다."""
    left, top, right, bottom = rectangle
    return (
        round(left + (right - left) * CURSOR_VALUE_WINDOW_CLICK_REL[0]),
        round(top + (bottom - top) * CURSOR_VALUE_WINDOW_CLICK_REL[1]),
    )


def find_cursor_value_window(
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    title_keyword: str = CURSOR_VALUE_TITLE_KEYWORD,
) -> CursorValueWindow:
    """title에 '커서값'이 포함된 현재 커서값 창을 찾는다."""
    candidates = tuple(
        window
        for window in (window_enum_fn or enumerate_top_level_windows)()
        if window.visible and window.enabled and title_keyword in window.title
    )
    if not candidates:
        raise CursorValueError(f"title에 {title_keyword!r}이 포함된 커서값 창을 찾지 못했습니다.")
    return sorted(candidates, key=lambda item: item.title)[0]


def find_universal_viewer_main_window(
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
) -> CursorValueWindow:
    """현재 열린 Universal Viewer 메인 창을 찾는다."""
    candidates = tuple(
        window
        for window in (window_enum_fn or enumerate_top_level_windows)()
        if window.visible
        and window.enabled
        and window.title.casefold() == UNIVERSAL_VIEWER_TITLE.casefold()
        and window.class_name.casefold().startswith(UNIVERSAL_VIEWER_CLASS_PREFIX.casefold())
    )
    if not candidates:
        raise CursorValueError("Universal Viewer 메인 창을 찾지 못했습니다.")
    return sorted(candidates, key=lambda item: item.hwnd)[0]


def window_size(rectangle: tuple[int, int, int, int]) -> tuple[int, int]:
    """window rectangle에서 width/height를 반환한다."""
    left, top, right, bottom = rectangle
    return (right - left, bottom - top)


def is_window_size_close(
    actual_size: tuple[int, int],
    expected_size: tuple[int, int],
    *,
    tolerance: int,
) -> bool:
    return (
        abs(actual_size[0] - expected_size[0]) <= tolerance
        and abs(actual_size[1] - expected_size[1]) <= tolerance
    )


def select_ab_cursor_coordinate_profile(
    main_window: CursorValueWindow,
    *,
    profiles: tuple[dict[str, object], ...] = AB_CURSOR_COORDINATE_PROFILES,
    tolerance: int = AB_CURSOR_PROFILE_SIZE_TOLERANCE_PX,
) -> dict[str, object] | None:
    """COMPUTERNAME이 아니라 Universal Viewer class/size로 A/B cursor profile을 선택한다."""
    actual_size = window_size(main_window.rectangle)
    for profile in profiles:
        expected_class = str(profile["main_class"])
        expected_size = tuple(int(value) for value in profile["main_size"])  # type: ignore[arg-type]
        if not main_window.class_name.startswith(expected_class):
            continue
        if not is_window_size_close(actual_size, expected_size, tolerance=tolerance):
            continue
        return profile
    return None


def ab_cursor_profile_point(profile: dict[str, object], key: str) -> tuple[float, float]:
    value = profile[key]
    if not isinstance(value, tuple) or len(value) != 2:
        raise CursorValueError(f"A/B cursor profile coordinate가 올바르지 않습니다: key={key}, value={value!r}")
    return (float(value[0]), float(value[1]))


def active_ab_cursor_coordinates_for_window(
    main_window: CursorValueWindow,
) -> tuple[dict[str, object] | None, tuple[float, float], tuple[float, float], tuple[float, float]]:
    """현재 main window layout에 맞는 A start/A max/B release rel 좌표를 반환한다."""
    profile = select_ab_cursor_coordinate_profile(main_window)
    if profile is not None:
        a_start = ab_cursor_profile_point(profile, "ab_a_start")
        a_max = ab_cursor_profile_point(profile, "ab_a_max")
        b_release = ab_cursor_profile_point(profile, "ab_b_release_target")
        return profile, a_start, a_max, b_release
    return (
        None,
        AB_CURSOR_A_START_REL,
        (AB_CURSOR_A_MAX_X_REL, AB_CURSOR_A_FIXED_Y_REL),
        AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL,
    )


def enumerate_top_level_windows() -> tuple[CursorValueWindow, ...]:
    """win32gui로 top-level window를 읽는다."""
    try:
        import win32gui
        import win32process
    except Exception as exc:  # pragma: no cover - Windows 의존 경로
        raise CursorValueError(f"win32gui를 불러올 수 없어 커서값 창을 탐지할 수 없습니다: {exc}") from exc

    windows: list[CursorValueWindow] = []

    def enum_window(hwnd: int, _param: object) -> None:
        try:
            title = str(win32gui.GetWindowText(hwnd)).strip()
            class_name = str(win32gui.GetClassName(hwnd)).strip()
            visible = bool(win32gui.IsWindowVisible(hwnd))
            enabled = bool(win32gui.IsWindowEnabled(hwnd))
            rectangle = tuple(int(value) for value in win32gui.GetWindowRect(hwnd))
            _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        windows.append(
            CursorValueWindow(
                hwnd=int(hwnd),
                title=title,
                class_name=class_name,
                pid=int(pid) if pid is not None else None,
                rectangle=rectangle,  # type: ignore[arg-type]
                visible=visible,
                enabled=enabled,
            )
        )

    win32gui.EnumWindows(enum_window, None)
    return tuple(windows)


def move_cursor_value_window_below_graph_or_safe_area(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    move_window_fn: MoveWindowFunction | None = None,
    screen_rect_fn: ScreenRectFunction | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> CursorValueWindowMoveResult:
    """커서값 창을 Universal Viewer 하단 안전 영역으로 이동한다."""
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    windows_before = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: windows_before)
    cursor_window = find_cursor_value_window(window_enum_fn=lambda: windows_before)
    old_rect = cursor_window.rectangle
    main_left, main_top, main_right, main_bottom = main_window.rectangle
    cursor_left, cursor_top, cursor_right, cursor_bottom = old_rect
    cursor_width = cursor_right - cursor_left
    cursor_height = cursor_bottom - cursor_top
    if cursor_width <= 0 or cursor_height <= 0:
        raise CursorValueError(f"커서값 창 rectangle이 올바르지 않습니다: {old_rect}")

    target_x = main_left + 20
    target_y = main_bottom - cursor_height - 20
    menu_safe_y = main_top + 90
    target_y = max(target_y, menu_safe_y)
    screen_left, screen_top, screen_right, screen_bottom = (screen_rect_fn or get_virtual_screen_rect)()
    target_x = clamp_int(target_x, screen_left, max(screen_left, screen_right - cursor_width))
    target_y = clamp_int(target_y, screen_top, max(screen_top, screen_bottom - cursor_height))
    target_rect = (target_x, target_y, target_x + cursor_width, target_y + cursor_height)

    logger.info("cursor value window found | rect=%s", old_rect)
    logger.info("old cursor value window rectangle: %s", old_rect)
    logger.info("target safe rectangle: %s", target_rect)
    mover = move_window_fn or move_window
    mover(cursor_window.hwnd, target_x, target_y, cursor_width, cursor_height)
    wait_fn(0.3)

    windows_after = tuple(enumerate_windows())
    moved_window = find_cursor_value_window(window_enum_fn=lambda: windows_after)
    logger.info("moved cursor value window rectangle: %s", moved_window.rectangle)
    logger.info("cursor value window moved away from File menu")
    return CursorValueWindowMoveResult(main_window, cursor_window, moved_window, target_rect)


def focus_universal_viewer_main_window(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    focus_window_fn: FocusWindowFunction | None = None,
) -> CursorValueWindow:
    """현재 Universal Viewer 메인 창을 전면/포커스로 전환한다."""
    main_window = find_universal_viewer_main_window(window_enum_fn=window_enum_fn)
    logger.info("Universal Viewer main window focus request | hwnd=%s | rect=%s", main_window.hwnd, main_window.rectangle)
    focuser = focus_window_fn or focus_window
    focuser(main_window.hwnd)
    logger.info("Universal Viewer main window focused | hwnd=%s", main_window.hwnd)
    return main_window


def normalize_universal_viewer_main_window(
    logger: logging.Logger,
    *,
    main_window: object | None = None,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    restore_window_fn: RestoreWindowFunction | None = None,
    move_window_fn: MoveWindowFunction | None = None,
    get_window_rectangle_fn: GetWindowRectangleFunction | None = None,
    focus_window_fn: FocusWindowFunction | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> UniversalViewerWindowNormalizeResult:
    """Universal Viewer main window를 보정된 크기/위치로 정규화한다."""
    hwnd: int | None = None
    if main_window is not None:
        raw_hwnd = getattr(main_window, "hwnd", None) or getattr(main_window, "handle", None)
        if raw_hwnd is not None:
            hwnd = int(raw_hwnd)
    if hwnd is None:
        hwnd = find_universal_viewer_main_window(window_enum_fn=window_enum_fn).hwnd

    rectangle_reader = get_window_rectangle_fn or get_window_rectangle
    before_rect = rectangle_reader(hwnd)
    logger.info("Universal Viewer window before normalize: %s", format_rect_for_log(before_rect))

    restorer = restore_window_fn or restore_window
    mover = move_window_fn or move_window
    focuser = focus_window_fn or focus_window

    restorer(hwnd)
    wait_fn(0.2)
    mover(
        hwnd,
        UNIVERSAL_VIEWER_NORMALIZED_LEFT,
        UNIVERSAL_VIEWER_NORMALIZED_TOP,
        UNIVERSAL_VIEWER_NORMALIZED_WIDTH,
        UNIVERSAL_VIEWER_NORMALIZED_HEIGHT,
    )
    wait_fn(0.3)
    after_rect = rectangle_reader(hwnd)
    logger.info("Universal Viewer window after normalize: %s", format_rect_for_log(after_rect))
    focuser(hwnd)
    wait_fn(0.2)
    logger.info("Universal Viewer main window focused after normalize | hwnd=%s", hwnd)
    return UniversalViewerWindowNormalizeResult(hwnd, before_rect, after_rect, UNIVERSAL_VIEWER_NORMALIZED_RECT)


def open_cursor_value_window_from_universal_viewer_main_window(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    move_fn: MoveFunction | None = None,
    click_fn: ClickFunction | None = None,
    focus_window_fn: FocusWindowFunction | None = None,
    get_window_rectangle_fn: GetWindowRectangleFunction | None = None,
    desktop_factory: UiaDesktopFactory | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> CursorValueWindow:
    """Cursor Value ON/OFF toolbar 버튼을 우선 사용하고, 실패 시 fresh rect 좌표 fallback으로 연다."""
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    windows_before = tuple(enumerate_windows())

    try:
        existing_window = find_cursor_value_window(window_enum_fn=lambda: windows_before)
    except CursorValueError:
        existing_window = None

    if existing_window is not None:
        logger.info(
            "cursor value window already open | title=%s | hwnd=%s | rectangle=%s",
            existing_window.title,
            existing_window.hwnd,
            existing_window.rectangle,
        )
        return existing_window

    logger.info("Cursor value window open started")

    return open_cursor_value_window_via_uia_menu(
        logger,
        window_enum_fn=enumerate_windows,
        focus_window_fn=focus_window_fn,
        desktop_factory=desktop_factory,
        wait_fn=wait_fn,
    )


def open_cursor_value_window_via_uia_menu(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    focus_window_fn: FocusWindowFunction | None = None,
    desktop_factory: UiaDesktopFactory | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> CursorValueWindow:
    """UIA 메뉴 경로 윈도우(W) > 커서값 표시를 click_input으로 실행한다."""
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    windows_before = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: windows_before)
    (focus_window_fn or focus_window)(main_window.hwnd)
    logger.info("Universal Viewer main window focused before Cursor Value Display UIA menu")

    desktop = make_uia_desktop(desktop_factory)
    try:
        main_wrapper = desktop.window(handle=main_window.hwnd)  # type: ignore[attr-defined]
        focus_uia_wrapper_if_possible(main_wrapper, logger)
        descendants = tuple(safe_uia_descendants(main_wrapper))
    except Exception as exc:
        raise CursorValueError(f"Universal Viewer UIA menu tree를 읽지 못했습니다: {exc}") from exc

    window_menu = find_first_visible_enabled_uia_wrapper(descendants, is_universal_viewer_window_menu_text)
    if window_menu is None:
        names = tuple(filter(None, (read_uia_wrapper_name(wrapper) for wrapper in descendants)))
        raise CursorValueError(f"윈도우 UIA menu item을 찾지 못했습니다. UIA 이름 후보={names[:30]}")

    logger.info(
        "matched Window menu | text=%s | type=%s | rect=%s",
        read_uia_wrapper_name(window_menu),
        safe_uia_control_type(window_menu),
        safe_uia_rectangle(window_menu),
    )
    window_menu.click_input()  # type: ignore[attr-defined]
    logger.info("Window menu UIA click_input completed")
    wait_fn(CURSOR_VALUE_WINDOW_MENU_WAIT_SECONDS)

    cursor_value_item = wait_for_cursor_value_display_menu_item(desktop, main_window.pid, logger)
    logger.info(
        "matched Cursor Value Display menu | text=%s | type=%s | rect=%s",
        read_uia_wrapper_name(cursor_value_item),
        safe_uia_control_type(cursor_value_item),
        safe_uia_rectangle(cursor_value_item),
    )
    cursor_value_item.click_input()  # type: ignore[attr-defined]
    logger.info("Cursor Value Display menu UIA click_input completed")
    wait_fn(CURSOR_VALUE_DISPLAY_WAIT_SECONDS)

    detected_window = wait_for_cursor_value_dialog(enumerate_windows, logger)
    logger.info(
        "detected cursor value dialog | title=%s | class=%s | rect=%s",
        detected_window.title,
        detected_window.class_name,
        detected_window.rectangle,
    )
    logger.info("Cursor value window open completed")
    return detected_window


def open_cursor_value_window_via_toolbar_button(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    desktop_factory: UiaDesktopFactory | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> CursorValueWindow:
    """Universal Viewer toolbar Button 'Cursor Value ON/OFF'를 UIA로 실행한다."""
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    windows_before = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: windows_before)
    desktop = make_uia_desktop(desktop_factory)
    try:
        main_wrapper = desktop.window(handle=main_window.hwnd)  # type: ignore[attr-defined]
        focus_uia_wrapper_if_possible(main_wrapper, logger)
        wrappers = (main_wrapper, *safe_uia_descendants(main_wrapper))
    except Exception as exc:
        raise CursorValueError(f"Universal Viewer UIA toolbar tree를 읽지 못했습니다: {exc}") from exc

    button = find_first_visible_enabled_uia_wrapper(wrappers, is_cursor_value_toolbar_button)
    if button is None:
        names = tuple(filter(None, (read_uia_wrapper_name(wrapper) for wrapper in wrappers)))
        raise CursorValueError(f"Cursor Value ON/OFF toolbar button을 찾지 못했습니다. UIA 이름 후보={names[:30]}")

    logger.info("Cursor Value ON/OFF toolbar semantic action | name=%s", read_uia_wrapper_name(button))
    invoke_or_click_uia_wrapper(button, logger, "Cursor Value ON/OFF toolbar button")
    wait_fn(CURSOR_VALUE_DISPLAY_WAIT_SECONDS)
    detected_window = find_cursor_value_window(window_enum_fn=enumerate_windows)
    logger.info("Cursor value window detected")
    logger.info("Cursor value window rectangle: %s", detected_window.rectangle)
    logger.info("Cursor value window open completed")
    return detected_window


def fresh_window_rectangle_for_coordinate_fallback(
    window: CursorValueWindow,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    get_window_rectangle_fn: GetWindowRectangleFunction | None = None,
    logger: logging.Logger,
) -> tuple[int, int, int, int]:
    """좌표 fallback 직전에 현재 window rectangle을 다시 읽는다."""
    if get_window_rectangle_fn is not None or window_enum_fn is None:
        rectangle_reader = get_window_rectangle_fn or get_window_rectangle
        try:
            fresh_rect = rectangle_reader(window.hwnd)
            validate_plausible_window_rect(fresh_rect, "Universal Viewer main window")
            logger.info("Universal Viewer fresh current rectangle for coordinate fallback: %s", fresh_rect)
            return fresh_rect
        except Exception as exc:
            if window_enum_fn is None:
                raise
            logger.warning("fresh rectangle read failed; injected window snapshot rectangle을 사용합니다: %s", exc)

    validate_plausible_window_rect(window.rectangle, "Universal Viewer main window")
    return window.rectangle


def make_uia_desktop(desktop_factory: UiaDesktopFactory | None = None) -> object:
    """테스트 주입 또는 pywinauto Desktop(backend='uia') 객체를 만든다."""
    if desktop_factory is not None:
        return desktop_factory("uia")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise CursorValueError("pywinauto가 설치되어 있지 않아 UIA semantic action을 사용할 수 없습니다.") from exc
    return Desktop(backend="uia")


def focus_uia_wrapper_if_possible(wrapper: object, logger: logging.Logger) -> None:
    try:
        wrapper.set_focus()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("UIA wrapper focus를 건너뜁니다: %s", exc)


def invoke_or_click_uia_wrapper(wrapper: object, logger: logging.Logger, label: str) -> None:
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
    except Exception as exc:
        raise CursorValueError(f"{label} UIA action 실패: invoke={invoke_error}, click_input={exc}") from exc


def find_first_visible_enabled_uia_wrapper(wrappers: Iterable[object], predicate: Callable[[object], bool]) -> object | None:
    for wrapper in wrappers:
        if safe_uia_bool_call(wrapper, "is_visible", True) is False:
            continue
        if safe_uia_bool_call(wrapper, "is_enabled", True) is False:
            continue
        if predicate(wrapper):
            return wrapper
    return None


def is_cursor_value_toolbar_button(wrapper: object) -> bool:
    name = normalize_button_text(read_uia_wrapper_name(wrapper))
    expected = normalize_button_text(UNIVERSAL_VIEWER_CURSOR_VALUE_BUTTON_TEXT)
    if name != expected:
        return False
    control_type = safe_uia_control_type(wrapper).casefold()
    return not control_type or "button" in control_type


def is_universal_viewer_window_menu_text(wrapper: object) -> bool:
    """Universal Viewer 상단 윈도우(W) 메뉴 후보인지 확인한다."""
    normalized = normalize_menu_text(read_uia_wrapper_name(wrapper))
    return "윈도우" in normalized or "window" in normalized


def is_cursor_value_display_menu_text(wrapper: object) -> bool:
    """윈도우 메뉴 아래 커서값 표시 항목 후보인지 확인한다."""
    normalized = normalize_menu_text(read_uia_wrapper_name(wrapper))
    return "커서값표시" in normalized or "커서값" in normalized or "cursorvalue" in normalized


def normalize_menu_text(text: str) -> str:
    """메뉴 검색용으로 공백/accelerator/괄호/말줄임표를 제거한다."""
    return (
        text.replace("&", "")
        .replace(" ", "")
        .replace("\t", "")
        .replace("(", "")
        .replace(")", "")
        .replace("...", "")
        .replace("…", "")
        .strip()
        .casefold()
    )


def normalize_button_text(text: str) -> str:
    return text.replace("&", "").replace("(", "").replace(")", "").strip().casefold()


def safe_uia_descendants(wrapper: object) -> tuple[object, ...]:
    try:
        return tuple(wrapper.descendants())  # type: ignore[attr-defined]
    except Exception:
        return ()


def read_uia_wrapper_name(wrapper: object) -> str:
    for value in (
        safe_uia_call(wrapper, "window_text", ""),
        getattr(getattr(wrapper, "element_info", None), "name", ""),
    ):
        if value:
            return str(value).strip()
    return ""


def safe_uia_rectangle(wrapper: object) -> object:
    """로그용 UIA rectangle을 읽는다."""
    try:
        return wrapper.rectangle()  # type: ignore[attr-defined]
    except Exception:
        return getattr(getattr(wrapper, "element_info", None), "rectangle", "")


def safe_uia_process_id(wrapper: object) -> int | None:
    """UIA wrapper process id를 가능한 범위에서 읽는다."""
    for value in (
        safe_uia_call(wrapper, "process_id", None),
        getattr(getattr(wrapper, "element_info", None), "process_id", None),
    ):
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return None


def safe_uia_control_type(wrapper: object) -> str:
    return str(
        safe_uia_call(wrapper, "friendly_class_name", "")
        or getattr(getattr(wrapper, "element_info", None), "control_type", "")
        or ""
    )


def safe_uia_bool_call(wrapper: object, method_name: str, default: bool | None) -> bool | None:
    value = safe_uia_call(wrapper, method_name, default)
    if value is None:
        return None
    return bool(value)


def safe_uia_call(wrapper: object, method_name: str, default: object) -> object:
    try:
        method = getattr(wrapper, method_name)
        return method()
    except Exception:
        return default


def safe_desktop_windows(desktop: object) -> tuple[object, ...]:
    """Desktop(backend='uia').windows() 후보를 안전하게 읽는다."""
    try:
        return tuple(desktop.windows())  # type: ignore[attr-defined]
    except Exception:
        return ()


def iter_visible_uia_menu_candidates(desktop: object, owner_pid: int | None) -> tuple[object, ...]:
    """열린 popup menu에서 보이는 UIA 후보를 수집하되 가능한 경우 Universal Viewer PID로 제한한다."""
    candidates: list[object] = []
    for root in safe_desktop_windows(desktop):
        for wrapper in (root, *safe_uia_descendants(root)):
            if safe_uia_bool_call(wrapper, "is_visible", True) is False:
                continue
            if safe_uia_bool_call(wrapper, "is_enabled", True) is False:
                continue
            wrapper_pid = safe_uia_process_id(wrapper)
            if owner_pid is not None and wrapper_pid is not None and wrapper_pid != owner_pid:
                continue
            candidates.append(wrapper)
    return tuple(candidates)


def wait_for_cursor_value_display_menu_item(
    desktop: object,
    owner_pid: int | None,
    logger: logging.Logger,
    *,
    timeout_seconds: float = 3.0,
    poll_interval: float = 0.2,
) -> object:
    """윈도우 메뉴를 연 뒤 커서값 표시 UIA MenuItem을 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    last_names: tuple[str, ...] = ()
    while time.monotonic() <= deadline:
        candidates = iter_visible_uia_menu_candidates(desktop, owner_pid)
        last_names = tuple(filter(None, (read_uia_wrapper_name(wrapper) for wrapper in candidates)))
        menu_item = find_first_visible_enabled_uia_wrapper(candidates, is_cursor_value_display_menu_text)
        if menu_item is not None:
            return menu_item
        time.sleep(poll_interval)
    logger.warning("Cursor Value Display UIA menu candidates: %s", last_names[:50])
    raise CursorValueError("커서값 표시 UIA MenuItem을 찾지 못했습니다.")


def wait_for_cursor_value_dialog(
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]],
    logger: logging.Logger,
    *,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.2,
) -> CursorValueWindow:
    """top-level 커서값 dialog(title contains 커서값, class #32770)를 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    last_candidates: tuple[CursorValueWindow, ...] = ()
    while time.monotonic() <= deadline:
        windows = tuple(window_enum_fn())
        candidates = tuple(
            window
            for window in windows
            if window.visible
            and window.enabled
            and CURSOR_VALUE_TITLE_KEYWORD in window.title
            and window.class_name == "#32770"
        )
        if candidates:
            return sorted(candidates, key=lambda item: item.hwnd)[0]
        last_candidates = tuple(window for window in windows if CURSOR_VALUE_TITLE_KEYWORD in window.title)
        time.sleep(poll_interval)
    logger.warning("cursor value dialog candidates after UIA menu click: %s", last_candidates)
    raise CursorValueError("커서값 dialog(title contains 커서값, class #32770)를 찾지 못했습니다.")


def validate_plausible_window_rect(rectangle: tuple[int, int, int, int], label: str) -> None:
    left, top, right, bottom = rectangle
    if right - left < 100 or bottom - top < 100:
        raise CursorValueError(f"{label} rectangle이 비정상적으로 작습니다: {rectangle}")


def ensure_cursor_value_window_open(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
) -> CursorValueWindow:
    """커서값 창이 열린 상태인지 확인한다."""
    window = find_cursor_value_window(window_enum_fn=window_enum_fn)
    logger.info("Cursor value window opened | title=%s | hwnd=%s | rect=%s", window.title, window.hwnd, window.rectangle)
    return window


def test_ab_cursor_drag_read(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    move_to_fn: MoveToFunction | None = None,
    move_fn: MoveFunction | None = None,
    mouse_down_fn: MouseButtonFunction | None = None,
    mouse_up_fn: MouseButtonFunction | None = None,
    click_fn: ClickFunction | None = None,
    hotkey_fn: HotkeyFunction | None = None,
    clipboard_reader: ClipboardReader | None = None,
    focus_window_fn: FocusWindowFunction | None = None,
    get_window_rectangle_fn: GetWindowRectangleFunction | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> ABCursorDragReadResult:
    """Universal Viewer 그래프에서 A→B cursor drag 후 커서값 차이를 읽는 임시 검증 모드."""
    logger.info("AB cursor drag test started")
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    initial_windows = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: initial_windows)
    cursor_window = find_cursor_value_window(window_enum_fn=lambda: initial_windows)

    if window_enum_fn is None:
        normalize_universal_viewer_main_window(logger, main_window=main_window, wait_fn=wait_fn)
        refreshed_windows = tuple(enumerate_windows())
        main_window = find_universal_viewer_main_window(window_enum_fn=lambda: refreshed_windows)
        cursor_window = find_cursor_value_window(window_enum_fn=lambda: refreshed_windows)

    if window_enum_fn is None or focus_window_fn is not None:
        (focus_window_fn or focus_window)(main_window.hwnd)

    main_rect = fresh_window_rectangle_for_coordinate_fallback(
        main_window,
        window_enum_fn=window_enum_fn,
        get_window_rectangle_fn=get_window_rectangle_fn,
        logger=logger,
    )
    main_window_for_result = CursorValueWindow(
        main_window.hwnd,
        main_window.title,
        main_window.class_name,
        main_window.pid,
        main_rect,
        main_window.visible,
        main_window.enabled,
    )

    main_window_for_profile = CursorValueWindow(
        main_window.hwnd,
        main_window.title,
        main_window.class_name,
        main_window.pid,
        main_rect,
        main_window.visible,
        main_window.enabled,
    )
    ab_profile, a_start_rel, a_max_rel, b_release_rel = active_ab_cursor_coordinates_for_window(main_window_for_profile)
    if ab_profile is not None:
        logger.info(
            "A/B cursor coordinate profile selected | class=%s | size=%s",
            ab_profile["main_class"],
            ab_profile["main_size"],
        )

    a_candidate_abs = point_from_relative(main_rect, a_start_rel)
    a_search_right_limit_abs = point_from_relative(main_rect, a_max_rel)
    b_release_abs = point_from_relative(main_rect, b_release_rel)
    validate_point_inside_rect(a_candidate_abs, main_rect, "A cursor candidate")
    validate_point_inside_rect(a_search_right_limit_abs, main_rect, "A cursor search right limit")
    validate_point_inside_rect(b_release_abs, main_rect, "B cursor release")

    logger.info("Universal Viewer main window rectangle: %s", main_rect)
    logger.info("cursor value window rectangle: %s", cursor_window.rectangle)
    logger.info(
        "a_search_left_limit_rel=%s | a_search_left_limit_abs=%s",
        a_start_rel,
        a_candidate_abs,
    )
    logger.info(
        "a_search_right_limit_rel=%s | a_search_right_limit_abs=%s",
        a_max_rel,
        a_search_right_limit_abs,
    )
    logger.info(
        "b_release_overshoot_target_rel=%s | b_release_overshoot_target_abs=%s",
        b_release_rel,
        b_release_abs,
    )

    move_to_action = move_to_fn or move_mouse_to
    drag_ab_cursor_from_a_to_b(
        a_candidate_abs,
        b_release_abs,
        logger,
        move_to_fn=move_to_action,
        mouse_down_fn=mouse_down_fn,
        mouse_up_fn=mouse_up_fn,
    )
    wait_fn(AB_CURSOR_AFTER_DRAG_WAIT_SECONDS)

    logger.info("BEFORE reading cursor value difference")
    move_action = move_fn or move_mouse
    cursor_value_result = read_cursor_value_absolute_time_difference(
        logger,
        window_enum_fn=enumerate_windows,
        move_fn=move_action,
        click_fn=click_fn,
        hotkey_fn=hotkey_fn,
        clipboard_reader=clipboard_reader,
        wait_fn=wait_fn,
    )
    logger.info("parsed absolute time difference: %s", cursor_value_result.absolute_time_difference)
    logger.info("parsed seconds: %s", cursor_value_result.difference_seconds)
    logger.info("AB cursor drag test completed")
    logger.info("PDF was not printed")
    return ABCursorDragReadResult(
        main_window=main_window_for_result,
        cursor_window=cursor_window,
        a_candidate_rel=a_start_rel,
        a_candidate_abs=a_candidate_abs,
        b_release_rel=b_release_rel,
        b_release_abs=b_release_abs,
        cursor_value_result=cursor_value_result,
        a_search_right_limit_rel=a_max_rel,
        a_search_right_limit_abs=a_search_right_limit_abs,
    )


def preview_ab_cursor_profile(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    move_fn: MoveFunction | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> ABCursorProfilePreviewResult:
    """현재 Universal Viewer main window size에 맞는 A/B cursor profile 좌표를 mouse move로만 미리 확인한다."""
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    windows = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: windows)
    profile = select_ab_cursor_coordinate_profile(main_window)
    if profile is None:
        raise CursorValueError(
            "현재 Universal Viewer main window size에 맞는 A/B cursor profile을 찾지 못했습니다. "
            f"class={main_window.class_name!r}, size={window_size(main_window.rectangle)}, rectangle={main_window.rectangle}"
        )

    a_start_rel = ab_cursor_profile_point(profile, "ab_a_start")
    a_max_rel = ab_cursor_profile_point(profile, "ab_a_max")
    b_release_rel = ab_cursor_profile_point(profile, "ab_b_release_target")
    a_start_abs = point_from_relative(main_window.rectangle, a_start_rel)
    a_max_abs = point_from_relative(main_window.rectangle, a_max_rel)
    b_release_abs = point_from_relative(main_window.rectangle, b_release_rel)
    for label, point in (
        ("ab_a_start", a_start_abs),
        ("ab_a_max", a_max_abs),
        ("ab_b_release_target", b_release_abs),
    ):
        validate_point_inside_rect(point, main_window.rectangle, label)

    logger.info("A/B cursor profile preview | main_window_rect=%s | size=%s", main_window.rectangle, window_size(main_window.rectangle))
    logger.info("ab_a_start rel=%s abs=%s", a_start_rel, a_start_abs)
    logger.info("ab_a_max rel=%s abs=%s", a_max_rel, a_max_abs)
    logger.info("ab_b_release_target rel=%s abs=%s", b_release_rel, b_release_abs)
    move_action = move_fn or move_mouse
    for point in (a_start_abs, a_max_abs, b_release_abs):
        move_action(point)
        wait_fn(0.2)
    return ABCursorProfilePreviewResult(
        main_window=main_window,
        profile=profile,
        a_start_rel=a_start_rel,
        a_start_abs=a_start_abs,
        a_max_rel=a_max_rel,
        a_max_abs=a_max_abs,
        b_release_rel=b_release_rel,
        b_release_abs=b_release_abs,
    )


def _adjust_ab_cursors_to_30min_progress_legacy(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    attempt_reader_fn: AdjustmentReadFunction | None = None,
    move_to_fn: MoveToFunction | None = None,
    move_fn: MoveFunction | None = None,
    mouse_down_fn: MouseButtonFunction | None = None,
    mouse_up_fn: MouseButtonFunction | None = None,
    click_fn: ClickFunction | None = None,
    hotkey_fn: HotkeyFunction | None = None,
    clipboard_reader: ClipboardReader | None = None,
    wait_fn: WaitFunction = time.sleep,
    max_iterations: int = AB_CURSOR_MAX_ADJUST_ITERATIONS,
) -> ABCursorAdjustmentResult:
    """A cursor 위치를 자동 조정해 A/B 절대시간 차가 30분 범위에 들어오도록 시도한다."""
    logger.info("AB cursor 30min adjustment started")
    logger.info(
        "accepted range: %s-%s seconds | target=%s",
        AB_CURSOR_ACCEPT_MIN_SECONDS,
        AB_CURSOR_ACCEPT_MAX_SECONDS,
        AB_CURSOR_TARGET_SECONDS,
    )
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    initial_windows = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: initial_windows)
    cursor_window = find_cursor_value_window(window_enum_fn=lambda: initial_windows)
    logger.info("Universal Viewer main window rectangle: %s", main_window.rectangle)
    logger.info("cursor value window rectangle: %s", cursor_window.rectangle)

    attempts: list[ABCursorAdjustmentAttempt] = []
    best_attempt: ABCursorAdjustmentAttempt | None = None
    attempt_number = 0

    def run_attempt(phase: str, progress: float) -> ABCursorAdjustmentAttempt:
        nonlocal attempt_number, best_attempt
        attempt_number += 1
        a_candidate_rel = interpolate_a_cursor_candidate_rel(progress)
        a_candidate_abs = point_from_relative(main_window.rectangle, a_candidate_rel)
        b_release_abs = point_from_relative(main_window.rectangle, AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL)
        validate_point_inside_rect(a_candidate_abs, main_window.rectangle, "A cursor candidate")
        validate_point_inside_rect(b_release_abs, main_window.rectangle, "B cursor release")
        logger.info(
            "AB cursor adjustment attempt | attempt=%s | phase=%s | progress=%.6f | "
            "a_candidate_rel=%s | a_candidate_abs=%s | b_release_rel=%s | b_release_abs=%s",
            attempt_number,
            phase,
            progress,
            a_candidate_rel,
            a_candidate_abs,
            AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL,
            b_release_abs,
        )
        if attempt_reader_fn is not None:
            cursor_value_result = attempt_reader_fn(
                attempt_number,
                phase,
                progress,
                a_candidate_rel,
                a_candidate_abs,
                AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL,
                b_release_abs,
            )
        else:
            drag_ab_cursor_from_a_to_b(
                a_candidate_abs,
                b_release_abs,
                logger,
                move_to_fn=move_to_fn,
                mouse_down_fn=mouse_down_fn,
                mouse_up_fn=mouse_up_fn,
            )
            wait_fn(AB_CURSOR_AFTER_DRAG_WAIT_SECONDS)
            cursor_value_result = read_cursor_value_absolute_time_difference(
                logger,
                window_enum_fn=enumerate_windows,
                move_fn=move_fn,
                click_fn=click_fn,
                hotkey_fn=hotkey_fn,
                clipboard_reader=clipboard_reader,
                wait_fn=wait_fn,
            )
        seconds = cursor_value_result.difference_seconds
        decision = classify_ab_cursor_seconds(seconds)
        attempt = ABCursorAdjustmentAttempt(
            attempt_number=attempt_number,
            phase=phase,
            progress=progress,
            a_candidate_rel=a_candidate_rel,
            a_candidate_abs=a_candidate_abs,
            b_release_rel=AB_CURSOR_B_RELEASE_OVERSHOOT_TARGET_REL,
            b_release_abs=b_release_abs,
            absolute_time_difference=cursor_value_result.absolute_time_difference,
            seconds=seconds,
            decision=decision,
        )
        attempts.append(attempt)
        best_attempt = choose_better_ab_adjustment_attempt(best_attempt, attempt)
        logger.info(
            "AB cursor adjustment result | attempt=%s | absolute_time_difference=%s | "
            "seconds=%s | decision=%s",
            attempt_number,
            attempt.absolute_time_difference,
            attempt.seconds,
            attempt.decision,
        )
        return attempt

    initial = run_attempt("initial", 0.0)
    if is_ab_cursor_seconds_accepted(initial.seconds):
        return build_ab_adjustment_result(True, attempts, best_attempt, "success")
    if initial.seconds < AB_CURSOR_ACCEPT_MIN_SECONDS:
        logger.warning("Left A limit is already shorter than accepted range. Recalibration required.")
        return build_ab_adjustment_result(
            False,
            attempts,
            best_attempt,
            "Left A limit is already shorter than accepted range. Recalibration required.",
        )

    previous_long_attempt = initial
    bracket_low_progress: float | None = None
    bracket_high_progress: float | None = None
    for progress in AB_CURSOR_COARSE_PROGRESS_VALUES:
        try:
            coarse = run_attempt("coarse", progress)
        except CursorValueError:
            if progress == 1.0:
                return build_ab_adjustment_result(
                    False,
                    attempts,
                    best_attempt,
                    "Right A limit or B release did not produce a valid cursor difference.",
                )
            raise
        if progress == 1.0 and coarse.seconds == 0:
            return build_ab_adjustment_result(
                False,
                attempts,
                best_attempt,
                "Right A limit or B release did not produce a valid cursor difference.",
            )
        if is_ab_cursor_seconds_accepted(coarse.seconds):
            return build_ab_adjustment_result(True, attempts, best_attempt, "success")
        if coarse.seconds < AB_CURSOR_ACCEPT_MIN_SECONDS:
            bracket_low_progress = previous_long_attempt.progress
            bracket_high_progress = coarse.progress
            logger.info(
                "bracket found | previous_progress=%.6f seconds=%s | current_progress=%.6f seconds=%s",
                previous_long_attempt.progress,
                previous_long_attempt.seconds,
                coarse.progress,
                coarse.seconds,
            )
            break
        previous_long_attempt = coarse

    if bracket_low_progress is None or bracket_high_progress is None:
        return build_ab_adjustment_result(
            False,
            attempts,
            best_attempt,
            "Right A limit is still longer than 1800 seconds. Move A right limit farther right.",
        )

    low_progress = bracket_low_progress
    high_progress = bracket_high_progress
    for _iteration in range(max_iterations):
        mid_progress = (low_progress + high_progress) / 2
        binary = run_attempt("binary", mid_progress)
        if is_ab_cursor_seconds_accepted(binary.seconds):
            return build_ab_adjustment_result(True, attempts, best_attempt, "success")
        if binary.seconds > AB_CURSOR_ACCEPT_MAX_SECONDS:
            logger.info("too long, move A right | progress=%.6f | seconds=%s", mid_progress, binary.seconds)
            low_progress = mid_progress
        else:
            logger.info("too short, move A left | progress=%.6f | seconds=%s", mid_progress, binary.seconds)
            high_progress = mid_progress

    return build_ab_adjustment_result(
        False,
        attempts,
        best_attempt,
        "Accepted range was not reached within max iterations.",
    )


def adaptive_ab_cursor_x_step(seconds: float) -> float:
    """현재 A/B 차이 초 값에 따라 다음 A.x 우측 이동량을 결정한다."""
    if seconds > 2400:
        return 0.050
    if seconds > 2000:
        return 0.030
    if seconds > 1850:
        return 0.015
    if seconds > AB_CURSOR_ACCEPT_MAX_SECONDS:
        return 0.005
    return AB_CURSOR_MIN_ADJUST_STEP


def adjust_ab_cursors_to_30min(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    attempt_reader_fn: AdjustmentReadFunction | None = None,
    move_to_fn: MoveToFunction | None = None,
    move_fn: MoveFunction | None = None,
    mouse_down_fn: MouseButtonFunction | None = None,
    mouse_up_fn: MouseButtonFunction | None = None,
    click_fn: ClickFunction | None = None,
    hotkey_fn: HotkeyFunction | None = None,
    clipboard_reader: ClipboardReader | None = None,
    mouse_position_fn: MousePositionFunction | None = None,
    wait_fn: WaitFunction = time.sleep,
    max_iterations: int = AB_CURSOR_MAX_ADJUST_ITERATIONS,
    focus_window_fn: FocusWindowFunction | None = None,
    get_window_rectangle_fn: GetWindowRectangleFunction | None = None,
) -> ABCursorAdjustmentResult:
    """저장된 그래프 좌표 기반으로 A cursor를 우측 조정해 30분 차이를 찾는다."""
    logger.info("AB cursor 30min adjustment started")
    logger.info(
        "accepted range: %s-%s seconds | target=%s",
        AB_CURSOR_ACCEPT_MIN_SECONDS,
        AB_CURSOR_ACCEPT_MAX_SECONDS,
        AB_CURSOR_TARGET_SECONDS,
    )
    enumerate_windows = window_enum_fn or enumerate_top_level_windows
    initial_windows = tuple(enumerate_windows())
    main_window = find_universal_viewer_main_window(window_enum_fn=lambda: initial_windows)
    cursor_window = find_cursor_value_window(window_enum_fn=lambda: initial_windows)
    if window_enum_fn is None:
        normalize_universal_viewer_main_window(logger, main_window=main_window, wait_fn=wait_fn)
        refreshed_windows = tuple(enumerate_windows())
        main_window = find_universal_viewer_main_window(window_enum_fn=lambda: refreshed_windows)
        cursor_window = find_cursor_value_window(window_enum_fn=lambda: refreshed_windows)
    main_rect = fresh_window_rectangle_for_coordinate_fallback(
        main_window,
        window_enum_fn=window_enum_fn,
        get_window_rectangle_fn=get_window_rectangle_fn,
        logger=logger,
    )
    main_window_for_profile = CursorValueWindow(
        main_window.hwnd,
        main_window.title,
        main_window.class_name,
        main_window.pid,
        main_rect,
        main_window.visible,
        main_window.enabled,
    )
    ab_profile, a_start_rel, a_max_rel, b_release_rel = active_ab_cursor_coordinates_for_window(main_window_for_profile)
    a_fixed_y_rel = a_start_rel[1]
    a_max_x_rel = a_max_rel[0]
    if ab_profile is not None:
        logger.info(
            "A/B cursor coordinate profile selected | class=%s | size=%s | unified_y=%s",
            ab_profile["main_class"],
            ab_profile["main_size"],
            a_fixed_y_rel,
        )

    b_release_abs = point_from_relative(main_rect, b_release_rel)
    validate_point_inside_rect(b_release_abs, main_rect, "B cursor release")

    logger.info("Universal Viewer main window rectangle: %s", main_rect)
    logger.info("cursor value window rectangle: %s", cursor_window.rectangle)
    logger.info(
        "a_start_rel=%s | fixed_a_y=%s | max_a_x=%s | b_release_rel=%s | b_release_abs=%s",
        a_start_rel,
        a_fixed_y_rel,
        a_max_x_rel,
        b_release_rel,
        b_release_abs,
    )

    attempts: list[ABCursorAdjustmentAttempt] = []
    best_attempt: ABCursorAdjustmentAttempt | None = None
    attempt_number = 0
    current_mouse_position_action = mouse_position_fn or get_mouse_position

    def run_attempt(phase: str, candidate_x: float) -> ABCursorAdjustmentAttempt:
        nonlocal attempt_number, best_attempt
        if candidate_x > a_max_x_rel:
            raise CursorValueError(
                f"A cursor candidate_x가 max_a_x를 초과했습니다: {candidate_x:.6f} > {a_max_x_rel:.6f}"
            )
        a_candidate_rel = (candidate_x, a_fixed_y_rel)
        if window_enum_fn is None or focus_window_fn is not None:
            (focus_window_fn or focus_window)(main_window.hwnd)
        current_main_rect = fresh_window_rectangle_for_coordinate_fallback(
            main_window,
            window_enum_fn=window_enum_fn,
            get_window_rectangle_fn=get_window_rectangle_fn,
            logger=logger,
        )
        a_candidate_abs = point_from_relative(current_main_rect, a_candidate_rel)
        b_release_abs_current = point_from_relative(current_main_rect, b_release_rel)
        validate_point_inside_rect(a_candidate_abs, current_main_rect, "A cursor candidate")
        validate_point_inside_rect(b_release_abs_current, current_main_rect, "B cursor release")
        if a_candidate_rel[0] >= b_release_rel[0]:
            raise CursorValueError(
                "A cursor candidate x는 B release x보다 왼쪽이어야 합니다: "
                f"A={a_candidate_rel[0]:.6f}, B={b_release_rel[0]:.6f}"
            )

        attempt_number += 1
        current_mouse_position = current_mouse_position_action()
        logger.info(
            "AB cursor adjustment attempt | attempt=%s | phase=%s | candidate_x=%.6f | "
            "current_physical_mouse_position_before_move_to_A=%s | "
            "main_window_rect=%s | a_candidate_rel=%s | a_candidate_abs=%s | b_release_rel=%s | b_release_abs=%s",
            attempt_number,
            phase,
            candidate_x,
            current_mouse_position,
            current_main_rect,
            a_candidate_rel,
            a_candidate_abs,
            b_release_rel,
            b_release_abs_current,
        )

        if attempt_reader_fn is not None:
            cursor_value_result = attempt_reader_fn(
                attempt_number,
                phase,
                candidate_x,
                a_candidate_rel,
                a_candidate_abs,
                b_release_rel,
                b_release_abs_current,
            )
        else:
            drag_ab_cursor_from_a_to_b(
                a_candidate_abs,
                b_release_abs_current,
                logger,
                move_to_fn=move_to_fn,
                mouse_down_fn=mouse_down_fn,
                mouse_up_fn=mouse_up_fn,
            )
            wait_fn(AB_CURSOR_AFTER_DRAG_WAIT_SECONDS)
            logger.info("BEFORE cursor value read")
            cursor_value_result = read_cursor_value_absolute_time_difference(
                logger,
                window_enum_fn=enumerate_windows,
                move_fn=move_fn,
                click_fn=click_fn,
                hotkey_fn=hotkey_fn,
                clipboard_reader=clipboard_reader,
                wait_fn=wait_fn,
            )

        logger.info(
            "Cursor value read completed. Next A candidate will be computed from stored graph coordinates, "
            "not current mouse position."
        )
        seconds = cursor_value_result.difference_seconds
        decision = classify_ab_cursor_seconds(seconds)
        attempt = ABCursorAdjustmentAttempt(
            attempt_number=attempt_number,
            phase=phase,
            progress=candidate_x,
            a_candidate_rel=a_candidate_rel,
            a_candidate_abs=a_candidate_abs,
            b_release_rel=b_release_rel,
            b_release_abs=b_release_abs_current,
            absolute_time_difference=cursor_value_result.absolute_time_difference,
            seconds=seconds,
            decision=decision,
        )
        attempts.append(attempt)
        best_attempt = choose_better_ab_adjustment_attempt(best_attempt, attempt)
        logger.info(
            "AB cursor adjustment result | attempt=%s | absolute_time_difference=%s | "
            "seconds=%s | decision=%s",
            attempt_number,
            attempt.absolute_time_difference,
            attempt.seconds,
            attempt.decision,
        )
        return attempt

    initial = run_attempt("initial", a_start_rel[0])
    if is_ab_cursor_seconds_accepted(initial.seconds):
        return build_ab_adjustment_result(True, attempts, best_attempt, "success")
    if initial.seconds < AB_CURSOR_ACCEPT_MIN_SECONDS:
        logger.warning("A start limit is already shorter than accepted range. Recalibration required.")
        return build_ab_adjustment_result(
            False,
            attempts,
            best_attempt,
            "A start limit is already shorter than accepted range. Recalibration required.",
        )

    last_too_long_x = initial.progress
    last_too_long_seconds = initial.seconds
    low_x: float | None = None
    high_x: float | None = None

    while attempt_number < AB_CURSOR_MAX_ADJUST_ATTEMPTS:
        candidate_x = last_too_long_x + adaptive_ab_cursor_x_step(last_too_long_seconds)
        if candidate_x > a_max_x_rel:
            return build_ab_adjustment_result(
                False,
                attempts,
                best_attempt,
                "A candidate x exceeded max_a_x before reaching accepted range.",
            )
        coarse = run_attempt("coarse", candidate_x)
        if is_ab_cursor_seconds_accepted(coarse.seconds):
            return build_ab_adjustment_result(True, attempts, best_attempt, "success")
        if coarse.seconds < AB_CURSOR_ACCEPT_MIN_SECONDS:
            low_x = last_too_long_x
            high_x = coarse.progress
            logger.info(
                "bracket found | previous_x=%.6f seconds=%s | current_x=%.6f seconds=%s",
                last_too_long_x,
                last_too_long_seconds,
                coarse.progress,
                coarse.seconds,
            )
            break
        last_too_long_x = coarse.progress
        last_too_long_seconds = coarse.seconds

    if low_x is None or high_x is None:
        return build_ab_adjustment_result(
            False,
            attempts,
            best_attempt,
            "Right A limit is still longer than 1800 seconds. Move A right limit farther right.",
        )

    for _iteration in range(max_iterations):
        if attempt_number >= AB_CURSOR_MAX_ADJUST_ATTEMPTS:
            break
        mid_x = (low_x + high_x) / 2
        binary = run_attempt("binary", mid_x)
        if is_ab_cursor_seconds_accepted(binary.seconds):
            return build_ab_adjustment_result(True, attempts, best_attempt, "success")
        if binary.seconds > AB_CURSOR_ACCEPT_MAX_SECONDS:
            logger.info("too long, move A right | candidate_x=%.6f | seconds=%s", mid_x, binary.seconds)
            low_x = mid_x
        else:
            logger.info("too short, move A left | candidate_x=%.6f | seconds=%s", mid_x, binary.seconds)
            high_x = mid_x

    return build_ab_adjustment_result(
        False,
        attempts,
        best_attempt,
        "Accepted range was not reached within max iterations.",
    )


def build_ab_adjustment_result(
    success: bool,
    attempts: Iterable[ABCursorAdjustmentAttempt],
    best_attempt: ABCursorAdjustmentAttempt | None,
    reason: str,
) -> ABCursorAdjustmentResult:
    """조정 결과 객체를 생성한다."""
    return ABCursorAdjustmentResult(success, tuple(attempts), best_attempt, reason)


def interpolate_a_cursor_candidate_rel(progress: float) -> tuple[float, float]:
    """left/right limit 사이 progress 위치의 A cursor 상대 좌표를 계산한다."""
    if progress < 0 or progress > 1:
        raise CursorValueError(f"A cursor progress는 0~1 사이여야 합니다: {progress}")
    left_x, left_y = AB_CURSOR_A_SEARCH_LEFT_LIMIT_REL
    right_x, right_y = AB_CURSOR_A_SEARCH_RIGHT_LIMIT_REL
    return (
        left_x + ((right_x - left_x) * progress),
        left_y + ((right_y - left_y) * progress),
    )


def is_ab_cursor_seconds_accepted(seconds: float) -> bool:
    """A/B cursor 차이가 허용 범위 안인지 확인한다."""
    return AB_CURSOR_ACCEPT_MIN_SECONDS <= seconds <= AB_CURSOR_ACCEPT_MAX_SECONDS


def classify_ab_cursor_seconds(seconds: float) -> str:
    """A/B cursor 초 값에 따른 다음 조정 방향을 반환한다."""
    if is_ab_cursor_seconds_accepted(seconds):
        return "success"
    if seconds > AB_CURSOR_ACCEPT_MAX_SECONDS:
        return "too long, move A right"
    return "too short, move A left"


def choose_better_ab_adjustment_attempt(
    current: ABCursorAdjustmentAttempt | None,
    candidate: ABCursorAdjustmentAttempt,
) -> ABCursorAdjustmentAttempt:
    """실패 시 보고할 최선 시도를 고른다."""
    if current is None:
        return candidate
    if is_ab_cursor_seconds_accepted(candidate.seconds):
        return candidate
    if is_ab_cursor_seconds_accepted(current.seconds):
        return current
    candidate_under_or_equal = candidate.seconds <= AB_CURSOR_ACCEPT_MAX_SECONDS
    current_under_or_equal = current.seconds <= AB_CURSOR_ACCEPT_MAX_SECONDS
    if candidate_under_or_equal and current_under_or_equal:
        return candidate if candidate.seconds > current.seconds else current
    if candidate_under_or_equal and not current_under_or_equal:
        return candidate
    if current_under_or_equal and not candidate_under_or_equal:
        return current
    candidate_distance = abs(candidate.seconds - AB_CURSOR_TARGET_SECONDS)
    current_distance = abs(current.seconds - AB_CURSOR_TARGET_SECONDS)
    return candidate if candidate_distance < current_distance else current


def drag_ab_cursor_from_a_to_b(
    a_point: tuple[int, int],
    b_point: tuple[int, int],
    logger: logging.Logger,
    *,
    move_to_fn: MoveToFunction | None = None,
    mouse_down_fn: MouseButtonFunction | None = None,
    mouse_up_fn: MouseButtonFunction | None = None,
    duration: float = AB_CURSOR_DRAG_DURATION_SECONDS,
) -> None:
    """A 지점에서 왼쪽 버튼을 누른 채 B 지점까지 이동하고 반드시 버튼을 놓는다."""
    move_to_action = move_to_fn or move_mouse_to
    mouse_down_action = mouse_down_fn or mouse_down
    mouse_up_action = mouse_up_fn or mouse_up
    mouse_is_down = False
    try:
        logger.info("BEFORE moveTo A | point=%s | duration=%s", a_point, AB_CURSOR_MOVE_TO_A_DURATION_SECONDS)
        move_to_action(a_point, AB_CURSOR_MOVE_TO_A_DURATION_SECONDS)
        logger.info("AFTER moveTo A")
        logger.info("BEFORE mouseDown at A | point=%s | button=left", a_point)
        mouse_down_action("left")
        mouse_is_down = True
        logger.info("AFTER mouseDown")
        logger.info("BEFORE moveTo B release | point=%s | duration=%s", b_point, duration)
        move_to_action(b_point, duration)
        logger.info("AFTER moveTo B release")
    finally:
        if mouse_is_down:
            logger.info("BEFORE mouseUp at B | point=%s | button=left", b_point)
            mouse_up_action("left")
            logger.info("AFTER mouseUp")


def read_cursor_value_absolute_time_difference(
    logger: logging.Logger,
    *,
    window_enum_fn: Callable[[], Iterable[CursorValueWindow]] | None = None,
    move_fn: MoveFunction | None = None,
    click_fn: ClickFunction | None = None,
    hotkey_fn: HotkeyFunction | None = None,
    clipboard_reader: ClipboardReader | None = None,
    wait_fn: WaitFunction = time.sleep,
) -> CursorValueReadResult:
    """커서값 창 중앙을 클릭하고 Ctrl+A/C로 절대시간 '차' 값을 읽는다."""
    window = find_cursor_value_window(window_enum_fn=window_enum_fn)
    click_point = cursor_value_window_center(window.rectangle)
    logger.info(
        "커서값 창 탐지 | title=%s | class=%s | hwnd=%s | pid=%s | rect=%s",
        window.title,
        window.class_name,
        window.hwnd,
        window.pid,
        window.rectangle,
    )
    logger.info(
        "커서값 창 중앙 클릭 | cursor_value_window_click_rel=%s | cursor_value_window_click_abs=%s",
        CURSOR_VALUE_WINDOW_CLICK_REL,
        click_point,
    )

    move_action = move_fn or move_mouse
    click_action = click_fn or click_mouse
    hotkey_action = hotkey_fn or send_hotkey
    read_clipboard = clipboard_reader or read_clipboard_text

    move_action(click_point)
    click_action(click_point)
    hotkey_action("ctrl", "a")
    hotkey_action("ctrl", "c")
    wait_fn(CURSOR_VALUE_COPY_WAIT_SECONDS)
    clipboard_text = read_clipboard()
    value = extract_absolute_time_difference(clipboard_text)
    logger.info("커서값 clipboard 절대시간 차 값 파싱 완료 | value=%s", value)
    return CursorValueReadResult(window, click_point, clipboard_text, value)


def point_from_relative(rectangle: tuple[int, int, int, int], rel: tuple[float, float]) -> tuple[int, int]:
    """rectangle 기준 상대 좌표를 절대 좌표로 변환한다."""
    left, top, right, bottom = rectangle
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise CursorValueError(f"유효하지 않은 window rectangle입니다: {rectangle}")
    return (round(left + width * rel[0]), round(top + height * rel[1]))


def validate_point_inside_rect(point: tuple[int, int], rectangle: tuple[int, int, int, int], label: str) -> None:
    """절대 좌표가 rectangle 내부인지 확인한다."""
    x, y = point
    left, top, right, bottom = rectangle
    if not (left <= x <= right and top <= y <= bottom):
        raise CursorValueError(f"{label} 좌표가 Universal Viewer 메인 창 밖입니다: point={point}, rect={rectangle}")


def extract_absolute_time_difference(clipboard_text: str) -> str:
    """clipboard table/text에서 절대시간 행의 '차' 값을 추출한다."""
    lines = [line.strip() for line in clipboard_text.splitlines() if line.strip()]
    if not lines:
        raise CursorValueError("clipboard text가 비어 있어 절대시간 차 값을 읽을 수 없습니다.")

    parsed_rows = [split_clipboard_row(line) for line in lines]
    header_index = find_column_index(parsed_rows, "차")
    if header_index is not None:
        for row in parsed_rows:
            if row and "절대시간" in row[0] and header_index < len(row):
                value = normalize_duration_candidate(row[header_index])
                if value:
                    return value

    for line in lines:
        if "절대시간" not in line:
            continue
        value = extract_absolute_time_difference_from_line(line)
        if value:
            return value

    raise CursorValueError("clipboard text에서 절대시간 행의 '차' 값을 찾지 못했습니다.")


def extract_absolute_time_difference_from_line(line: str) -> str | None:
    """절대시간 한 줄에서 A/B 절대시각을 제외하고 '차' duration 값을 추출한다."""
    if "\t" in line:
        fields = [field.strip() for field in line.split("\t")]
        if len(fields) >= 4:
            value = normalize_duration_candidate(fields[-1])
            if value:
                return value

    if "차" in line:
        after_difference_label = line.split("차", 1)[1]
        value = last_duration_value(after_difference_label)
        if value:
            return value

    return last_duration_value(line)


def split_clipboard_row(line: str) -> list[str]:
    """탭/쉼표/복수 공백 기반 clipboard row 분리."""
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    if "," in line:
        return [cell.strip() for cell in line.split(",")]
    return [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]


def find_column_index(rows: Iterable[list[str]], column_name: str) -> int | None:
    """분리된 행들에서 지정 column index를 찾는다."""
    for row in rows:
        for index, cell in enumerate(row):
            if cell.strip() == column_name:
                return index
    return None


def normalize_time_value(value: str) -> str | None:
    """문자열에서 HH:MM:SS.mmm 형태 값을 추출한다."""
    return first_time_value(value)


def normalize_duration_candidate(value: str) -> str | None:
    """절대 날짜-시간을 제외한 문자열에서 duration 후보를 추출한다."""
    return last_duration_value(value)


def remove_absolute_datetime_values(text: str) -> str:
    """YYYY/MM/DD HH:MM:SS.mmm 형태의 절대 날짜-시간 값을 제거한다."""
    return ABSOLUTE_DATETIME_RE.sub(" ", text)


def last_duration_value(text: str) -> str | None:
    """절대 날짜-시간 내부 시각을 제외하고 마지막 duration 값을 반환한다."""
    text_without_datetimes = remove_absolute_datetime_values(text)
    return last_time_value(text_without_datetimes)


def first_time_value(text: str) -> str | None:
    match = TIME_VALUE_RE.search(text)
    return normalize_millisecond(match.group(0)) if match else None


def last_time_value(text: str) -> str | None:
    matches = TIME_VALUE_RE.findall(text)
    return normalize_millisecond(matches[-1]) if matches else None


def normalize_millisecond(value: str) -> str:
    """밀리초 자릿수를 3자리로 맞춘다."""
    if "." not in value:
        return f"{value}.000"
    head, tail = value.split(".", 1)
    return f"{head}.{tail[:3].ljust(3, '0')}"


def duration_text_to_seconds(value: str) -> float:
    """HH:MM:SS.mmm 형식의 duration 문자열을 초로 변환한다."""
    normalized = normalize_millisecond(value.strip())
    match = re.fullmatch(r"(?P<hours>\d{1,2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})\.(?P<millis>\d{3})", normalized)
    if not match:
        raise CursorValueError(f"절대시간 차 값을 초로 변환할 수 없습니다: {value!r}")
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    millis = int(match.group("millis"))
    return (hours * 3600) + (minutes * 60) + seconds + (millis / 1000)


def get_mouse_position() -> tuple[int, int] | None:
    """현재 물리 마우스 위치를 로깅용으로만 읽는다."""
    try:
        import pyautogui

        position = pyautogui.position()
        return (int(position[0]), int(position[1]))
    except Exception:  # pragma: no cover - GUI 환경 의존 로깅 보조
        return None


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    """정수 값을 지정 범위 안으로 제한한다."""
    if maximum < minimum:
        return minimum
    return min(max(value, minimum), maximum)


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    """현재 Windows 가상 화면 rectangle을 반환한다."""
    try:
        import win32api
        import win32con

        left = int(win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN))
        top = int(win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN))
        width = int(win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN))
        height = int(win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN))
        return (left, top, left + width, top + height)
    except Exception:  # pragma: no cover - Windows GUI 환경 의존 보조
        return (0, 0, 1920, 1080)


def get_window_rectangle(hwnd: int) -> tuple[int, int, int, int]:
    """Win32 GetWindowRect로 창 rectangle을 읽는다."""
    try:
        import win32gui

        return tuple(int(value) for value in win32gui.GetWindowRect(hwnd))  # type: ignore[return-value]
    except Exception as exc:  # pragma: no cover - GUI 환경 의존 경로
        raise CursorValueError(f"Universal Viewer 창 rectangle 읽기 실패: hwnd={hwnd} ({exc})") from exc


def restore_window(hwnd: int) -> None:
    """Win32 ShowWindow(SW_RESTORE)로 최대화/최소화 상태를 해제한다."""
    try:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception as exc:  # pragma: no cover - GUI 환경 의존 경로
        raise CursorValueError(f"Universal Viewer 창 restore 실패: hwnd={hwnd} ({exc})") from exc


def format_rect_for_log(rectangle: tuple[int, int, int, int]) -> str:
    """left/top/width/height 형식의 로그 문자열을 만든다."""
    left, top, right, bottom = rectangle
    return f"left={left} top={top} width={right - left} height={bottom - top}"


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """Win32 MoveWindow로 특정 창만 이동한다."""
    try:
        import win32gui

        win32gui.MoveWindow(hwnd, x, y, width, height, True)
    except Exception as exc:  # pragma: no cover - GUI 환경 의존 경로
        raise CursorValueError(f"커서값 창 이동 실패: hwnd={hwnd}, target=({x}, {y}, {width}, {height}) ({exc})") from exc


def focus_window(hwnd: int) -> None:
    """Win32 SetForegroundWindow로 특정 창에 포커스를 준다."""
    try:
        import win32gui

        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:  # pragma: no cover - GUI 환경 의존 경로
        raise CursorValueError(f"Universal Viewer 창 포커스 실패: hwnd={hwnd} ({exc})") from exc


def move_mouse(point: tuple[int, int]) -> None:
    move_mouse_to(point, 0.05)


def move_mouse_to(point: tuple[int, int], duration: float) -> None:
    try:
        import pyautogui

        pyautogui.moveTo(point[0], point[1], duration=duration)
    except Exception as exc:  # pragma: no cover - GUI 의존 경로
        raise CursorValueError(f"커서값 창 마우스 이동 실패: point={point} ({exc})") from exc


def click_mouse(point: tuple[int, int]) -> None:
    try:
        import pyautogui

        pyautogui.click(x=point[0], y=point[1])
    except Exception as exc:  # pragma: no cover - GUI 의존 경로
        raise CursorValueError(f"커서값 창 클릭 실패: point={point} ({exc})") from exc


def mouse_down(button: str = "left") -> None:
    try:
        import pyautogui

        pyautogui.mouseDown(button=button)
    except Exception as exc:  # pragma: no cover - GUI 의존 경로
        raise CursorValueError(f"A cursor mouseDown 실패: button={button} ({exc})") from exc


def mouse_up(button: str = "left") -> None:
    try:
        import pyautogui

        pyautogui.mouseUp(button=button)
    except Exception as exc:  # pragma: no cover - GUI 의존 경로
        raise CursorValueError(f"B cursor mouseUp 실패: button={button} ({exc})") from exc


def send_hotkey(first_key: str, second_key: str) -> None:
    try:
        import pyautogui

        pyautogui.hotkey(first_key, second_key)
    except Exception as exc:  # pragma: no cover - GUI 의존 경로
        raise CursorValueError(f"커서값 창 hotkey 입력 실패: {first_key}+{second_key} ({exc})") from exc


def read_clipboard_text() -> str:
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return ""
            return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:  # pragma: no cover - Windows clipboard 의존 경로
        raise CursorValueError(f"clipboard text 읽기 실패: {exc}") from exc
