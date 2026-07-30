"""Downloaded recorder files to Universal Viewer PDF integration."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.manual_pdf_workflow import run_manual_pdf_workflow
from integrations.universal_viewer.pdf_printing import (
    PrintToPdfResult,
    make_unique_pdf_path,
    print_raw_file_to_pdf,
)
from integrations.universal_viewer.viewer_discovery import WindowInfo, inspect_windows


PROJECT_ROOT = Path(__file__).resolve().parent
SAVE_CHANGES_CONFIRM_BUTTONS = ("예", "Yes", "확인", "OK")


class _CallbackHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        self.callback(self.format(record))


def convert_raw_to_pdf(
    raw_path: str | Path,
    log_callback: Callable[[str], None] = print,
    *,
    pdf_filename_suffix: str = "",
) -> PrintToPdfResult:
    """Apply the complete Viewer report workflow and print a unique PDF."""
    source = Path(raw_path).expanduser().resolve()
    output_source = source.with_suffix(".pdf")
    if pdf_filename_suffix:
        output_source = output_source.with_name(
            f"{output_source.stem}{pdf_filename_suffix}{output_source.suffix}"
        )
    output_pdf = make_unique_pdf_path(output_source)
    config = AppConfig(project_root=PROJECT_ROOT)

    logger = logging.getLogger(f"equipment_automation.pdf.{id(log_callback)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    handler = _CallbackHandler(log_callback)
    handler.setFormatter(logging.Formatter("PDF | %(message)s"))
    logger.addHandler(handler)

    def print_without_archive_copy(*args, **kwargs):
        # 자동 시험의 PDF는 raw 파일과 같은 최종 시험 폴더에 바로 생성한다.
        # 기존 Desktop archive 복사는 중복 PDF를 만들기 때문에 이 경로에서만 생략한다.
        kwargs["archive_copy_fn"] = lambda _pdf_path: None
        return print_raw_file_to_pdf(*args, **kwargs)

    close_universal_viewer_instances(config, logger, reason="before opening next raw data")
    try:
        workflow_result = run_manual_pdf_workflow(
            source,
            config,
            logger,
            explicit_output_pdf=output_pdf,
            print_pdf_fn=print_without_archive_copy,
        )
        return workflow_result.pdf_result
    finally:
        close_universal_viewer_instances(config, logger, reason="after PDF workflow")


def close_universal_viewer_instances(
    config: AppConfig,
    logger: logging.Logger,
    *,
    reason: str,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.5,
) -> None:
    """Close current Universal Viewer main windows so each raw file starts fresh."""
    try:
        inspection = inspect_windows(logger, config.universal_viewer)
    except Exception as exc:
        logger.warning("Universal Viewer close skipped (%s): window inspection failed: %s", reason, exc)
        return

    targets = inspection.automation_targets
    if not targets:
        logger.info("Universal Viewer close skipped (%s): no running main window", reason)
        return

    logger.info("Universal Viewer close started (%s) | count=%s", reason, len(targets))
    for window in targets:
        close_universal_viewer_window(window, logger)

    deadline = time.monotonic() + timeout_seconds
    remaining = targets
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        try:
            remaining = inspect_windows(logger, config.universal_viewer).automation_targets
        except Exception as exc:
            logger.warning("Universal Viewer close wait stopped (%s): %s", reason, exc)
            return
        if not remaining:
            logger.info("Universal Viewer close completed (%s)", reason)
            return

    logger.warning(
        "Universal Viewer close timed out (%s) | remaining=%s",
        reason,
        ", ".join(_format_window(window) for window in remaining),
    )


def close_universal_viewer_window(window: WindowInfo, logger: logging.Logger) -> None:
    """Send a normal close request to one Universal Viewer window."""
    if window.handle is None:
        logger.warning("Universal Viewer close skipped: window handle is unknown | %s", _format_window(window))
        return

    try:
        from pywinauto import Desktop

        Desktop(backend=window.backend).window(handle=window.handle).close()
        logger.info("Universal Viewer close requested | %s", _format_window(window))
    except Exception as exc:
        logger.info(
            "Universal Viewer close request needs confirmation or timed out | %s | %s",
            _format_window(window),
            exc,
        )

    accept_universal_viewer_save_prompt(window, logger)


def accept_universal_viewer_save_prompt(
    window: WindowInfo,
    logger: logging.Logger,
    *,
    timeout_seconds: float = 3.0,
    poll_interval_seconds: float = 0.25,
    desktop_factory: Callable[[str], object] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Accept Universal Viewer save-changes confirmation after closing a modified file."""
    deadline = time.monotonic() + timeout_seconds
    make_desktop = desktop_factory or _make_desktop
    backends = _dedupe_backends((window.backend, "win32", "uia"))

    while time.monotonic() < deadline:
        for backend in backends:
            try:
                desktop = make_desktop(backend)
                dialogs = tuple(desktop.windows())  # type: ignore[attr-defined]
            except Exception:
                continue

            for dialog in dialogs:
                if not _is_same_process_dialog(dialog, window.pid):
                    continue
                texts = _collect_wrapper_texts(dialog)
                if not _looks_like_save_changes_prompt(texts):
                    continue
                button = _find_confirmation_button(dialog)
                if button is None:
                    logger.warning("Universal Viewer save prompt found but confirm button was not found | texts=%s", texts)
                    return False
                _click_wrapper(button)
                logger.info(
                    "Universal Viewer save prompt accepted | pid=%s | button=%s",
                    window.pid,
                    _safe_wrapper_text(button),
                )
                return True
        sleep_fn(poll_interval_seconds)

    logger.info("Universal Viewer save prompt not shown | pid=%s", window.pid)
    return False


