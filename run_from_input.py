"""VS Code Run 버튼으로 input 폴더 Raw Data를 선택해 기존 수동 PDF workflow를 실행한다."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence


SUPPORTED_RAW_EXTENSIONS = {".dae", ".gev"}
IGNORED_TEMP_SUFFIXES = {".tmp", ".partial", ".crdownload"}
DEFAULT_CONFIRM_YES = {"", "y", "yes", "Y", "YES", "Yes"}
FILE_STABLE_SECONDS = 5.0
FILE_STABLE_POLL_SECONDS = 0.5


class RunFromInputError(RuntimeError):
    """Run 버튼 런처에서 사용자 선택 또는 실행 준비가 실패했을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class RawFileEntry:
    """input 폴더에서 발견한 Raw Data 후보."""

    path: Path
    modified_time: float

    @property
    def modified_text(self) -> str:
        """화면에 표시할 LastWriteTime 문자열."""
        return datetime.fromtimestamp(self.modified_time).strftime("%Y-%m-%d %H:%M:%S")


def is_supported_raw_file(path: Path) -> bool:
    """지원 확장자이며 임시/미완성 파일이 아닌지 확인한다."""
    if not path.is_file():
        return False
    if path.name.endswith("~"):
        return False
    if path.suffix.casefold() in IGNORED_TEMP_SUFFIXES:
        return False
    return path.suffix.casefold() in SUPPORTED_RAW_EXTENSIONS


def list_supported_raw_files(input_dir: Path) -> list[RawFileEntry]:
    """input 폴더의 .DAE/.GEV 파일을 수정시간 최신순으로 반환한다."""
    if not input_dir.exists():
        raise RunFromInputError(f"input 폴더가 없습니다: {input_dir}")
    if not input_dir.is_dir():
        raise RunFromInputError(f"input 경로가 폴더가 아닙니다: {input_dir}")

    entries = [
        RawFileEntry(path=path, modified_time=path.stat().st_mtime)
        for path in input_dir.iterdir()
        if is_supported_raw_file(path)
    ]
    if not entries:
        raise RunFromInputError(f"input 폴더에 .DAE 또는 .GEV 파일이 없습니다: {input_dir}")
    return sorted(entries, key=lambda entry: (entry.modified_time, entry.path.name.casefold()), reverse=True)


def print_raw_file_menu(entries: Sequence[RawFileEntry], print_fn: Callable[[str], None] = print) -> None:
    """사용자가 선택할 수 있도록 번호 목록을 출력한다."""
    print_fn("Select raw data file from input:")
    print_fn("")
    max_name_length = max(len(entry.path.name) for entry in entries)
    for index, entry in enumerate(entries, start=1):
        print_fn(f"[{index}] {entry.path.name.ljust(max_name_length)}    {entry.modified_text}")
    print_fn("")


def select_raw_file(
    entries: Sequence[RawFileEntry],
    *,
    input_fn: Callable[[str], str] = input,
) -> Path:
    """번호 입력을 받아 Raw Data 파일 하나를 선택한다. Enter는 [1]로 처리한다."""
    if not entries:
        raise RunFromInputError("선택할 Raw Data 파일이 없습니다.")

    value = input_fn("Enter number [1]: ").strip()
    if value == "":
        selected_index = 1
    else:
        try:
            selected_index = int(value)
        except ValueError as exc:
            raise RunFromInputError(f"올바른 번호가 아닙니다: {value!r}") from exc

    if selected_index < 1 or selected_index > len(entries):
        raise RunFromInputError(f"선택 번호가 범위를 벗어났습니다: {selected_index}")

    selected_path = entries[selected_index - 1].path
    if not selected_path.exists():
        raise RunFromInputError(f"선택한 파일이 더 이상 존재하지 않습니다: {selected_path}")
    return selected_path


