"""공통 Raw Data 검증, 작업 복사본 및 출력명 관리."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


SUPPORTED_RAW_EXTENSIONS: dict[str, str] = {".dae": "MV2000", ".gev": "GP20"}


class RawDataValidationError(ValueError):
    """지원 Raw Data 입력이 유효하지 않을 때 발생한다."""


class CopyVerificationError(IOError):
    """작업 복사본의 무결성 검증에 실패했을 때 발생한다."""


def validate_raw_data_file(path: Path) -> Path:
    """파일 존재 여부, 지원 확장자 및 읽기 가능 여부를 검증한다."""
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise RawDataValidationError(f"파일이 없습니다: {resolved}")
    if not resolved.is_file():
        raise RawDataValidationError(f"일반 파일이 아닙니다: {resolved}")
    if resolved.suffix.casefold() not in SUPPORTED_RAW_EXTENSIONS:
        supported = ", ".join(extension.upper() for extension in SUPPORTED_RAW_EXTENSIONS)
        raise RawDataValidationError(
            f"지원하지 않는 확장자입니다: {resolved.suffix or '(없음)'} (지원 형식: {supported})"
        )
    try:
        with resolved.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise RawDataValidationError(f"파일을 읽을 수 없습니다: {resolved} ({exc})") from exc
    return resolved


def device_family_for(path: Path) -> str:
    """확장자에 대응하는 장비군을 반환한다."""
    try:
        return SUPPORTED_RAW_EXTENSIONS[path.suffix.casefold()]
    except KeyError as exc:
        raise RawDataValidationError(f"지원하지 않는 확장자입니다: {path.suffix or '(없음)'}") from exc


def discover_raw_data_files(input_dir: Path) -> list[Path]:
    """input 폴더 바로 아래에서 지원 Raw Data를 이름순으로 찾는다."""
    if not input_dir.exists():
        return []
    return sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in SUPPORTED_RAW_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )


def resolve_input_files(arguments: Iterable[Path], input_dir: Path) -> list[Path]:
    """명령행 파일 또는 input 폴더의 지원 Raw Data를 검증한다."""
    candidates = list(arguments) or discover_raw_data_files(input_dir)
    if not candidates:
        raise RawDataValidationError(f"처리할 .DAE 또는 .GEV 파일이 없습니다: {input_dir}")
    return [validate_raw_data_file(path) for path in candidates]


def raw_type_label(source: Path) -> str:
    """파일명에 사용할 DAE 또는 GEV 유형 문자열을 반환한다."""
    validate_raw_data_file(source)
    return source.suffix[1:].upper()


def build_work_filename(source: Path) -> str:
    """동일 stem의 형식 간 충돌을 막는 작업본 파일명을 만든다."""
    type_label = raw_type_label(source)
    return f"{source.stem}_{type_label}{source.suffix.upper()}"


def build_pdf_filename(source: Path, timestamp: datetime | None = None) -> str:
    """형식 유형과 시각을 포함한 예정 PDF 파일명을 만든다."""
    value = timestamp or datetime.now()
    return f"{source.stem}_{raw_type_label(source)}_{value:%Y%m%d_%H%M%S}.pdf"


def copy_to_work_dir(source: Path, work_dir: Path) -> Path:
    """원본을 유형별 작업명으로 복사하고 크기와 SHA256을 검증한다."""
    validated = validate_raw_data_file(source)
    work_dir.mkdir(parents=True, exist_ok=True)
    base_name = Path(build_work_filename(validated))
    destination = work_dir / base_name
    counter = 1
    while destination.exists():
        destination = work_dir / f"{base_name.stem}_{counter}{base_name.suffix}"
        counter += 1
    shutil.copy2(validated, destination)
    verify_copied_file(validated, destination)
    return destination


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """파일을 변경하지 않고 SHA256 해시를 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_copied_file(source: Path, copied: Path) -> None:
    """원본과 작업본의 크기 및 SHA256이 같은지 확인한다."""
    source_size = source.stat().st_size
    copied_size = copied.stat().st_size
    if source_size != copied_size:
        raise CopyVerificationError(
            f"복사 파일 크기가 다릅니다: 원본={source_size}바이트, 작업본={copied_size}바이트"
        )
    source_hash = calculate_sha256(source)
    copied_hash = calculate_sha256(copied)
    if source_hash != copied_hash:
        raise CopyVerificationError(
            f"복사 파일 SHA256이 다릅니다: 원본={source_hash}, 작업본={copied_hash}"
        )
