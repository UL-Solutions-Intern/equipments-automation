"""Universal Viewer에서 Microsoft Print to PDF로 출력하는 Stage 4 기능."""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Protocol

from result_folders import RESULTS_FOLDER_NAME

from .config import AppConfig
from .pdf_validator import PdfDependencyError, PdfValidationError, validate_pdf
from .viewer_launcher import ViewerOpenResult, open_prepared_raw_file


MICROSOFT_PRINT_TO_PDF = "Microsoft Print to PDF"
PRINT_DIALOG_TITLES = ("Print", "인쇄")
SAVE_DIALOG_TITLES = (
    "Save Print Output As",
    "인쇄 출력 저장",
    "다른 이름으로 저장",
    "다음 이름으로 프린터 출력 저장",
    "프린터 출력 저장",
    "Print Output",
)
OVERWRITE_CONFIRM_TITLES = ("Confirm Save As", "다른 이름으로 저장 확인", "저장 확인", "파일 바꾸기 확인")
OVERWRITE_CONFIRM_BUTTONS = ("예", "Yes", "확인", "OK")
PRINT_DIALOG_TIMEOUT_SECONDS = 15.0
SAVE_DIALOG_TIMEOUT_SECONDS = 20.0
PDF_CREATE_TIMEOUT_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 0.5
POST_SAVE_CLICK_WAIT_SECONDS = 3.0


class PdfPrintingError(RuntimeError):
    """PDF 인쇄 자동화 단계에서 실패했을 때 발생한다."""


class PrintProcessLike(Protocol):
    """테스트 가능한 인쇄 자동화 함수 인터페이스."""

    def __call__(self, opened: ViewerOpenResult, output_pdf_path: Path, logger: logging.Logger) -> None: ...


OpenRawFileFunction = Callable[..., ViewerOpenResult]
PdfValidationFunction = Callable[[Path, logging.Logger], int | None]
PdfArchiveCopyFunction = Callable[[Path], Path | None]
Win32DialogFinder = Callable[[tuple[str, ...], int | None], "Win32DialogInfo | None"]


@dataclass(frozen=True, slots=True)
class Win32DialogInfo:
    """win32gui fallback으로 찾은 top-level 대화상자 정보."""

    hwnd: int
    title: str
    class_name: str
    pid: int | None
    visible: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class Win32ChildControlInfo:
    """win32gui fallback으로 찾은 대화상자 child control 정보."""

    hwnd: int
    title: str
    class_name: str
    pid: int | None
    visible: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class PrintToPdfResult:
    """Stage 4 PDF 출력 결과."""

    opened: ViewerOpenResult
    output_pdf_path: Path
    pdf_size_bytes: int
    pdf_page_count: int | None
    validation_warning: str
    desktop_archive_pdf_path: Path | None = None
    desktop_archive_warning: str = ""


@dataclass(frozen=True, slots=True)
class SaveDialogActionResult:
    """PDF 저장 대화상자 입력/저장 클릭 결과."""

    dialog_hwnd: int | None
    edit_hwnd: int | None
    save_button_hwnd: int | None
    entered_text: str
    click_method: str


@dataclass(frozen=True, slots=True)
class FilenameEntryResult:
    """파일명 입력 검증 결과."""

    text: str
    verified: bool
    paste_attempted: bool


def print_raw_file_to_pdf(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    explicit_output_pdf: Path | None = None,
    open_raw_file_fn: OpenRawFileFunction = open_prepared_raw_file,
    print_automation_fn: PrintProcessLike | None = None,
    pdf_validation_fn: PdfValidationFunction | None = None,
    archive_copy_fn: PdfArchiveCopyFunction | None = None,
) -> PrintToPdfResult:
    """작업본을 Viewer로 연 뒤 Microsoft Print to PDF로 출력한다."""
    if explicit_output_pdf is not None:
        _assert_pdf_path_not_in_input(explicit_output_pdf, config.input_dir)

    logger.info("Stage 4 시작 | 원본=%s", source_path)
    opened = open_raw_file_fn(
        source_path,
        config,
        logger,
        explicit_viewer_exe=explicit_viewer_exe,
    )
    if not opened.hint_verified:
        raise PdfPrintingError(
            "작업본이 Universal Viewer에 열린 상태를 확인하지 못해 PDF 인쇄를 중단합니다. "
            f"작업본={opened.work_copy_path} | 수집 힌트={opened.raw_file_hints}"
        )

    output_pdf_path = resolve_output_pdf_path(
        config,
        opened.planned_pdf_path,
        explicit_output_pdf=explicit_output_pdf,
    )
    logger.info("PDF 출력 경로 확정 | %s", output_pdf_path)

    logger.info("Microsoft Print to PDF 인쇄 자동화 시작 | 작업본=%s", opened.work_copy_path)
    save_result: SaveDialogActionResult | None = None
    if print_automation_fn is None:
        save_result = automate_print_to_pdf(
            opened,
            output_pdf_path,
            logger,
            allow_overwrite_confirmation=explicit_output_pdf is not None,
        )
    else:
        print_automation_fn(opened, output_pdf_path, logger)

    wait_for_pdf_created(
        output_pdf_path,
        owner_pid=opened.main_window.pid,
        save_dialog_hwnd=save_result.dialog_hwnd if save_result is not None else None,
        filename_edit_hwnd=save_result.edit_hwnd if save_result is not None else None,
    )
    validator = pdf_validation_fn or validate_printed_pdf
    try:
        page_count = validator(output_pdf_path, logger)
        validation_warning = ""
    except PdfDependencyError as exc:
        page_count = None
        validation_warning = str(exc)
        logger.info("pypdf 선택 검증 생략: %s", exc)

    pdf_size = output_pdf_path.stat().st_size
    desktop_archive_pdf_path: Path | None = None
    desktop_archive_warning = ""
    try:
        archive_copy = archive_copy_fn or copy_pdf_to_desktop_archive
        desktop_archive_pdf_path = archive_copy(output_pdf_path)
        if desktop_archive_pdf_path is not None:
            logger.info(
                "PDF desktop archive copy completed | source=%s | destination=%s",
                output_pdf_path,
                desktop_archive_pdf_path,
            )
    except Exception as exc:
        desktop_archive_warning = f"PDF desktop archive copy failed: {exc}"
        logger.warning(
            "PDF desktop archive copy failed | source=%s | error=%s",
            output_pdf_path,
            exc,
        )
    logger.info(
        "PDF 출력 완료 | 파일=%s | 크기=%s바이트 | 페이지=%s",
        output_pdf_path,
        pdf_size,
        page_count if page_count is not None else "선택 검증 생략",
    )
    return PrintToPdfResult(
        opened,
        output_pdf_path,
        pdf_size,
        page_count,
        validation_warning,
        desktop_archive_pdf_path,
        desktop_archive_warning,
    )


