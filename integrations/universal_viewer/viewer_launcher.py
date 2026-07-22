"""Universal Viewer 실행 파일 탐색 및 작업본 열기(Stage 3)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from .config import AppConfig, ViewerProfile
from .models import ProcessingStatus
from .ui_inspection import find_raw_file_hints
from .viewer_discovery import WindowInfo, WindowInspection, inspect_windows
from .workflow import Workflow


class ViewerLaunchError(RuntimeError):
    """Universal Viewer 실행 또는 연결에 실패했을 때 발생한다."""


class PopenLike(Protocol):
    """테스트 가능한 subprocess.Popen 최소 인터페이스."""

    pid: int


PopenFactory = Callable[[Sequence[str]], PopenLike]
WhichFunction = Callable[[str], str | None]
InspectWindowsFunction = Callable[[logging.Logger, ViewerProfile], WindowInspection]
HintCollector = Callable[[int | None], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ViewerOpenResult:
    """작업본을 Universal Viewer로 연 결과."""

    source_path: Path
    work_copy_path: Path
    viewer_exe_path: Path
    planned_pdf_path: Path
    process_id: int | None
    main_window: WindowInfo
    raw_file_hints: tuple[str, ...]
    hint_verified: bool
    matched_raw_file_hints: tuple[str, ...]
    warning_message: str


def discover_viewer_executable(
    explicit_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    program_files_roots: Iterable[Path] | None = None,
    which: WhichFunction = shutil.which,
) -> Path:
    """Universal Viewer 실행 파일을 우선순위에 따라 찾는다.

    우선순위:
    1. 명령행 --viewer-exe
    2. UNIVERSAL_VIEWER_EXE 환경 변수
    3. Program Files / Program Files (x86) 하위 UnivViewer.exe 검색
    4. PATH의 UnivViewer.exe
    """
    environment = environ if environ is not None else os.environ

    if explicit_path is not None:
        return _validate_executable_path(explicit_path, "--viewer-exe")

    env_value = environment.get("UNIVERSAL_VIEWER_EXE", "").strip().strip('"')
    if env_value:
        return _validate_executable_path(Path(env_value), "UNIVERSAL_VIEWER_EXE")

    for found in _iter_program_files_candidates(
        program_files_roots if program_files_roots is not None else _default_program_files_roots(environment)
    ):
        return found

    path_result = which("UnivViewer.exe")
    if path_result:
        return _validate_executable_path(Path(path_result), "PATH")

    raise ViewerLaunchError(
        "Universal Viewer 실행 파일(UnivViewer.exe)을 찾지 못했습니다. "
        "--viewer-exe \"C:\\path\\to\\UnivViewer.exe\"로 지정하거나 "
        "UNIVERSAL_VIEWER_EXE 환경 변수를 설정하십시오."
    )


def launch_viewer_with_file(
    viewer_exe_path: Path,
    work_copy_path: Path,
    *,
    popen_factory: PopenFactory | None = None,
) -> PopenLike:
    """Universal Viewer에 작업 복사본 경로를 인자로 전달해 실행한다."""
    executable = _validate_executable_path(viewer_exe_path, "Universal Viewer 실행 파일")
    raw_copy = work_copy_path.expanduser().resolve()
    if not raw_copy.exists() or not raw_copy.is_file():
        raise ViewerLaunchError(f"열 작업 복사본이 없습니다: {raw_copy}")

    command = [str(executable), str(raw_copy)]
    popen = popen_factory or subprocess.Popen
    try:
        return popen(command)
    except OSError as exc:
        raise ViewerLaunchError(f"Universal Viewer 실행 실패: {exc}") from exc


def open_prepared_raw_file(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    discover_executable_fn: Callable[[Path | None], Path] | None = None,
    launch_fn: Callable[[Path, Path], PopenLike] | None = None,
    wait_for_window_fn: Callable[[logging.Logger, ViewerProfile, int | None], WindowInfo | None] | None = None,
    hint_collector: HintCollector | None = None,
) -> ViewerOpenResult:
    """원본을 작업본으로 준비한 뒤 Universal Viewer로 작업본만 연다."""
    workflow = Workflow(
        config,
        logger,
        dry_run=False,
        success_message="작업 복사본 생성 및 파일 크기·SHA256 검증 완료. Universal Viewer로 작업본 열기를 진행합니다.",
    )
    preparation = workflow.process(source_path)
    if preparation.status is not ProcessingStatus.SUCCESS or preparation.working_path is None:
        detail = preparation.error_message or str(preparation.status)
        raise ViewerLaunchError(f"작업 복사본 준비 실패: {detail}")

    discover = discover_executable_fn or (lambda explicit: discover_viewer_executable(explicit))
    launcher = launch_fn or launch_viewer_with_file
    wait_for_window = wait_for_window_fn or wait_for_viewer_main_window
    collect_hints = hint_collector or collect_opened_raw_file_hints

    viewer_exe_path = discover(explicit_viewer_exe)
    process = launcher(viewer_exe_path, preparation.working_path)
    process_id = getattr(process, "pid", None)
    logger.info(
        "Universal Viewer 실행 | exe=%s | 작업본=%s | PID=%s",
        viewer_exe_path,
        preparation.working_path,
        process_id if process_id is not None else "확인 불가",
    )

    main_window = wait_for_window(logger, config.universal_viewer, process_id)
    if main_window is None:
        raise ViewerLaunchError(
            "Universal Viewer 메인 창을 찾지 못했습니다. "
            "Viewer가 정상 실행되었는지, title=Universal Viewer 및 class=Universal_Viewer 계열 창이 있는지 확인하십시오."
        )

    if process_id is not None and main_window.pid is not None and process_id != main_window.pid:
        logger.info(
            "Universal Viewer 실행 프로세스 PID와 탐지된 메인 창 PID가 다릅니다. "
            "기존 Viewer 인스턴스에 파일이 열린 경우 정상일 수 있습니다. | 실행PID=%s | 메인창PID=%s",
            process_id,
            main_window.pid,
        )

    raw_file_hints = wait_for_opened_raw_hint(main_window.handle, preparation.working_path, collect_hints)
    matched_hints = matching_work_copy_hints(raw_file_hints, preparation.working_path)
    hint_verified = bool(matched_hints)
    warning_message = ""
    if not hint_verified:
        warning_message = (
            f"Universal Viewer UI에서 작업본 파일명({preparation.working_path.name})을 확인하지 못했습니다. "
            "파일 열기 상태를 수동으로 확인하십시오. 인쇄 또는 설정 변경은 수행하지 않았습니다."
        )
        logger.warning("%s | 수집 힌트=%s", warning_message, raw_file_hints)
    else:
        logger.info(
            "Universal Viewer 작업본 열림 확인 | 작업본=%s | 일치 힌트=%s | 전체 힌트=%s",
            preparation.working_path,
            matched_hints,
            raw_file_hints,
        )

    return ViewerOpenResult(
        source_path=preparation.source_path,
        work_copy_path=preparation.working_path,
        viewer_exe_path=viewer_exe_path,
        planned_pdf_path=preparation.planned_pdf_path,
        process_id=process_id,
        main_window=main_window,
        raw_file_hints=raw_file_hints,
        hint_verified=hint_verified,
        matched_raw_file_hints=matched_hints,
        warning_message=warning_message,
    )


def wait_for_viewer_main_window(
    logger: logging.Logger,
    profile: ViewerProfile,
    preferred_pid: int | None = None,
    *,
    timeout_seconds: float = 15.0,
    poll_interval_seconds: float = 0.5,
    inspect_windows_fn: InspectWindowsFunction = inspect_windows,
) -> WindowInfo | None:
    """Universal Viewer 메인 창을 일정 시간 동안 읽기 전용으로 찾는다."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            inspection = inspect_windows_fn(logger, profile)
            selected = select_viewer_main_window(inspection, preferred_pid)
            if selected is not None:
                return selected
        except Exception as exc:
            last_error = exc
            logger.warning("Universal Viewer 창 연결 재시도: %s", exc)

        if time.monotonic() >= deadline:
            if last_error is not None:
                logger.warning("Universal Viewer 창 탐지 제한 시간 초과 | 마지막 오류=%s", last_error)
            return None
        time.sleep(poll_interval_seconds)


