"""Universal Viewer 메인 창 UI를 클릭 없이 읽기 전용으로 조사한다."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol

from .config import ViewerProfile
from .viewer_discovery import WindowInfo, inspect_windows


PRIORITY_MENU_KEYWORDS = ("파일", "File", "표시", "View", "인쇄", "Print")
ALLOWED_MENU_PATH_ROOTS = ("파일", "File", "표시", "View")
RAW_FILE_PATTERN = re.compile(
    r"(?:[A-Za-z]:\\[^\n\r\t<>:\"|?*\[\]]+?\.(?:DAE|GEV)|[^\\/\n\r\[\]]+?\.(?:DAE|GEV))",
    re.IGNORECASE,
)


class UiWrapper(Protocol):
    """테스트 가능한 pywinauto 래퍼의 최소 인터페이스."""

    def window_text(self) -> str: ...

    def class_name(self) -> str: ...

    def control_id(self) -> int: ...

    def friendly_class_name(self) -> str: ...

    def is_visible(self) -> bool: ...

    def is_enabled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class UiElementInfo:
    """읽기 전용으로 수집한 컨트롤 정보."""

    depth: int
    title: str
    class_name: str
    control_id: int | None
    control_type: str
    visible: bool | None
    enabled: bool | None


@dataclass(frozen=True, slots=True)
class UiInspectionResult:
    """UI 조사 결과 파일과 주요 상태."""

    report_path: Path
    main_window_found: bool
    element_count: int
    raw_file_hints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeMenuItemInfo:
    """Windows native menu handle에서 읽은 메뉴 항목 정보."""

    path: str
    text: str
    command_id: int | None
    has_submenu: bool
    enabled: bool | None
    separator: bool
    depth: int


@dataclass(frozen=True, slots=True)
class ToolbarMenuItemInfo:
    """MFC/Afx 메뉴 바 Toolbar에서 읽은 항목 정보."""

    source: str
    text: str
    index: int
    command_id: int | None
    class_name: str
    control_id: int | None
    rectangle: str
    visible: bool | None
    enabled: bool | None
    separator: bool | None
    accessibility_name: str


@dataclass(frozen=True, slots=True)
class MenuPathInspectionResult:
    """상위 메뉴를 제한적으로 열어 조사한 결과."""

    report_path: Path
    main_window_found: bool
    opened_menu_count: int
    before_raw_file_hints: tuple[str, ...]
    after_raw_file_hints: tuple[str, ...]
    state_unchanged: bool


@dataclass(frozen=True, slots=True)
class MenuPathItemInfo:
    """열린 메뉴 또는 팝업에서 읽은 하위 메뉴 항목 정보."""

    root_menu: str
    path: str
    text: str
    index: int
    command_id: int | None
    source: str
    visible: bool | None
    enabled: bool | None
    rectangle: str
    class_name: str
    hwnd: int | None = None


@dataclass(frozen=True, slots=True)
class PopupWindowInfo:
    """메뉴 열기 전후 비교에 사용하는 top-level 창 정보."""

    pid: int | None
    hwnd: int | None
    class_name: str
    title: str
    visible: bool | None
    backend: str


@dataclass(frozen=True, slots=True)
class DesktopUiaElementInfo:
    """Desktop 전체에서 읽은 메뉴 관련 UIA 요소 정보."""

    name: str
    pid: int | None
    control_type: str
    class_name: str
    hwnd: int | None
    visible: bool | None
    enabled: bool | None
    rectangle: str


@dataclass(frozen=True, slots=True)
class MenuUiSnapshot:
    """상위 메뉴 클릭 전후의 popup/UIA 상태 스냅샷."""

    windows: tuple[PopupWindowInfo, ...]
    uia_elements: tuple[DesktopUiaElementInfo, ...]


@dataclass(frozen=True, slots=True)
class MenuOpeningProbeResult:
    """단일 클릭 후 UI 상태 변화로 검증한 메뉴 열기 결과."""

    click_attempted: bool
    opening_verified: bool
    new_windows: tuple[PopupWindowInfo, ...]
    new_uia_elements: tuple[DesktopUiaElementInfo, ...]
    items: tuple[MenuPathItemInfo, ...]


def inspect_viewer_ui(
    logger: logging.Logger,
    profile: ViewerProfile,
    logs_dir: Path,
    now: datetime | None = None,
) -> UiInspectionResult:
    """Universal Viewer 메인 창의 메뉴와 컨트롤을 읽기 전용으로 조사한다.

    Viewer 실행, 파일 열기, 클릭, 포커스 변경, 키보드 입력, PDF 생성은 수행하지 않는다.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    report_path = logs_dir / f"ui_inspection_{timestamp}.txt"

    lines: list[str] = [
        "Universal Viewer UI 읽기 전용 조사 결과",
        f"조사 시각: {(now or datetime.now()).isoformat(timespec='seconds')}",
        "주의: 이 조사는 클릭, 포커스 변경, 파일 열기, 키보드 입력, PDF 생성을 수행하지 않습니다.",
        "",
    ]

    try:
        window_inspection = inspect_windows(logger, profile)
        main_window = _select_main_window(window_inspection.automation_targets)
        if main_window is None:
            message = "Universal Viewer 메인 창을 찾지 못했습니다. GDI+ 보조 창은 조사 대상에서 제외했습니다."
            logger.warning(message)
            lines.append(message)
            _write_report(report_path, lines)
            return UiInspectionResult(report_path, False, 0, ())

        lines.extend(
            [
                "[메인 창]",
                f"title: {main_window.title}",
                f"PID: {main_window.pid if main_window.pid is not None else '확인 불가'}",
                f"HWND: {main_window.handle if main_window.handle is not None else '확인 불가'}",
                f"Window class: {main_window.window_class or '확인 불가'}",
                f"Backend: {main_window.backend}",
                f"main_window={str(main_window.main_window).lower()}",
                f"helper_window={str(main_window.helper_window).lower()}",
                "",
            ]
        )

        from pywinauto import Desktop

        desktop = Desktop(backend="win32")
        viewer_window = (
            desktop.window(handle=main_window.handle)
            if main_window.handle is not None
            else desktop.window(
                title=profile.main_window_title,
                class_name_re=rf"^{re.escape(profile.main_class_prefix)}.*",
            )
        )

        native_menu_result = inspect_native_menu(main_window.handle)
        if native_menu_result[0]:
            logger.info("Universal Viewer native menu 조사: %s", native_menu_result[0])
        native_menu_items = native_menu_result[1]
        native_priority_items = tuple(item for item in native_menu_items if is_priority_menu_text(item.path))
        pywinauto_menu_lines = _inspect_menus(viewer_window)
        elements = collect_ui_elements(viewer_window)
        toolbar_menu_items = inspect_menu_bar_toolbars(viewer_window)
        uia_menu_items = inspect_uia_menu_accessibility(main_window.handle)
        menu_bar_items = toolbar_menu_items + uia_menu_items
        toolbar_priority_items = tuple(
            item
            for item in menu_bar_items
            if is_priority_menu_text(item.text) or is_priority_menu_text(item.accessibility_name)
        )
        raw_file_hints = find_raw_file_hints(
            [main_window.title, main_window.window_class]
            + [element.title for element in elements]
            + [item.path for item in native_menu_items]
            + [item.text for item in menu_bar_items]
            + [item.accessibility_name for item in menu_bar_items]
            + pywinauto_menu_lines
        )

        lines.append("[우선 조사 메뉴]")
        if native_priority_items:
            lines.extend(format_native_menu_item(item) for item in native_priority_items)
        elif toolbar_priority_items:
            lines.extend(format_toolbar_menu_item(item) for item in toolbar_priority_items)
        elif pywinauto_menu_lines:
            lines.extend(pywinauto_menu_lines)
        else:
            lines.append("파일/표시/인쇄 관련 메뉴를 확인하지 못했습니다. 메뉴 구조를 추측하지 않습니다.")
        lines.append("")

        lines.append("[Native 메뉴 조사]")
        if native_menu_result[0]:
            lines.append(native_menu_result[0])
        if native_menu_items:
            lines.extend(format_native_menu_item(item) for item in native_menu_items)
        elif not native_menu_result[0]:
            lines.append("native menu not found")
        lines.append("")

        lines.append("[MFC/Afx 메뉴 바 Toolbar 조사]")
        if menu_bar_items:
            lines.append(f"menu bar/accessibility 항목 수: {len(menu_bar_items)}")
            lines.extend(format_toolbar_menu_item(item) for item in menu_bar_items)
        else:
            lines.append("메뉴 바 Toolbar 항목을 확인하지 못했습니다. 버튼 텍스트나 항목 구조를 추측하지 않습니다.")
        lines.append("")

        lines.append("[하위 컨트롤]")
        if elements:
            lines.extend(format_ui_element(element) for element in elements)
        else:
            lines.append("하위 컨트롤을 확인하지 못했습니다.")
        lines.append("")

        lines.append("[현재 열린 Raw Data 파일 힌트]")
        if raw_file_hints:
            lines.extend(f"- {hint}" for hint in raw_file_hints)
        else:
            lines.append("UI 텍스트에서 .DAE 또는 .GEV 파일명을 확인하지 못했습니다.")

        _write_report(report_path, lines)
        logger.info("Universal Viewer UI 조사 완료: %s", report_path)
        return UiInspectionResult(report_path, True, len(elements), raw_file_hints)
    except Exception as exc:
        logger.exception("Universal Viewer UI 조사 실패: %s", exc)
        lines.append(f"Universal Viewer UI 조사 실패: {exc}")
        _write_report(report_path, lines)
        return UiInspectionResult(report_path, False, 0, ())


