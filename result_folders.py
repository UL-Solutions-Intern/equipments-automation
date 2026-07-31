"""시험별 결과 폴더 경로 생성."""

from __future__ import annotations

import ctypes
from datetime import datetime
import os
from pathlib import Path


RESULTS_FOLDER_NAME = "3. Heating Test Result"


def resolve_desktop_folder() -> Path:
    """OneDrive 리디렉션을 포함한 Windows의 실제 바탕화면을 반환한다."""
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(
            None,
            0x0010,  # CSIDL_DESKTOPDIRECTORY
            None,
            0,
            buffer,
        )
        if result == 0 and buffer.value:
            return Path(buffer.value).expanduser().resolve()
    return (Path.home() / "Desktop").expanduser().resolve()


def default_results_root() -> Path:
    """기본 시험 결과 저장 루트."""
    return resolve_desktop_folder() / RESULTS_FOLDER_NAME


def create_unique_test_folder(
    base_folder: str | Path,
    started_at: datetime | None = None,
) -> Path:
    """시험 시작마다 YYYY-MM-DD, YYYY-MM-DD(2)... 폴더를 생성한다."""
    root = Path(base_folder).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    date_name = (started_at or datetime.now()).strftime("%Y-%m-%d")

    duplicate_no = 1
    while True:
        folder_name = date_name if duplicate_no == 1 else f"{date_name}({duplicate_no})"
        candidate = root / folder_name
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            duplicate_no += 1
