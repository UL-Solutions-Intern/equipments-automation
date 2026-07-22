"""프로젝트 경로와 기본 설정."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ViewerProfile:
    """Universal Viewer 창 탐색 설정."""

    name: str
    title_keywords: tuple[str, ...]
    class_name_patterns: tuple[str, ...]
    backend_priority: tuple[Literal["win32", "uia"], ...]
    main_window_title: str
    main_class_prefix: str
    helper_window_titles: tuple[str, ...]
    helper_class_names: tuple[str, ...]
    verified_version: str
    verified_backend: Literal["win32", "uia"]


UNIVERSAL_VIEWER_PROFILE = ViewerProfile(
    name="universal_viewer",
    title_keywords=("SMARTDAC+ STANDARD Universal Viewer", "Universal Viewer", "데이터보기", "Viewer"),
    # R3.12.01 환경에서 검증된 접두사만 사용하며 전체 버전 문자열은 고정하지 않는다.
    class_name_patterns=("Universal_Viewer",),
    backend_priority=("win32", "uia"),
    main_window_title="Universal Viewer",
    main_class_prefix="Universal_Viewer",
    helper_window_titles=("GDI+ Window (UnivViewer.exe)",),
    helper_class_names=("GDI+ Hook Window Class",),
    verified_version="R3.12.01",
    verified_backend="win32",
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """실행 중 사용하는 경로 설정."""

    project_root: Path = PROJECT_ROOT
    universal_viewer: ViewerProfile = UNIVERSAL_VIEWER_PROFILE

    @property
    def input_dir(self) -> Path:
        return self.project_root / "input"

    @property
    def output_dir(self) -> Path:
        return self.project_root / "output"

    @property
    def work_dir(self) -> Path:
        return self.output_dir / "work"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    def ensure_directories(self) -> None:
        """프로그램이 관리하는 폴더를 생성한다."""
        for directory in (self.input_dir, self.output_dir, self.work_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
