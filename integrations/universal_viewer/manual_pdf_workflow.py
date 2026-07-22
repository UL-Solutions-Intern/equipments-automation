"""최종 수동 절차 기반 PDF 생성 workflow 오케스트레이션."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .cursor_value import (
    ABCursorAdjustmentResult,
    CursorValueError,
    CursorValueWindow,
    adjust_ab_cursors_to_30min,
    focus_universal_viewer_main_window,
    move_cursor_value_window_below_graph_or_safe_area,
    normalize_universal_viewer_main_window,
    open_cursor_value_window_from_universal_viewer_main_window,
)
from .display_group_settings import (
    DisplayGroupApplyConfirmedResult,
    DisplayGroupInspectionError,
    apply_display_group_max_48_confirmed,
    apply_time_axis_full_display_by_coordinates,
)
from .pdf_printing import PrintToPdfResult, print_raw_file_to_pdf
from .viewer_launcher import ViewerLaunchError, ViewerOpenResult, open_prepared_raw_file


class ManualPdfWorkflowError(RuntimeError):
    """최종 수동 PDF workflow 실패 시 발생한다."""


OpenPreparedRawFileFunction = Callable[..., ViewerOpenResult]
ApplyTimeAxisFunction = Callable[..., object]
ApplyDisplayGroupMax48Function = Callable[..., DisplayGroupApplyConfirmedResult]
EnsureCursorWindowFunction = Callable[[logging.Logger], CursorValueWindow]
AdjustAbCursorsFunction = Callable[[logging.Logger], ABCursorAdjustmentResult]
MoveCursorWindowFunction = Callable[[logging.Logger], object]
FocusViewerFunction = Callable[[logging.Logger], object]
PrintPdfFunction = Callable[..., PrintToPdfResult]
NormalizeViewerWindowFunction = Callable[..., object]


@dataclass(frozen=True, slots=True)
class ManualPdfWorkflowResult:
    """최종 수동 PDF workflow 결과."""

    opened: ViewerOpenResult
    display_group_result: DisplayGroupApplyConfirmedResult
    ab_adjustment_result: ABCursorAdjustmentResult
    pdf_result: PrintToPdfResult

    @property
    def absolute_time_difference(self) -> str:
        """최종 A/B 절대시간 차 문자열."""
        return self.ab_adjustment_result.absolute_time_difference

    @property
    def difference_seconds(self) -> float:
        """최종 A/B 절대시간 차 초 값."""
        return self.ab_adjustment_result.difference_seconds


def run_manual_pdf_workflow(
    source_path: Path,
    config: AppConfig,
    logger: logging.Logger,
    *,
    explicit_viewer_exe: Path | None = None,
    explicit_output_pdf: Path | None = None,
    open_raw_file_fn: OpenPreparedRawFileFunction = open_prepared_raw_file,
    time_axis_fn: ApplyTimeAxisFunction = apply_time_axis_full_display_by_coordinates,
    display_group_fn: ApplyDisplayGroupMax48Function = apply_display_group_max_48_confirmed,
    cursor_window_fn: EnsureCursorWindowFunction = open_cursor_value_window_from_universal_viewer_main_window,
    ab_adjustment_fn: AdjustAbCursorsFunction = adjust_ab_cursors_to_30min,
    move_cursor_window_fn: MoveCursorWindowFunction = move_cursor_value_window_below_graph_or_safe_area,
    focus_viewer_fn: FocusViewerFunction = focus_universal_viewer_main_window,
    print_pdf_fn: PrintPdfFunction = print_raw_file_to_pdf,
    normalize_viewer_window_fn: NormalizeViewerWindowFunction = normalize_universal_viewer_main_window,
) -> ManualPdfWorkflowResult:
    """구현 완료된 단계들을 정해진 순서로 연결해 최종 PDF를 생성한다."""
    logger.info("Manual PDF workflow started")
    logger.info("Raw file validated | %s", source_path)

    try:
        opened = open_raw_file_fn(source_path, config, logger, explicit_viewer_exe=explicit_viewer_exe)
    except Exception as exc:
        raise ManualPdfWorkflowError(f"Universal Viewer open/work copy preparation failed: {exc}") from exc

    logger.info("Work copy created and verified | %s", opened.work_copy_path)
    logger.info("Universal Viewer opened | hwnd=%s | pid=%s", opened.main_window.handle, opened.main_window.pid)

    try:
        normalize_viewer_window_fn(logger, main_window=opened.main_window)
    except Exception as exc:
        raise ManualPdfWorkflowError(f"Universal Viewer window normalization failed: {exc}") from exc

    try:
        logger.info("Applying Time Axis -> Full Display")
        time_axis_fn(opened, logger)
        logger.info("Time Axis -> Full Display completed")
    except Exception as exc:
        raise ManualPdfWorkflowError(f"Time axis full display failed: {exc}") from exc

    try:
        logger.info("Applying Display Group Settings")
        display_group_result = display_group_fn(
            source_path,
            config,
            logger,
            explicit_viewer_exe=explicit_viewer_exe,
            open_raw_file_fn=lambda *_args, **_kwargs: opened,
            time_axis_full_display_fn=lambda *_args, **_kwargs: None,
        )
        logger.info("Display Group Settings completed")
    except (DisplayGroupInspectionError, ViewerLaunchError) as exc:
        raise ManualPdfWorkflowError(f"Display group max 48 failed: {exc}") from exc

    try:
        logger.info("Opening Cursor Value Display")
        cursor_window_fn(logger)
        logger.info("Cursor Value Display opened")
    except CursorValueError as exc:
        raise ManualPdfWorkflowError(f"Cursor value window open/check failed: {exc}") from exc

    logger.info("A/B 30min adjustment started")
    ab_result = ab_adjustment_fn(logger)
    if not ab_result.success:
        raise ManualPdfWorkflowError(f"A/B 30min adjustment failed: {ab_result.reason}")
    logger.info("A/B 30min adjustment completed")
    logger.info("Final A/B difference string and seconds | %s | %s", ab_result.absolute_time_difference, ab_result.difference_seconds)

    try:
        move_cursor_window_fn(logger)
        logger.info("Cursor value window moved away from File menu")
    except CursorValueError as exc:
        logger.warning("Cursor value window safe move failed; continuing to existing print flow: %s", exc)

    try:
        focus_viewer_fn(logger)
    except CursorValueError as exc:
        raise ManualPdfWorkflowError(f"Universal Viewer focus failed before PDF print: {exc}") from exc

    try:
        logger.info("PDF print started")
        pdf_result = print_pdf_fn(
            opened.source_path,
            config,
            logger,
            explicit_viewer_exe=explicit_viewer_exe,
            explicit_output_pdf=explicit_output_pdf,
            open_raw_file_fn=lambda *_args, **_kwargs: opened,
        )
        logger.info("PDF print completed")
    except Exception as exc:
        raise ManualPdfWorkflowError(f"PDF printing failed: {exc}") from exc

    logger.info("PDF path | %s", pdf_result.output_pdf_path)
    logger.info("PDF size | %s", pdf_result.pdf_size_bytes)
    logger.info("Manual PDF workflow completed")
    return ManualPdfWorkflowResult(opened, display_group_result, ab_result, pdf_result)
