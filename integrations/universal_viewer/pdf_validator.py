"""생성된 PDF의 선택적 검증."""

from __future__ import annotations

from pathlib import Path


PYPDF_INSTALL_GUIDE = "PDF 검증 기능을 사용하려면 '.venv\\Scripts\\python -m pip install pypdf'를 실행하세요."


class PdfDependencyError(RuntimeError):
    """pypdf가 설치되지 않았을 때 발생한다."""


class PdfValidationError(ValueError):
    """PDF 파일이 유효하지 않을 때 발생한다."""


def validate_pdf(path: Path) -> int:
    """PDF를 열어 페이지 수를 반환한다. pypdf는 선택적 의존성이다."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfDependencyError(PYPDF_INSTALL_GUIDE) from exc

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PdfValidationError(f"PDF 파일이 없습니다: {resolved}")
    try:
        page_count = len(PdfReader(str(resolved)).pages)
    except Exception as exc:
        raise PdfValidationError(f"PDF를 읽을 수 없습니다: {resolved} ({exc})") from exc
    if page_count < 1:
        raise PdfValidationError(f"페이지가 없는 PDF입니다: {resolved}")
    return page_count