def select_viewer_main_window(inspection: WindowInspection, preferred_pid: int | None = None) -> WindowInfo | None:
    """탐지 결과에서 메인 창을 선택하되 가능하면 실행한 프로세스 PID를 우선한다."""
    targets = inspection.automation_targets
    if preferred_pid is not None:
        for window in targets:
            if window.pid == preferred_pid:
                return window
    return targets[0] if targets else None


def wait_for_opened_raw_hint(
    hwnd: int | None,
    work_copy_path: Path,
    hint_collector: HintCollector | None = None,
    *,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.5,
) -> tuple[str, ...]:
    """UI 텍스트에서 작업본 파일명 힌트가 보일 때까지 짧게 기다린다."""
    deadline = time.monotonic() + timeout_seconds
    latest_hints: tuple[str, ...] = ()
    collect_hints = hint_collector or collect_opened_raw_file_hints
    while True:
        latest_hints = collect_hints(hwnd)
        if raw_hint_contains_work_copy(latest_hints, work_copy_path):
            return latest_hints
        if time.monotonic() >= deadline:
            return latest_hints
        time.sleep(poll_interval_seconds)


def collect_opened_raw_file_hints(hwnd: int | None) -> tuple[str, ...]:
    """Universal Viewer 메인 창의 win32/UIA 텍스트에서 DAE/GEV 파일 힌트를 수집한다."""
    if hwnd is None:
        return ()

    texts: list[str] = []
    try:
        from pywinauto import Desktop

        win32_window = Desktop(backend="win32").window(handle=hwnd)
        texts.append(str(win32_window.window_text()))
        for wrapper in win32_window.descendants():
            texts.append(str(_safe_call(wrapper, "window_text", "")))
    except Exception:
        pass

    try:
        from pywinauto import Desktop

        uia_window = Desktop(backend="uia").window(handle=hwnd)
        texts.append(str(uia_window.window_text()))
        for wrapper in uia_window.descendants():
            texts.append(str(_safe_call(wrapper, "window_text", "")))
            texts.append(str(getattr(getattr(wrapper, "element_info", None), "name", "")))
    except Exception:
        pass

    return find_raw_file_hints(texts)


