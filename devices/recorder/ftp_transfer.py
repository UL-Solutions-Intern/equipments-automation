from __future__ import annotations

from dataclasses import dataclass
from ftplib import FTP, all_errors
from pathlib import Path
import re
import time


@dataclass(frozen=True)
class RecorderFTPConfig:
    device_key: str
    host: str
    port: int = 21
    remote_dir: str = "/MEM0/DATA"
    extension: str = ""
    user: str = "anonymous"
    password: str = ""


def extract_real_filename(raw_entry: str, extension: str) -> str | None:
    text = raw_entry.strip().rstrip("/")
    if not text:
        return None

    pattern = re.compile(rf"([^\s/\\]+{re.escape(extension)})\s*$", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).split("/")[-1].split("\\")[-1]


def timestamp_from_filename(filename: str) -> str:
    mv = re.search(r"_(\d{6})_(\d{6})\.[A-Za-z0-9]+$", filename)
    if mv:
        return mv.group(1) + mv.group(2)

    groups = re.findall(r"\d{6,}", filename)
    return "".join(groups[-2:]) if groups else ""


class RecorderFTPClient:
    def __init__(self, config: RecorderFTPConfig, log_callback=print):
        self.config = config
        self.log = log_callback

    def connect(self) -> FTP:
        ftp = FTP()
        ftp.connect(self.config.host, self.config.port, timeout=15)
        if self.config.user:
            ftp.login(user=self.config.user, passwd=self.config.password)
        else:
            ftp.login()
        ftp.set_pasv(True)
        ftp.cwd(self.config.remote_dir)
        return ftp

    def list_file_names(self) -> set[str]:
        with self.connect() as ftp:
            return {filename for filename, _ in self.list_target_files(ftp)}

    def list_target_files(self, ftp: FTP) -> list[tuple[str, str]]:
        raw_entries = ftp.nlst()
        result: list[tuple[str, str]] = []
        seen: set[str] = set()

        for raw in raw_entries:
            filename = extract_real_filename(raw, self.config.extension)
            if filename and filename not in seen:
                result.append((filename, raw))
                seen.add(filename)

        return result

    def get_mdtm(self, ftp: FTP, filename: str) -> str:
        candidates = [
            filename,
            f"{self.config.remote_dir.rstrip('/')}/{filename}",
        ]
        for path in candidates:
            try:
                response = ftp.sendcmd(f"MDTM {path}")
                parts = response.split()
                if len(parts) >= 2:
                    return parts[-1]
            except all_errors:
                pass
        return ""

    def choose_latest_file(self, ftp: FTP, files: list[tuple[str, str]]) -> tuple[str, str]:
        if not files:
            raise RuntimeError(
                f"No {self.config.extension} files found in {self.config.remote_dir}."
            )

        ranked = []
        for index, (filename, raw) in enumerate(files):
            mdtm = self.get_mdtm(ftp, filename)
            name_time = timestamp_from_filename(filename)
            ranked.append(((mdtm, name_time, index), filename, raw))

        ranked.sort()
        _, filename, raw = ranked[-1]
        return filename, raw

    def next_number(self, folder: Path) -> int:
        pattern = re.compile(
            rf"^(\d+)_{re.escape(self.config.device_key)}"
            rf"{re.escape(self.config.extension)}$",
            re.IGNORECASE,
        )
        max_no = 0
        for path in folder.iterdir():
            if not path.is_file():
                continue
            match = pattern.match(path.name)
            if match:
                max_no = max(max_no, int(match.group(1)))
        return max_no + 1

    def download_with_fallback(self, ftp: FTP, filename: str, part_path: Path) -> int:
        remote_candidates = [
            filename,
            f"{self.config.remote_dir.rstrip('/')}/{filename}",
        ]
        last_error: Exception | None = None

        for remote_name in remote_candidates:
            part_path.unlink(missing_ok=True)
            try:
                self.log(f"FTP command: RETR {remote_name}")
                with part_path.open("wb") as fp:
                    ftp.retrbinary(f"RETR {remote_name}", fp.write, blocksize=65536)

                size = part_path.stat().st_size
                if size <= 0:
                    raise RuntimeError("Downloaded file size is 0 bytes.")
                return size
            except Exception as exc:
                last_error = exc
                part_path.unlink(missing_ok=True)
                self.log(f"Failed: RETR {remote_name} / {exc}")

        raise RuntimeError(f"Could not download recorder file: {last_error}")

    def download_latest(
        self,
        output_folder,
        previous_files: set[str] | None = None,
        wait_seconds: float = 20.0,
        poll_interval: float = 2.0,
        local_filename_stem: str | None = None,
    ) -> tuple[str, Path, int]:
        folder = Path(output_folder)
        folder.mkdir(parents=True, exist_ok=True)

        deadline = time.monotonic() + wait_seconds
        selected: tuple[FTP, str, str] | None = None
        ftp_to_close: FTP | None = None

        try:
            while True:
                ftp = self.connect()
                ftp_to_close = ftp
                files = self.list_target_files(ftp)
                candidates = files
                if previous_files is not None:
                    new_files = [(name, raw) for name, raw in files if name not in previous_files]
                    if new_files:
                        candidates = new_files
                    elif time.monotonic() < deadline:
                        ftp.quit()
                        ftp_to_close = None
                        time.sleep(poll_interval)
                        continue

                filename, raw = self.choose_latest_file(ftp, candidates)
                selected = (ftp, filename, raw)
                break

            ftp, filename, raw_entry = selected
            self.log(f"FTP raw entry: {raw_entry}")
            self.log(f"FTP download filename: {filename}")

            suffix = self.config.extension.upper()
            if local_filename_stem:
                final_path = folder / f"{local_filename_stem}{suffix}"
            else:
                number = self.next_number(folder)
                final_path = folder / f"{number:03d}_{self.config.device_key}{suffix}"

            def stem_in_use(stem: str) -> bool:
                return any(
                    path.is_file() and path.stem.casefold() == stem.casefold()
                    for path in folder.iterdir()
                )

            if stem_in_use(final_path.stem):
                base_stem = final_path.stem
                duplicate_no = 2
                while True:
                    candidate = folder / f"{base_stem} ({duplicate_no}){suffix}"
                    if not stem_in_use(candidate.stem):
                        final_path = candidate
                        break
                    duplicate_no += 1

            part_path = final_path.with_name(final_path.name + ".part")

            size = self.download_with_fallback(ftp, filename, part_path)
            part_path.replace(final_path)
            return filename, final_path, size
        finally:
            if ftp_to_close is not None:
                try:
                    ftp_to_close.quit()
                except all_errors:
                    ftp_to_close.close()