def verify_file_is_stable(
    path: Path,
    *,
    stable_seconds: float = FILE_STABLE_SECONDS,
    poll_seconds: float = FILE_STABLE_POLL_SECONDS,
    wait_fn: Callable[[float], None] = time.sleep,
) -> None:
    """파일 크기가 지정 시간 동안 변하지 않고 읽기 가능한지 확인한다."""
    if not path.exists():
        raise RunFromInputError(f"선택한 파일이 존재하지 않습니다: {path}")
    if not path.is_file():
        raise RunFromInputError(f"선택한 경로가 파일이 아닙니다: {path}")

    try:
        with path.open("rb") as file:
            file.read(1)
    except OSError as exc:
        raise RunFromInputError(f"선택한 파일을 읽기 위해 열 수 없습니다: {path} ({exc})") from exc

    previous_size = path.stat().st_size
    stable_elapsed = 0.0
    while stable_elapsed < stable_seconds:
        wait_time = min(poll_seconds, stable_seconds - stable_elapsed)
        if wait_time > 0:
            wait_fn(wait_time)
        current_size = path.stat().st_size
        if current_size != previous_size:
            previous_size = current_size
            stable_elapsed = 0.0
            continue
        stable_elapsed += wait_time


def unique_pdf_path(path: Path) -> Path:
    """기본 PDF 경로가 이미 있으면 숫자 suffix를 붙여 충돌을 피한다."""
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def build_output_pdf_path(raw_path: Path, output_dir: Path, now: datetime | None = None) -> Path:
    """선택한 Raw Data 파일명과 현재 시각으로 output PDF 경로를 만든다."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return unique_pdf_path(output_dir / f"{raw_path.stem}_manual_{timestamp}.pdf")


def build_subprocess_command(
    raw_path: Path,
    output_pdf_path: Path,
    *,
    python_executable: str = sys.executable,
) -> list[str]:
    """기존 integrations.universal_viewer.main workflow를 subprocess로 실행할 명령 목록을 만든다."""
    return [
        python_executable,
        "-m",
        "integrations.universal_viewer.main",
        str(raw_path),
        "--run-manual-pdf-workflow",
        "--output-pdf",
        str(output_pdf_path),
    ]


def confirm_execution(
    *,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """실행 전 사용자 확인을 받는다. Enter는 Yes로 처리한다."""
    answer = input_fn("Continue? [Y/n] ").strip()
    return answer in DEFAULT_CONFIRM_YES


def run_existing_manual_pdf_workflow(command: Sequence[str], project_root: Path) -> int:
    """subprocess로 기존 integrations.universal_viewer.main 수동 PDF workflow를 실행한다."""
    completed = subprocess.run(list(command), cwd=project_root)
    return int(completed.returncode)


def run_launcher(
    *,
    project_root: Path,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    workflow_runner: Callable[[Sequence[str], Path], int] = run_existing_manual_pdf_workflow,
    now: datetime | None = None,
    stable_seconds: float = FILE_STABLE_SECONDS,
    wait_fn: Callable[[float], None] = time.sleep,
) -> int:
    """input 파일 선택부터 기존 workflow subprocess 호출까지 수행한다."""
    input_dir = project_root / "input"
    output_dir = project_root / "output"

    entries = list_supported_raw_files(input_dir)
    print_raw_file_menu(entries, print_fn=print_fn)
    selected_raw_file = select_raw_file(entries, input_fn=input_fn)
    verify_file_is_stable(selected_raw_file, stable_seconds=stable_seconds, wait_fn=wait_fn)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_pdf_path = build_output_pdf_path(selected_raw_file, output_dir, now)

    print_fn("Selected raw data:")
    print_fn(str(selected_raw_file))
    print_fn("")
    print_fn("Output PDF:")
    print_fn(str(output_pdf_path))
    print_fn("")

    if not confirm_execution(input_fn=input_fn):
        print_fn("사용자가 실행을 취소했습니다.")
        return 1

    command = build_subprocess_command(selected_raw_file, output_pdf_path)
    exit_code = workflow_runner(command, project_root)
    if exit_code == 0:
        print_fn("PDF automation completed.")
        print_fn(f"PDF path: {output_pdf_path}")
    else:
        print_fn("PDF automation failed.")
        print_fn(f"Exit code: {exit_code}")
    return exit_code


def main() -> int:
    """VS Code Run 버튼에서 호출되는 진입점."""
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)
    try:
        return run_launcher(project_root=project_root)
    except RunFromInputError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
