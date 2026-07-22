"""안전한 파일 준비 워크플로."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .file_manager import build_pdf_filename, build_work_filename, copy_to_work_dir, device_family_for
from .logging_setup import append_csv_result
from .models import ProcessingResult, ProcessingStatus


class Workflow:
    """공통 Raw Data를 준비하되 Universal Viewer와 인쇄는 조작하지 않는다."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        dry_run: bool = True,
        success_message: str | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.dry_run = dry_run
        self.success_message = success_message
        self.csv_path = config.logs_dir / "processing_results.csv"

    def process(self, source: Path) -> ProcessingResult:
        """dry-run 계획을 기록하거나 검증된 작업 복사본을 준비한다."""
        now = datetime.now()
        source_extension = source.suffix.upper()
        device_family = device_family_for(source)
        planned_pdf_path = self.config.output_dir / build_pdf_filename(source, now)
        work_path: Path | None = None
        try:
            planned_work_path = self.config.work_dir / build_work_filename(source)
            if self.dry_run:
                status = ProcessingStatus.DRY_RUN
                message = (
                    f"계획: {source} → {planned_work_path} 복사 및 무결성 검증. "
                    "dry-run이므로 실제 복사, Universal Viewer 실행 및 PDF 생성을 수행하지 않았습니다."
                )
            else:
                work_path = copy_to_work_dir(source, self.config.work_dir)
                status = ProcessingStatus.SUCCESS
                message = self.success_message or (
                    "작업 복사본 생성 및 파일 크기·SHA256 검증 완료. "
                    "Universal Viewer 실행, 마우스/키보드 입력, PDF 출력은 수행하지 않았습니다."
                )
            result = ProcessingResult(
                source_extension, device_family, self.config.universal_viewer.name,
                source, work_path, planned_pdf_path, status, "", now,
            )
            self.logger.info(
                "%s | 확장자=%s | 장비군=%s | 프로필=%s | 원본=%s | 작업본=%s | 예정PDF=%s",
                message, source_extension, device_family, self.config.universal_viewer.name,
                source, work_path, planned_pdf_path,
            )
        except Exception as exc:
            # GUI 단계가 추가되면 이곳에 현재 활성 창 제목도 함께 기록한다(TODO).
            result = ProcessingResult(
                source_extension, device_family, self.config.universal_viewer.name,
                source, work_path, planned_pdf_path, ProcessingStatus.FAILED, str(exc), now,
            )
            self.logger.exception("처리 실패 | 원본=%s | 원인=%s | 현재 창 제목=GUI 자동화 미구현", source, exc)
        append_csv_result(self.csv_path, result)
        return result

    # TODO: Universal Viewer 사용자 매뉴얼과 실제 UI 확인 후 메뉴명/버튼명을 확정한다.
    # TODO: UI Automation으로 인식되지 않는 그래프/드래그만 pyautogui 좌표를 설정한다.
    # TODO: 명시적인 실행 승인 시에만 Microsoft Print to PDF 인쇄를 수행한다.