def inspect_viewer_menu_paths(
    logger: logging.Logger,
    profile: ViewerProfile,
    logs_dir: Path,
    now: datetime | None = None,
) -> MenuPathInspectionResult:
    """허용된 상위 메뉴만 열어 하위 메뉴 경로를 조사하고 즉시 닫는다.

    이 기능은 파일 열기, 저장, 설정 변경, 인쇄, PDF 생성을 수행하지 않는다.
    하위 메뉴 항목은 클릭하거나 invoke하지 않는다.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    current_time = now or datetime.now()
    report_path = logs_dir / f"menu_path_inspection_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"
    lines: list[str] = [
        "Universal Viewer 메뉴 경로 제한 조사 결과",
        f"조사 시각: {current_time.isoformat(timespec='seconds')}",
        "주의: 이 조사는 파일(F), 표시(V) 상위 메뉴만 열고 하위 항목은 선택하지 않습니다.",
        "금지: 파일 열기, 저장, 설정 변경, 인쇄, PDF 생성, 하위 메뉴 invoke/click",
        "",
    ]

    try:
        window_inspection = inspect_windows(logger, profile)
        main_window = _select_main_window(window_inspection.automation_targets)
        if main_window is None:
            message = "Universal Viewer 메인 창을 찾지 못했습니다."
            logger.warning(message)
            lines.append(message)
            _write_report(report_path, lines)
            return MenuPathInspectionResult(report_path, False, 0, (), (), False)

        lines.extend(
            [
                "[메인 창]",
                f"title: {main_window.title}",
                f"PID: {main_window.pid if main_window.pid is not None else '확인 불가'}",
                f"HWND: {main_window.handle if main_window.handle is not None else '확인 불가'}",
                f"Window class: {main_window.window_class or '확인 불가'}",
                "허용 상위 메뉴: 파일(F), 표시(V)",
                "",
            ]
        )

        before_hints = _collect_current_raw_file_hints(main_window.handle)
        lines.append("[조사 전 열린 Raw Data 파일 힌트]")
        lines.extend(f"- {hint}" for hint in before_hints) if before_hints else lines.append("(확인되지 않음)")
        lines.append("")

        menu_roots = _find_allowed_uia_top_menu_wrappers(main_window.handle)
        lines.append("[허용 상위 메뉴 후보]")
        if menu_roots:
            for index, (text, wrapper) in enumerate(menu_roots):
                lines.append(f"- index={index} | text={text} | rectangle={_safe_rectangle_text(wrapper)}")
        else:
            lines.append("허용된 상위 메뉴 후보를 찾지 못했습니다.")
        lines.append("")

        opened_count = 0
        all_path_items: list[MenuPathItemInfo] = []
        for root_index, (root_text, wrapper) in enumerate(menu_roots):
            lines.append(f"[메뉴 열기 조사: {root_text}]")
            if not _is_allowed_menu_root(root_text):
                lines.append(f"건너뜀: 허용되지 않은 상위 메뉴입니다. text={root_text}")
                lines.append("")
                continue
            try:
                baseline_signatures = _collect_open_menu_signatures(main_window.handle)
                probe = _probe_menu_opening(
                    root_text,
                    wrapper,
                    main_window.pid,
                    main_window.handle,
                    baseline_signatures,
                )
                lines.append(f"상위 메뉴 단일 click 시도: {str(probe.click_attempted).lower()}")
                lines.append(
                    "메뉴 열기 UI 상태 검증: "
                    + ("verified" if probe.opening_verified else "menu opening not verified")
                )
                lines.append("[popup window delta]")
                if probe.new_windows:
                    lines.extend(format_popup_window_delta(item) for item in probe.new_windows)
                else:
                    lines.append("- 새 top-level popup window 없음")
                lines.append("[Desktop/UIA delta]")
                if probe.new_uia_elements:
                    lines.extend(format_desktop_uia_delta(item) for item in probe.new_uia_elements)
                else:
                    lines.append("- 새 Menu/MenuItem/Pane/Window 요소 없음")

                if probe.opening_verified:
                    opened_count += 1
                path_items = probe.items
                all_path_items.extend(path_items)
                if path_items:
                    for item in path_items:
                        lines.append(format_menu_path_item(item))
                else:
                    lines.append("열린 메뉴의 하위 항목을 확인하지 못했습니다. 위 delta를 실제 결과로 남깁니다.")
            except Exception as exc:
                logger.exception("%s 메뉴 경로 조사 실패: %s", root_text, exc)
                lines.append(f"메뉴 경로 조사 실패: {exc}")
            finally:
                time.sleep(0.2)
                lines.append("메뉴 닫기: 조사 함수에서 Esc 한 번 전송")
                lines.append("")

        priority_items = tuple(item for item in all_path_items if is_priority_menu_text(item.text) or is_priority_menu_text(item.path))
        lines.append("[파일 열기 / 표시 상세설정 / 인쇄 관련 후보]")
        if priority_items:
            lines.extend(format_menu_path_item(item) for item in priority_items)
        else:
            lines.append("관련 후보를 찾지 못했습니다.")
        lines.append("")

        after_hints = _collect_current_raw_file_hints(main_window.handle)
        state_unchanged = before_hints == after_hints
        lines.append("[조사 후 상태 확인]")
        lines.append(f"조사 후 열린 Raw Data 파일 힌트: {', '.join(after_hints) if after_hints else '(확인되지 않음)'}")
        lines.append(f"열린 파일 힌트 변경 없음: {str(state_unchanged).lower()}")
        lines.append("설정 변경, 파일 열기, 인쇄, PDF 생성 명령은 실행하지 않았습니다.")

        _write_report(report_path, lines)
        logger.info("Universal Viewer 메뉴 경로 조사 완료: %s", report_path)
        return MenuPathInspectionResult(report_path, True, opened_count, before_hints, after_hints, state_unchanged)
    except Exception as exc:
        logger.exception("Universal Viewer 메뉴 경로 조사 실패: %s", exc)
        lines.append(f"Universal Viewer 메뉴 경로 조사 실패: {exc}")
        _write_report(report_path, lines)
        return MenuPathInspectionResult(report_path, False, 0, (), (), False)


def collect_ui_elements(root: object) -> tuple[UiElementInfo, ...]:
    """pywinauto 창 래퍼에서 하위 컨트롤 정보를 안전하게 수집한다."""
    elements: list[UiElementInfo] = []
    wrappers = _safe_descendants(root)
    for wrapper in wrappers:
        elements.append(_to_ui_element(wrapper, depth=1))
    return tuple(elements)


def format_ui_element(element: UiElementInfo) -> str:
    """컨트롤 정보를 보고서 한 줄로 만든다."""
    indent = "  " * element.depth
    return (
        f"{indent}- title={element.title or '(없음)'} | "
        f"class={element.class_name or '확인 불가'} | "
        f"control_id={element.control_id if element.control_id is not None else '확인 불가'} | "
        f"control_type={element.control_type or '확인 불가'} | "
        f"visible={_format_bool(element.visible)} | enabled={_format_bool(element.enabled)}"
    )


def find_raw_file_hints(texts: Iterable[str]) -> tuple[str, ...]:
    """UI 텍스트에서 DAE/GEV 파일명으로 보이는 문자열을 중복 없이 찾는다."""
    hints: list[str] = []
    for text in texts:
        for match in RAW_FILE_PATTERN.findall(text):
            hint = _normalize_raw_file_hint(match)
            if hint and hint not in hints:
                hints.append(hint)
    return tuple(hints)


def is_priority_menu_text(text: str) -> bool:
    """파일, 표시, 인쇄 관련 메뉴인지 확인한다."""
    normalized = text.strip().replace("&", "")
    lowered = normalized.casefold()
    for keyword in PRIORITY_MENU_KEYWORDS:
        key = keyword.casefold()
        if lowered.startswith(key):
            return True
        if f"> {key}" in lowered or f"| text={key}" in lowered:
            return True
    return False


def inspect_native_menu(hwnd: int | None) -> tuple[str, tuple[NativeMenuItemInfo, ...]]:
    """Win32 native menu handle을 읽기 전용으로 조사한다.

    반환값의 첫 항목은 상태 메시지이며, 메뉴 핸들이 없거나 읽기 실패 시 실제 사유를 담는다.
    """
    if hwnd is None:
        return "native menu not found: hwnd를 확인할 수 없습니다.", ()
    try:
        import win32gui

        menu_handle = win32gui.GetMenu(hwnd)
        if not menu_handle:
            return "native menu not found", ()
        items = tuple(_enumerate_native_menu(menu_handle, parent_path="", depth=0))
        return f"native menu handle: {menu_handle}", items
    except Exception as exc:
        return f"native menu read error: {exc}", ()


def inspect_menu_bar_toolbars(root: object) -> tuple[ToolbarMenuItemInfo, ...]:
    """MFC/Afx 메뉴 바 Toolbar 후보의 버튼/항목 정보를 읽기 전용으로 조사한다."""
    items: list[ToolbarMenuItemInfo] = []
    for wrapper in _safe_descendants(root):
        element = _to_ui_element(wrapper, depth=1)
        if not is_menu_bar_toolbar_candidate(element):
            continue
        items.extend(_inspect_toolbar_wrapper(wrapper, element))
        if not items:
            items.append(
                ToolbarMenuItemInfo(
                    source="menu_bar_toolbar",
                    text=element.title,
                    index=-1,
                    command_id=None,
                    class_name=element.class_name,
                    control_id=element.control_id,
                    rectangle=_safe_rectangle_text(wrapper),
                    visible=element.visible,
                    enabled=element.enabled,
                    separator=None,
                    accessibility_name=_safe_accessibility_name(wrapper),
                )
            )
    return tuple(items)


def inspect_uia_menu_accessibility(hwnd: int | None) -> tuple[ToolbarMenuItemInfo, ...]:
    """UI Automation accessibility 트리에서 메뉴 관련 이름을 읽기 전용으로 보조 조사한다."""
    if hwnd is None:
        return ()
    try:
        from pywinauto import Desktop

        viewer_window = Desktop(backend="uia").window(handle=hwnd)
        descendants = tuple(viewer_window.descendants())
    except Exception:
        return ()

    items: list[ToolbarMenuItemInfo] = []
    for index, wrapper in enumerate(descendants):
        name = _first_non_empty(
            _safe_call(wrapper, "window_text", ""),
            _safe_accessibility_name(wrapper),
            getattr(getattr(wrapper, "element_info", None), "name", ""),
        )
        control_type = str(_safe_call(wrapper, "friendly_class_name", ""))
        class_name = str(_safe_call(wrapper, "class_name", ""))
        if not _is_uia_menu_related(str(name), control_type, class_name):
            continue
        items.append(
            ToolbarMenuItemInfo(
                source="uia_accessibility",
                text=str(name),
                index=index,
                command_id=None,
                class_name=class_name,
                control_id=None,
                rectangle=_safe_rectangle_text(wrapper),
                visible=_safe_bool_call(wrapper, "is_visible", None),
                enabled=_safe_bool_call(wrapper, "is_enabled", None),
                separator=None,
                accessibility_name=_safe_accessibility_name(wrapper) or str(name),
            )
        )
    return tuple(items)


def is_menu_bar_toolbar_candidate(element: UiElementInfo) -> bool:
    """Universal Viewer의 MFC/Afx 메뉴 바로 보이는 Toolbar 후보인지 확인한다."""
    title_match = element.title.strip() == "메뉴 모음"
    control_id_match = element.control_id == 59398
    class_match = element.class_name.startswith("Afx:ToolBar")
    return class_match and (title_match or control_id_match)


def _is_uia_menu_related(name: str, control_type: str, class_name: str) -> bool:
    """UIA 요소가 메뉴 조사에 관련 있어 보이는지 읽은 속성만으로 판단한다."""
    combined = f"{name} {control_type} {class_name}"
    if is_priority_menu_text(combined):
        return True
    menu_markers = ("메뉴", "Menu", "ToolBar", "Toolbar", "Afx:ToolBar")
    return any(marker.casefold() in combined.casefold() for marker in menu_markers)


def format_native_menu_item(item: NativeMenuItemInfo) -> str:
    """native 메뉴 항목 정보를 보고서 한 줄로 만든다."""
    indent = "  " * item.depth
    command_id = item.command_id if item.command_id is not None else "없음"
    enabled = "확인 불가" if item.enabled is None else str(item.enabled).lower()
    return (
        f"{indent}- path={item.path or '(제목 없음)'} | "
        f"text={item.text or '(제목 없음)'} | "
        f"command_id={command_id} | "
        f"submenu={str(item.has_submenu).lower()} | "
        f"enabled={enabled} | "
        f"separator={str(item.separator).lower()}"
    )


def format_toolbar_menu_item(item: ToolbarMenuItemInfo) -> str:
    """Toolbar 메뉴 후보 항목 정보를 보고서 한 줄로 만든다."""
    command_id = item.command_id if item.command_id is not None else "확인 불가"
    control_id = item.control_id if item.control_id is not None else "확인 불가"
    visible = _format_bool(item.visible)
    enabled = _format_bool(item.enabled)
    separator = "확인 불가" if item.separator is None else str(item.separator).lower()
    return (
        f"- source={item.source} | "
        f"text={item.text or '(확인 불가)'} | "
        f"index={item.index} | "
        f"command_id={command_id} | "
        f"class={item.class_name or '확인 불가'} | "
        f"control_id={control_id} | "
        f"rectangle={item.rectangle or '확인 불가'} | "
        f"visible={visible} | enabled={enabled} | "
        f"separator={separator} | "
        f"accessibility_name={item.accessibility_name or '(확인 불가)'}"
    )


def inspect_open_menu_items(
    root_menu: str,
    main_hwnd: int | None,
    exclude_signatures: set[tuple[str, str, str]] | None = None,
) -> tuple[MenuPathItemInfo, ...]:
    """현재 열린 팝업 메뉴와 UIA 트리에서 하위 메뉴 항목을 읽는다."""
    items: list[MenuPathItemInfo] = []
    items.extend(_inspect_open_uia_menu_items(root_menu, main_hwnd))
    items.extend(_inspect_open_win32_popup_menu_items(root_menu))
    if exclude_signatures:
        items = [item for item in items if _menu_path_signature(item) not in exclude_signatures]
    return _deduplicate_menu_path_items(items)


def format_menu_path_item(item: MenuPathItemInfo) -> str:
    """메뉴 경로 조사 항목을 보고서 한 줄로 만든다."""
    command_id = item.command_id if item.command_id is not None else "확인 불가"
    return (
        f"- path={item.path or '(확인 불가)'} | "
        f"text={item.text or '(확인 불가)'} | "
        f"index={item.index} | "
        f"command_id={command_id} | "
        f"source={item.source} | "
        f"visible={_format_bool(item.visible)} | "
        f"enabled={_format_bool(item.enabled)} | "
        f"rectangle={item.rectangle or '확인 불가'} | "
        f"class={item.class_name or '확인 불가'} | "
        f"HWND={item.hwnd if item.hwnd is not None else '확인 불가'}"
    )


def format_popup_window_delta(item: PopupWindowInfo) -> str:
    """새 top-level popup 창을 로그 한 줄로 만든다."""
    return (
        f"- PID={item.pid if item.pid is not None else '확인 불가'} | "
        f"HWND={item.hwnd if item.hwnd is not None else '확인 불가'} | "
        f"class={item.class_name or '확인 불가'} | "
        f"visible={_format_bool(item.visible)} | title/text={item.title or '(없음)'} | "
        f"backend={item.backend}"
    )


def format_desktop_uia_delta(item: DesktopUiaElementInfo) -> str:
    """새 Desktop/UIA 메뉴 관련 요소를 로그 한 줄로 만든다."""
    return (
        f"- PID={item.pid if item.pid is not None else '확인 불가'} | "
        f"ControlType={item.control_type or '확인 불가'} | "
        f"text={item.name or '(없음)'} | class={item.class_name or '확인 불가'} | "
        f"HWND={item.hwnd if item.hwnd is not None else '확인 불가'} | "
        f"visible={_format_bool(item.visible)} | enabled={_format_bool(item.enabled)} | "
        f"rectangle={item.rectangle or '확인 불가'}"
    )


def _select_main_window(windows: Iterable[WindowInfo]) -> WindowInfo | None:
    """win32 메인 창만 선택하고 GDI+ 보조 창은 제외한다."""
    for window in windows:
        if window.main_window and not window.helper_window and window.backend == "win32":
            return window
    return None


def _normalize_raw_file_hint(value: str) -> str:
    """UI 라벨이 붙은 문자열에서 실제 파일명 또는 경로 부분만 남긴다."""
    hint = value.strip()
    if len(hint) >= 3 and hint[1:3] == ":\\":
        return hint
    if ":" in hint:
        hint = hint.rsplit(":", 1)[-1].strip()
    return hint


def _inspect_menus(viewer_window: object) -> list[str]:
    """win32 메뉴 텍스트를 읽고 파일/표시/인쇄 관련 항목을 우선 기록한다."""
    menu_lines: list[str] = []
    try:
        menu_items = viewer_window.menu_items()  # type: ignore[attr-defined]
    except Exception:
        return menu_lines

    for item in menu_items:
        text = _safe_menu_text(item)
        if is_priority_menu_text(text):
            menu_lines.append(f"- {text}")
            for child in _safe_sub_items(item):
                child_text = _safe_menu_text(child)
                menu_lines.append(f"  - {child_text or '(제목 없음)'}")
    return menu_lines


def _inspect_toolbar_wrapper(wrapper: object, element: UiElementInfo) -> list[ToolbarMenuItemInfo]:
    """pywinauto Toolbar 래퍼에서 버튼 단위 정보를 안전하게 읽는다."""
    button_count = _safe_int_call(wrapper, "button_count")
    buttons = _safe_toolbar_buttons(wrapper, button_count)
    if not buttons and button_count <= 0:
        return []

    items: list[ToolbarMenuItemInfo] = []
    if buttons:
        for index, button in enumerate(buttons):
            items.append(_to_toolbar_item(button, element, index))
        return items

    for index in range(button_count):
        button = _safe_toolbar_button_at(wrapper, index)
        if button is None:
            items.append(
                ToolbarMenuItemInfo(
                    source="menu_bar_toolbar",
                    text="",
                    index=index,
                    command_id=None,
                    class_name=element.class_name,
                    control_id=element.control_id,
                    rectangle=_safe_rectangle_text(wrapper),
                    visible=element.visible,
                    enabled=element.enabled,
                    separator=None,
                    accessibility_name="",
                )
            )
        else:
            items.append(_to_toolbar_item(button, element, index))
    return items


def _collect_current_raw_file_hints(hwnd: int | None) -> tuple[str, ...]:
    """현재 UIA/win32 텍스트에서 열린 Raw Data 파일 힌트를 수집한다."""
    texts: list[str] = []
    if hwnd is None:
        return ()
    try:
        from pywinauto import Desktop

        win32_window = Desktop(backend="win32").window(handle=hwnd)
        texts.extend(element.title for element in collect_ui_elements(win32_window))
    except Exception:
        pass
    for item in inspect_uia_menu_accessibility(hwnd):
        texts.extend((item.text, item.accessibility_name))
    return find_raw_file_hints(texts)


def _find_allowed_uia_top_menu_wrappers(hwnd: int | None) -> tuple[tuple[str, object], ...]:
    """UIA accessibility 트리에서 파일/표시 상위 메뉴 래퍼만 찾는다."""
    if hwnd is None:
        return ()
    try:
        from pywinauto import Desktop

        descendants = tuple(Desktop(backend="uia").window(handle=hwnd).descendants())
    except Exception:
        return ()

    found: list[tuple[str, object]] = []
    seen: set[str] = set()
    for wrapper in descendants:
        text = str(
            _first_non_empty(
                _safe_call(wrapper, "window_text", ""),
                _safe_accessibility_name(wrapper),
                getattr(getattr(wrapper, "element_info", None), "name", ""),
            )
        ).strip()
        if not text or not _is_allowed_menu_root(text):
            continue
        if not _safe_bool_call(wrapper, "is_visible", None):
            continue
        if text in seen:
            continue
        seen.add(text)
        found.append((text, wrapper))
    return tuple(found)


def _is_allowed_menu_root(text: str) -> bool:
    """탐색이 허용된 상위 메뉴인지 확인한다."""
    normalized = text.strip().replace("&", "")
    return any(normalized.casefold().startswith(root.casefold()) for root in ALLOWED_MENU_PATH_ROOTS)


def _open_top_menu_only(wrapper: object) -> bool:
    """확보된 wrapper rectangle 중심을 이용해 상위 메뉴에 단일 click만 시도한다."""
    try:
        wrapper.click_input()  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def _open_top_menu_by_accelerator(root_text: str) -> bool:
    """허용된 상위 메뉴를 Alt 가속키로만 연다."""
    accelerator = _accelerator_key_for_root(root_text)
    if accelerator is None:
        return False
    try:
        from pywinauto.keyboard import send_keys

        send_keys(f"%{accelerator}")
        return True
    except Exception:
        return False


def _accelerator_key_for_root(root_text: str) -> str | None:
    """파일/표시 상위 메뉴에 대해서만 Alt 가속키를 반환한다."""
    normalized = root_text.strip().replace("&", "")
    if normalized.casefold().startswith("파일") or normalized.casefold().startswith("file"):
        return "F"
    if normalized.casefold().startswith("표시") or normalized.casefold().startswith("view"):
        return "V"
    return None


def _close_open_menu() -> None:
    """열린 메뉴를 Esc로 닫는다."""
    try:
        from pywinauto.keyboard import send_keys

        send_keys("{ESC}")
    except Exception:
        pass


def _probe_menu_opening(
    root_text: str,
    wrapper: object,
    main_pid: int | None,
    main_hwnd: int | None,
    baseline_signatures: set[tuple[str, str, str]],
    *,
    snapshot_fn: object | None = None,
    click_fn: object | None = None,
    close_fn: object | None = None,
    sleep_fn: object | None = None,
    inspect_items_fn: object | None = None,
) -> MenuOpeningProbeResult:
    """상위 메뉴를 한 번 클릭하고 전후 UI delta로 열림을 검증한 뒤 Esc로 닫는다.

    테스트용 콜백은 상위 메뉴 클릭·스냅샷·Esc만 대체한다. 하위 항목에 대한
    click/invoke/Enter 동작은 이 함수에 존재하지 않는다.
    """
    snapshot = snapshot_fn or _capture_menu_ui_snapshot
    click = click_fn or _open_top_menu_only
    close = close_fn or _close_open_menu
    sleeper = sleep_fn or time.sleep
    inspect_items = inspect_items_fn or inspect_open_menu_items
    before = snapshot(main_pid)  # type: ignore[operator]
    click_attempted = False
    try:
        click_attempted = bool(click(wrapper))  # type: ignore[operator]
        sleeper(0.5)  # type: ignore[operator]  # 300~700ms 범위의 안정화 대기
        after = snapshot(main_pid)  # type: ignore[operator]
        new_windows = _new_popup_windows(before, after)
        new_elements = _new_desktop_uia_elements(before, after, main_pid)
        opening_verified = bool(new_windows or new_elements)
        items: tuple[MenuPathItemInfo, ...] = ()
        if opening_verified:
            collected = list(inspect_items(root_text, main_hwnd, baseline_signatures))  # type: ignore[operator]
            collected.extend(_menu_items_from_uia_delta(root_text, new_elements))
            items = _deduplicate_menu_path_items(collected)
        return MenuOpeningProbeResult(
            click_attempted=click_attempted,
            opening_verified=opening_verified,
            new_windows=new_windows,
            new_uia_elements=new_elements,
            items=items,
        )
    finally:
        close()  # type: ignore[operator]


def _capture_menu_ui_snapshot(main_pid: int | None) -> MenuUiSnapshot:
    """Desktop 전체의 top-level 창과 메뉴 관련 UIA 요소를 읽기 전용 수집한다."""
    windows: list[PopupWindowInfo] = []
    uia_elements: list[DesktopUiaElementInfo] = []
    try:
        from pywinauto import Desktop

        for window in Desktop(backend="win32").windows():
            pid = _safe_process_id(window)
            class_name = str(_safe_call(window, "class_name", ""))
            if pid != main_pid and not _is_popup_class(class_name):
                continue
            windows.append(
                PopupWindowInfo(
                    pid=pid,
                    hwnd=_safe_handle(window),
                    class_name=class_name,
                    title=str(_safe_call(window, "window_text", "")),
                    visible=_safe_bool_call(window, "is_visible", None),
                    backend="win32",
                )
            )

        desktop_uia = Desktop(backend="uia")
        for top_window in desktop_uia.windows():
            wrappers = [top_window, *_safe_descendants(top_window)]
            for wrapper in wrappers:
                control_type = _safe_control_type(wrapper)
                if control_type.casefold() not in {"menu", "menuitem", "menu item", "pane", "window"}:
                    continue
                uia_elements.append(
                    DesktopUiaElementInfo(
                        name=str(_first_non_empty(_safe_call(wrapper, "window_text", ""), _safe_accessibility_name(wrapper))),
                        pid=_safe_process_id(wrapper),
                        control_type=control_type,
                        class_name=str(_safe_call(wrapper, "class_name", "")),
                        hwnd=_safe_handle(wrapper),
                        visible=_safe_bool_call(wrapper, "is_visible", None),
                        enabled=_safe_bool_call(wrapper, "is_enabled", None),
                        rectangle=_safe_rectangle_text(wrapper),
                    )
                )
    except Exception:
        pass
    return MenuUiSnapshot(tuple(windows), tuple(uia_elements))


def _new_popup_windows(before: MenuUiSnapshot, after: MenuUiSnapshot) -> tuple[PopupWindowInfo, ...]:
    before_keys = {_popup_window_signature(item) for item in before.windows}
    return tuple(item for item in after.windows if _popup_window_signature(item) not in before_keys)


def _new_desktop_uia_elements(
    before: MenuUiSnapshot, after: MenuUiSnapshot, main_pid: int | None
) -> tuple[DesktopUiaElementInfo, ...]:
    before_keys = {_desktop_uia_signature(item) for item in before.uia_elements}
    return tuple(
        item
        for item in after.uia_elements
        if _desktop_uia_signature(item) not in before_keys
        and (item.pid == main_pid or _is_popup_class(item.class_name))
    )


def _popup_window_signature(item: PopupWindowInfo) -> tuple[int | None, str, str]:
    return (item.hwnd, item.class_name, item.title)


def _desktop_uia_signature(item: DesktopUiaElementInfo) -> tuple[str, int | None, str, str, int | None, str]:
    return (item.name, item.pid, item.control_type, item.class_name, item.hwnd, item.rectangle)


def _is_popup_class(class_name: str) -> bool:
    normalized = class_name.casefold()
    return "#32768" in normalized or "popup" in normalized or "afx" in normalized


def _menu_items_from_uia_delta(
    root_text: str, elements: Iterable[DesktopUiaElementInfo]
) -> tuple[MenuPathItemInfo, ...]:
    items: list[MenuPathItemInfo] = []
    for index, element in enumerate(elements):
        if element.control_type.casefold() not in {"menuitem", "menu item"}:
            continue
        items.append(
            MenuPathItemInfo(
                root_menu=root_text,
                path=f"{root_text} > {element.name or f'(index {index})'}",
                text=element.name,
                index=index,
                command_id=None,
                source="desktop_uia_delta",
                visible=element.visible,
                enabled=element.enabled,
                rectangle=element.rectangle,
                class_name=element.class_name,
                hwnd=element.hwnd,
            )
        )
    return tuple(items)


def _inspect_open_uia_menu_items(root_menu: str, main_hwnd: int | None) -> list[MenuPathItemInfo]:
    """열린 메뉴 상태에서 UIA 트리와 팝업에서 하위 항목을 읽는다."""
    items: list[MenuPathItemInfo] = []
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        wrappers: list[object] = []
        if main_hwnd is not None:
            try:
                wrappers.extend(desktop.window(handle=main_hwnd).descendants())
            except Exception:
                pass
        try:
            for window in desktop.windows():
                title = str(_safe_call(window, "window_text", ""))
                class_name = str(_safe_call(window, "class_name", ""))
                if "menu" in title.casefold() or "menu" in class_name.casefold() or "#32768" in class_name:
                    wrappers.append(window)
                    wrappers.extend(_safe_descendants(window))
        except Exception:
            pass
        for index, wrapper in enumerate(wrappers):
            text = str(
                _first_non_empty(
                    _safe_call(wrapper, "window_text", ""),
                    _safe_accessibility_name(wrapper),
                    getattr(getattr(wrapper, "element_info", None), "name", ""),
                )
            ).strip()
            if not text or text == root_menu:
                continue
            class_name = str(_safe_call(wrapper, "class_name", ""))
            control_type = str(_safe_call(wrapper, "friendly_class_name", ""))
            if not _looks_like_open_menu_item(text, class_name, control_type):
                continue
            items.append(
                MenuPathItemInfo(
                    root_menu=root_menu,
                    path=f"{root_menu} > {text}",
                    text=text,
                    index=index,
                    command_id=None,
                    source="uia_open_menu",
                    visible=_safe_bool_call(wrapper, "is_visible", None),
                    enabled=_safe_bool_call(wrapper, "is_enabled", None),
                    rectangle=_safe_rectangle_text(wrapper),
                    class_name=class_name,
                )
            )
    except Exception:
        return items
    return items


def _inspect_open_win32_popup_menu_items(root_menu: str) -> list[MenuPathItemInfo]:
    """열린 #32768 팝업 메뉴 창에서 가능한 win32 정보를 읽는다."""
    items: list[MenuPathItemInfo] = []
    try:
        from pywinauto import Desktop

        popup_windows = [
            window
            for window in Desktop(backend="win32").windows()
            if str(_safe_call(window, "class_name", "")) == "#32768"
        ]
    except Exception:
        return items
    for popup in popup_windows:
        children = _safe_descendants(popup)
        if not children:
            text = str(_safe_call(popup, "window_text", "")).strip()
            items.append(
                MenuPathItemInfo(
                    root_menu=root_menu,
                    path=f"{root_menu} > {text or '(popup menu)'}",
                    text=text,
                    index=0,
                    command_id=None,
                    source="win32_popup_menu",
                    visible=_safe_bool_call(popup, "is_visible", None),
                    enabled=_safe_bool_call(popup, "is_enabled", None),
                    rectangle=_safe_rectangle_text(popup),
                    class_name=str(_safe_call(popup, "class_name", "")),
                )
            )
            continue
        for index, child in enumerate(children):
            text = str(_first_non_empty(_safe_call(child, "window_text", ""), _safe_accessibility_name(child))).strip()
            items.append(
                MenuPathItemInfo(
                    root_menu=root_menu,
                    path=f"{root_menu} > {text or f'(index {index})'}",
                    text=text,
                    index=index,
                    command_id=_safe_command_id(child),
                    source="win32_popup_menu",
                    visible=_safe_bool_call(child, "is_visible", None),
                    enabled=_safe_bool_call(child, "is_enabled", None),
                    rectangle=_safe_rectangle_text(child),
                    class_name=str(_safe_call(child, "class_name", "")),
                )
            )
    return items


