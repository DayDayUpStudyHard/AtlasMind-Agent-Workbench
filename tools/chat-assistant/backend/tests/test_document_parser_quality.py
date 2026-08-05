import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.document_parser import DocumentParser, assess_extracted_text_quality
from app.services.document_parser_types import ParsedBlock


class DocumentParserQualityTest(unittest.TestCase):
    def test_marks_garbled_pdf_text_as_low_quality(self):
        result = assess_extracted_text_quality(
            "9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。"
            "逾期超过 :\\0 天，叩方可暂停履行。"
        )

        self.assertEqual("LOW", result["level"])
        self.assertTrue(result["requiresOcr"])
        self.assertGreater(len(result["signals"]), 0)

    def test_keeps_clean_contract_text(self):
        result = assess_extracted_text_quality(
            "乙方应在合同生效后十五日内完成初步设计，并向甲方提交完整设计文件。"
        )

        self.assertEqual("HIGH", result["level"])
        self.assertFalse(result["requiresOcr"])

    def test_auto_reparses_low_quality_text_with_available_ocr(self):
        parser = DocumentParser()

        def fake_pdf_parser(path, progress_callback=None, parse_mode="OCR", force_ocr=False,
                            allow_disabled_ocr=False):
            if parse_mode == "FAST":
                yield ParsedBlock("9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。")
            else:
                yield ParsedBlock("乙方应在合同签订后10日内提交完整履约保函，并完成项目实施方案。")

        with patch.object(parser, "_iter_pdf", side_effect=fake_pdf_parser), \
             patch("app.services.document_parser._ocr_runtime_available", return_value=True), \
             patch("app.services.document_parser.settings.ocr_enabled", False), \
             patch("app.services.document_parser.settings.mineru_enabled", False), \
             patch("app.services.document_parser.settings.pdf_auto_reparse", True):
            blocks = list(parser._iter_pdf_auto(Path("contract.pdf")))

        self.assertEqual("OCR", parser.last_diagnostics["provider"])
        self.assertTrue(parser.last_diagnostics["qualityEscalated"])
        self.assertIn("完整履约保函", blocks[0].text)

    def test_auto_reparse_records_provider_unavailable_without_hiding_text(self):
        parser = DocumentParser()

        def fake_pdf_parser(path, progress_callback=None, parse_mode="OCR", force_ocr=False,
                            allow_disabled_ocr=False):
            yield ParsedBlock("9. :l 履约 1呆民:乙方在合同签订 10 日之内，应向 IFl方提交保雨。")

        with patch.object(parser, "_iter_pdf", side_effect=fake_pdf_parser), \
             patch("app.services.document_parser._ocr_runtime_available", return_value=False), \
             patch("app.services.document_parser._mineru_runtime_available", return_value=False), \
             patch("app.services.document_parser.settings.pdf_auto_reparse", True):
            blocks = list(parser._iter_pdf_auto(Path("contract.pdf")))

        self.assertEqual("FAST", parser.last_diagnostics["provider"])
        self.assertEqual("UNAVAILABLE", parser.last_diagnostics["qualityEscalationStatus"])
        self.assertTrue(blocks)
        self.assertTrue(parser.last_diagnostics["requiresReparse"])


if __name__ == "__main__":
    unittest.main()
