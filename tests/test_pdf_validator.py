"""PDF 선택적 의존성 관련 테스트."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.universal_viewer.pdf_validator import PdfDependencyError, PdfValidationError, validate_pdf


class PdfValidatorTests(unittest.TestCase):
    def test_missing_pdf_reports_dependency_or_file_error(self) -> None:
        """pypdf 설치 상태와 무관하게 명확한 전용 예외를 반환한다."""
        with TemporaryDirectory() as directory:
            try:
                validate_pdf(Path(directory) / "missing.pdf")
            except PdfDependencyError as exc:
                self.assertIn("pip install pypdf", str(exc))
            except PdfValidationError as exc:
                self.assertIn("PDF 파일이 없습니다", str(exc))
            else:
                self.fail("존재하지 않는 PDF가 검증을 통과했습니다.")


if __name__ == "__main__":
    unittest.main()