def _collect_open_menu_signatures(main_hwnd: int | None) -> set[tuple[str, str, str]]:
    """메뉴를 열기 전 이미 보이는 후보의 signature를 수집한다."""
    baseline: list[MenuPathItemInfo] = []
    baseline.extend(_inspect_open_uia_menu_items("__baseline__", main_hwnd))
    baseline.extend(_inspect_open_win32_popup_menu_items("__baseline__"))
    return {_menu_path_signature(item) for item in baseline}


def _menu_path_signature(item: MenuPathItemInfo) -> tuple[str, str, str]:
    return (item.text, item.rectangle, item.source)


def _looks_like_open_menu_item(text: str, class_name: str, control_type: str) -> bool:
    """열린 메뉴 항목으로 볼 만한 UIA 요소인지 확인한다."""
    combined = f"{text} {class_name} {control_type}".casefold()
    if any(marker in combined for marker in ("menuitem", "menu item", "#32768", "popup")):
        return True
    if text and not text.startswith("Universal Viewer"):
        return True
    return False


def _deduplicate_menu_path_items(items: Iterable[MenuPathItemInfo]) -> tuple[MenuPathItemInfo, ...]:
    """동일한 메뉴 텍스트/위치를 중복 기록하지 않는다."""
    deduped: list[MenuPathItemInfo] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        key = (item.root_menu, item.text, item.rectangle, item.source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped)