def copy_pdf_to_desktop_archive(
    pdf_path: Path,
    now: datetime | None = None,
    desktop_dir: Path | None = None,
) -> Path:
    """검증된 PDF를 Desktop 날짜별 보관 폴더로 복사한다."""
    source = pdf_path.expanduser().resolve()
    if not source.is_file():
        raise PdfPrintingError(f"Desktop archive copy source PDF does not exist: {source}")

    archive_date = (now or datetime.now()).strftime("%Y-%m-%d")
    desktop = resolve_desktop_dir(desktop_dir)
    archive_dir = desktop / RESULTS_FOLDER_NAME / archive_date
    archive_dir.mkdir(parents=True, exist_ok=True)

    destination = archive_dir / source.name
    if destination.exists():
        if destination.stat().st_size == source.stat().st_size:
            return destination
        destination = next_available_archive_copy_path(destination)

    shutil.copy2(source, destination)
    return destination


def resolve_desktop_dir(desktop_dir: Path | None = None) -> Path:
    """Desktop 경로를 USERPROFILE 우선으로 해석한다."""
    if desktop_dir is not None:
        return desktop_dir.expanduser().resolve()
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return (Path(userprofile) / "Desktop").expanduser().resolve()
    return (Path.home() / "Desktop").expanduser().resolve()