def raw_hint_contains_work_copy(hints: Iterable[str], work_copy_path: Path) -> bool:
    """수집한 힌트에 작업본 파일명이 포함되어 있는지 확인한다."""
    return bool(matching_work_copy_hints(hints, work_copy_path))


def matching_work_copy_hints(hints: Iterable[str], work_copy_path: Path) -> tuple[str, ...]:
    """수집한 힌트 중 작업본 파일명 또는 전체 경로와 일치하는 항목만 반환한다."""
    expected_name = work_copy_path.name.casefold()
    expected_path = str(work_copy_path).casefold()
    matched: list[str] = []
    for hint in hints:
        normalized = hint.casefold()
        if expected_name in normalized or expected_path in normalized:
            matched.append(hint)
    return tuple(matched)


def _validate_executable_path(path: Path, source_label: str) -> Path:
    candidate = path.expanduser().resolve()
    if not candidate.exists() or not candidate.is_file():
        raise ViewerLaunchError(
            f"{source_label} 경로가 유효한 실행 파일이 아닙니다: {candidate}. "
            "--viewer-exe로 UnivViewer.exe 경로를 지정하거나 UNIVERSAL_VIEWER_EXE 환경 변수를 설정하십시오."
        )
    return candidate


def _default_program_files_roots(environ: Mapping[str, str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        value = environ.get(key, "").strip()
        if value:
            roots.append(Path(value))
    roots.extend((Path("C:/Program Files"), Path("C:/Program Files (x86)")))
    return tuple(_dedupe_paths(roots))


def _iter_program_files_candidates(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        try:
            base = root.expanduser().resolve()
        except OSError:
            continue
        if not base.exists() or not base.is_dir():
            continue
        try:
            matches = sorted(base.rglob("UnivViewer.exe"), key=lambda item: str(item).casefold())
        except OSError:
            continue
        for match in matches:
            if match.is_file():
                yield match.resolve()


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _safe_call(obj: object, method_name: str, default: object) -> object:
    try:
        return getattr(obj, method_name)()
    except Exception:
        return default