def _to_toolbar_item(button: object, parent: UiElementInfo, index: int) -> ToolbarMenuItemInfo:
    """Toolbar 버튼 객체를 보고서용 데이터로 변환한다."""
    text = _first_non_empty(
        _safe_call(button, "window_text", ""),
        _safe_call(button, "text", ""),
        _safe_call(button, "friendly_class_name", ""),
    )
    accessibility_name = _safe_accessibility_name(button)
    command_id = _safe_command_id(button)
    return ToolbarMenuItemInfo(
        source="menu_bar_toolbar",
        text=str(text),
        index=index,
        command_id=command_id,
        class_name=str(_safe_call(button, "class_name", parent.class_name) or parent.class_name),
        control_id=parent.control_id,
        rectangle=_safe_rectangle_text(button),
        visible=_safe_bool_call(button, "is_visible", parent.visible),
        enabled=_safe_bool_call(button, "is_enabled", parent.enabled),
        separator=_safe_separator(button),
        accessibility_name=accessibility_name,
    )


def _safe_toolbar_buttons(wrapper: object, button_count: int) -> tuple[object, ...]:
    for method_name in ("buttons",):
        try:
            method = getattr(wrapper, method_name)
            buttons = tuple(method())
            if buttons:
                return buttons
        except Exception:
            continue
    buttons: list[object] = []
    for index in range(max(button_count, 0)):
        button = _safe_toolbar_button_at(wrapper, index)
        if button is not None:
            buttons.append(button)
    return tuple(buttons)


