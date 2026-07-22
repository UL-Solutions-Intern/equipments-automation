"""공통 Raw Data 파일 관리 테스트."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.universal_viewer.file_manager import (
    CopyVerificationError,
    RawDataValidationError,
    build_pdf_filename,
    calculate_sha256,
    copy_to_work_dir,
    device_family_for,
    validate_raw_data_file,
    verify_copied_file,
)


class FileManagerTests(unittest.TestCase):
    def test_supported_extensions_are_case_insensitive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("record.DAE", "record.gev"):
                source = root / name
                source.write_bytes(b"raw-data")
                self.assertEqual(validate_raw_data_file(source), source.resolve())

    def test_unsupported_extension_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "record.txt"
            source.write_text("data", encoding="utf-8")
            with self.assertRaisesRegex(RawDataValidationError, "지원하지 않는 확장자"):
                validate_raw_data_file(source)

    def test_copy_does_not_modify_source(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "record.GEV"
            original = b"unchanged raw data"
            source.write_bytes(original)
            copied = copy_to_work_dir(source, root / "work")
            self.assertEqual(copied.read_bytes(), original)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(calculate_sha256(source), calculate_sha256(copied))

    def test_same_stem_dae_and_gev_do_not_collide(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dae = root / "sample.DAE"
            gev = root / "sample.GEV"
            dae.write_bytes(b"dae")
            gev.write_bytes(b"gev")
            dae_work = copy_to_work_dir(dae, root / "work")
            gev_work = copy_to_work_dir(gev, root / "work")
            timestamp = datetime(2026, 6, 29, 14, 30, 5)
            self.assertEqual(dae_work.name, "sample_DAE.DAE")
            self.assertEqual(gev_work.name, "sample_GEV.GEV")
            self.assertNotEqual(build_pdf_filename(dae, timestamp), build_pdf_filename(gev, timestamp))

    def test_device_family_mapping(self) -> None:
        self.assertEqual(device_family_for(Path("sample.DAE")), "MV2000")
        self.assertEqual(device_family_for(Path("sample.gev")), "GP20")

    def test_verify_copied_file_rejects_different_size(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.DAE"
            copied = root / "copied.DAE"
            source.write_bytes(b"source")
            copied.write_bytes(b"different-size")
            with self.assertRaises(CopyVerificationError):
                verify_copied_file(source, copied)


if __name__ == "__main__":
    unittest.main()
