"""워크플로 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class ProcessingStatus(str, Enum):
    """파일 처리 상태."""

    SUCCESS = "성공"
    DRY_RUN = "드라이런"
    FAILED = "실패"


@dataclass(slots=True)
class ProcessingResult:
    """한 Raw Data 파일의 처리 결과."""

    source_extension: str
    device_family: str
    viewer_profile: str
    source_path: Path
    working_path: Path | None
    planned_pdf_path: Path
    status: ProcessingStatus
    error_message: str
    processed_at: datetime