def next_available_archive_copy_path(destination: Path) -> Path:
    """기존 보관 PDF와 크기가 다를 때 덮어쓰지 않는 _copyN 경로를 찾는다."""
    counter = 2
    while True:
        candidate = destination.with_name(f"{destination.stem}_copy{counter}{destination.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_output_pdf_path(
    config: AppConfig,
    planned_pdf_path: Path,
    *,
    explicit_output_pdf: Path | None = None,
) -> Path:
    """명시 또는 기본 PDF 출력 경로를 안전하게 확정한다."""
    if explicit_output_pdf is not None:
        resolved = explicit_output_pdf.expanduser().resolve()
        _assert_pdf_path_not_in_input(resolved, config.input_dir)
        _assert_pdf_suffix(resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    resolved = planned_pdf_path.expanduser().resolve()
    _assert_pdf_path_not_in_input(resolved, config.input_dir)
    _assert_pdf_suffix(resolved)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return make_unique_pdf_path(resolved)


def make_unique_pdf_path(path: Path) -> Path:
    """기본 PDF 경로가 이미 있으면 덮어쓰지 않도록 suffix를 붙인다."""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def wait_for_pdf_created(
    path: Path,
    *,
    timeout_seconds: float = PDF_CREATE_TIMEOUT_SECONDS,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    owner_pid: int | None = None,
    save_dialog_hwnd: int | None = None,
    filename_edit_hwnd: int | None = None,
) -> None:
    """PDF 파일이 생성되고 0바이트보다 커질 때까지 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if path.is_file() and path.stat().st_size > 0:
            return
        if time.monotonic() >= deadline:
            diagnostics = collect_pdf_wait_diagnostics(
                path,
                owner_pid=owner_pid,
                save_dialog_hwnd=save_dialog_hwnd,
                filename_edit_hwnd=filename_edit_hwnd,
            )
            raise PdfPrintingError(f"PDF 생성 대기 시간이 초과되었습니다: {path} | {diagnostics}")
        time.sleep(poll_interval_seconds)


def validate_printed_pdf(path: Path, logger: logging.Logger) -> int | None:
    """PDF 존재/크기 검증 후 pypdf가 있으면 페이지 수도 검증한다."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PdfPrintingError(f"PDF 파일이 생성되지 않았습니다: {resolved}")
    if resolved.stat().st_size <= 0:
        raise PdfPrintingError(f"PDF 파일 크기가 0바이트입니다: {resolved}")
    try:
        return validate_pdf(resolved)
    except PdfDependencyError:
        raise
    except PdfValidationError as exc:
        raise PdfPrintingError(str(exc)) from exc


def automate_print_to_pdf(
    opened: ViewerOpenResult,
    output_pdf_path: Path,
    logger: logging.Logger,
    *,
    allow_overwrite_confirmation: bool = False,
) -> SaveDialogActionResult:
    """pywinauto로 Ctrl+P, 프린터 선택, 저장 대화상자를 처리한다."""
    try:
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
    except ImportError as exc:
        raise PdfPrintingError("pywinauto가 설치되어 있어야 PDF 인쇄 자동화를 수행할 수 있습니다.") from exc

    logger.info("Universal Viewer 메인 창에 Ctrl+P 전송 | HWND=%s", opened.main_window.handle)
    if opened.main_window.handle is None:
        raise PdfPrintingError("Universal Viewer 메인 창 HWND를 확인하지 못해 Ctrl+P를 전송하지 않습니다.")
    try:
        Desktop(backend="win32").window(handle=opened.main_window.handle).set_focus()
    except Exception as exc:
        raise PdfPrintingError(f"Universal Viewer 메인 창에 포커스를 맞추지 못했습니다: {exc}") from exc
    send_keys("^p")
    desktop = Desktop(backend="uia")

    print_dialog = wait_for_dialog(
        desktop,
        PRINT_DIALOG_TITLES,
        timeout_seconds=PRINT_DIALOG_TIMEOUT_SECONDS,
        diagnostic_label="인쇄 대화상자",
        owner_pid=opened.main_window.pid,
        logger=logger,
    )
    select_or_verify_microsoft_print_to_pdf(print_dialog, logger)
    click_dialog_button(print_dialog, ("Print", "인쇄", "OK", "확인"), "인쇄 확인 버튼")

    save_dialog = wait_for_dialog(
        desktop,
        SAVE_DIALOG_TITLES,
        timeout_seconds=SAVE_DIALOG_TIMEOUT_SECONDS,
        diagnostic_label="PDF 저장 대화상자",
        owner_pid=opened.main_window.pid,
        logger=logger,
    )
    return enter_save_path_and_confirm(
        save_dialog,
        output_pdf_path,
        logger,
        owner_pid=opened.main_window.pid,
        allow_overwrite_confirmation=allow_overwrite_confirmation,
    )


def wait_for_dialog(
    desktop: object,
    title_candidates: Iterable[str],
    *,
    timeout_seconds: float,
    diagnostic_label: str,
    owner_pid: int | None = None,
    logger: logging.Logger | None = None,
    win32_dialog_finder: Win32DialogFinder | None = None,
) -> object:
    """제목 후보에 맞는 top-level 대화상자를 기다린다.

    pywinauto Desktop 탐지를 우선 사용하고, 실패하면 win32gui.EnumWindows
    fallback으로 Universal Viewer PID의 modal #32770 대화상자를 찾는다.
    """
    candidates = tuple(title_candidates)
    deadline = time.monotonic() + timeout_seconds
    last_titles: tuple[str, ...] = ()
    finder = win32_dialog_finder or find_win32_dialog_info
    while True:
        try:
            windows = tuple(desktop.windows())  # type: ignore[attr-defined]
            last_titles = tuple(_safe_text(window) for window in windows if _safe_text(window))
            for window in windows:
                title = _safe_text(window)
                if any(candidate.casefold() in title.casefold() for candidate in candidates):
                    return window
        except Exception as exc:
            last_titles = (f"대화상자 조사 오류: {exc}",)

        win32_dialog = finder(candidates, owner_pid)
        if win32_dialog is not None:
            if logger is not None:
                logger.info(
                    "win32gui 대화상자 탐지 | title=%s | class=%s | HWND=%s | PID=%s",
                    win32_dialog.title,
                    win32_dialog.class_name,
                    win32_dialog.hwnd,
                    win32_dialog.pid if win32_dialog.pid is not None else "확인 불가",
                )
            try:
                return desktop.window(handle=win32_dialog.hwnd)  # type: ignore[attr-defined]
            except Exception as exc:
                raise PdfPrintingError(
                    f"{diagnostic_label} win32gui 탐지 후 pywinauto 연결 실패: "
                    f"HWND={win32_dialog.hwnd}, title={win32_dialog.title}, class={win32_dialog.class_name}, "
                    f"pid={win32_dialog.pid} ({exc})"
                ) from exc

        if time.monotonic() >= deadline:
            raise PdfPrintingError(
                f"{diagnostic_label}를 찾지 못했습니다. 제목 후보={candidates}, 현재 top-level 창={last_titles}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def find_win32_dialog_info(
    title_candidates: tuple[str, ...],
    owner_pid: int | None,
    *,
    enum_windows_fn: Callable[[], Iterable[int]] | None = None,
    read_window_info_fn: Callable[[int], Win32DialogInfo] | None = None,
) -> Win32DialogInfo | None:
    """win32gui로 visible/enabled #32770 modal 대화상자를 찾는다."""
    matches: list[Win32DialogInfo] = []
    for hwnd in _enum_top_level_hwnds(enum_windows_fn):
        try:
            info = (read_window_info_fn or _read_win32_dialog_info)(hwnd)
        except Exception:
            continue
        if not _is_matching_win32_dialog(info, title_candidates, owner_pid):
            continue
        matches.append(info)
    if not matches:
        return None
    if owner_pid is not None:
        for info in matches:
            if info.pid == owner_pid:
                return info
    return matches[0]


def _enum_top_level_hwnds(enum_windows_fn: Callable[[], Iterable[int]] | None = None) -> tuple[int, ...]:
    if enum_windows_fn is not None:
        return tuple(enum_windows_fn())
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


def _read_win32_dialog_info(hwnd: int) -> Win32DialogInfo:
    import win32gui
    import win32process

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return Win32DialogInfo(
        hwnd=hwnd,
        title=str(win32gui.GetWindowText(hwnd)).strip(),
        class_name=str(win32gui.GetClassName(hwnd)).strip(),
        pid=int(pid) if pid is not None else None,
        visible=bool(win32gui.IsWindowVisible(hwnd)),
        enabled=bool(win32gui.IsWindowEnabled(hwnd)),
    )


def _enum_child_hwnds(
    parent_hwnd: int,
    enum_children_fn: Callable[[int], Iterable[int]] | None = None,
) -> tuple[int, ...]:
    if enum_children_fn is not None:
        return tuple(enum_children_fn(parent_hwnd))
    try:
        import win32gui
    except ImportError:
        return ()
    hwnds: list[int] = []

    def _callback(hwnd: int, _param: object) -> bool:
        hwnds.append(hwnd)
        return True

    win32gui.EnumChildWindows(parent_hwnd, _callback, None)
    return tuple(hwnds)


def _read_win32_child_control_info(hwnd: int) -> Win32ChildControlInfo:
    import win32gui
    import win32process

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return Win32ChildControlInfo(
        hwnd=hwnd,
        title=str(win32gui.GetWindowText(hwnd)).strip(),
        class_name=str(win32gui.GetClassName(hwnd)).strip(),
        pid=int(pid) if pid is not None else None,
        visible=bool(win32gui.IsWindowVisible(hwnd)),
        enabled=bool(win32gui.IsWindowEnabled(hwnd)),
    )


def _is_matching_win32_dialog(
    info: Win32DialogInfo,
    title_candidates: tuple[str, ...],
    owner_pid: int | None,
) -> bool:
    if not info.visible or not info.enabled:
        return False
    if info.class_name != "#32770":
        return False
    if owner_pid is not None and info.pid != owner_pid:
        return False
    title = info.title.casefold()
    return any(candidate.casefold() == title or candidate.casefold() in title for candidate in title_candidates)


def select_or_verify_microsoft_print_to_pdf(print_dialog: object, logger: logging.Logger) -> None:
    """인쇄 대화상자에서 Microsoft Print to PDF를 선택하거나 선택 상태를 확인한다."""
    if _select_printer_from_combo(print_dialog, MICROSOFT_PRINT_TO_PDF):
        logger.info("프린터 선택 완료 | %s", MICROSOFT_PRINT_TO_PDF)
        return
    if _dialog_contains_text(print_dialog, MICROSOFT_PRINT_TO_PDF):
        logger.info("프린터 표시 확인 | %s", MICROSOFT_PRINT_TO_PDF)
        return
    raise PdfPrintingError(
        f"{MICROSOFT_PRINT_TO_PDF} 프린터를 찾거나 선택하지 못했습니다. "
        "Windows 기능에서 Microsoft Print to PDF가 사용 가능한지 확인하십시오."
    )


def click_dialog_button(dialog: object, button_titles: Iterable[str], diagnostic_label: str) -> None:
    """대화상자에서 지정한 버튼을 클릭한다."""
    buttons = _safe_descendants(dialog, control_type="Button")
    for button in buttons:
        text = _safe_text(button)
        if any(_button_text_matches(text, candidate) for candidate in button_titles):
            try:
                button.click_input()  # type: ignore[attr-defined]
                return
            except Exception as exc:
                raise PdfPrintingError(f"{diagnostic_label} 클릭 실패: {exc}") from exc
    raise PdfPrintingError(f"{diagnostic_label}를 찾지 못했습니다. 후보={tuple(button_titles)}")


def enter_save_path_and_confirm(
    save_dialog: object,
    output_pdf_path: Path,
    logger: logging.Logger,
    *,
    owner_pid: int | None = None,
    allow_overwrite_confirmation: bool = False,
) -> SaveDialogActionResult:
    """PDF 저장 대화상자에 대상 경로를 입력하고 저장을 누른다."""
    absolute_pdf_path = output_pdf_path.expanduser().resolve()
    dialog_hwnd = _safe_handle(save_dialog)
    if dialog_hwnd is not None:
        edit = find_filename_edit_child_info(dialog_hwnd)
        if edit is not None:
            logger.info("PDF 저장 파일명 Edit 탐지 | HWND=%s", edit.hwnd)
            entry_result = enter_and_verify_filename(edit.hwnd, absolute_pdf_path, logger, dialog_hwnd=dialog_hwnd)
            entered_text = entry_result.text
            if entry_result.verified:
                logger.info("PDF 저장 경로 입력 확인 | HWND=%s | text=%s", edit.hwnd, entered_text)
            button = find_save_button_child_info(dialog_hwnd)
            if button is not None:
                logger.info("PDF 저장 버튼 탐지 | HWND=%s | title=%s", button.hwnd, button.title)
                if not entry_result.verified:
                    if not can_proceed_after_unreadable_filename(entry_result, dialog_hwnd, button):
                        raise PdfPrintingError(
                            f"PDF 저장 경로 입력 검증 실패: expected={absolute_pdf_path}, current={entered_text}"
                        )
                    logger.warning(
                        "PDF 저장 경로가 화면에 입력되었을 수 있으나 API로 읽을 수 없습니다. "
                        "clipboard paste 수행 및 저장 대화상자/버튼 활성 상태를 근거로 Save 클릭을 진행합니다. "
                        "expected=%s | current=%s | dialog_hwnd=%s | button_hwnd=%s",
                        absolute_pdf_path,
                        entered_text,
                        dialog_hwnd,
                        button.hwnd,
                    )
                click_method = click_save_button(button, save_dialog, logger)
                logger.info("PDF 저장 버튼 클릭 완료 | HWND=%s | method=%s", button.hwnd, click_method)
                handle_overwrite_confirmation(owner_pid, allow_overwrite_confirmation, logger)
                wait_for_save_dialog_to_close_or_pdf(dialog_hwnd, absolute_pdf_path, logger)
                return SaveDialogActionResult(dialog_hwnd, edit.hwnd, button.hwnd, entered_text, click_method)
            logger.info("win32 child에서 저장 버튼을 찾지 못해 pywinauto 버튼 탐지로 재시도합니다.")
        else:
            logger.info("win32 child에서 파일명 Edit를 찾지 못해 pywinauto Edit 탐지로 재시도합니다.")

    edits = _safe_descendants(save_dialog, control_type="Edit")
    if not edits:
        raise PdfPrintingError("PDF 저장 대화상자에서 파일명 입력란을 찾지 못했습니다.")
    try:
        edits[0].set_edit_text(str(absolute_pdf_path))  # type: ignore[attr-defined]
        current_text = _safe_text(edits[0])
        if not _filename_entry_matches(current_text, absolute_pdf_path):
            raise PdfPrintingError(
                f"PDF 저장 경로 입력 검증 실패: expected={absolute_pdf_path}, current={current_text}"
            )
    except Exception as exc:
        raise PdfPrintingError(f"PDF 저장 경로 입력 실패: {exc}") from exc
    logger.info("PDF 저장 경로 입력 확인 | %s", absolute_pdf_path)
    click_dialog_button(save_dialog, ("Save", "저장", "OK", "확인"), "PDF 저장 버튼")
    logger.info("PDF 저장 버튼 클릭 완료")
    handle_overwrite_confirmation(owner_pid, allow_overwrite_confirmation, logger)
    if dialog_hwnd is not None:
        wait_for_save_dialog_to_close_or_pdf(dialog_hwnd, absolute_pdf_path, logger)
    return SaveDialogActionResult(dialog_hwnd, None, None, str(absolute_pdf_path), "pywinauto_click_input")


def find_filename_edit_child_info(
    dialog_hwnd: int,
    *,
    enum_children_fn: Callable[[int], Iterable[int]] | None = None,
    read_child_info_fn: Callable[[int], Win32ChildControlInfo] | None = None,
) -> Win32ChildControlInfo | None:
    """PDF 저장 대화상자에서 visible/enabled 파일명 Edit 컨트롤을 찾는다."""
    for hwnd in _enum_child_hwnds(dialog_hwnd, enum_children_fn):
        try:
            info = (read_child_info_fn or _read_win32_child_control_info)(hwnd)
        except Exception:
            continue
        if info.visible and info.enabled and info.class_name.casefold() == "edit":
            return info
    return None


def find_save_button_child_info(
    dialog_hwnd: int,
    *,
    enum_children_fn: Callable[[int], Iterable[int]] | None = None,
    read_child_info_fn: Callable[[int], Win32ChildControlInfo] | None = None,
) -> Win32ChildControlInfo | None:
    """PDF 저장 대화상자에서 visible/enabled 저장 버튼을 찾는다."""
    for hwnd in _enum_child_hwnds(dialog_hwnd, enum_children_fn):
        try:
            info = (read_child_info_fn or _read_win32_child_control_info)(hwnd)
        except Exception:
            continue
        if not info.visible or not info.enabled:
            continue
        if info.class_name.casefold() != "button":
            continue
        if _is_save_button_title(info.title):
            return info
    return None


def enter_and_verify_filename(
    edit_hwnd: int,
    output_pdf_path: Path,
    logger: logging.Logger,
    *,
    dialog_hwnd: int | None = None,
    strict_verification: bool = False,
) -> FilenameEntryResult:
    """파일명 Edit에 절대 PDF 경로를 입력하고 실제 반영 여부를 검증한다."""
    expected = str(output_pdf_path.expanduser().resolve())
    logger.info("PDF 저장 경로 WM_SETTEXT 입력 시도 | HWND=%s | path=%s", edit_hwnd, expected)
    set_win32_edit_text(edit_hwnd, expected)
    current = get_win32_text(edit_hwnd)
    if _filename_entry_matches(current, output_pdf_path):
        logger.info("PDF 저장 경로 입력 검증 성공 | HWND=%s | current=%s", edit_hwnd, current)
        return FilenameEntryResult(current, True, False)

    logger.info("Edit WM_SETTEXT 검증 실패, 부모 ComboBox 입력 시도 | HWND=%s | current=%s", edit_hwnd, current)
    combo_hwnd = find_parent_combobox(edit_hwnd)
    if combo_hwnd is not None:
        set_win32_edit_text(combo_hwnd, expected)
        current = get_win32_text(edit_hwnd) or get_win32_text(combo_hwnd)
        if _filename_entry_matches(current, output_pdf_path):
            logger.info("PDF 저장 경로 입력 검증 성공 | ComboBox HWND=%s | current=%s", combo_hwnd, current)
            return FilenameEntryResult(current, True, False)

    logger.info("pywinauto set_edit_text fallback 시도 | HWND=%s | current=%s", edit_hwnd, current)
    try_pywinauto_set_edit_text(edit_hwnd, expected)
    current = get_win32_text(edit_hwnd)
    if _filename_entry_matches(current, output_pdf_path):
        logger.info("PDF 저장 경로 입력 검증 성공 | pywinauto | HWND=%s | current=%s", edit_hwnd, current)
        return FilenameEntryResult(current, True, False)

    logger.info(
        "WM_SETTEXT 입력 검증 실패, clipboard paste fallback 시도 | HWND=%s | expected=%s | current=%s",
        edit_hwnd,
        expected,
        current,
    )
    paste_text_with_clipboard(edit_hwnd, expected, dialog_hwnd=dialog_hwnd)
    current = get_win32_text(edit_hwnd)
    if _filename_entry_matches(current, output_pdf_path):
        logger.info("PDF 저장 경로 입력 검증 성공 | clipboard | HWND=%s | current=%s", edit_hwnd, current)
        return FilenameEntryResult(current, True, True)

    if strict_verification:
        raise PdfPrintingError(f"PDF 저장 경로 입력 검증 실패: expected={expected}, current={current}")
    logger.warning("PDF 저장 경로 입력값을 API로 검증하지 못했습니다. expected=%s | current=%s", expected, current)
    return FilenameEntryResult(current, False, True)


def set_win32_edit_text(hwnd: int, text: str) -> None:
    """win32 Edit/ComboBox 컨트롤에 포커스 없이 WM_SETTEXT로 텍스트를 입력한다."""
    try:
        import win32con
        import win32gui

        win32gui.SendMessage(hwnd, win32con.WM_SETTEXT, 0, text)
    except Exception as exc:
        raise PdfPrintingError(f"PDF 저장 경로 입력 실패: HWND={hwnd} ({exc})") from exc


def get_win32_text(hwnd: int) -> str:
    """win32 컨트롤 텍스트를 읽는다."""
    try:
        import win32gui

        return str(win32gui.GetWindowText(hwnd)).strip()
    except Exception as exc:
        raise PdfPrintingError(f"PDF 저장 경로 확인 실패: HWND={hwnd} ({exc})") from exc


def paste_text_with_clipboard(hwnd: int, text: str, *, dialog_hwnd: int | None = None) -> None:
    """클립보드 paste로 Edit 컨트롤에 텍스트를 입력한다."""
    try:
        import win32clipboard
        import win32con
        import win32gui
        if dialog_hwnd is not None:
            try:
                win32gui.SetForegroundWindow(dialog_hwnd)
            except Exception:
                pass
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        win32gui.SendMessage(hwnd, getattr(win32con, "EM_SETSEL", 0x00B1), 0, -1)
        win32gui.SendMessage(hwnd, getattr(win32con, "WM_PASTE", 0x0302), 0, 0)
    except Exception as exc:
        raise PdfPrintingError(f"clipboard paste 방식의 PDF 저장 경로 입력 실패: HWND={hwnd} ({exc})") from exc


def find_parent_combobox(edit_hwnd: int) -> int | None:
    """Edit의 부모가 ComboBox이면 해당 HWND를 반환한다."""
    try:
        import win32gui

        parent = int(win32gui.GetParent(edit_hwnd))
        if parent and str(win32gui.GetClassName(parent)).casefold() == "combobox":
            return parent
    except Exception:
        return None
    return None


def try_pywinauto_set_edit_text(edit_hwnd: int, text: str) -> None:
    """가능하면 pywinauto wrapper로 Edit 텍스트를 설정한다."""
    try:
        from pywinauto import Desktop

        wrapper = Desktop(backend="win32").window(handle=edit_hwnd)
        wrapper.set_edit_text(text)
    except Exception:
        return


def click_win32_button(hwnd: int) -> None:
    """win32 Button 컨트롤을 클릭한다."""
    try:
        import win32con
        import win32gui

        win32gui.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
    except Exception as exc:
        raise PdfPrintingError(f"PDF 저장 버튼 클릭 실패: HWND={hwnd} ({exc})") from exc


def click_save_button(button: Win32ChildControlInfo, save_dialog: object, logger: logging.Logger) -> str:
    """저장 버튼을 BM_CLICK 우선, 실패/무반응 시 pywinauto/좌표 클릭으로 누른다."""
    dialog_hwnd = _safe_handle(save_dialog)
    try:
        click_win32_button(button.hwnd)
        if dialog_hwnd is None or not is_window_visible_enabled(dialog_hwnd):
            logger.info("PDF 저장 버튼 클릭 방식: BM_CLICK")
            return "BM_CLICK"
        logger.info("BM_CLICK 후 저장 대화상자가 계속 표시되어 pywinauto click_input 재시도 | HWND=%s", button.hwnd)
    except PdfPrintingError as exc:
        logger.info("BM_CLICK 실패, pywinauto click_input 재시도 | HWND=%s | error=%s", button.hwnd, exc)
    try:
        from pywinauto import Desktop

        Desktop(backend="win32").window(handle=button.hwnd).click_input()
        if dialog_hwnd is None or not is_window_visible_enabled(dialog_hwnd):
            logger.info("PDF 저장 버튼 클릭 방식: pywinauto click_input")
            return "pywinauto_click_input"
        logger.info("pywinauto click_input 후 저장 대화상자가 계속 표시되어 좌표 클릭 재시도 | HWND=%s", button.hwnd)
    except Exception as exc:
        logger.info("pywinauto click_input 실패, 좌표 클릭 재시도 | HWND=%s | error=%s", button.hwnd, exc)
    try:
        import win32api
        import win32con
        import win32gui

        left, top, right, bottom = win32gui.GetWindowRect(button.hwnd)
        x = (left + right) // 2
        y = (top + bottom) // 2
        dialog_hwnd = _safe_handle(save_dialog)
        if dialog_hwnd is not None:
            try:
                win32gui.SetForegroundWindow(dialog_hwnd)
            except Exception:
                pass
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        logger.info("PDF 저장 버튼 클릭 방식: coordinate_click | x=%s | y=%s", x, y)
        return "coordinate_click"
    except Exception as exc:
        raise PdfPrintingError(f"PDF 저장 버튼 클릭 실패: HWND={button.hwnd} ({exc})") from exc


def can_proceed_after_unreadable_filename(
    entry_result: FilenameEntryResult,
    dialog_hwnd: int,
    button: Win32ChildControlInfo,
) -> bool:
    """입력값을 API로 읽을 수 없을 때 Save 클릭을 진행해도 되는지 판단한다."""
    return (
        entry_result.paste_attempted
        and is_window_visible_enabled(dialog_hwnd)
        and button.visible
        and button.enabled
    )


def handle_overwrite_confirmation(
    owner_pid: int | None,
    allow_overwrite_confirmation: bool,
    logger: logging.Logger,
) -> None:
    """명시 출력 경로일 때만 overwrite 확인 대화상자를 승인한다."""
    deadline = time.monotonic() + POST_SAVE_CLICK_WAIT_SECONDS
    while time.monotonic() < deadline:
        dialog = find_win32_dialog_info(OVERWRITE_CONFIRM_TITLES, owner_pid)
        if dialog is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        if not allow_overwrite_confirmation:
            raise PdfPrintingError(
                "덮어쓰기 확인 대화상자가 표시되었지만 기본 생성 경로에서는 덮어쓰기를 허용하지 않습니다. "
                f"dialog title={dialog.title}, HWND={dialog.hwnd}, PID={dialog.pid}"
            )
        logger.info(
            "덮어쓰기 확인 대화상자 탐지 | title=%s | class=%s | HWND=%s | PID=%s",
            dialog.title,
            dialog.class_name,
            dialog.hwnd,
            dialog.pid if dialog.pid is not None else "확인 불가",
        )
        button = find_confirmation_button_child_info(dialog.hwnd)
        if button is None:
            raise PdfPrintingError(f"덮어쓰기 확인 대화상자의 승인 버튼을 찾지 못했습니다: HWND={dialog.hwnd}")
        logger.info("덮어쓰기 확인 버튼 클릭 | HWND=%s | title=%s", button.hwnd, button.title)
        click_win32_button(button.hwnd)
        return


def find_confirmation_button_child_info(
    dialog_hwnd: int,
    *,
    enum_children_fn: Callable[[int], Iterable[int]] | None = None,
    read_child_info_fn: Callable[[int], Win32ChildControlInfo] | None = None,
) -> Win32ChildControlInfo | None:
    """덮어쓰기 확인 대화상자에서 승인 버튼을 찾는다."""
    for hwnd in _enum_child_hwnds(dialog_hwnd, enum_children_fn):
        try:
            info = (read_child_info_fn or _read_win32_child_control_info)(hwnd)
        except Exception:
            continue
        if not info.visible or not info.enabled or info.class_name.casefold() != "button":
            continue
        if any(_button_text_matches(info.title, candidate) for candidate in OVERWRITE_CONFIRM_BUTTONS):
            return info
    return None


def wait_for_save_dialog_to_close_or_pdf(
    save_dialog_hwnd: int,
    output_pdf_path: Path,
    logger: logging.Logger,
    *,
    timeout_seconds: float = POST_SAVE_CLICK_WAIT_SECONDS,
) -> None:
    """저장 클릭 후 짧게 대화상자 종료 또는 PDF 생성을 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if output_pdf_path.is_file() and output_pdf_path.stat().st_size > 0:
            logger.info("저장 버튼 클릭 후 PDF 파일 생성 확인 | %s", output_pdf_path)
            return
        if not is_window_visible_enabled(save_dialog_hwnd):
            logger.info("PDF 저장 대화상자 닫힘 확인 | HWND=%s", save_dialog_hwnd)
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    logger.info("저장 버튼 클릭 후 짧은 대기 내 PDF 생성/대화상자 종료를 확인하지 못했습니다.")


def is_window_visible_enabled(hwnd: int) -> bool:
    """창이 visible/enabled 상태인지 확인한다."""
    try:
        info = _read_win32_dialog_info(hwnd)
        return info.visible and info.enabled
    except Exception:
        return False


def collect_pdf_wait_diagnostics(
    expected_pdf_path: Path,
    *,
    owner_pid: int | None = None,
    save_dialog_hwnd: int | None = None,
    filename_edit_hwnd: int | None = None,
) -> str:
    """PDF 생성 대기 timeout 시점의 진단 정보를 만든다."""
    save_dialog_visible = _is_save_dialog_visible(owner_pid, save_dialog_hwnd)
    confirm_dialog = find_win32_dialog_info(OVERWRITE_CONFIRM_TITLES, owner_pid)
    visible_windows = describe_visible_top_level_windows(owner_pid=owner_pid)
    current_edit_text = get_win32_text_or_none(filename_edit_hwnd) if filename_edit_hwnd is not None else "확인 불가"
    return (
        f"expected_pdf_path={expected_pdf_path}; "
        f"save_dialog_visible={str(save_dialog_visible).lower()}; "
        f"current_edit_text={current_edit_text}; "
        f"confirm_or_error_dialog={format_win32_dialog(confirm_dialog)}; "
        f"visible_windows={visible_windows}"
    )


def get_win32_text_or_none(hwnd: int) -> str:
    try:
        return get_win32_text(hwnd)
    except Exception:
        return "확인 불가"


def describe_visible_top_level_windows(owner_pid: int | None = None) -> tuple[str, ...]:
    """현재 visible top-level 창 정보를 문자열로 수집한다."""
    windows: list[str] = []
    for hwnd in _enum_top_level_hwnds():
        try:
            info = _read_win32_dialog_info(hwnd)
        except Exception:
            continue
        if not info.visible:
            continue
        if owner_pid is not None and info.pid != owner_pid:
            continue
        windows.append(
            f"HWND={info.hwnd}|title={info.title}|class={info.class_name}|pid={info.pid}|enabled={int(info.enabled)}"
        )
    return tuple(windows)


def format_win32_dialog(dialog: Win32DialogInfo | None) -> str:
    if dialog is None:
        return "없음"
    return (
        f"HWND={dialog.hwnd}|title={dialog.title}|class={dialog.class_name}|"
        f"pid={dialog.pid}|visible={int(dialog.visible)}|enabled={int(dialog.enabled)}"
    )


def _is_save_dialog_visible(owner_pid: int | None, save_dialog_hwnd: int | None) -> bool:
    if save_dialog_hwnd is not None and is_window_visible_enabled(save_dialog_hwnd):
        return True
    return find_win32_dialog_info(SAVE_DIALOG_TITLES, owner_pid) is not None


def _select_printer_from_combo(dialog: object, printer_name: str) -> bool:
    for combo in _safe_descendants(dialog, control_type="ComboBox"):
        try:
            combo.select(printer_name)  # type: ignore[attr-defined]
            return True
        except Exception:
            pass
        try:
            combo.expand()  # type: ignore[attr-defined]
            for item in _safe_descendants(combo):
                if _safe_text(item).casefold() == printer_name.casefold():
                    item.click_input()  # type: ignore[attr-defined]
                    return True
        except Exception:
            pass
    return False


def _dialog_contains_text(dialog: object, text: str) -> bool:
    for child in _safe_descendants(dialog):
        if _safe_text(child).casefold() == text.casefold():
            return True
    return False


def _safe_descendants(dialog: object, **kwargs: object) -> tuple[object, ...]:
    try:
        return tuple(dialog.descendants(**kwargs))  # type: ignore[attr-defined]
    except Exception:
        return ()


def _safe_text(wrapper: object) -> str:
    try:
        return str(wrapper.window_text()).strip()  # type: ignore[attr-defined]
    except Exception:
        try:
            return str(getattr(getattr(wrapper, "element_info", None), "name", "")).strip()
        except Exception:
            return ""


def _button_text_matches(text: str, candidate: str) -> bool:
    normalized_text = _normalize_button_text(text)
    normalized_candidate = _normalize_button_text(candidate)
    return normalized_text == normalized_candidate or normalized_text.startswith(f"{normalized_candidate}(")


def _normalize_button_text(text: str) -> str:
    return text.strip().replace("&", "").casefold()


def _is_save_button_title(text: str) -> bool:
    normalized = _normalize_button_text(text)
    return normalized == "save" or normalized.startswith("save(") or normalized.startswith("저장")


def _filename_entry_matches(current_text: str, expected_path: Path) -> bool:
    normalized_current = current_text.casefold()
    expected_absolute = str(expected_path.expanduser().resolve()).casefold()
    expected_name = expected_path.name.casefold()
    return expected_absolute in normalized_current or expected_name in normalized_current


def _safe_handle(wrapper: object) -> int | None:
    for value in (
        getattr(wrapper, "handle", None),
        getattr(getattr(wrapper, "element_info", None), "handle", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _assert_pdf_path_not_in_input(path: Path, input_dir: Path) -> None:
    target = path.expanduser().resolve()
    input_root = input_dir.expanduser().resolve()
    try:
        target.relative_to(input_root)
    except ValueError:
        return
    raise PdfPrintingError(f"PDF 출력 경로는 input 폴더 내부일 수 없습니다: {target}")


def _assert_pdf_suffix(path: Path) -> None:
    if path.suffix.casefold() != ".pdf":
        raise PdfPrintingError(f"PDF 출력 경로는 .pdf 확장자여야 합니다: {path}")
