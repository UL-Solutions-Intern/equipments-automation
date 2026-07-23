from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pdf_converter import convert_raw_to_pdf


class PdfOutputLocationTests(TestCase):
    def test_automatic_pdf_stays_beside_raw_without_archive_copy(self):
        raw_path = Path("C:/results/2026-07-23/sample.DAE")
        pdf_result = SimpleNamespace(
            output_pdf_path=raw_path.with_suffix(".pdf"),
            pdf_size_bytes=123,
        )
        workflow_result = SimpleNamespace(pdf_result=pdf_result)

        with patch(
            "pdf_converter.run_manual_pdf_workflow",
            return_value=workflow_result,
        ) as run_workflow:
            result = convert_raw_to_pdf(raw_path, lambda _message: None)

        self.assertIs(result, pdf_result)
        workflow_kwargs = run_workflow.call_args.kwargs
        self.assertEqual(
            workflow_kwargs["explicit_output_pdf"],
            raw_path.with_suffix(".pdf").resolve(),
        )

        print_pdf_fn = workflow_kwargs["print_pdf_fn"]
        with patch(
            "pdf_converter.print_raw_file_to_pdf",
            return_value=pdf_result,
        ) as print_raw:
            self.assertIs(print_pdf_fn("source", "config", "logger"), pdf_result)

        archive_copy_fn = print_raw.call_args.kwargs["archive_copy_fn"]
        self.assertIsNone(archive_copy_fn(Path("sample.pdf")))
