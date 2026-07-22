"""텍스트 및 CSV 로깅 설정."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from .models import ProcessingResult


CSV_FIELDS = (
    "processed_at",
    "source_extension",
    "device_family",
    "viewer_profile",
    "source_path",
    "working_path",
    "planned_pdf_path",
    "status",
    "error_message",
)


def setup_logging(logs_dir: Path) -> tuple[logging.Logger, Path]:
    """파일과 콘솔에 기록하는 로거를 구성한다."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "automation.log"
    logger = logging.getLogger("mv2000_automation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_path


def append_csv_result(csv_path: Path, result: ProcessingResult) -> None:
    """처리 결과 한 건을 UTF-8 BOM CSV에 추가한다."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_legacy_csv_if_needed(csv_path)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "processed_at": result.processed_at.isoformat(timespec="seconds"),
                "source_extension": result.source_extension,
                "device_family": result.device_family,
                "viewer_profile": result.viewer_profile,
                "source_path": str(result.source_path),
                "working_path": str(result.working_path or ""),
                "planned_pdf_path": str(result.planned_pdf_path),
                "status": result.status.value,
                "error_message": result.error_message,
            }
        )


def _archive_legacy_csv_if_needed(csv_path: Path) -> None:
    """기존 스키마 CSV를 보존 이름으로 옮기고 새 스키마 기록을 준비한다."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return
    with csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
        first_row = next(csv.reader(stream), [])
    if tuple(first_row) == CSV_FIELDS:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    legacy_path = csv_path.with_name(f"{csv_path.stem}_legacy_{timestamp}{csv_path.suffix}")
    csv_path.replace(legacy_path)