def _make_desktop(backend: str) -> object:
    from pywinauto import Desktop

    return Desktop(backend=backend)


def _dedupe_backends(backends: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for backend in backends:
        if backend not in result:
            result.append(backend)
    return tuple(result)


def _is_same_process_dialog(wrapper: object, owner_pid: int | None) -> bool:
    if owner_pid is not None and _safe_wrapper_pid(wrapper) != owner_pid:
        return False
    class_name = _safe_wrapper_class_name(wrapper).casefold()
    title = _safe_wrapper_text(wrapper).casefold()
    return class_name == "#32770" or "universal viewer" in title


def _collect_wrapper_texts(wrapper: object) -> tuple[str, ...]:
    texts = [_safe_wrapper_text(wrapper)]
    for child in _safe_wrapper_descendants(wrapper):
        text = _safe_wrapper_text(child)
        if text:
            texts.append(text)
    return tuple(text for text in texts if text)


def _looks_like_save_changes_prompt(texts: tuple[str, ...]) -> bool:
    blob = "\n".join(texts).casefold()
    return (
        ("변경" in blob and "저장" in blob)
        or ("save" in blob and ("change" in blob or "modified" in blob))
        or ("保存" in blob and ("変更" in blob or "保存しますか" in blob))
    )


def _find_confirmation_button(dialog: object) -> object | None:
    for child in _safe_wrapper_descendants(dialog):
        if _safe_wrapper_class_name(child).casefold() != "button":
            continue
        text = _safe_wrapper_text(child)
        if any(_button_text_matches(text, candidate) for candidate in SAVE_CHANGES_CONFIRM_BUTTONS):
            return child
    return None


def _button_text_matches(text: str, candidate: str) -> bool:
    normalized_text = _normalize_button_text(text)
    normalized_candidate = _normalize_button_text(candidate)
    return normalized_text == normalized_candidate or normalized_text.startswith(f"{normalized_candidate}(")


def _normalize_button_text(text: str) -> str:
    return text.strip().replace("&", "").casefold()


def _click_wrapper(wrapper: object) -> None:
    hwnd = _safe_wrapper_handle(wrapper)
    if hwnd is not None:
        try:
            import win32con
            import win32gui

            win32gui.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
            return
        except Exception:
            pass

    try:
        wrapper.click_input()  # type: ignore[attr-defined]
        return
    except Exception:
        pass
    wrapper.invoke()  # type: ignore[attr-defined]


def _safe_wrapper_descendants(wrapper: object) -> tuple[object, ...]:
    try:
        return tuple(wrapper.descendants())  # type: ignore[attr-defined]
    except Exception:
        return ()


def _safe_wrapper_text(wrapper: object) -> str:
    try:
        return str(wrapper.window_text()).strip()  # type: ignore[attr-defined]
    except Exception:
        try:
            return str(getattr(getattr(wrapper, "element_info", None), "name", "")).strip()
        except Exception:
            return ""


def _safe_wrapper_class_name(wrapper: object) -> str:
    try:
        return str(wrapper.class_name()).strip()  # type: ignore[attr-defined]
    except Exception:
        return ""


def _safe_wrapper_pid(wrapper: object) -> int | None:
    try:
        return int(wrapper.process_id())  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _safe_wrapper_handle(wrapper: object) -> int | None:
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


def _format_window(window: WindowInfo) -> str:
    return (
        f"title={window.title!r}, pid={window.pid}, "
        f"class={window.window_class!r}, handle={window.handle}"
    )