def _safe_toolbar_button_at(wrapper: object, index: int) -> object | None:
    for method_name in ("button", "get_button"):
        try:
            method = getattr(wrapper, method_name)
            return method(index)
        except Exception:
            continue
    return None


def _enumerate_native_menu(menu_handle: int, parent_path: str, depth: int) -> Iterable[NativeMenuItemInfo]:
    """GetMenu 계열 API로 메뉴 항목을 재귀적으로 열거한다."""
    import win32con
    import win32gui

    count = win32gui.GetMenuItemCount(menu_handle)
    if count < 0:
        return
    for index in range(count):
        text = _read_native_menu_text(menu_handle, index)
        submenu_handle = win32gui.GetSubMenu(menu_handle, index)
        state = win32gui.GetMenuState(menu_handle, index, win32con.MF_BYPOSITION)
        separator = bool(state & win32con.MF_SEPARATOR)
        disabled = bool(state & win32con.MF_DISABLED or state & win32con.MF_GRAYED)
        enabled = None if separator else not disabled
        command_id = None
        if not submenu_handle and not separator:
            raw_command_id = win32gui.GetMenuItemID(menu_handle, index)
            command_id = None if raw_command_id in (-1, 0xFFFFFFFF) else int(raw_command_id)
        label = text or "(separator)" if separator else text or f"(index {index})"
        path = f"{parent_path} > {label}" if parent_path else label
        item = NativeMenuItemInfo(
            path=path,
            text=text,
            command_id=command_id,
            has_submenu=bool(submenu_handle),
            enabled=enabled,
            separator=separator,
            depth=depth,
        )
        yield item
        if submenu_handle:
            yield from _enumerate_native_menu(submenu_handle, path, depth + 1)


