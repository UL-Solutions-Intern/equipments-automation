"""Downloaded recorder files to Universal Viewer PDF integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.manual_pdf_workflow import run_manual_pdf_workflow
from integrations.universal_viewer.pdf_printing import (
    PrintToPdfResult,
    make_unique_pdf_path,
    print_raw_file_to_pdf,
)


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

    workflow_result = run_manual_pdf_workflow(
        source,
        AppConfig(project_root=PROJECT_ROOT),
        logger,
        explicit_output_pdf=output_pdf,
        print_pdf_fn=print_without_archive_copy,
    )
    return workflow_result.pdf_result
