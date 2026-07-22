"""DAE/GEV 안전 준비 워크플로 테스트."""

import logging
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.universal_viewer.config import AppConfig
from integrations.universal_viewer.models import ProcessingStatus
from integrations.universal_viewer.workflow import Workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(f"workflow-test-{id(self)}")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def _run(self, suffix: str, dry_run: bool):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / f"sample{suffix}"
        source.write_bytes(b"raw-data")
        config = AppConfig(project_root=root)
        result = Workflow(config, self.logger, dry_run=dry_run).process(source)
        return config, source, result

    def test_dae_dry_run_success(self) -> None:
        config, _, result = self._run(".DAE", True)
        self.assertEqual(result.status, ProcessingStatus.DRY_RUN)
        self.assertEqual(result.device_family, "MV2000")
        self.assertIsNone(result.working_path)
        self.assertFalse(config.work_dir.exists())

    def test_gev_dry_run_success(self) -> None:
        _, _, result = self._run(".GEV", True)
        self.assertEqual(result.status, ProcessingStatus.DRY_RUN)
        self.assertEqual(result.device_family, "GP20")

    def test_dae_prepare_only_success(self) -> None:
        _, source, result = self._run(".DAE", False)
        self.assertEqual(result.status, ProcessingStatus.SUCCESS)
        self.assertEqual(result.working_path.read_bytes(), source.read_bytes())  # type: ignore[union-attr]

    def test_gev_prepare_only_success(self) -> None:
        config, source, result = self._run(".GEV", False)
        self.assertEqual(result.status, ProcessingStatus.SUCCESS)
        self.assertEqual(result.working_path.read_bytes(), source.read_bytes())  # type: ignore[union-attr]
        with (config.logs_dir / "processing_results.csv").open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["source_extension"], ".GEV")
        self.assertEqual(row["device_family"], "GP20")
        self.assertEqual(row["viewer_profile"], "universal_viewer")
        self.assertEqual(row["error_message"], "")


if __name__ == "__main__":
    unittest.main()