def _read_native_menu_text(menu_handle: int, index: int) -> str:
    """메뉴 텍스트를 위치 기준으로 안전하게 읽는다."""
    import win32con
    import win32gui

    try:
        return win32gui.GetMenuString(menu_handle, index, win32con.MF_BYPOSITION).strip()
    except Exception:
        return ""


def _safe_descendants(root: object) -> tuple[object, ...]:
    try:
        return tuple(root.descendants())  # type: ignore[attr-defined]
    except Exception:
        return ()


def _to_ui_element(wrapper: object, depth: int) -> UiElementInfo:
    return UiElementInfo(
        depth=depth,
        title=_safe_call(wrapper, "window_text", ""),
        class_name=_safe_call(wrapper, "class_name", ""),
        control_id=_safe_call(wrapper, "control_id", None),
        control_type=_safe_call(wrapper, "friendly_class_name", ""),
        visible=_safe_call(wrapper, "is_visible", None),
        enabled=_safe_call(wrapper, "is_enabled", None),
    )


def _safe_menu_text(item: object) -> str:
    for method_name in ("text", "window_text"):
        value = _safe_call(item, method_name, "")
        if value:
            return str(value)
    return str(item)


def _safe_sub_items(item: object) -> tuple[object, ...]:
    for method_name in ("sub_items", "items"):
        try:
            method = getattr(item, method_name)
            return tuple(method())
        except Exception:
            continue
    return ()


