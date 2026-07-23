"""열린 Windows 창을 클릭 없이 읽기 전용으로 조사한다."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Iterable, Literal

from .config import ViewerProfile

WindowBackend = Literal["win32", "uia"]


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """읽기 전용으로 수집한 최상위 창 정보."""

    title: str
    pid: int | None
    window_class: str
    backend: WindowBackend
    handle: int | None = None
    main_window: bool = False
    helper_window: bool = False


@dataclass(frozen=True, slots=True)
class WindowInspection:
    """Viewer 후보와 일반 창을 분리한 조사 결과."""

    viewer_candidates: tuple[WindowInfo, ...]
    general_windows: tuple[WindowInfo, ...]

    @property
    def automation_targets(self) -> tuple[WindowInfo, ...]:
        """향후 자동화 연결에 사용할 메인 창만 반환한다."""
        return tuple(window for window in self.viewer_candidates if window.main_window)


def inspect_windows(logger: logging.Logger, profile: ViewerProfile) -> WindowInspection:
    """현재 열린 최상위 창 정보를 읽고 Universal Viewer 후보를 분리한다.

    win32 백엔드를 우선 사용하고 사용할 수 없을 때 uia로 재시도한다.
    창을 클릭하거나 포커스 및 상태를 변경하지 않는다.
    """
    try:
        from pywinauto import Desktop

        last_error: Exception | None = None
        for backend in profile.backend_priority:
            try:
                windows = [
                    _to_window_info(window, backend)
                    for window in Desktop(backend=backend).windows()
                    if window.window_text().strip()
                ]
                inspection = classify_windows(windows, profile)
                for window in inspection.automation_targets:
                    if window.backend == profile.verified_backend:
                        logger.info(
                            "Universal Viewer %s / %s backend 검증 완료 | PID=%s | class=%s",
                            profile.verified_version,
                            profile.verified_backend,
                            window.pid,
                            window.window_class,
                        )
                return inspection
            except Exception as exc:
                last_error = exc
                logger.warning("%s 백엔드 창 조사 실패, 다음 백엔드를 시도합니다: %s", backend, exc)
        assert last_error is not None
        raise last_error
    except Exception as exc:  # GUI 백엔드 오류를 실행 전체 실패로 만들지 않는다.
        logger.exception("Windows 창 조사 실패: %s", exc)
        raise RuntimeError(f"Windows 창 조사에 실패했습니다: {exc}") from exc


def classify_windows(windows: Iterable[WindowInfo], profile: ViewerProfile) -> WindowInspection:
    """창을 Viewer 후보와 일반 창으로 분류하고 제목순으로 정렬한다."""
    raw_windows = tuple(windows)
    main_pids = {
        window.pid
        for window in raw_windows
        if window.pid is not None and is_main_window(window, profile)
    }
    classified = tuple(_classify_window(window, profile, main_pids) for window in raw_windows)
    candidates = tuple(
        sorted(
            (item for item in classified if is_viewer_candidate(item, profile)),
            key=lambda item: (not item.main_window, item.helper_window, item.title.casefold()),
        )
    )
    general = tuple(
        sorted(
            (item for item in classified if not is_viewer_candidate(item, profile)),
            key=lambda item: item.title.casefold(),
        )
    )
    return WindowInspection(candidates, general)


def is_viewer_candidate(window: WindowInfo, profile: ViewerProfile) -> bool:
    """프로필의 제목 또는 검증된 클래스 패턴으로 후보 여부를 확인한다."""
    normalized_title = window.title.casefold()
    normalized_class = window.window_class.casefold()
    title_matches = any(keyword.casefold() in normalized_title for keyword in profile.title_keywords)
    class_matches = any(pattern.casefold() in normalized_class for pattern in profile.class_name_patterns)
    return window.main_window or window.helper_window or title_matches or class_matches


def is_main_window(window: WindowInfo, profile: ViewerProfile) -> bool:
    """검증된 제목과 클래스 접두사가 모두 일치하는 메인 창인지 확인한다."""
    return (
        window.title.casefold() == profile.main_window_title.casefold()
        and window.window_class.casefold().startswith(profile.main_class_prefix.casefold())
    )


def is_helper_window(window: WindowInfo, profile: ViewerProfile) -> bool:
    """자동화 대상에서 제외할 Universal Viewer 보조 창인지 확인한다."""
    title = window.title.casefold()
    window_class = window.window_class.casefold()
    return (
        any(title == candidate.casefold() for candidate in profile.helper_window_titles)
        or any(window_class == candidate.casefold() for candidate in profile.helper_class_names)
    )


def _classify_window(window: WindowInfo, profile: ViewerProfile, main_pids: set[int]) -> WindowInfo:
    """원본 창 정보에 메인/보조 상태를 부여한다."""
    helper = window.pid in main_pids and is_helper_window(window, profile)
    main = is_main_window(window, profile) and not helper
    return replace(window, main_window=main, helper_window=helper)


def format_viewer_candidate(window: WindowInfo) -> str:
    """Universal Viewer 후보를 CLI 출력 형식으로 만든다."""
    pid = window.pid if window.pid is not None else "확인 불가"
    window_class = window.window_class or "확인 불가"
    return (
        f"[Universal Viewer 후보] {window.title}\n"
        f"  PID: {pid}\n"
        f"  Window class: {window_class}\n"
        f"  Backend: {window.backend}\n"
        f"  main_window={str(window.main_window).lower()}\n"
        f"  helper_window={str(window.helper_window).lower()}"
    )


def _to_window_info(window: object, backend: str) -> WindowInfo:
    """pywinauto 창 래퍼를 안전한 데이터 객체로 변환한다."""
    title = window.window_text().strip()  # type: ignore[attr-defined]
    try:
        pid = int(window.process_id())  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pid = None
    try:
        window_class = str(window.class_name())  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError):
        window_class = ""
    try:
        handle = int(window.handle)  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        handle = None
    if backend not in ("win32", "uia"):
        raise ValueError(f"지원하지 않는 백엔드입니다: {backend}")
    return WindowInfo(title, pid, window_class, backend, handle)  # type: ignore[arg-type]
