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


class _CallbackHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        self.callback(self.format(record))


def convert_raw_to_pdf(
    raw_path: str | Path,
    log_callback: Callable[[str], None] = print,
) -> PrintToPdfResult:
    """Apply the complete Viewer report workflow and print a unique PDF."""
    source = Path(raw_path).expanduser().resolve()
    output_pdf = make_unique_pdf_path(source.with_suffix(".pdf"))
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
        logger.warning("Universal Viewer close request failed | %s | %s", _format_window(window), exc)


def _format_window(window: WindowInfo) -> str:
    return (
        f"title={window.title!r}, pid={window.pid}, "
        f"class={window.window_class!r}, handle={window.handle}"
    )