def _safe_call(obj: object, method_name: str, default: object) -> object:
    try:
        method = getattr(obj, method_name)
        return method()
    except Exception:
        return default


def _safe_int_call(obj: object, method_name: str) -> int:
    value = _safe_call(obj, method_name, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_bool_call(obj: object, method_name: str, default: bool | None) -> bool | None:
    value = _safe_call(obj, method_name, default)
    if value is None:
        return None
    return bool(value)


def _safe_command_id(button: object) -> int | None:
    for method_name in ("command_id", "id"):
        value = _safe_call(button, method_name, None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_handle(obj: object) -> int | None:
    """wrapper 또는 element_info에서 HWND를 안전하게 읽는다."""
    for value in (
        getattr(obj, "handle", None),
        getattr(getattr(obj, "element_info", None), "handle", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_process_id(obj: object) -> int | None:
    """wrapper의 process ID를 읽기 전용으로 안전하게 읽는다."""
    for value in (
        _safe_call(obj, "process_id", None),
        getattr(getattr(obj, "element_info", None), "process_id", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_control_type(obj: object) -> str:
    """UIA ControlType을 friendly name과 element_info에서 읽는다."""
    return str(
        _first_non_empty(
            _safe_call(obj, "friendly_class_name", ""),
            getattr(getattr(obj, "element_info", None), "control_type", ""),
        )
    )


def _safe_separator(button: object) -> bool | None:
    for method_name in ("is_separator", "separator"):
        value = _safe_call(button, method_name, None)
        if value is not None:
            return bool(value)
    return None


def _safe_rectangle_text(obj: object) -> str:
    rectangle = _safe_call(obj, "rectangle", None)
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


def _safe_accessibility_name(obj: object) -> str:
    for method_name in ("legacy_properties", "get_properties"):
        properties = _safe_call(obj, method_name, None)
        if isinstance(properties, dict):
            for key in ("Name", "name", "AccessibleName", "accessible_name"):
                value = properties.get(key)
                if value:
                    return str(value)
    for method_name in ("element_info",):
        element_info = getattr(obj, method_name, None)
        name = getattr(element_info, "name", None)
        if name:
            return str(name)
    return ""


def _first_non_empty(*values: object) -> object:
    for value in values:
        if value:
            return value
    return ""


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "확인 불가"
    return str(value).lower()


def _write_report(report_path: Path, lines: Iterable[str]) -> None:
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
